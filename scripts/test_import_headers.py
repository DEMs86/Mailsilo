"""Regression test: attachments with awkward header encodings must import.

Two shapes used to crash or corrupt the archive:

1. ``Content-Disposition`` that needs RFC 2047 decoding — under the compat32
   policy Python returns an ``email.header.Header`` object, so the importer's
   ``.lower()`` raised AttributeError and the message failed with HTTP 500.
2. ``filename="Отчёт.docx"`` written as raw cp1251 bytes (no encoding
   declared) — ``get_filename()`` returned mojibake instead of the name.

Usage:  python scripts/test_import_headers.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as database  # noqa: E402
from app.importers.eml import import_eml  # noqa: E402
from test_yandex_import import DDL  # noqa: E402

# RFC 2047 encoded filename: the parser hands back a Header object.
ENCODED = (
    "From: sender@example.com\r\n"
    "To: box@example.com\r\n"
    "Subject: encoded attachment name\r\n"
    "Date: Mon, 05 Feb 2024 10:00:00 +0300\r\n"
    "Message-ID: <encoded-1@test.local>\r\n"
    "MIME-Version: 1.0\r\n"
    'Content-Type: multipart/mixed; boundary="B1"\r\n'
    "\r\n"
    "--B1\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\n"
    "body\r\n"
    "--B1\r\n"
    "Content-Type: application/pdf\r\n"
    'Content-Disposition: attachment; filename="=?utf-8?B?0J7RgtGH0ZHRgi5wZGY=?="\r\n'
    "Content-Transfer-Encoding: base64\r\n\r\n"
    "JVBERi0xLjQK\r\n"
    "--B1--\r\n"
).encode()

# Raw cp1251 bytes inside the header, no encoding declared at all.
RAW_1251 = (
    b"From: sender@example.com\r\n"
    b"To: box@example.com\r\n"
    b"Subject: raw 8-bit attachment name\r\n"
    b"Date: Mon, 05 Feb 2024 10:00:00 +0300\r\n"
    b"Message-ID: <raw-1@test.local>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="B2"\r\n'
    b"\r\n"
    b"--B2\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"body\r\n"
    b"--B2\r\n"
    b"Content-Type: application/pdf\r\n"
    b'Content-Disposition: attachment; filename="' + "Объявление.docx".encode("cp1251") + b'"\r\n'
    b"Content-Transfer-Encoding: base64\r\n\r\n"
    b"JVBERi0xLjQK\r\n"
    b"--B2--\r\n"
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="import_headers_"))
    engine = create_engine(f"sqlite:///{tmp / 'h.db'}")
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    database._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(("  OK   " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    print("1. Вложение с RFC 2047-именем (раньше — 500 AttributeError)")
    path = tmp / "encoded.eml"
    path.write_bytes(ENCODED)
    try:
        imported = import_eml(path, account_email="box@example.com", folder="Inbox")
        check("импорт не упал", imported == 1, f"imported={imported}")
    except Exception as exc:  # noqa: BLE001 - that is exactly what we test
        check("импорт не упал", False, f"{type(exc).__name__}: {exc}")

    print("2. Вложение с сырым cp1251-именем (раньше — мусор вместо имени)")
    raw_path = tmp / "raw1251.eml"
    raw_path.write_bytes(RAW_1251)
    try:
        imported = import_eml(raw_path, account_email="box@example.com", folder="Inbox")
        check("импорт не упал", imported == 1, f"imported={imported}")
    except Exception as exc:  # noqa: BLE001
        check("импорт не упал", False, f"{type(exc).__name__}: {exc}")

    with database._SessionLocal() as session:
        names = [row[0] for row in session.execute(text("SELECT filename FROM attachments"))]
    print("   имена вложений в базе:", names)
    check("имя из RFC 2047 декодировано", "Отчёт.pdf" in names, str(names))
    check("имя из cp1251 декодировано", "Объявление.docx" in names, str(names))
    check("мусорных символов нет",
          not any("\ufffd" in n or any(0xD800 <= ord(c) <= 0xDFFF for c in n) for n in names),
          str(names))

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {failures}")
        return 1
    print("ВСЁ ПРОЙДЕНО")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
