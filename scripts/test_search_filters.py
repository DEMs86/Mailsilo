"""Tests for the extended /api/emails filters (sender, recipient, subject, archives, sorting).

Runs against SQLite with the real router — no Postgres and no live server needed.
The full-text `q` path is Postgres-only, so it is covered indirectly through the
ILIKE fallback and is exercised on the live instance instead.

Usage:  python scripts/test_search_filters.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.database as database  # noqa: E402
from app.api import emails as emails_api  # noqa: E402
from app.api.deps import get_current_user  # noqa: E402
from test_yandex_import import DDL  # noqa: E402

ROWS = [
    # (account, folder, subject, sender_name, sender_email, to, cc, date)
    (1, "Входящие", "Отчёт по проекту Пакш", "Иван Петров", "ivan@rosatom.ru", "me@rasu.ru", "", "2026-01-10T09:00:00"),
    (1, "Входящие", "Совещание в среду", "Мария Сидорова", "maria@rosatom.ru", "team@rasu.ru", "boss@rasu.ru", "2026-03-05T15:30:00"),
    (2, "Входящие", "Отчёт по проекту Эль-Дабаа", "Иван Петров", "ivan@rosatom.ru", "me@rasu.ru", "", "2026-02-20T11:00:00"),
    (2, "Отправленные", "Re: Совещание в среду", "Я", "me@rasu.ru", "maria@rosatom.ru", "", "2026-03-06T08:00:00"),
    (2, "Входящие", "Счёт на оплату", "Бухгалтерия", "buh@vendor.ru", "finance@rasu.ru", "", "2025-12-28T18:45:00"),
]


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="search_test_"))
    # get_session() hands out sessions without closing them; NullPool keeps the
    # test from exhausting a real pool before it finishes.
    engine = create_engine(f"sqlite:///{tmp / 's.db'}", poolclass=NullPool)
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        for account in (1, 2):
            conn.execute(text(
                "INSERT INTO accounts (id, name, email, imap_server, enabled, is_imported, folders) "
                f"VALUES ({account}, 'acc{account}', 'acc{account}@test.local', 'mail.test', 0, 1, 'Inbox')"
            ))
        for index, (acct, folder, subject, name, email_addr, to, cc, date) in enumerate(ROWS, 1):
            conn.execute(text(
                "INSERT INTO emails (id, account_id, folder, message_id, subject, sender_name, sender_email, "
                "recipients_to, recipients_cc, date, body_text, is_read, is_imported) VALUES "
                "(:id, :acct, :folder, :mid, :subject, :name, :email, :to, :cc, :date, :body, 1, 1)"
            ), {
                "id": index, "acct": acct, "folder": folder, "mid": f"<m{index}@test>",
                "subject": subject, "name": name, "email": email_addr, "to": to, "cc": cc,
                "date": date, "body": f"тело письма {subject}",
            })
        conn.execute(text(
            "INSERT INTO accounts (id, name, email, imap_server, enabled, is_imported, folders) "
            "VALUES (3, 'empty', 'empty@test.local', 'mail.test', 0, 1, 'Inbox')"
        ))
    database._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(emails_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "t", "is_admin": True}
    client = TestClient(app)

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        print(("  OK   " if condition else "  FAIL ") + name + (f" — {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    def search(**params) -> dict:
        resp = client.get("/api/emails", params={"per_page": 50, **params})
        assert resp.status_code == 200, resp.text
        return resp.json()

    print("1. Фильтр по отправителю")
    data = search(sender="ivan@rosatom")
    check("адрес отправителя", data["total"] == 2, str(data["total"]))
    data = search(sender="Петров")
    check("имя отправителя", data["total"] == 2, str(data["total"]))
    data = search(sender="нет-такого")
    check("пустой результат", data["total"] == 0, str(data["total"]))

    print("2. Фильтр по получателю")
    data = search(recipient="team@rasu.ru")
    check("получатель в To", data["total"] == 1, str(data["total"]))
    data = search(recipient="boss@rasu.ru")
    check("получатель в Cc", data["total"] == 1, str(data["total"]))
    data = search(recipient="maria@rosatom.ru")
    check("получатель в отправленных", data["total"] == 1, str(data["total"]))

    print("3. Фильтр по теме")
    data = search(subject="Отчёт")
    check("подстрока темы", data["total"] == 2, str(data["total"]))
    # SQLite lower() is ASCII-only, so Cyrillic case folding is a Postgres
    # behaviour; it is checked on the live instance instead.
    data = search(sender="IVAN@ROSATOM")
    check("регистронезависимо (ASCII)", data["total"] == 2, str(data["total"]))

    print("4. Выбор архивов")
    data = search(account_ids="1")
    check("один архив", data["total"] == 2, str(data["total"]))
    data = search(account_ids="1,2")
    check("два архива", data["total"] == 5, str(data["total"]))
    data = search(account_ids="1")
    data2 = search(account_id=1)
    check("account_ids и account_id совпадают", data["total"] == data2["total"], f'{data["total"]} vs {data2["total"]}')

    print("5. Комбинация фильтров")
    data = search(sender="ivan@rosatom", account_ids="2")
    check("отправитель + архив", data["total"] == 1, str(data["total"]))
    data = search(sender="ivan@rosatom", subject="Пакш")
    check("отправитель + тема", data["total"] == 1, str(data["total"]))
    data = search(sender="ivan@rosatom", folder="Отправленные")
    check("отправитель + папка", data["total"] == 0, str(data["total"]))

    print("6. Сортировка")
    asc = search(sort_by="date", sort_order="asc")
    desc = search(sort_by="date", sort_order="desc")
    dates_asc = [item["date"] for item in asc["items"]]
    dates_desc = [item["date"] for item in desc["items"]]
    check("по дате возрастание", dates_asc == sorted(dates_asc), str(dates_asc))
    check("по дате убывание", dates_desc == sorted(dates_desc, reverse=True), str(dates_desc))
    subj = search(sort_by="subject", sort_order="asc")
    subs = [item["subject"] for item in subj["items"]]
    check("по теме возрастание", subs == sorted(subs), str(subs))
    rec = search(sort_by="recipient", sort_order="asc")
    check("сортировка по получателю не падает", rec["total"] == 5, str(rec["total"]))

    print("7. Пагинация и счётчик")
    page1 = search(account_ids="1,2", per_page=2, page=1)
    page2 = search(account_ids="1,2", per_page=2, page=2)
    check("total одинаков на страницах", page1["total"] == page2["total"] == 5, f'{page1["total"]}/{page2["total"]}')
    check("страницы не пересекаются",
          not ({i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}))

    print("8. Экспорт MBOX подчиняется тем же фильтрам")
    from app.services.email_service import EmailService
    with database._SessionLocal() as db:
        total_sender = EmailService.get_export_query(None, None, None, db, sender="ivan@rosatom").count()
        total_both = EmailService.get_export_query(None, None, None, db, sender="ivan@rosatom",
                                                   subject="Пакш").count()
        total_archives = EmailService.get_export_query(None, None, None, db, account_ids=[1, 2]).count()
    check("экспорт по отправителю", total_sender == 2, str(total_sender))
    check("экспорт с двумя фильтрами", total_both == 1, str(total_both))
    check("экспорт по списку архивов", total_archives == 5, str(total_archives))

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {failures}")
        return 1
    print("ВСЁ ПРОЙДЕНО")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
