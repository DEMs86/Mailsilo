"""HTTP-level smoke test for POST /api/import/yandex-dump.

Boots a minimal FastAPI app that mounts only the import router, backed by a
throwaway SQLite database, and uploads a real dump archive through the same
multipart request the client will use against the live MailSilo.

Usage:  python scripts/test_import_endpoint.py
"""

from __future__ import annotations

import io
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database as database  # noqa: E402
from app.api.deps import get_current_user  # noqa: E402
from app.api import imports as imports_api  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from test_yandex_import import DDL, build_dump  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="yaapi_test_"))
    engine = create_engine(f"sqlite:///{tmp / 'api.db'}")
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    database._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    dump = tmp / "dump"
    build_dump(dump)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in dump.rglob("*"):
            zf.write(path, "dump/" + str(path.relative_to(dump)))

    app = FastAPI()
    app.include_router(imports_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"username": "tester", "is_admin": True}

    client = TestClient(app)
    resp = client.post(
        "/api/import/yandex-dump",
        files={"file": ("dump.zip", buf.getvalue(), "application/zip")},
        data={"account_email": "AkulovDmE@yandex.ru"},
    )
    print("POST /api/import/yandex-dump ->", resp.status_code)
    if resp.status_code != 200:
        print(resp.text)
        return 1
    task_id = resp.json()["task_id"]

    state = None
    for _ in range(100):
        state = client.get(f"/api/import/status/{task_id}").json()
        if state.get("status") in ("done", "error"):
            break
        time.sleep(0.1)

    print("status:", {k: state.get(k) for k in ("status", "imported", "skipped", "failed", "total", "folders", "account_id")})
    ok = (
        state.get("status") == "done"
        and state.get("imported") == 3
        and state.get("failed") == 0
        and state.get("account_id")
    )
    print("OK" if ok else "FAIL", "— эндпоинт создал аккаунт и разложил письма по папкам")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
