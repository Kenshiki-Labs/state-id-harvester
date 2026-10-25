from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest

from state_id_harvester.ocr import ocr_page


def test_oversized_page_is_tiled_without_exceeding_pixel_budget(tmp_path: Path) -> None:
    from test_extraction import fixture_pdf

    from state_id_harvester.extract import extract
    from state_id_harvester.models import Options

    download = fixture_pdf(tmp_path)
    document = extract(
        download,
        str(tmp_path),
        Options(dpi=100, max_pixels=500_000, max_render_pages=1, detect_boundaries=False),
    )
    plates = [a for a in document.assets if a.kind == "page_render"]
    assert len(plates) > 1
    assert all(a.width * a.height <= 500_000 for a in plates)
    geometry = next(a for a in document.assets if a.path.endswith("geometry/pages.json"))
    pages = json.loads((tmp_path / geometry.path).read_text())
    assert pages[1]["render_tiles"]
    assert all(t["dpi"] == 100 for t in pages[1]["render_tiles"])


def test_local_ocr_maps_words_to_unrotated_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("state_id_harvester.ocr.shutil.which", lambda _: "/test/tesseract")
    tsv = (
        b"level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        b"5\t1\t1\t1\t1\t1\t100\t100\t80\t20\t95.0\tTactile\n"
    )

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=tsv, stderr=b"")

    monkeypatch.setattr("state_id_harvester.ocr.subprocess.run", run)
    with pymupdf.open() as document:
        page = document.new_page(width=100, height=100)
        blocks, raw = ocr_page(page, 1)
    assert raw == tsv
    assert blocks[0].method == "local_ocr"
    assert blocks[0].text == "Tactile"
    assert blocks[0].ocr_confidence == 95.0
    assert blocks[0].bbox == pytest.approx((28.8, 28.8, 51.84, 34.56))


def test_archive_restore_rejects_traversal(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    part = incoming / "library-001.tar.gz"
    with tarfile.open(part, "w:gz") as archive:
        member = tarfile.TarInfo("../outside.txt")
        member.size = 4
        archive.addfile(member, BytesIO(b"evil"))
    index = [
        {
            "name": part.name,
            "sha256": hashlib.sha256(part.read_bytes()).hexdigest(),
            "size_bytes": part.stat().st_size,
        }
    ]
    (incoming / "library-index.json").write_text(json.dumps(index))
    result = subprocess.run(
        [sys.executable, "scripts/unpack_library.py", str(incoming), str(tmp_path / "output")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "escapes" in result.stderr
    assert not (tmp_path / "outside.txt").exists()


def test_archive_restore_rejects_modified_part(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    part = incoming / "library-001.tar.gz"
    part.write_bytes(b"modified")
    (incoming / "library-index.json").write_text(
        json.dumps([{"name": part.name, "sha256": "0" * 64, "size_bytes": 8}])
    )
    result = subprocess.run(
        [sys.executable, "scripts/unpack_library.py", str(incoming), str(tmp_path / "output")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "integrity" in result.stderr
