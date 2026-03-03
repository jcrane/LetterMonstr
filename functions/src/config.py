"""
Configuration loader for LetterMonstr Cloud Functions.

Loads secrets from Google Secret Manager and non-secret config
from environment variables, producing a config dict matching
the structure expected by all app modules.
"""

import logging
import os

from google.cloud import secretmanager

logger = logging.getLogger(__name__)

_config: dict | None = None

SECRET_NAMES = {
    "gmail-app-password": ("email", "password"),
    "anthropic-api-key": ("llm", "anthropic_api_key"),
}

_ENV_DEFAULTS = {
    "email": {
        "fetch_email": ("FETCH_EMAIL", "lettermonstr@gmail.com"),
        "imap_server": ("IMAP_SERVER", "imap.gmail.com"),
        "imap_port": ("IMAP_PORT", 993),
        "folders": ("EMAIL_FOLDERS", "INBOX"),
        "initial_lookback_days": ("INITIAL_LOOKBACK_DAYS", 7),
        "periodic_fetch": ("PERIODIC_FETCH", "true"),
        "mark_read_only_after_summary": ("MARK_READ_ONLY_AFTER_SUMMARY", "true"),
    },
    "summary": {
        "smtp_server": ("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": ("SMTP_PORT", 587),
        "sender_email": ("SENDER_EMAIL", "lettermonstr@gmail.com"),
        "recipient_email": ("RECIPIENT_EMAIL", ""),
        "subject_prefix": ("SUBJECT_PREFIX", "[LetterMonstr] "),
        "frequency": ("SUMMARY_FREQUENCY", "daily"),
        "delivery_time": ("DELIVERY_TIME", "18:00"),
    },
    "llm": {
        "model": ("LLM_MODEL", "claude-sonnet-4-20250514"),
        "max_tokens": ("LLM_MAX_TOKENS", 16000),
        "temperature": ("LLM_TEMPERATURE", 0.5),
    },
    "content": {
        "max_links_per_email": ("MAX_LINKS_PER_EMAIL", 5),
        "max_link_depth": ("MAX_LINK_DEPTH", 1),
        "request_timeout": ("REQUEST_TIMEOUT", 10),
        "user_agent": ("USER_AGENT", "LetterMonstr/1.0"),
        "ad_keywords": ("AD_KEYWORDS", "sponsored,advertisement,promoted,partner,paid"),
    },
}

BOOL_FIELDS = {"periodic_fetch", "mark_read_only_after_summary"}
INT_FIELDS = {"imap_port", "smtp_port", "max_tokens", "max_links_per_email",
              "max_link_depth", "request_timeout", "initial_lookback_days"}
FLOAT_FIELDS = {"temperature"}
COMMA_SPLIT_FIELDS = {"folders", "ad_keywords"}


def _get_project_id() -> str:
    for var in ("GCP_PROJECT", "GCLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        project_id = os.environ.get(var)
        if project_id:
            return project_id
    raise EnvironmentError(
        "GCP project ID not found. Set GCP_PROJECT, GCLOUD_PROJECT, "
        "or GOOGLE_CLOUD_PROJECT environment variable."
    )


def _load_secret(client: secretmanager.SecretManagerServiceClient,
                 project_id: str, secret_id: str) -> str:
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def _coerce_value(key: str, raw: str):
    if key in BOOL_FIELDS:
        return raw.strip().lower() in ("true", "1", "yes")
    if key in INT_FIELDS:
        return int(raw)
    if key in FLOAT_FIELDS:
        return float(raw)
    if key in COMMA_SPLIT_FIELDS:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def _load_env_config() -> dict:
    config: dict = {}
    for section, fields in _ENV_DEFAULTS.items():
        config[section] = {}
        for key, (env_var, default) in fields.items():
            raw = os.environ.get(env_var, str(default))
            config[section][key] = _coerce_value(key, raw)
    return config


ALLOWED_FIRESTORE_KEYS: dict[str, set[str]] = {
    section: set(fields.keys())
    for section, fields in _ENV_DEFAULTS.items()
}


def _filter_firestore_settings(raw: dict) -> dict:
    """Strip any keys not present in the known config schema."""
    filtered: dict = {}
    for section, values in raw.items():
        if section not in ALLOWED_FIRESTORE_KEYS:
            logger.warning("Ignoring unknown Firestore config section: %s", section)
            continue
        if not isinstance(values, dict):
            continue
        allowed = ALLOWED_FIRESTORE_KEYS[section]
        section_data = {}
        for key, val in values.items():
            if key in allowed:
                section_data[key] = val
            else:
                logger.warning("Ignoring unknown Firestore config key: %s.%s", section, key)
        if section_data:
            filtered[section] = section_data
    return filtered


def _load_firestore_settings() -> dict | None:
    """Try to read settings/app_config from Firestore.

    Returns the document dict on success, or None if unavailable.
    Only keys present in the known config schema are accepted.
    """
    try:
        import firebase_admin
        from firebase_admin import firestore as fb_firestore

        if not firebase_admin._apps:
            firebase_admin.initialize_app()

        db = fb_firestore.client()
        doc = db.collection("settings").document("app_config").get()
        if doc.exists:
            data = doc.to_dict()
            data.pop("updated_at", None)
            filtered = _filter_firestore_settings(data)
            logger.info("Loaded settings from Firestore")
            return filtered
        logger.info("No settings document in Firestore, using defaults")
    except Exception:
        logger.warning("Could not read Firestore settings, using defaults",
                       exc_info=True)
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (override wins)."""
    merged = dict(base)
    for key, value in override.items():
        if (key in merged
                and isinstance(merged[key], dict)
                and isinstance(value, dict)):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_secrets(config: dict) -> None:
    project_id = _get_project_id()
    client = secretmanager.SecretManagerServiceClient()

    for secret_id, (section, key) in SECRET_NAMES.items():
        try:
            value = _load_secret(client, project_id, secret_id)
            config.setdefault(section, {})[key] = value
            logger.info("Loaded secret '%s'", secret_id)
        except Exception:
            logger.exception("Failed to load secret '%s'", secret_id)
            raise


def load_config() -> dict:
    """Return the application config dict, loading and caching on first call.

    Priority (highest wins): Secret Manager > Firestore settings > env vars > defaults.
    """
    global _config
    if _config is not None:
        return _config

    logger.info("Loading LetterMonstr configuration")

    config = _load_env_config()

    firestore_settings = _load_firestore_settings()
    if firestore_settings:
        config = _deep_merge(config, firestore_settings)

    _load_secrets(config)

    _config = config
    logger.info("Configuration loaded successfully")
    return _config


def invalidate_cache() -> None:
    """Clear the cached config so the next load_config() re-reads everything."""
    global _config
    _config = None
