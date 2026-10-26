"""Regression test: non-ASCII attachment names must not break downloads.

Reproduces the old behaviour (HTTP 500 + UnicodeEncodeError in the server log)
and asserts the RFC 5987 fix, on SQLite, without a running MailSilo.

Usage:  python scripts/test_attachment_names.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as database  # noqa: E402
from app.api import emails as emails_api  # noqa: E402
from app.api.deps import get_current_user  # noqa: E402
from test_yandex_import import DDL  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="att_names_"))
    engine = create_engine(f"sqlite:///{tmp / 'att.db'}")
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    database._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with database._SessionLocal() as s:
        s.execute(text(
            "INSERT INTO accounts (id, name, email, imap_server, enabled, is_imported, folders) "
            "VALUES (1, 'Тест', 'box@example.com', 'mail.example.com', 0, 1, 'INBOX')"
        ))
        s.execute(text(
            "INSERT INTO emails (id, account_id, folder, message_id, subject, sender_email, "
            "body_text, is_read, is_imported) VALUES "
            "(1, 1, 'Inbox', '<m1@test>', 'Печать документа', 'a@b.c', 'тело', 1, 1)"
        ))
        s.execute(text(
            "INSERT INTO attachments (id, email_id, filename, content_type, size, data) VALUES "
            "(1, 1, 'печать.docx', 'application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document', 4, :blob)"
        ), {"blob": b"PK\x03\x04"})
        s.execute(text(
            "INSERT INTO attachments (id, email_id, filename, content_type, size, data) VALUES "
            "(2, 1, 'plain.pdf', 'application/pdf', 4, :blob)"
        ), {"blob": b"%PDF"})
        s.commit()

    app = FastAPI()
    app.include_router(emails_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "t", "is_admin": True}
    client = TestClient(app, raise_server_exceptions=False)

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(("  OK   " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    print("1. Скачивание вложения с кириллическим именем")
    resp = client.get("/api/emails/1/attachment/1")
    check("статус 200", resp.status_code == 200, f"получен {resp.status_code}: {resp.text[:120]}")
    check("байты вложения совпадают", resp.content == b"PK\x03\x04", repr(resp.content[:20]))
    disposition = resp.headers.get("content-disposition", "")
    check("filename* с UTF-8 именем", "filename*=UTF-8''" in disposition, disposition)
    check("имя закодировано (percent-encoding)", "%D0%BF%D0%B5%D1%87%D0%B0%D1%82%D1%8C" in disposition,
          disposition)
    check("ASCII-фолбэк присутствует", 'filename="' in disposition, disposition)
    print(f"     заголовок: {disposition}")

    print("2. ASCII-имя не сломано")
    resp = client.get("/api/emails/1/attachment/2")
    check("статус 200", resp.status_code == 200, str(resp.status_code))
    check("filename остался plain.pdf", 'filename="plain.pdf"' in resp.headers.get("content-disposition", ""),
          resp.headers.get("content-disposition", ""))

    print("3. Экспорт письма с кириллической темой")
    resp = client.get("/api/emails/1/export")
    check("статус 200", resp.status_code == 200, f"получен {resp.status_code}: {resp.text[:120]}")
    check("filename* в заголовке", "filename*=UTF-8''" in resp.headers.get("content-disposition", ""),
          resp.headers.get("content-disposition", ""))

    print("\n" + ("ВСЁ ПРОЙДЕНО" if not failures else f"ПРОВАЛЕНО: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
