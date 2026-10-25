"""Optional local OCR, bounded by raster size and subprocess time."""

from __future__ import annotations

import csv
import io
import math
import shutil
import subprocess
from collections import defaultdict
from typing import Any

import pymupdf

from .models import TextBlock


def ocr_page(page: Any, number: int) -> tuple[list[TextBlock], bytes]:
    executable = shutil.which("tesseract")
    if executable is None:
        raise RuntimeError("--ocr requires the local tesseract executable")
    scale = min(250 / 72, math.sqrt(6_000_000 / max(page.rect.get_area(), 1)))
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False, annots=False
    )
    result = subprocess.run(
        [executable, "stdin", "stdout", "-l", "eng", "--psm", "11", "tsv"],
        input=pix.tobytes("png"),
        capture_output=True,
        timeout=45,
        check=True,
    )
    if len(result.stdout) > 10_000_000:
        raise ValueError("OCR output exceeds byte budget")
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(result.stdout.decode("utf-8")), delimiter="\t"):
        if row["level"] == "5" and row["text"].strip() and float(row["conf"]) >= 35:
            groups[(row["block_num"], row["par_num"], row["line_num"])].append(row)
    blocks: list[TextBlock] = []
    for words in groups.values():
        x0 = min(int(w["left"]) for w in words)
        y0 = min(int(w["top"]) for w in words)
        x1 = max(int(w["left"]) + int(w["width"]) for w in words)
        y1 = max(int(w["top"]) + int(w["height"]) for w in words)
        blocks.append(
            TextBlock(
                page_number=number,
                bbox=(
                    (x0 + pix.x) / scale,
                    (y0 + pix.y) / scale,
                    (x1 + pix.x) / scale,
                    (y1 + pix.y) / scale,
                ),
                text=" ".join(w["text"] for w in words),
                method="local_ocr",
                ocr_confidence=sum(float(w["conf"]) for w in words) / len(words),
            )
        )
    return blocks, result.stdout
