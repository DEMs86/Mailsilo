
from __future__ import annotations

import email
import hashlib
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

from app.models import Email, Attachment, Account
from app.database import get_session


def _str_header(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return _decode_payload(value)
    return str(value)


def _clean_str(value: str) -> str:
    return value.replace("\x00", "")


def _decode_payload(
    payload: bytes | None,
    charset: str | None = None,
) -> str:
    """Decode message bytes using the declared charset and safe fallbacks."""
    if payload is None:
        return ""

    # First respect the charset specified by the message.
    candidates = []
    if charset:
        candidates.append(charset.strip().strip('"').strip("'"))

    # UTF-8 is the usual default for modern mail.
    candidates.extend(["utf-8", "cp1251", "koi8-r", "latin-1"])

    tried = set()
    for encoding in candidates:
        encoding_key = encoding.lower()
        if encoding_key in tried:
            continue
        tried.add(encoding_key)

        try:
            return payload.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue

    # latin-1 normally makes this unreachable, but keep a final fallback.
    return payload.decode("utf-8", errors="replace")


def _decode_mime(value: str | bytes | None) -> str:
    """Decode MIME-encoded headers and filenames."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")

    result: list[str] = []
    try:
        parts = decode_header(value)
    except Exception:
        return value

    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(_decode_payload(part, charset))
        else:
            result.append(str(part))

    # Do not insert spaces between encoded header fragments.
    return "".join(result)


def _parse_address(header_value: str) -> tuple[str, str]:
    decoded = _decode_mime(header_value)
    name, address = parseaddr(decoded)
    return _decode_mime(name).strip(), address.strip()


def _parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None

    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
    except (TypeError, ValueError, OverflowError):
        return None

    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def _get_body(msg: email.message.Message) -> tuple[str, str]:
    """Extract plain-text and HTML bodies without decoding attachments as text."""
    text_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue

            # Files should be handled by _get_attachments(), not as body text.
            if part.get_content_disposition() == "attachment":
                continue

            content_type = part.get_content_type().lower()
            if content_type not in ("text/plain", "text/html"):
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            charset = part.get_content_charset()
            decoded = _decode_payload(payload, charset)

            if content_type == "text/plain":
                text_parts.append(decoded)
            else:
                html_parts.append(decoded)
    else:
        content_type = msg.get_content_type().lower()
        payload = msg.get_payload(decode=True)

        if payload is not None:
            decoded = _decode_payload(payload, msg.get_content_charset())
            if content_type == "text/html":
                html_parts.append(decoded)
            elif content_type == "text/plain":
                text_parts.append(decoded)

    return "\n".join(text_parts), "\n".join(html_parts)


def _get_attachments(
    msg: email.message.Message,
) -> list[tuple[str, str, str, bytes]]:
    attachments: list[tuple[str, str, str, bytes]] = []

    if not msg.is_multipart():
        return attachments

    for part in msg.walk():
        if part.is_multipart():
            continue

        content_type = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()
        content_id = (part.get("Content-ID") or "").strip("<>").strip()

        is_inline_image = (
            content_type.startswith("image/")
            and (content_id or "inline" in disposition)
        )
        is_attachment = "attachment" in disposition

        if not is_inline_image and not is_attachment:
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        filename = part.get_filename()
        if filename:
            filename = _decode_mime(filename)
        elif content_id:
            filename = content_id
        else:
            filename = "inline_image"

        attachments.append((filename, content_type, content_id, payload))

    return attachments


def _ensure_account(session, sender_email: str) -> int:
    if not sender_email:
        return 0

    account = (
        session.query(Account)
        .filter(Account.email == sender_email)
        .first()
    )
    if account:
        return account.id

    domain = (
        sender_email.split("@")[-1]
        if "@" in sender_email
        else "unknown"
    )

    account = Account(
        name=sender_email,
        email=sender_email,
        imap_server=f"mail.{domain}",
        imap_port=993,
        imap_use_ssl=True,
        username=sender_email,
        folders="INBOX",
        enabled=False,
        is_imported=True,
    )
    session.add(account)
    session.flush()
    return account.id


def ensure_import_account(
    session,
    email_address: str,
    name: str | None = None,
) -> int:
    """Get or create one archive-only account for a whole mailbox.

    Unlike ``_ensure_account`` (which creates an account per sender when no
    account is selected) this keeps a migration/dump in a single account. The
    account is flagged ``is_imported`` and disabled, so the background IMAP
    fetcher never polls a server that is not configured.
    """
    email_address = (email_address or "").strip()
    if not email_address:
        return 0

    account = (
        session.query(Account)
        .filter(Account.email == email_address)
        .first()
    )
    if account:
        return account.id

    domain = (
        email_address.split("@")[-1]
        if "@" in email_address
        else "unknown"
    )

    account = Account(
        name=name or email_address,
        email=email_address,
        imap_server=f"mail.{domain}",
        imap_port=993,
        imap_use_ssl=True,
        username=email_address,
        folders="INBOX",
        enabled=False,
        is_imported=True,
    )
    session.add(account)
    session.flush()
    return account.id


def import_eml(
    filepath: str | Path,
    account_id: int = 0,
    folder: str = "Imported",
    is_read: bool = False,
    fallback_date: datetime | None = None,
    account_email: str = "",
) -> int:
    p = Path(filepath)
    raw_bytes = p.read_bytes()
    msg = email.message_from_bytes(raw_bytes)

    msg_id = _str_header(msg.get("Message-ID", "")).strip()
    if not msg_id:
        msg_id = "fallback-" + hashlib.sha256(raw_bytes).hexdigest()[:32]

    subject = _decode_mime(msg.get("Subject", ""))
    sender_name, sender_email = _parse_address(
        _str_header(msg.get("From", ""))
    )
    date = _parse_date(_str_header(msg.get("Date", "")))
    if date is None and fallback_date is not None:
        # The Yandex dump keeps the server-side timestamp in manifest.jsonl;
        # keep it when the message has no usable Date header.
        date = fallback_date

    text, html = _get_body(msg)
    attachments = _get_attachments(msg)

    # Normalize folder paths for consistent storage.
    folder = folder.replace("\\", "/").strip("/")
    if not folder:
        folder = "Imported"

    session = get_session()
    count = 0

    try:
        if account_id == 0 and account_email:
            account_id = ensure_import_account(session, account_email)
        if account_id == 0 and sender_email:
            account_id = _ensure_account(session, sender_email)

        existing = (
            session.query(Email)
            .filter(
                Email.message_id == msg_id,
                Email.account_id == account_id,
                Email.folder == folder,
            )
            .first()
        )

        if existing is None:
            email_entry = Email(
                account_id=account_id,
                folder=folder,
                message_id=msg_id,
                subject=_clean_str(subject),
                sender_name=_clean_str(sender_name),
                sender_email=_clean_str(sender_email),
                recipients_to=_clean_str(
                    _decode_mime(msg.get("To", ""))
                ),
                recipients_cc=_clean_str(
                    _decode_mime(msg.get("Cc", ""))
                ),
                recipients_bcc=_clean_str(
                    _decode_mime(msg.get("Bcc", ""))
                ),
                date=date,
                received_date=date,
                body_text=_clean_str(text)[:500000],
                body_html=_clean_str(html)[:500000],
                raw=raw_bytes,
                has_attachments=bool(attachments),
                is_read=is_read,
                is_imported=True,
                imported_from=p.name,
            )
            session.add(email_entry)
            session.flush()

            for filename, content_type, content_id, payload in attachments:
                attachment = Attachment(
                    email_id=email_entry.id,
                    filename=filename,
                    content_type=content_type,
                    content_id=content_id,
                    size=len(payload),
                    data=payload,
                )
                session.add(attachment)

            count = 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return count
