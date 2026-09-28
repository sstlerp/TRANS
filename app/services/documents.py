"""Document management (spec §43).

Files are stored under `ERP_STORAGE_DIR` with an opaque, generated storage
key (YYYY/MM/<uuid>.<ext>).  Users never see or supply a filesystem path;
downloads go through an access-checked endpoint that maps id → storage key.
"""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import audit, snapshot
from app.core.errors import BusinessError, NotFound
from app.core.utils import file_sha256, now
from app.models.system import Document, DocumentLink

# magic-number checks for the types we accept
_MAGIC = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG"],
    ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
    ".xlsx": [b"PK\x03\x04"], ".docx": [b"PK\x03\x04"],
    ".xls": [b"\xd0\xcf\x11\xe0"], ".doc": [b"\xd0\xcf\x11\xe0"],
}


def safe_filename(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or "file"
    return name[:200]


def validate_upload(filename: str, data: bytes) -> str:
    s = get_settings()
    ext = Path(filename).suffix.lower()
    allowed = [e.strip() for e in s.allowed_upload_ext.split(",")]
    if ext not in allowed:
        raise BusinessError(f"File type {ext or '(none)'} is not allowed. Allowed: {', '.join(allowed)}")
    if len(data) == 0:
        raise BusinessError("Empty file")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise BusinessError(f"File exceeds {s.max_upload_mb} MB")
    sigs = _MAGIC.get(ext)
    if sigs and not any(data.startswith(sig) for sig in sigs):
        raise BusinessError("File content does not match its extension")
    return ext


def store_bytes(data: bytes, ext: str) -> str:
    d = now()
    key = f"{d:%Y}/{d:%m}/{uuid.uuid4().hex}{ext}"
    path = get_settings().storage_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def read_bytes(storage_key: str) -> bytes:
    base = get_settings().storage_dir.resolve()
    path = (base / storage_key).resolve()
    if base not in path.parents:
        raise NotFound("Document")
    if not path.exists():
        raise NotFound("Document file")
    return path.read_bytes()


def upload(db: Session, user, entity_type: str, entity_id: int, document_type: str, filename: str, data: bytes,
           remarks: str | None = None, replaces_id: int | None = None) -> Document:
    fname = safe_filename(filename)
    ext = validate_upload(fname, data)
    version, prev = 1, None
    if replaces_id:
        prev = db.get(Document, replaces_id)
        if not prev or prev.entity_type != entity_type or prev.entity_id != entity_id:
            raise NotFound("Document to replace")
        version = prev.version + 1
        prev.is_active = False
    doc = Document(document_type=document_type, entity_type=entity_type, entity_id=entity_id, file_name=fname,
                   storage_key=store_bytes(data, ext), content_type=mimetypes.guess_type(fname)[0],
                   size_bytes=len(data), sha256=file_sha256(data), version=version,
                   previous_document_id=prev.id if prev else None, uploaded_by=getattr(user, "id", None),
                   uploaded_at=now(), remarks=remarks, created_by=getattr(user, "id", None))
    db.add(doc)
    db.flush()
    audit(db, user, "UPLOAD", "document", doc.id, new=snapshot(doc))
    return doc


def list_for(db: Session, entity_type: str, entity_id: int, include_inactive: bool = False) -> list[Document]:
    linked = select(DocumentLink.document_id).where(DocumentLink.entity_type == entity_type,
                                                     DocumentLink.entity_id == entity_id)
    q = select(Document).where(or_(and_(Document.entity_type == entity_type, Document.entity_id == entity_id),
                                   Document.id.in_(linked)))
    if not include_inactive:
        q = q.where(Document.is_active.is_(True))
    return list(db.execute(q.order_by(Document.uploaded_at.desc())).scalars())


def link(db: Session, user, document_id: int, entity_type: str, entity_id: int) -> DocumentLink:
    if not db.get(Document, document_id):
        raise NotFound("Document")
    dl = DocumentLink(document_id=document_id, entity_type=entity_type, entity_id=entity_id, created_at=now())
    db.add(dl)
    audit(db, user, "LINK", "document", document_id, new={"entity_type": entity_type, "entity_id": entity_id})
    return dl


def has_document(db: Session, entity_type: str, entity_id: int) -> bool:
    return bool(list_for(db, entity_type, entity_id))
