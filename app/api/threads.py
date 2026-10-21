from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Email
from app.api.deps import get_current_user

router = APIRouter(
    prefix="/api/threads",
    tags=["threads"],
    dependencies=[Depends(get_current_user)],
)

# Mail clients do not store conversation ids here, so a conversation is the set
# of emails of one account whose subject is the same once reply/forward prefixes
# are stripped.
_PREFIX_PY = re.compile(r"^\s*((re|fw|fwd|aw|sv|antw|wg|ответ|пере|tr)\s*:\s*)+", re.IGNORECASE)
_PREFIX_SQL = r"^\s*((re|fw|fwd|aw|sv|antw|wg|ответ|пере|tr)\s*:\s*)+"


def normalize_subject(subject: str) -> str:
    return _PREFIX_PY.sub("", subject or "").strip()


def _serialize(email: Email) -> dict:
    return {
        "id": email.id,
        "subject": email.subject,
        "sender_name": email.sender_name,
        "sender_email": email.sender_email,
        "date": email.date.isoformat() if email.date else None,
        "has_attachments": email.has_attachments,
        "is_read": email.is_read,
        "folder": email.folder,
    }


@router.get("")
def get_thread(email_id: int = Query(..., ge=1), session: Session = Depends(get_session)):
    """All emails that belong to the conversation of the given email."""
    email = session.query(Email).filter(Email.id == email_id).first()
    if not email:
        raise HTTPException(404, "Email not found")

    core = normalize_subject(email.subject)
    if not core:
        emails = [email]
    else:
        normalized = func.btrim(
            func.regexp_replace(func.lower(Email.subject), _PREFIX_SQL, "", "g")
        )
        query = session.query(Email).filter(normalized == core.lower())
        if email.account_id is not None:
            query = query.filter(Email.account_id == email.account_id)
        emails = query.order_by(func.coalesce(Email.date, Email.created_at).asc()).all()

    return {
        "subject": core or email.subject,
        "total": len(emails),
        "items": [_serialize(item) for item in emails],
    }
