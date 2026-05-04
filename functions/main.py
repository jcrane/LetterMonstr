"""
Cloud Function entry points for LetterMonstr.

HTTP-triggered functions:
  - fetch_and_process: fetches emails via IMAP, parses, crawls links, stores in Firestore
  - generate_and_send_summary: reads unsummarized content, generates summary via Claude, sends email
  - update_secrets: updates Secret Manager values from the settings UI
"""

import json
import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_functions import https_fn, options
from google.cloud import secretmanager

from src.config import load_config
from src import firestore_db
from src.mail_handling.fetcher import EmailFetcher
from src.mail_handling.parser import EmailParser
from src.mail_handling.sender import EmailSender
from src.crawl.crawler import WebCrawler
from src.summarize.processor import ContentProcessor
from src.summarize.generator import SummaryGenerator

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("lettermonstr")

FUNCTION_REGION = "us-central1"
FUNCTION_MEMORY = options.MemoryOption.MB_512
FUNCTION_TIMEOUT = 540
FUNCTION_MAX_INSTANCES = 1


def _generate_content_hash(subject: str, content: str) -> str:
    """Deterministic hash for dedup based on subject + first 1000 chars of content."""
    payload = f"{subject}_{content[:1000]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# fetch_and_process
# ---------------------------------------------------------------------------

@https_fn.on_request(
    region=FUNCTION_REGION,
    memory=FUNCTION_MEMORY,
    timeout_sec=FUNCTION_TIMEOUT,
    max_instances=FUNCTION_MAX_INSTANCES,
)
def fetch_and_process(req: https_fn.Request) -> https_fn.Response:
    """Fetch newsletters via IMAP, parse content, crawl links, store in Firestore."""
    logger.info("=== fetch_and_process invoked ===")

    try:
        config = load_config()
    except Exception:
        logger.exception("Failed to load config")
        return https_fn.Response("Config error", status=500)

    try:
        fetcher = EmailFetcher(config["email"])
        parser = EmailParser()
        crawler = WebCrawler(config["content"])

        # 1. Fetch emails from IMAP
        logger.info("Connecting to IMAP and fetching emails...")
        raw_emails = fetcher.fetch_new_emails()

        if not raw_emails:
            logger.info("No new emails found")
            return https_fn.Response(json.dumps({"processed": 0}), status=200,
                                     content_type="application/json")

        logger.info("Fetched %d raw emails", len(raw_emails))
        processed_count = 0

        for idx, email in enumerate(raw_emails):
            try:
                message_id = email.get("message_id", "")
                subject = email.get("subject", "No Subject")
                logger.info("Processing %d/%d: %s", idx + 1, len(raw_emails), subject)

                # Skip already-processed emails
                if message_id and firestore_db.is_email_processed(message_id):
                    logger.info("Already processed, skipping: %s", message_id)
                    continue

                # 2. Parse the email
                parsed = parser.parse(email)
                if not parsed:
                    logger.warning("Parser returned nothing for: %s", subject)
                    continue

                content = parsed.get("content", "")
                content_type = parsed.get("content_type", "text")
                links = parsed.get("links", [])

                if not content:
                    logger.warning("No content after parsing: %s", subject)
                    continue

                # 3. Store the processed email record
                firestore_db.store_processed_email(
                    message_id=message_id,
                    subject=subject,
                    sender=email.get("sender", ""),
                    date_received=email.get("date", datetime.now(timezone.utc)),
                )

                # 4. Store email content
                content_str = content if isinstance(content, str) else json.dumps(content)
                content_doc_id = firestore_db.store_email_content(
                    email_message_id=message_id,
                    content_type=content_type,
                    content=content_str,
                )

                # 5. Store extracted links
                for link in links:
                    url = link.get("url", "")
                    if url:
                        firestore_db.store_link(
                            content_doc_id=content_doc_id,
                            url=url,
                            title=link.get("title", ""),
                        )

                # 6. Crawl links
                crawled_items = []
                if links:
                    crawled_items = crawler.crawl(links)
                    logger.info("Crawled %d links for: %s", len(crawled_items), subject)

                # 7. Build the processed content structure (matches old format)
                clean_content = content_str
                if content_type == "html" and len(content_str) > 500:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(content_str, "html.parser")
                        text = soup.get_text(separator="\n", strip=True)
                        if len(text) > 200:
                            clean_content = text
                    except Exception:
                        pass

                content_structure = {
                    "source": subject,
                    "content": clean_content,
                    "content_type": content_type,
                    "date": email.get("date", datetime.now(timezone.utc)).isoformat()
                    if isinstance(email.get("date"), datetime)
                    else str(email.get("date", "")),
                }

                if crawled_items:
                    content_structure["articles"] = [
                        {"title": ci.get("title", ""), "url": ci.get("url", ""),
                         "content": ci.get("content", "")}
                        for ci in crawled_items if not ci.get("is_ad")
                    ]

                content_hash = _generate_content_hash(subject, clean_content)

                if firestore_db.content_hash_exists(content_hash):
                    logger.info("Duplicate content hash, skipping: %s", subject)
                    continue

                firestore_db.store_processed_content(
                    email_message_id=message_id,
                    source=subject,
                    content_type=content_type,
                    processed_content_json=json.dumps(content_structure),
                    content_hash=content_hash,
                )

                processed_count += 1
                logger.info("Successfully processed: %s", subject)

            except Exception:
                logger.exception("Error processing email: %s",
                                 email.get("subject", "unknown"))

        logger.info("=== fetch_and_process complete: %d emails processed ===",
                     processed_count)
        return https_fn.Response(
            json.dumps({"processed": processed_count}),
            status=200,
            content_type="application/json",
        )

    except Exception:
        logger.exception("Unhandled error in fetch_and_process")
        return https_fn.Response("Internal error", status=500)


