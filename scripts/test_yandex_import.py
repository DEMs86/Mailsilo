"""Offline smoke test for the yandex-dump importer.

Runs the real importer against a throwaway SQLite database (the production
schema is PostgreSQL, so tables are created with equivalent DDL by hand) and
checks that folders, read flags, dates, attachments and idempotency survive.

Usage:  python scripts/test_yandex_import.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as database  # noqa: E402

DDL = """
CREATE TABLE accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255), email VARCHAR(255) UNIQUE,
  imap_server VARCHAR(255), imap_port INTEGER, imap_use_ssl BOOLEAN, username VARCHAR(255),
  password_encrypted TEXT, folders TEXT, enabled BOOLEAN, sync_interval VARCHAR(10),
  last_fetch TIMESTAMP, oauth_provider VARCHAR(50), oauth_refresh_token TEXT,
  oauth_token_expiry TIMESTAMP, smtp_server VARCHAR(255), smtp_port INTEGER,
  smtp_use_ssl BOOLEAN, smtp_username VARCHAR(255), smtp_password_encrypted TEXT,
  is_imported BOOLEAN, created_at TIMESTAMP
);
CREATE TABLE emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, folder VARCHAR(255),
  uid INTEGER, uidvalidity INTEGER, message_id VARCHAR(512), subject VARCHAR(512),
  sender_name VARCHAR(255), sender_email VARCHAR(255), recipients_to TEXT,
  recipients_cc TEXT, recipients_bcc TEXT, date TIMESTAMP, received_date TIMESTAMP,
  body_text TEXT, body_html TEXT, raw BLOB, has_attachments BOOLEAN, is_read BOOLEAN,
  is_flagged BOOLEAN, is_imported BOOLEAN, imported_from VARCHAR(255),
  search_vector TEXT, created_at TIMESTAMP
);
CREATE TABLE attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email_id INTEGER, filename VARCHAR(512),
  content_type VARCHAR(255), content_id VARCHAR(255), size INTEGER, data BLOB,
  file_path VARCHAR(1024), created_at TIMESTAMP
);
"""


def eml(subject: str, sender: str, date: str | None, body: str, attachment: bool = False) -> bytes:
    headers = [f"From: {sender}", f"To: AkulovDmE@yandex.ru", f"Subject: =?utf-8?B?{_b64(subject)}?="]
    if date:
        headers.append(f"Date: {date}")
    headers.append(f"Message-ID: <{abs(hash((subject, sender, date))) }@test.local>")
    if not attachment:
        return ("\r\n".join(headers) + "\r\nMIME-Version: 1.0\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body + "\r\n").encode()
    boundary = "BOUNDARY42"
    headers.append("MIME-Version: 1.0")
    headers.append(f'Content-Type: multipart/mixed; boundary="{boundary}"')
    payload = (
        f"\r\n--{boundary}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
        f'\r\n--{boundary}\r\nContent-Type: application/pdf; name="doc.pdf"\r\n'
        'Content-Disposition: attachment; filename="doc.pdf"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQK\r\n"
        f"--{boundary}--\r\n"
    )
    return ("\r\n".join(headers) + payload).encode()


def _b64(value: str) -> str:
    import base64

    return base64.b64encode(value.encode()).decode()


def build_dump(base: Path) -> None:
    (base / "Inbox").mkdir(parents=True)
    (base / "Sent").mkdir()
    (base / "Inbox" / "1.eml").write_bytes(
        eml("Прочитанное письмо", "Ivan <ivan@example.com>", "Mon, 05 Feb 2024 10:00:00 +0300", "privet")
    )
    (base / "Inbox" / "2.eml").write_bytes(
        eml("Непрочитанное с вложением", "petr@example.com", "Tue, 06 Feb 2024 11:30:00 +0300", "file", True)
    )
    # No Date header: the manifest timestamp must be used instead.
    (base / "Sent" / "3.eml").write_bytes(
        eml("Письмо без даты", "AkulovDmE@yandex.ru", None, "sent body")
    )
    stamp = int(datetime(2023, 12, 31, 21, 15, tzinfo=timezone.utc).timestamp())
    lines = [
        {"mid": "1", "folder": "Inbox", "unread": False, "timestamp": stamp, "path": "Inbox/1.eml"},
        {"mid": "2", "folder": "Inbox", "unread": True, "timestamp": stamp, "path": "Inbox/2.eml"},
        {"mid": "3", "folder": "Отправленные", "unread": True, "timestamp": stamp * 1000,
         "path": "Sent/3.eml"},
    ]
    (base / "manifest.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="yadump_test_"))
    db_path = tmp / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    database._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    from app.importers.yandex_dump import import_yandex_dump

    dump = tmp / "dump"
    build_dump(dump)
    zip_path = tmp / "dump.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for path in dump.rglob("*"):
            zf.write(path, path.relative_to(dump.parent))

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(("  OK   " if cond else "  FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    print("1. Импорт из каталога (папка дампа )…")
    first = import_yandex_dump(dump, account_email="AkulovDmE@yandex.ru")
    check("импортировано 3 письма", first["imported"] == 3, str(first))
    check("ошибок нет", first["failed"] == 0, str(first["errors"]))

    with database._SessionLocal() as s:
        accounts = s.execute(text("SELECT id, email, is_imported, enabled FROM accounts")).all()
        check("создан ровно один аккаунт", len(accounts) == 1, str(accounts))
        check("аккаунт помечен imported и выключен",
              bool(accounts[0][2]) and not bool(accounts[0][3]), str(accounts))
        check("email аккаунта — адрес ящика", accounts[0][1] == "AkulovDmE@yandex.ru")

        rows = s.execute(text(
            "SELECT folder, is_read, date, subject, has_attachments FROM emails ORDER BY id"
        )).all()
        by_subject = {r[3]: r for r in rows}
        check("письмо из Inbox в папке Inbox", "Inbox" in {r[0] for r in rows}, str(rows))
        check("папка «Отправленные» сохранена (как в манифесте)",
              "Отправленные" in {r[0] for r in rows}, str(rows))
        read_row = [r for r in rows if "Прочитанное" in r[3]][0]
        unread_row = [r for r in rows if "Непрочитанное" in r[3]][0]
        check("прочитанное осталось прочитанным", read_row[1] is True or read_row[1] == 1, str(read_row))
        check("непрочитанное осталось непрочитанным", unread_row[1] in (False, 0), str(unread_row))

        no_date = [r for r in rows if "без даты" in r[3]][0]
        check("дата подставлена из manifest.timestamp (мс)", no_date[2] is not None, str(no_date))
        if no_date[2] is not None:
            got = no_date[2]
            if isinstance(got, str):
                got = datetime.fromisoformat(got)
            check("дата из манифеста верна",
                  abs((got - datetime(2023, 12, 31, 21, 15)).total_seconds()) < 5, str(no_date[2]))

        atts = s.execute(text("SELECT filename, size FROM attachments")).all()
        check("вложение перенесено", len(atts) == 1 and atts[0][1] > 0, str(atts))
        check("флаг has_attachments выставлен", bool(unread_row[4]))

    print("2. Повторный импорт того же дампа (идемпотентность)…")
    second = import_yandex_dump(dump, account_email="AkulovDmE@yandex.ru")
    check("ничего не задублировано", second["imported"] == 0 and second["skipped"] == 3, str(second))

    print("3. Импорт из ZIP (папка дампа внутри архива)…")
    third = import_yandex_dump(zip_path, account_email="AkulovDmE@yandex.ru")
    check("zip распознан и не задублирован",
          third["imported"] == 0 and third["total"] == 3, str(third))

    print("4. Импорт из ZIP в новый аккаунт…")
    fourth = import_yandex_dump(zip_path, account_email="other@example.com")
    check("новый ящик = новый аккаунт с 3 письмами",
          fourth["imported"] == 3, str(fourth))
    check("в новом аккаунте правильные папки",
          set(fourth["folders"]) == {"Inbox", "Отправленные"}, str(fourth["folders"]))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)} -> {failures}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
