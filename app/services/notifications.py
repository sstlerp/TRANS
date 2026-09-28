"""Notification framework (spec §44): in-app notifications + pluggable channels.

`notify()` is idempotent through `dedupe_key` (e.g. one "expires in 7 days"
alert per renewal per reminder day).  Channels other than IN_APP are
delivered by `ChannelSender` implementations; EMAIL uses SMTP settings from
the environment, SMS/WhatsApp are extension points.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.utils import now
from app.models.system import Notification, NotificationRule

log = logging.getLogger("erp.notify")


class ChannelSender:
    def send(self, rule: NotificationRule, n: Notification) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class EmailSender(ChannelSender):
    def send(self, rule, n):
        s = get_settings()
        if not s.smtp_host or not rule.recipient_emails:
            return False
        msg = EmailMessage()
        msg["Subject"] = n.title
        msg["From"] = s.smtp_from or s.smtp_user
        msg["To"] = rule.recipient_emails
        msg.set_content(n.message or n.title)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
            return True
        except Exception:  # noqa: BLE001 - never break business flow on mail failure
            log.exception("E-mail notification failed for %s", n.dedupe_key)
            return False


CHANNELS: dict[str, ChannelSender] = {"EMAIL": EmailSender()}


def notify(db: Session, event_type: str, title: str, message: str | None = None, severity: str = "INFO",
           entity_type: str | None = None, entity_id: int | None = None, link_url: str | None = None,
           dedupe_key: str | None = None, user_id: int | None = None) -> Notification | None:
    rule = db.execute(select(NotificationRule).where(NotificationRule.event_type == event_type,
                                                     NotificationRule.is_active.is_(True))).scalars().first()
    if rule is not None and "IN_APP" not in (rule.channels or ""):
        channels = []
    else:
        channels = ["IN_APP"]
    if dedupe_key and db.execute(select(Notification.id).where(Notification.dedupe_key == dedupe_key)).first():
        return None
    n = Notification(event_type=event_type, severity=rule.severity if rule and severity == "INFO" else severity,
                     title=title[:200], message=message, entity_type=entity_type, entity_id=entity_id,
                     link_url=link_url, user_id=user_id, role_id=rule.recipient_role_id if rule else None,
                     dedupe_key=dedupe_key, created_at=now())
    if rule:
        for ch in (rule.channels or "").split(","):
            ch = ch.strip().upper()
            if ch in CHANNELS and CHANNELS[ch].send(rule, n):
                channels.append(ch)
    n.channels_sent = ",".join(channels)
    try:
        with db.begin_nested():
            db.add(n)
            db.flush()
    except IntegrityError:
        return None
    return n
