#!/usr/bin/env python3
"""Import a yandex-mail-export dump from the command line.

Useful when the dump already lives on the server (run it inside the
container, next to the app code):

    docker exec -it mailsilo python scripts/import_yandex_dump.py \
        /app/data/yandex-dump --email AkulovDmE@yandex.ru

Both a directory and a .zip archive are accepted. Folders, read flags and
dates are preserved; re-running is safe (messages are deduplicated by
message_id + account + folder).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.importers.yandex_dump import import_yandex_dump  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="каталог дампа или .zip")
    ap.add_argument("--account-id", type=int, default=0, help="id существующего аккаунта")
    ap.add_argument("--email", default="", help="адрес ящика: аккаунт будет найден или создан")
    args = ap.parse_args()

    if not args.account_id and not args.email:
        ap.error("укажите --account-id или --email")

    last = [0]

    def progress(current: int, total: int) -> None:
        # One line, overwritten in place, so a long import stays readable.
        step = max(1, total // 100)
        if current == total or current - last[0] >= step:
            last[0] = current
            print(f"\r  {current}/{total} ({current * 100 // max(total, 1)}%)", end="", flush=True)

    result = import_yandex_dump(
        args.source,
        account_id=args.account_id,
        account_email=args.email,
        progress_cb=progress,
    )
    print()

    print(f"Писем в манифесте: {result['total']}")
    print(f"Импортировано:     {result['imported']}")
    print(f"Уже было:          {result['skipped']}")
    print(f"Ошибок:            {result['failed']}")
    print(f"Аккаунт id:        {result['account_id']}")
    if result["folders"]:
        print("Папки:")
        for name, count in sorted(result["folders"].items()):
            print(f"  {name}: {count}")
    for error in result["errors"]:
        print(f"  ! {error}")

    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
