from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Account, Attachment, Email
from app.api.deps import get_current_user

router = APIRouter(
    prefix="/api/files",
    tags=["files"],
    dependencies=[Depends(get_current_user)],
)

# Attachments do not store their extension, so it is derived from the file name
# directly in SQL: the last dot-separated segment, lowercased. Files without a
# dot (or ending with one) get an empty extension.
_EXT = case(
    (
        func.strpos(Attachment.filename, ".") > 0,
        func.lower(func.reverse(func.split_part(func.reverse(Attachment.filename), ".", 1))),
    ),
    else_="",
)


def _ext_of(filename: str) -> str:
    name = filename or ""
    if "." not in name:
        return ""
    ext = name.rsplit(".", 1)[1].lower()
    return ext


def _serialize(att: Attachment, email: Optional[Email], account: Optional[Account]) -> dict:
    return {
        "id": att.id,
        "filename": att.filename or "",
        "ext": _ext_of(att.filename or ""),
        "size": att.size or 0,
        "content_type": att.content_type or "",
        "email_id": att.email_id,
        "subject": email.subject if email else "",
        "folder": email.folder if email else "",
        "date": email.date.isoformat() if email and email.date else None,
        "account_id": email.account_id if email else None,
        "account_email": account.email if account else "",
    }


@router.get("/extensions")
def list_extensions(session: Session = Depends(get_session)):
    """Every distinct file extension with the number of files, for the filter list."""
    rows = (
        session.query(_EXT.label("ext"), func.count(Attachment.id))
        .group_by(_EXT)
        .all()
    )
    items = [{"ext": ext or "", "count": count} for ext, count in rows]
    items.sort(key=lambda item: (-item["count"], item["ext"]))
    return {"total": sum(item["count"] for item in items), "items": items}


@router.get("")
def list_files(
    ext: Optional[str] = Query(None, description="Filter by extension, e.g. pdf"),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    sort_by: str = Query("filename"),
    sort_order: str = Query("asc"),
    session: Session = Depends(get_session),
):
    """All files of all archives with their owning email."""
    query = (
        session.query(Attachment, Email, Account)
        .outerjoin(Email, Email.id == Attachment.email_id)
        .outerjoin(Account, Account.id == Email.account_id)
    )

    if ext is not None:
        query = query.filter(_EXT == ext.lower())

    sort_columns = {
        "filename": func.lower(Attachment.filename),
        "ext": _EXT,
        "size": Attachment.size,
        "date": Email.date,
    }
    column = sort_columns.get(sort_by, sort_columns["filename"])
    order = column.asc() if sort_order == "asc" else column.desc()
    query = query.order_by(order, Attachment.id.asc())

    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [_serialize(att, email, account) for att, email, account in rows],
    }
