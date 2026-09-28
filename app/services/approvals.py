"""Configurable approval workflow (spec §66).

A service asks `requires_approval(action_type, amount)`; if an active
`approval_rules` row applies, it stores its pending work (e.g. an allocation
with status PENDING_APPROVAL) and calls `create_request`.  Approvers act via
`decide()`.  When the final level approves, the registered handler for the
action type finalises the work inside the same transaction.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.errors import BusinessError, NotFound, PermissionDenied
from app.core.utils import now
from app.models.finance import ApprovalAction, ApprovalRequest, ApprovalRule

_HANDLERS: dict[str, tuple[Callable, Callable | None]] = {}


def register(action_type: str, on_approve: Callable, on_reject: Callable | None = None) -> None:
    _HANDLERS[action_type] = (on_approve, on_reject)


def requires_approval(db: Session, action_type: str, amount: Decimal | None = None) -> ApprovalRule | None:
    q = select(ApprovalRule).where(ApprovalRule.action_type == action_type, ApprovalRule.is_active.is_(True))
    if amount is not None:
        q = q.where(or_(ApprovalRule.min_amount.is_(None), ApprovalRule.min_amount <= amount))
    else:
        q = q.where(ApprovalRule.min_amount.is_(None))
    return db.execute(q.order_by(ApprovalRule.levels.desc())).scalars().first()


def create_request(db: Session, user, rule: ApprovalRule, action_type: str, entity_type: str, entity_id: int | None,
                   summary: str, amount: Decimal | None = None, payload: dict | None = None) -> ApprovalRequest:
    req = ApprovalRequest(action_type=action_type, entity_type=entity_type, entity_id=entity_id, amount=amount,
                          payload=payload, summary=summary[:500], status="PENDING", current_level=0,
                          required_levels=rule.levels, rule_id=rule.id, requested_by=getattr(user, "id", None),
                          created_by=getattr(user, "id", None))
    db.add(req)
    db.flush()
    audit(db, user, "APPROVAL_REQUEST", entity_type, entity_id, new={"request_id": req.id, "summary": summary})
    from app.services.notifications import notify
    notify(db, "APPROVAL_PENDING", f"Approval required: {action_type.replace('_', ' ').title()}", summary,
           severity="WARNING", entity_type="approval_request", entity_id=req.id, link_url="/approvals",
           dedupe_key=f"approval:{req.id}")
    return req


def decide(db: Session, user, request_id: int, approve: bool, remarks: str | None = None) -> ApprovalRequest:
    req = db.get(ApprovalRequest, request_id, with_for_update=True)
    if not req:
        raise NotFound("Approval request")
    if req.status != "PENDING":
        raise BusinessError(f"Request is already {req.status}")
    rule = db.get(ApprovalRule, req.rule_id) if req.rule_id else None
    perm = rule.approver_permission if rule else "approval.approve"
    if not user.has(perm):
        raise PermissionDenied(f"Missing permission: {perm}")
    if req.requested_by == user.id and not (rule and rule.allow_self_approval) and not user.is_superuser:
        raise PermissionDenied("You cannot approve your own request")
    if not approve and not remarks:
        raise BusinessError("A reason is required to reject")
    level = req.current_level + 1
    db.add(ApprovalAction(request_id=req.id, level=level, action="APPROVE" if approve else "REJECT",
                          acted_by=user.id, acted_at=now(), remarks=remarks))
    handler = _HANDLERS.get(req.action_type)
    if not approve:
        req.status = "REJECTED"
        if handler and handler[1]:
            handler[1](db, user, req)
    else:
        req.current_level = level
        if level >= req.required_levels:
            req.status = "APPROVED"
            if handler:
                handler[0](db, user, req)
    req.updated_by = user.id
    audit(db, user, "APPROVE" if approve else "REJECT", "approval_request", req.id,
          new={"status": req.status, "level": level}, reason=remarks)
    db.flush()
    return req