# ---------------------------------------------------------------------------
# generate_and_send_summary
# ---------------------------------------------------------------------------

def _do_generate_and_send(config: dict) -> dict:
    """Core logic: read unsummarized content, generate summary, send email.

    Returns a dict with keys: status, items_summarized, email_sent, summary_doc_id.
    Raises on fatal errors.
    """
    raw_items = firestore_db.get_unsummarized_content()
    if not raw_items:
        logger.info("No unsummarized content available")
        return {"status": "no_content", "items_summarized": 0, "email_sent": False}

    logger.info("Found %d unsummarized content items", len(raw_items))

    content_items = []
    doc_ids = []
    for item in raw_items:
        try:
            pc_json = item.get("processed_content", "{}")
            pc = json.loads(pc_json) if isinstance(pc_json, str) else pc_json
            pc["source"] = pc.get("source", item.get("source", "Unknown"))
            content_items.append(pc)
            doc_ids.append(item["id"])
        except Exception:
            logger.exception("Error deserializing content item %s", item.get("id"))

    if not content_items:
        logger.warning("No valid content items after deserialization")
        return {"status": "no_valid_content", "items_summarized": 0, "email_sent": False}

    processor = ContentProcessor(config["content"])
    deduplicated = processor.process_and_deduplicate(content_items)

    frequency = config["summary"].get("frequency", "daily")
    summary_format = "weekly" if frequency == "weekly" else "newsletter"
    format_preferences = {"format": summary_format}
    # Cross-summary dedup window: must overlap the previous run, so 9 days for
    # weekly (7-day cadence + slack), 5 days for daily.
    history_lookback_days = 9 if frequency == "weekly" else 5

    history = firestore_db.get_recent_summarized_history(days=history_lookback_days)
    if history and deduplicated:
        deduplicated = processor.filter_with_history(deduplicated, history)

    if not deduplicated:
        logger.info("All content already summarized or filtered")
        return {"status": "all_filtered", "items_summarized": 0, "email_sent": False}

    logger.info("After dedup/filter: %d content items", len(deduplicated))

    recent_summaries = firestore_db.get_recent_summaries(days=history_lookback_days)
    recent_headlines = _extract_headlines_from_summaries(recent_summaries)

    generator = SummaryGenerator(config["llm"])

    max_tokens_per_batch = 25000
    batches = _split_into_batches(deduplicated, max_tokens_per_batch)
    logger.info("Split content into %d batches", len(batches))

    batch_summaries = []
    for i, batch in enumerate(batches):
        logger.info("Generating summary for batch %d/%d (%d items)",
                     i + 1, len(batches), len(batch))
        result = generator.generate_summary(
            batch,
            format_preferences=format_preferences,
            recent_headlines=recent_headlines,
        )
        summary_text = result.get("summary", "") if isinstance(result, dict) else str(result)
        if summary_text and not summary_text.startswith("Error"):
            batch_summaries.append(summary_text)

    if not batch_summaries:
        logger.error("No summaries generated — Claude API may have failed")
        return {"status": "generation_failed", "items_summarized": 0, "email_sent": False}

    final_summary = (
        batch_summaries[0]
        if len(batch_summaries) == 1
        else generator.combine_summaries(batch_summaries)
    )

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=7) if frequency == "weekly" else now
    summary_doc_id = firestore_db.create_summary(
        summary_text=final_summary,
        summary_type=frequency,
        period_start=period_start,
        period_end=now,
    )

    firestore_db.mark_content_summarized(doc_ids, summary_doc_id)

    for item in deduplicated:
        try:
            title = processor._extract_content_title(item)
            content = item.get("content", "")
            fingerprint = processor._extract_meaningful_fingerprint(content)
            content_hash = processor._generate_content_hash(item)
            firestore_db.store_summarized_content_history(
                content_hash=content_hash,
                content_title=title[:255] if title else "",
                content_fingerprint=fingerprint or "",
                summary_doc_id=summary_doc_id,
            )
        except Exception:
            logger.exception("Error storing content history")

    password = config["email"]["password"]
    sender = EmailSender(config["summary"], password)
    sent = sender.send_summary(final_summary)

    if sent:
        firestore_db.mark_summary_sent(summary_doc_id)
        logger.info("Summary email sent successfully")
    else:
        logger.error("Failed to send summary email")

    return {
        "status": "success",
        "items_summarized": len(deduplicated),
        "email_sent": sent,
        "summary_doc_id": summary_doc_id,
    }


WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday"}


def _is_scheduled_run_day(summary_config: dict) -> bool:
    """Return True if today (UTC) matches the configured cadence.

    Daily always returns True. Weekly returns True only on the configured
    `day_of_week`. Unknown frequency values are treated as daily.
    """
    frequency = summary_config.get("frequency", "daily")
    if frequency != "weekly":
        return True
    configured = str(summary_config.get("day_of_week", "monday")).strip().lower()
    if configured not in WEEKDAYS:
        logger.warning("Invalid day_of_week %r, defaulting to monday", configured)
        configured = "monday"
    today = datetime.now(timezone.utc).strftime("%A").lower()
    return today == configured


@https_fn.on_request(
    region=FUNCTION_REGION,
    memory=FUNCTION_MEMORY,
    timeout_sec=FUNCTION_TIMEOUT,
    max_instances=FUNCTION_MAX_INSTANCES,
)
def generate_and_send_summary(req: https_fn.Request) -> https_fn.Response:
    """Read unsummarized content from Firestore, generate summary, send email."""
    logger.info("=== generate_and_send_summary invoked ===")

    try:
        config = load_config()
    except Exception:
        logger.exception("Failed to load config")
        return https_fn.Response("Config error", status=500)

    if not _is_scheduled_run_day(config["summary"]):
        logger.info(
            "Skipping run: frequency=%s, day_of_week=%s, today=%s",
            config["summary"].get("frequency"),
            config["summary"].get("day_of_week"),
            datetime.now(timezone.utc).strftime("%A").lower(),
        )
        return https_fn.Response(
            json.dumps({"status": "skipped_not_scheduled_day"}),
            status=200, content_type="application/json",
        )

    try:
        result = _do_generate_and_send(config)
        status_code = 500 if result["status"] == "generation_failed" else 200
        logger.info("=== generate_and_send_summary complete ===")
        return https_fn.Response(
            json.dumps(result), status=status_code, content_type="application/json",
        )
    except Exception:
        logger.exception("Unhandled error in generate_and_send_summary")
        return https_fn.Response("Internal error", status=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_headlines_from_summaries(summaries: list[dict]) -> list[dict]:
    """Extract topic headlines from recent summary texts for LLM dedup context."""
    headlines = []
    for summary in summaries:
        text = summary.get("summary_text", "")
        date_val = summary.get("creation_date")
        date_str = ""
        if isinstance(date_val, datetime):
            date_str = date_val.strftime("%b %d")
        elif date_val:
            date_str = str(date_val)

        for pattern, flags in [
            (r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL),
            (r"<h3[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL),
        ]:
            matches = re.findall(pattern, text, flags)
            for heading in matches:
                clean = re.sub(r"<[^>]+>", "", heading).strip()
                if clean and len(clean) > 5:
                    headlines.append({"topic": clean, "date": date_str})
            if matches:
                break

    seen = set()
    unique = []
    for h in headlines:
        key = h["topic"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


def _split_into_batches(items: list[dict], max_tokens: int) -> list[list[dict]]:
    """Split content items into batches that fit within a token budget."""
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_tokens = 0

    for item in items:
        content = item.get("content", "")
        item_tokens = len(content) // 4 if isinstance(content, str) else 0

        if current_batch and current_tokens + item_tokens > max_tokens:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(item)
        current_tokens += item_tokens

    if current_batch:
        batches.append(current_batch)

    return batches if batches else [items]


# ---------------------------------------------------------------------------
# CORS helper
# ---------------------------------------------------------------------------

ALLOWED_ORIGIN = "https://lettermonstr.web.app"

def _cors_preflight(req: https_fn.Request) -> https_fn.Response | None:
    """Handle CORS preflight and return headers. Returns a Response for OPTIONS."""
    if req.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "3600",
        }
        return https_fn.Response("", status=204, headers=headers)
    return None


def _cors_headers() -> dict:
    return {"Access-Control-Allow-Origin": ALLOWED_ORIGIN}


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

AUTHORIZED_EMAIL = os.environ.get("AUTHORIZED_EMAIL", "")
if not AUTHORIZED_EMAIL:
    logger.warning("AUTHORIZED_EMAIL is not set — all auth-protected endpoints will reject requests")

def _verify_caller(req: https_fn.Request) -> str | None:
    """Verify Firebase ID token from Authorization header.

    Returns the user email if valid and authorized, or None.
    """
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    id_token = auth_header[7:]
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        decoded = firebase_auth.verify_id_token(id_token)
        email = decoded.get("email", "")
        if email == AUTHORIZED_EMAIL:
            return email
    except Exception:
        logger.exception("Token verification failed")
    return None


# ---------------------------------------------------------------------------
# update_secrets
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# trigger_summary  (UI-initiated, auth-protected)
# ---------------------------------------------------------------------------

@https_fn.on_request(
    region=FUNCTION_REGION,
    memory=FUNCTION_MEMORY,
    timeout_sec=FUNCTION_TIMEOUT,
    max_instances=FUNCTION_MAX_INSTANCES,
)
def trigger_summary(req: https_fn.Request) -> https_fn.Response:
    """Auth-protected endpoint to manually trigger a summary from the UI."""
    preflight = _cors_preflight(req)
    if preflight:
        return preflight

    headers = _cors_headers()

    caller = _verify_caller(req)
    if not caller:
        return https_fn.Response(
            json.dumps({"error": "Unauthorized"}),
            status=401,
            headers=headers,
            content_type="application/json",
        )

    logger.info("=== trigger_summary invoked by %s ===", caller)

    try:
        config = load_config()
    except Exception:
        logger.exception("Failed to load config")
        return https_fn.Response(
            json.dumps({"error": "Config error"}),
            status=500,
            headers=headers,
            content_type="application/json",
        )

    try:
        result = _do_generate_and_send(config)
        status_code = 500 if result["status"] == "generation_failed" else 200
        logger.info("=== trigger_summary complete: %s ===", result["status"])
        return https_fn.Response(
            json.dumps(result),
            status=status_code,
            headers=headers,
            content_type="application/json",
        )
    except Exception:
        logger.exception("Unhandled error in trigger_summary")
        return https_fn.Response(
            json.dumps({"error": "Internal error"}),
            status=500,
            headers=headers,
            content_type="application/json",
        )


# ---------------------------------------------------------------------------
# update_secrets
# ---------------------------------------------------------------------------

ALLOWED_SECRETS = {"gmail-app-password", "anthropic-api-key"}

@https_fn.on_request(
    region=FUNCTION_REGION,
    memory=options.MemoryOption.MB_256,
    timeout_sec=30,
    max_instances=1,
)
def update_secrets(req: https_fn.Request) -> https_fn.Response:
    """Update a secret value in Secret Manager. Requires Firebase Auth."""
    preflight = _cors_preflight(req)
    if preflight:
        return preflight

    headers = _cors_headers()

    caller = _verify_caller(req)
    if not caller:
        return https_fn.Response(
            json.dumps({"error": "Unauthorized"}),
            status=401,
            headers=headers,
            content_type="application/json",
        )

    try:
        body = req.get_json(silent=True) or {}
    except Exception:
        body = {}

    secret_id = body.get("secret_id", "")
    value = body.get("value", "")

    if secret_id not in ALLOWED_SECRETS:
        return https_fn.Response(
            json.dumps({"error": "Invalid secret_id"}),
            status=400,
            headers=headers,
            content_type="application/json",
        )

    MAX_SECRET_LENGTH = 256
    if not value:
        return https_fn.Response(
            json.dumps({"error": "value is required"}),
            status=400,
            headers=headers,
            content_type="application/json",
        )

    if len(value) > MAX_SECRET_LENGTH:
        return https_fn.Response(
            json.dumps({"error": f"value exceeds maximum length of {MAX_SECRET_LENGTH}"}),
            status=400,
            headers=headers,
            content_type="application/json",
        )

    try:
        import os
        project_id = os.environ.get(
            "GCLOUD_PROJECT",
            os.environ.get("GOOGLE_CLOUD_PROJECT", "lettermonstr"),
        )
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}/secrets/{secret_id}"
        client.add_secret_version(
            request={"parent": parent, "payload": {"data": value.encode("utf-8")}},
        )
        logger.info("Secret '%s' updated by %s", secret_id, caller)
        return https_fn.Response(
            json.dumps({"status": "ok", "secret_id": secret_id}),
            status=200,
            headers=headers,
            content_type="application/json",
        )
    except Exception:
        logger.exception("Failed to update secret '%s'", secret_id)
        return https_fn.Response(
            json.dumps({"error": "Failed to update secret"}),
            status=500,
            headers=headers,
            content_type="application/json",
        )
