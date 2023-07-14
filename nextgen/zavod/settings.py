from os import environ as env
from pathlib import Path
from banal import as_bool
from datetime import datetime
from normality import stringify


def env_str(name: str, default: str) -> str:
    """Ensure the env returns a string even on Windows (#100)."""
    value = stringify(env.get(name))
    return default if value is None else value


# Release version
RELEASE = env_str("ZAVOD_RELEASE", "latest")

# Logging configuration
LOG_JSON = as_bool(env_str("ZAVOD_LOG_JSON", "false"))

# Default paths
DATA_PATH = Path(env_str("ZAVOD_DATA_PATH", "data"))

# Per-run timestamp
RUN_TIME = datetime.utcnow().replace(microsecond=0)

# Bucket to back-fill missing data artifacts from
ARCHIVE_BUCKET = env.get("ZAVOD_ARCHIVE_BUCKET", None)
BACKFILL_RELEASE = env_str("ZAVOD_BACKFILL_RELEASE", "latest")

# HTTP settings
HTTP_TIMEOUT = 1200
HTTP_USER_AGENT = "Mozilla/5.0 (zavod)"
HTTP_USER_AGENT = env_str("ZAVOD_HTTP_USER_AGENT", HTTP_USER_AGENT)