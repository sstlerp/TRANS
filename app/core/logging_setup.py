"""Application logging: rotating file + console, with a filter that masks secrets."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from app.config import get_settings

_MASK = re.compile(r"(password|secret|token|api[_-]?key|authorization)(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,&]+)", re.I)


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _MASK.sub(r"\1\2***", record.msg)
        return True


def setup_logging() -> None:
    s = get_settings()
    root = logging.getLogger("erp")
    if root.handlers:
        return
    root.setLevel(s.log_level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(s.log_dir / "erp.log", maxBytes=10_000_000, backupCount=10, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(SecretFilter())
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.addFilter(SecretFilter())
    root.addHandler(fh)
    root.addHandler(ch)
