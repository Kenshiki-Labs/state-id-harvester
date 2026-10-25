"""Safely restore a prior library using Python's data extraction filter."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive_directory", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    index = json.loads((args.archive_directory / "library-index.json").read_text())
    for part in index:
        if Path(part["name"]).name != part["name"]:
            raise ValueError("Invalid archive part name")
        path = args.archive_directory / part["name"]
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != part["sha256"] or path.stat().st_size != part["size_bytes"]:
            raise ValueError("Archive part failed integrity verification")
    for part in index:
        with tarfile.open(args.archive_directory / part["name"], "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.issym() or member.islnk():
                    raise ValueError("Only regular files are permitted in library snapshots")
                path = (args.destination / member.name).resolve()
                if not path.is_relative_to(args.destination.resolve()):
                    raise ValueError("Archive path escapes output directory")
            archive.extractall(args.destination, filter="data")


if __name__ == "__main__":
    main()
