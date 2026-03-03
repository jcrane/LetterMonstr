"""Firestore data access layer for LetterMonstr.

Replaces the SQLAlchemy/SQLite models with Firestore collections
for use in Firebase Cloud Functions.
"""

import logging
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import firestore as firebase_firestore
from google.cloud import firestore

logger = logging.getLogger(__name__)

_db: firestore.Client | None = None

PROCESSED_EMAILS = "processed_emails"
EMAIL_CONTENTS = "email_contents"
LINKS = "links"
CRAWLED_CONTENTS = "crawled_contents"
PROCESSED_CONTENT = "processed_content"
SUMMARIES = "summaries"
SUMMARIZED_CONTENT_HISTORY = "summarized_content_history"


def init_firestore() -> firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client.

    Uses Application Default Credentials (auto-detected in Cloud Functions).
    """
    global _db
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    _db = firebase_firestore.client()
    return _db


def get_db() -> firestore.Client:
    """Return the module-level Firestore client, initializing if needed."""
    if _db is None:
        return init_firestore()
    return _db


# ---------------------------------------------------------------------------
# Processed Emails
# ---------------------------------------------------------------------------

def is_email_processed(message_id: str) -> bool:
    """Check whether an email with the given message_id has already been processed."""
    try:
        doc = get_db().collection(PROCESSED_EMAILS).document(message_id).get()
        return doc.exists
    except Exception:
        logger.exception("Error checking if email is processed: %s", message_id)
        return False


def store_processed_email(
    message_id: str,
    subject: str,
    sender: str,
    date_received: datetime,
) -> str:
    """Create or update a processed-email record. Returns the message_id."""
    try:
        get_db().collection(PROCESSED_EMAILS).document(message_id).set(
            {
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "date_received": date_received,
                "date_processed": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return message_id
    except Exception:
        logger.exception("Error storing processed email: %s", message_id)
        raise


# ---------------------------------------------------------------------------
# Email Contents
# ---------------------------------------------------------------------------

def store_email_content(
    email_message_id: str,
    content_type: str,
    content: str,
) -> str:
    """Store the body/content of an email. Returns the new document ID."""
    try:
        _, doc_ref = get_db().collection(EMAIL_CONTENTS).add(
            {
                "email_message_id": email_message_id,
                "content_type": content_type,
                "content": content,
                "date_stored": firestore.SERVER_TIMESTAMP,
            }
        )
        return doc_ref.id
    except Exception:
        logger.exception("Error storing email content for: %s", email_message_id)
        raise


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def store_link(content_doc_id: str, url: str, title: str | None = None) -> str:
    """Store a link extracted from email content. Returns the new document ID."""
    try:
        _, doc_ref = get_db().collection(LINKS).add(
            {
                "content_doc_id": content_doc_id,
                "url": url,
                "title": title,
                "crawled": False,
                "date_found": firestore.SERVER_TIMESTAMP,
            }
        )
        return doc_ref.id
    except Exception:
        logger.exception("Error storing link: %s", url)
        raise


def is_url_crawled(url: str) -> bool:
    """Check whether the given URL has already been crawled."""
    try:
        docs = (
            get_db()
            .collection(LINKS)
            .where("url", "==", url)
            .where("crawled", "==", True)
            .limit(1)
            .get()
        )
        return len(docs) > 0
    except Exception:
        logger.exception("Error checking if URL is crawled: %s", url)
        return False


# ---------------------------------------------------------------------------
# Crawled Contents
# ---------------------------------------------------------------------------

def store_crawled_content(
    link_doc_id: str,
    title: str | None,
    content: str,
    clean_content: str,
    is_ad: bool = False,
) -> str:
    """Store crawled page content and mark the parent link as crawled.

    Returns the new crawled-content document ID.
    """
    try:
        db = get_db()
        _, doc_ref = db.collection(CRAWLED_CONTENTS).add(
            {
                "link_doc_id": link_doc_id,
                "title": title,
                "content": content,
                "clean_content": clean_content,
                "is_ad": is_ad,
                "date_crawled": firestore.SERVER_TIMESTAMP,
            }
        )
        db.collection(LINKS).document(link_doc_id).update(
            {
                "crawled": True,
                "date_crawled": firestore.SERVER_TIMESTAMP,
            }
        )
        return doc_ref.id
    except Exception:
        logger.exception("Error storing crawled content for link: %s", link_doc_id)
        raise


# ---------------------------------------------------------------------------
# Processed Content
# ---------------------------------------------------------------------------

def store_processed_content(
    email_message_id: str,
    source: str,
    content_type: str,
    processed_content_json: str,
    content_hash: str,
) -> str:
    """Store processed (cleaned/structured) content. Returns the new document ID."""
    try:
        _, doc_ref = get_db().collection(PROCESSED_CONTENT).add(
            {
                "email_message_id": email_message_id,
                "source": source,
                "content_type": content_type,
                "processed_content": processed_content_json,
                "content_hash": content_hash,
                "is_summarized": False,
                "date_processed": firestore.SERVER_TIMESTAMP,
            }
        )
        return doc_ref.id
    except Exception:
        logger.exception(
            "Error storing processed content for: %s", email_message_id
        )
        raise


def content_hash_exists(content_hash: str) -> bool:
    """Check whether content with the given hash has already been processed."""
    try:
        docs = (
            get_db()
            .collection(PROCESSED_CONTENT)
            .where("content_hash", "==", content_hash)
            .limit(1)
            .get()
        )
        return len(docs) > 0
    except Exception:
        logger.exception("Error checking content hash: %s", content_hash)
        return False


def get_unsummarized_content() -> list[dict]:
    """Return all processed-content documents that have not yet been summarized."""
    try:
        docs = (
            get_db()
            .collection(PROCESSED_CONTENT)
            .where("is_summarized", "==", False)
            .order_by("date_processed")
            .get()
        )
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception:
        logger.exception("Error fetching unsummarized content")
        return []


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

def create_summary(
    summary_text: str,
    summary_type: str,
    period_start: datetime,
    period_end: datetime,
) -> str:
    """Create a new summary document. Returns the document ID."""
    try:
        _, doc_ref = get_db().collection(SUMMARIES).add(
            {
                "summary_text": summary_text,
                "summary_type": summary_type,
                "period_start": period_start,
                "period_end": period_end,
                "sent": False,
                "sent_date": None,
                "creation_date": firestore.SERVER_TIMESTAMP,
            }
        )
        return doc_ref.id
    except Exception:
        logger.exception("Error creating summary")
        raise


def mark_summary_sent(summary_doc_id: str) -> None:
    """Mark a summary as sent."""
    try:
        get_db().collection(SUMMARIES).document(summary_doc_id).update(
            {
                "sent": True,
                "sent_date": datetime.now(timezone.utc),
            }
        )
    except Exception:
        logger.exception("Error marking summary as sent: %s", summary_doc_id)
        raise


def mark_content_summarized(
    content_doc_ids: list[str],
    summary_doc_id: str,
) -> None:
    """Batch-update processed-content documents to mark them as summarized."""
    try:
        db = get_db()
        batch = db.batch()
        for doc_id in content_doc_ids:
            ref = db.collection(PROCESSED_CONTENT).document(doc_id)
            batch.update(ref, {
                "is_summarized": True,
                "summary_doc_id": summary_doc_id,
                "date_summarized": firestore.SERVER_TIMESTAMP,
            })
        batch.commit()
    except Exception:
        logger.exception("Error marking content as summarized")
        raise


def get_summary_by_id(summary_doc_id: str) -> dict | None:
    """Retrieve a single summary by document ID."""
    try:
        doc = get_db().collection(SUMMARIES).document(summary_doc_id).get()
        if doc.exists:
            return {"id": doc.id, **doc.to_dict()}
        return None
    except Exception:
        logger.exception("Error fetching summary: %s", summary_doc_id)
        return None


def get_recent_summaries(days: int = 5) -> list[dict]:
    """Return summaries that were sent within the last *days* days."""
    try:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        docs = (
            get_db()
            .collection(SUMMARIES)
            .where("creation_date", ">=", threshold)
            .where("sent", "==", True)
            .order_by("creation_date")
            .get()
        )
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception:
        logger.exception("Error fetching recent summaries")
        return []


# ---------------------------------------------------------------------------
# Summarized Content History
# ---------------------------------------------------------------------------

def store_summarized_content_history(
    content_hash: str,
    content_title: str,
    content_fingerprint: str,
    summary_doc_id: str,
) -> None:
    """Record that a piece of content was included in a summary.

    Uses content_hash as the document ID for fast dedup lookups.
    """
    try:
        get_db().collection(SUMMARIZED_CONTENT_HISTORY).document(content_hash).set(
            {
                "content_hash": content_hash,
                "content_title": content_title,
                "content_fingerprint": content_fingerprint,
                "summary_doc_id": summary_doc_id,
                "date_summarized": firestore.SERVER_TIMESTAMP,
            }
        )
    except Exception:
        logger.exception(
            "Error storing summarized content history: %s", content_hash
        )
        raise


def get_recent_summarized_history(days: int = 5) -> list[dict]:
    """Return summarized-content-history entries from the last *days* days."""
    try:
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        docs = (
            get_db()
            .collection(SUMMARIZED_CONTENT_HISTORY)
            .where("date_summarized", ">=", threshold)
            .order_by("date_summarized")
            .get()
        )
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception:
        logger.exception("Error fetching recent summarized history")
        return []
