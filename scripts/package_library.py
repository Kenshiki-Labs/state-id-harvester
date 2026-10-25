"""Create a checked release archive without locks, partial files, or absolute paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

from state_id_harvester.library import read_manifest, verify


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    errors = verify(args.source)
    if errors:
        raise SystemExit("\n".join(errors))
    args.destination.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(args.source)
    current_derived = {a.path for d in manifest.documents for a in d.assets}
    current_derived.update(
        str(Path(d.assets[0].path).parents[1] / "document.json")
        for d in manifest.documents
        if d.assets
    )
    parts: list[list[Path]] = [[]]
    part_size = 0
    for path in sorted(args.source.rglob("*")):
        relative = path.relative_to(args.source)
        if path.is_symlink():
            raise ValueError("Library archives must not contain symlinks")
        if not path.is_file() or any(p.startswith(".") for p in relative.parts):
            continue
        if "derived" in relative.parts and relative.as_posix() not in current_derived:
            continue
        if (
            relative.parts[0] == "runs"
            and path.name == "manifest.json"
            and relative.parts[1] != manifest.run_id
        ):
            continue
        size = path.stat().st_size
        if parts[-1] and part_size + size > 900_000_000:
            parts.append([])
            part_size = 0
        parts[-1].append(path)
        part_size += size
    index: list[dict[str, str | int]] = []
    for number, files in enumerate(parts, start=1):
        archive = args.destination / f"library-{number:03}.tar.gz"
        with tarfile.open(archive, "w:gz", compresslevel=1) as target:
            for path in files:
                target.add(path, arcname=path.relative_to(args.source).as_posix(), recursive=False)
        with archive.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        index.append(
            {"name": archive.name, "sha256": checksum, "size_bytes": archive.stat().st_size}
        )
        print(f"{archive}: {archive.stat().st_size:,} bytes; SHA-256 {checksum}")
    (args.destination / "library-index.json").write_text(json.dumps(index, indent=2) + "\n")
    (args.destination / "SHA256SUMS").write_text(
        "".join(f"{p['sha256']}  {p['name']}\n" for p in index)
    )


if __name__ == "__main__":
    main()
