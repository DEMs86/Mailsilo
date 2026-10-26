"""Import a yandex-mail-export dump (manifest.jsonl + <Folder>/<mid>.eml).

The generic EML importer stores every message in one folder and cannot keep
the read flag, because a single .eml upload does not carry that context. A
dump produced by https://github.com/leksuss/yandex-mail-export does carry it
in ``manifest.jsonl``::

    {"mid": "...", "folder": "Inbox", "unread": false,
     "timestamp": 1712345678, "path": "Inbox/123.eml"}

This module walks that manifest and imports each message into its original
folder, with its original read flag and date, into a single account.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_session
from app.importers.eml import ensure_import_account, import_eml

MANIFEST_NAME = "manifest.jsonl"
PROGRESS_EVERY = 25


def _find_root(base: Path) -> Path:
    """Locate the directory that contains manifest.jsonl.

    Accepts both a dump directory and an archive where the dump is nested one
    level deep (the usual result of zipping the dump folder itself).
    """
    if (base / MANIFEST_NAME).is_file():
        return base
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / MANIFEST_NAME).is_file():
            return child
    raise FileNotFoundError(
        f"{MANIFEST_NAME} not found in {base} or its direct subdirectories"
    )


def _entry_date(entry: dict) -> datetime | None:
    """manifest.timestamp is a unix timestamp (seconds or milliseconds)."""
    raw = entry.get("timestamp")
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # Yandex sometimes reports milliseconds.
    if value > 10_000_000_000:
        value /= 1000.0
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def import_yandex_dump(
    source: str | Path,
    account_id: int = 0,
    account_email: str = "",
    progress_cb=None,
) -> dict:
    """Import a dump directory or a .zip of it.

    ``account_id`` wins; otherwise ``account_email`` selects (or creates) one
    archive-only account for the whole mailbox, so a migration does not
    explode into one account per sender or per folder.
    """
    source = Path(source)
    tmpdir: Path | None = None

    try:
        if zipfile.is_zipfile(source):
            tmpdir = Path(tempfile.mkdtemp(prefix="mailsilo_yadump_"))
            with zipfile.ZipFile(source) as zf:
                _safe_extract(zf, tmpdir)
            root = _find_root(tmpdir)
        else:
            root = _find_root(source)

        manifest_path = root / MANIFEST_NAME
        entries: list[dict] = []
        with manifest_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        total = len(entries)
        imported = skipped = failed = 0
        errors: list[str] = []
        per_folder: dict[str, int] = {}

        if account_id == 0 and account_email:
            session = get_session()
            try:
                account_id = ensure_import_account(session, account_email)
                session.commit()
            finally:
                session.close()

        for index, entry in enumerate(entries, 1):
            rel = entry.get("path") or ""
            mid = entry.get("mid") or ""
            folder = (entry.get("folder") or "Imported").strip() or "Imported"

            if not rel:
                rel = f"{folder}/{mid}.eml"
            path = root / rel

            if not path.is_file():
                failed += 1
                if len(errors) < 100:
                    errors.append(f"missing file: {rel}")
                continue

            try:
                created = import_eml(
                    path,
                    account_id=account_id,
                    folder=folder,
                    is_read=not bool(entry.get("unread")),
                    fallback_date=_entry_date(entry),
                    account_email="" if account_id else account_email,
                )
            except Exception as exc:  # keep going, report at the end
                failed += 1
                if len(errors) < 100:
                    errors.append(f"{rel}: {exc}")
                continue

            if created:
                imported += 1
                per_folder[folder] = per_folder.get(folder, 0) + 1
            else:
                skipped += 1

            if progress_cb and (index % PROGRESS_EVERY == 0 or index == total):
                progress_cb(index, total)

        return {
            "total": total,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
            "folders": per_folder,
            "account_id": account_id,
        }
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """Extract while refusing entries that escape the target directory."""
    target = target.resolve()
    for member in zf.infolist():
        name = member.filename
        # Skip macOS resource forks and absolute/escaping paths.
        if name.startswith("__MACOSX/") or "__MACOSX" in name:
            continue
        dest = (target / name).resolve()
        if dest != target and target not in dest.parents:
            continue
        if member.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
