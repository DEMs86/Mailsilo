
from __future__ import annotations

import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Callable


from app.importers.eml import import_eml


def _check_readpst(readpst_path: str = "readpst") -> bool:
    """Check that readpst exists and can be executed."""
    executable = shutil.which(readpst_path)

    if executable is None:
        return False

    try:
        subprocess.run(
            [executable, "--version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def import_pst(
    filepath: str | Path,
    account_id: int = 0,
    readpst_path: str = "readpst",
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> tuple[int, list[str]]:
    return _import_with_readpst(
        filepath,
        account_id,
        readpst_path,
        progress_cb,
    )


def import_ost(
    filepath: str | Path,
    account_id: int = 0,
    readpst_path: str = "readpst",
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> tuple[int, list[str]]:
    return _import_with_readpst(
        filepath,
        account_id,
        readpst_path,
        progress_cb,
    )


def _import_with_readpst(
    filepath: str | Path,
    account_id: int = 0,
    readpst_path: str = "readpst",
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> tuple[int, list[str]]:
    src = Path(filepath)

    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")

    if not _check_readpst(readpst_path):
        raise RuntimeError(
            f"readpst is unavailable or not working: {readpst_path}"
        )

    if progress_cb:
        progress_cb(0, 0, "Extracting mail with readpst...")

    imported = 0
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="mailsilo-pst-") as tmpdir:
        output_dir = Path(tmpdir)

        cmd = [
            readpst_path,
            "-r",
            "-e",
            "-o",
            str(output_dir),
            "-D",
            str(src.resolve()),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"readpst timed out while processing {src.name}"
            ) from exc

        # Decode diagnostics defensively: they may contain non-UTF-8 bytes.
        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")

        if result.returncode != 0:
            raise RuntimeError(
                f"readpst failed (rc={result.returncode}): {stderr}"
            )

        eml_files = sorted(
            path
            for path in output_dir.rglob("*")
            if path.is_file() and path.suffix.lower() == ".eml"
        )
        total_files = len(eml_files)

        if total_files == 0:
            detail = stderr.strip() or stdout.strip() or "No EML files found"
            raise RuntimeError(
                f"readpst did not produce any EML files for "
                f"{src.name}: {detail}"
            )

        if progress_cb:
            progress_cb(0, total_files, "Importing extracted messages...")

        for index, eml_path in enumerate(eml_files, start=1):
            try:
                # Derive the mail folder from readpst's output directory tree.
                relative_parent = eml_path.parent.relative_to(output_dir)
                folder_parts = [
                    part for part in relative_parent.parts if part not in ("", ".")
                ]

                if folder_parts:
                    folder = "/".join(folder_parts)
                else:
                    folder = "Imported"

                imported += import_eml(
                    eml_path,
                    account_id=account_id,
                    folder=folder,
                )

            except Exception as exc:
                try:
                    display_path = eml_path.relative_to(output_dir)
                except ValueError:
                    display_path = eml_path.name

                errors.append(f"{display_path}: {exc}")

            if progress_cb and (
                index % 5 == 0 or index == total_files
            ):
                progress_cb(
                    index,
                    total_files,
                    f"Importing message {index}/{total_files}",
                )

    return imported, errors


def _check_dependencies() -> list[str]:
    if not _check_readpst():
        return [
            "readpst (install the pst-utils package in the application image)"
        ]
    return []
