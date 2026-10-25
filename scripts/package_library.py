"""Create verified private snapshot archives; no public release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

from state_id_harvester.library import read_manifest, verify
from state_id_harvester.models import Manifest
from state_id_harvester.paths import contained_path, managed_path


def retained_derivatives(manifest: Manifest, prefix: Path = Path()) -> set[str]:
    paths = {
        str(prefix / asset.path) for document in manifest.documents for asset in document.assets
    }
    paths.update(
        str(prefix / Path(document.assets[0].path).parents[1] / "document.json")
        for document in manifest.documents
        if document.assets
    )
    return paths


def included_file(relative: Path, derivatives: set[str], run_id: str) -> bool:
    if any(part.startswith(".") for part in relative.parts):
        return False
    if "derived" in relative.parts and relative.as_posix() not in derivatives:
        return False
    if relative.parts[0] == "runs" and relative.name == "manifest.json":
        return relative.parts[1] == run_id
    return True


def snapshot_files(source: Path) -> list[list[Path]]:
    manifest = read_manifest(source)
    derivatives = retained_derivatives(manifest)
    federal = source / "federal"
    if (federal / "manifest.json").is_file():
        errors = verify(federal)
        if errors:
            raise ValueError("\n".join(errors))
        derivatives.update(retained_derivatives(read_manifest(federal), Path("federal")))
    parts: list[list[Path]] = [[]]
    size = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Library archives must not contain symlinks")
        if not path.is_file() or not included_file(
            path.relative_to(source), derivatives, manifest.run_id
        ):
            continue
        if parts[-1] and size + path.stat().st_size > 900_000_000:
            parts.append([])
            size = 0
        parts[-1].append(path)
        size += path.stat().st_size
    return parts


def write_archive(source: Path, destination: Path, number: int, files: list[Path]) -> dict:
    name = f"library-{number:03}.tar.gz"
    path = contained_path(destination, name)
    with tarfile.open(path, "w:gz", compresslevel=1) as target:
        for asset in files:
            relative = asset.relative_to(source)
            checked = contained_path(source, relative)
            target.add(checked, arcname=relative.as_posix(), recursive=False)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"name": name, "sha256": checksum, "size_bytes": path.stat().st_size}


def package_library(source: Path, destination: Path) -> None:
    source, destination = managed_path(source), managed_path(destination)
    if destination.is_relative_to(source):
        raise ValueError("Snapshot destination must be outside its source directory")
    errors = verify(source)
    if errors:
        raise ValueError("\n".join(errors))
    parts = snapshot_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    index = [write_archive(source, destination, n, files) for n, files in enumerate(parts, 1)]
    contained_path(destination, "library-index.json").write_text(json.dumps(index, indent=2) + "\n")
    contained_path(destination, "SHA256SUMS").write_text(
        "".join(f"{p['sha256']}  {p['name']}\n" for p in index)
    )
    for part in index:
        print(
            f"Private archive: {part['name']}; {part['size_bytes']:,} bytes; "
            f"SHA-256 {part['sha256']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=managed_path)
    parser.add_argument("destination", type=managed_path)
    args = parser.parse_args()
    package_library(args.source, args.destination)


if __name__ == "__main__":
    main()
