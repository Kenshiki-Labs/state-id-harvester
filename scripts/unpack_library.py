"""Safely restore a prior library using Python's data extraction filter."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

from state_id_harvester.paths import contained_path, managed_path


def snapshot_parts(archive_directory: Path) -> list[dict]:
    index_path = archive_directory / "library-index.json"
    if index_path.is_symlink():
        raise ValueError("Snapshot index must not be a symlink")
    index = json.loads(index_path.read_text())
    if not isinstance(index, list) or not index or len(index) > 100:
        raise ValueError("Snapshot index must contain 1 through 100 archive parts")
    names = [part["name"] for part in index]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate archive part")
    for part in index:
        verify_part(archive_directory, part)
    return index


def verify_part(archive_directory: Path, part: dict) -> None:
    if not re.fullmatch(r"library-[0-9]{3,}\.tar\.gz", part["name"]):
        raise ValueError("Invalid archive part name")
    path = contained_path(archive_directory, part["name"])
    if path.is_symlink() or not path.is_file():
        raise ValueError("Archive part missing or unsafe")
    if not re.fullmatch(r"[a-f0-9]{64}", part["sha256"]):
        raise ValueError("Invalid archive digest")
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != part["sha256"] or path.stat().st_size != part["size_bytes"]:
        raise ValueError("Archive part failed integrity verification")


def inspect_archive(path: Path, destination: Path, names: set[str]) -> tuple[int, int]:
    expanded_bytes = 0
    member_count = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                raise ValueError("Only regular files are permitted in library snapshots")
            resolved = (destination / member.name).resolve()
            if not resolved.is_relative_to(destination.resolve()) or ".." in member.name.split("/"):
                raise ValueError("Archive path escapes output directory")
            normalized = str(resolved)
            if normalized in names:
                raise ValueError("Duplicate archive member")
            names.add(normalized)
            expanded_bytes += member.size
            member_count += 1
            if expanded_bytes > 40 * 1024**3 or member_count > 100_000:
                raise ValueError("Expanded snapshot exceeds restore budget")
    return expanded_bytes, member_count


def restore_library(archive_directory: Path, destination: Path) -> None:
    archive_directory, destination = managed_path(archive_directory), managed_path(destination)
    index = snapshot_parts(archive_directory)
    # Validate every part before writing anything to the destination.
    expanded_bytes = 0
    member_count = 0
    names: set[str] = set()
    for part in index:
        size, count = inspect_archive(archive_directory / part["name"], destination, names)
        expanded_bytes += size
        member_count += count
        if expanded_bytes > 40 * 1024**3 or member_count > 100_000:
            raise ValueError("Expanded snapshot exceeds restore budget")
    destination.mkdir(parents=True, exist_ok=True)
    for part in index:
        with tarfile.open(archive_directory / part["name"], "r:gz") as archive:
            archive.extractall(destination, filter="data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_directory", type=managed_path)
    parser.add_argument("destination", type=managed_path)
    args = parser.parse_args()
    restore_library(args.archive_directory, args.destination)


if __name__ == "__main__":
    main()
