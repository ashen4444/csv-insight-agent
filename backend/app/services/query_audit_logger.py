import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import QUERY_AUDIT_LOG_PATH


def write_query_audit_log(event: dict[str, Any]) -> None:
    QUERY_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    log_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event,
    }

    with QUERY_AUDIT_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(log_record, default=str) + "\n")