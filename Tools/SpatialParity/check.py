#!/usr/bin/env python3
"""Compile production spatial adapters against the existing OpenCV archive and compare full chains.

Run using Tools/CardEdges/requirements-macos-py39.txt in an isolated environment. Only synthetic
pixels are generated. The harness itself does not change capture or build artifacts.
"""
import argparse
import hashlib
import importlib.util
import json
import platform
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BRIDGE = ROOT / "Sources/IdentityEvidenceOpenCVBridge"
NATIVE = BRIDGE / "Spatial/Native"
VENDOR = BRIDGE / "Spatial/Vendor/EdgeDrawing"


def run(*args, **kwargs):
    return subprocess.run([str(value) for value in args], check=True, **kwargs)


def verify_sources():
    manifest = json.loads((VENDOR / "manifest.json").read_text())
    if manifest["version"] != "4.12.0":
        raise ValueError("Unsupported upstream version")
    for name, record in manifest["files"].items():
        if hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Upstream source mismatch: " + name)
    run(sys.executable, ROOT / "scripts/verify_capture_opencv.py")


def build(directory, sanitizers=False):
    framework = ROOT / "ThirdParty/OpenCV/opencv2.xcframework/macos-arm64_x86_64/opencv2.framework"
    sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    output = directory / "spatial-parity"
    command = ["xcrun", "--sdk", "macosx", "clang++", "-std=c++20", "-O2",
               "-fvisibility=hidden", "-fvisibility-inlines-hidden",
               "-ffile-prefix-map=" + str(ROOT) + "=.",
               "-target", platform.machine() + "-apple-macos13.0", "-isysroot", sdk,
               "-I" + str(VENDOR), "-I" + str(NATIVE), "-F" + str(framework.parent),
               HERE / "Native/main.cpp", NATIVE / "EdgeDrawingAdapter.cpp",
               NATIVE / "GrabCutAdapter.cpp",
               NATIVE / "SeedAdapter.cpp",
               VENDOR / "edge_drawing.cpp", framework / "opencv2", "-o", output]
    for dependency in ["Accelerate", "Foundation", "AVFoundation", "CoreMedia", "CoreVideo",
                       "CoreGraphics", "ImageIO", "QuartzCore", "AppKit"]:
        command.extend(["-framework", dependency])
    if sanitizers:
        command.extend(["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g"])
    run(*command)
    linked = subprocess.check_output(["otool", "-L", str(output)], text=True)
    if "opencv" in linked.lower():
        raise ValueError("Unexpected dynamically linked OpenCV runtime")
    return output


def compare(executable, directory):
    import numpy as np
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("desktop_edges", ROOT / "Tools/CardEdges/detect.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = json.loads(module.CONFIG.read_text())
    fixtures = {}
    fixtures["empty"] = np.zeros((128, 160, 3), dtype=np.uint8)
    steps = np.full((128, 160, 3), 220, dtype=np.uint8)
    steps[:, 40:80] = 90
    steps[:, 100:] = 140
    fixtures["adjacent"] = steps
    yy, xx = np.indices((257, 311))
    rgb = np.zeros((257, 311, 3), dtype=np.uint8)
    rgb[:, :, 0] = (xx * 3 + yy) % 256
    rgb[:, :, 1] = np.where((xx - 155) ** 2 + (yy - 128) ** 2 < 75 ** 2, 210, 20)
    rgb[:, :, 2] = np.where(xx > yy, 180, 60)
    fixtures["color-curves"] = rgb
    # More than 250,000 observed points must survive intact; segmentation is unnecessary
    # for this chain-preservation check and would obscure the property under test.
    stripe = np.where(np.arange(1024) % 4 < 2, 240, 10).astype(np.uint8)
    fixtures["dense-full-chains"] = np.broadcast_to(stripe[None, :, None], (1024, 1024, 3)).copy()
    fixtures["minimum"] = np.arange(75, dtype=np.uint8).reshape(5, 5, 3)
    for name, rgb in fixtures.items():
        expected_points, expected_offsets = module.detect_native(rgb, config)
        if name == "dense-full-chains" and len(expected_points) <= 250000:
            raise ValueError("Dense fixture does not exercise full chain preservation")
        for padding in (0, 13):
            height, width, _ = rgb.shape
            stride = width * 3 + padding
            packed = np.full((height, stride), 237, dtype=np.uint8)
            packed[:, :width * 3] = rgb.reshape(height, width * 3)
            raw = packed.tobytes()
            source = directory / "input.rgb"
            source.write_bytes(raw)
            points, offsets = directory / "points.bin", directory / "offsets.bin"
            run(executable, source, width, height, stride, points, offsets, stdout=subprocess.DEVNULL)
            np.testing.assert_array_equal(np.frombuffer(points.read_bytes(), dtype="<i4").reshape(-1, 2), expected_points)
            np.testing.assert_array_equal(np.frombuffer(offsets.read_bytes(), dtype="<u8"), expected_offsets)
            if source.read_bytes() != raw:
                raise ValueError("Source file changed")
            print(f"PASS {name}, row padding {padding}: exact ordered points and offsets")
    # Reject malformed extents before OpenCV can read source memory.
    for width, height, stride in [(4, 5, 15), (5, 4, 15), (1000, 1000, 3000), (5, 5, 14),
                                  (5, 5, 18446744073709551615)]:
        failed = subprocess.run([str(executable), str(source), str(width), str(height), str(stride),
                                 str(points), str(offsets)], capture_output=True)
        if failed.returncode != 1:
            raise ValueError("Invalid extent was not rejected")
    print("PASS five malformed or overflowing source extents rejected")


def compare_masks(executable, directory):
    import numpy as np
    sys.path.insert(0, str(ROOT / "Tools/CardBoundary"))
    # Import the existing desktop functions without replacing their dependencies or algorithm.
    import refine
    seeds = np.zeros((96, 128), dtype=np.uint8)
    seeds[12:84, 12:116] = 2
    seeds[20:76, 24:104] = 3
    seeds[30:66, 34:94] = 1
    rgb = np.full((96, 128, 3), [25, 50, 70], dtype=np.uint8)
    rgb[20:76, 24:104] = [210, 180, 140]
    fixtures = {"rectangle": (rgb, seeds)}
    hole_rgb, hole_seeds = rgb.copy(), seeds.copy()
    hole_rgb[42:52, 56:70] = [25, 50, 70]
    hole_seeds[42:52, 56:70] = 0
    fixtures["hole"] = (hole_rgb, hole_seeds)
    for name, (rgb, seeds) in fixtures.items():
        before_rgb, before_seeds = rgb.copy(), seeds.copy()
        expected_labels = refine.segment_native(rgb, seeds)
        _, expected_component, _ = refine.select_foreground(expected_labels, seeds)
        np.testing.assert_array_equal(rgb, before_rgb)
        np.testing.assert_array_equal(seeds, before_seeds)
        if name == "hole" and np.any(expected_component[42:52, 56:70]):
            raise ValueError("Reference hole was not retained")
        height, width, _ = rgb.shape
        for padding in (0, 11):
            stride = width * 3 + padding
            packed = np.full((height, stride), 239, dtype=np.uint8)
            packed[:, :width * 3] = rgb.reshape(height, width * 3)
            source, seed_file = directory / "mask-input.rgb", directory / "seeds.bin"
            labels, component = directory / "labels.bin", directory / "component.bin"
            source.write_bytes(packed.tobytes()); seed_file.write_bytes(seeds.tobytes())
            run(executable, "segment", source, width, height, stride, seed_file, labels, component)
            np.testing.assert_array_equal(np.frombuffer(labels.read_bytes(), dtype=np.uint8).reshape(height, width), expected_labels)
            np.testing.assert_array_equal(np.frombuffer(component.read_bytes(), dtype=np.uint8).reshape(height, width), expected_component)
            if source.read_bytes() != packed.tobytes() or seed_file.read_bytes() != seeds.tobytes():
                raise ValueError("Segmentation input changed")
            print(f"PASS {name}, row padding {padding}: exact GrabCut labels and core mask")
    # Four-connectivity must discard a diagonally touching island and retain holes. It must
    # refuse a definite core spanning disconnected components rather than choose the largest.
    selected = np.zeros((9, 11), dtype=np.uint8)
    selected[1:5, 1:5] = 3; selected[2, 2] = 0; selected[5:8, 5:8] = 3
    core = np.zeros_like(selected); core[3, 3] = 1
    _, expected, _ = refine.select_foreground(selected, core)
    labels.write_bytes(selected.tobytes()); seed_file.write_bytes(core.tobytes())
    run(executable, "select", labels, seed_file, 11, 9, component)
    np.testing.assert_array_equal(np.frombuffer(component.read_bytes(), dtype=np.uint8).reshape(9, 11), expected)
    if expected[6, 6] or expected[2, 2]:
        raise ValueError("Disconnected island or hole incorrectly selected")
    print("PASS four-connected selection preserves hole and discards diagonal island")
    for bad_core in (core.copy(), np.zeros_like(core)):
        if bad_core.any(): bad_core[6, 6] = 1
        try:
            refine.select_foreground(selected, bad_core)
        except ValueError:
            pass
        else:
            raise ValueError("Reference accepted invalid core")
        seed_file.write_bytes(bad_core.tobytes())
        failed = subprocess.run([str(executable), "select", str(labels), str(seed_file), "11", "9", str(component)], capture_output=True)
        if failed.returncode != 1 or b"Foreground core split or missing" not in failed.stderr:
            raise ValueError("Native accepted invalid core")
    print("PASS disconnected and absent cores rejected by desktop and native")
    # Segmentation admission rejects full-row truncation, invalid labels and invalid seed extent.
    height, width, _ = rgb.shape
    source.write_bytes(rgb.tobytes()[:-1]); seed_file.write_bytes(seeds.tobytes())
    for raw, seed_bytes, stride in [(rgb.tobytes()[:-1], seeds.tobytes(), width * 3),
                                   (rgb.tobytes(), seeds.tobytes()[:-1], width * 3),
                                   (rgb.tobytes(), bytes([4]) + seeds.tobytes()[1:], width * 3),
                                   (rgb.tobytes(), seeds.tobytes(), 18446744073709551615)]:
        source.write_bytes(raw); seed_file.write_bytes(seed_bytes)
        failed = subprocess.run([str(executable), "segment", str(source), str(width), str(height),
                                 str(stride), str(seed_file), str(labels), str(component)], capture_output=True)
        if failed.returncode != 1:
            raise ValueError("Invalid segmentation input accepted")
    print("PASS four malformed segmentation extents/labels rejected")


def compare_seeds(executable, directory):
    import numpy as np
    import shapely
    import rasterio
    from shapely.geometry import Polygon, box, mapping
    from rasterio.features import rasterize
    if shapely.geos_version_string != "3.11.4" or rasterio.__gdal_version__ != "3.9.3":
        raise ValueError("Seed oracle requires pinned GEOS3.11.4/GDAL3.9.3")
    width, height = 160, 140

    def reference(quad):
        corners = np.array(quad, dtype=float)
        polygon = Polygon(corners)
        if (not np.isfinite(corners).all() or len(np.unique(corners, axis=0)) != 4
                or polygon.area <= 0 or not polygon.is_valid
                or polygon.convex_hull.geom_type != "Polygon"
                or len(polygon.convex_hull.exterior.coords) != 5
                or not polygon.equals(polygon.convex_hull) or not box(0, 0, width, height).covers(polygon)):
            raise ValueError("Invalid prior")
        band = .04 * min(np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1))
        inner, outer = polygon.buffer(-band), polygon.buffer(band)
        if inner.is_empty or not box(0, 0, width, height).contains(outer):
            raise ValueError("Seed geometry outside source")
        labels = rasterize([(mapping(outer), 2), (mapping(polygon), 3), (mapping(inner), 1)],
                           out_shape=(height, width), fill=0, dtype="uint8", all_touched=False)
        if not all(np.any(labels == label) for label in (0, 1)):
            raise ValueError("Missing definite seed class")
        return labels

    fixtures = {
        "axis-aligned": [[30, 35], [120, 35], [120, 100], [30, 100]],
        "half-pixel": [[30.5, 35.5], [120.5, 35.5], [120.5, 100.5], [30.5, 100.5]],
        "subpixel": [[20.2, 23.4], [110.1, 20.7], [108.4, 97.2], [18.3, 92.6]],
        "rotated": [[40, 20], [130, 60], [105, 116], [15, 76]],
        "perspective": [[20, 20], [135, 37], [113, 112], [33, 99]],
        "degenerate": [[20, 20], [40, 20], [60, 20], [20, 60]],
        "duplicate": [[20, 20], [80, 20], [80, 20], [20, 60]],
        "crossed": [[20, 20], [80, 80], [80, 20], [20, 80]],
        "clipped": [[0, 20], [80, 20], [80, 80], [0, 80]],
    }
    rng = np.random.default_rng(7149)
    for index in range(128):
        fixtures[f"perspective-{index}"] = (np.array([[30., 30.], [120., 30.], [120., 110.], [30., 110.]])
                                             + rng.uniform(-12, 12, (4, 2))).tolist()
    accepted, refused = 0, 0
    output = directory / "automatic-seeds.bin"
    for name, quad in fixtures.items():
        for points in (quad, list(reversed(quad))):
            try:
                expected = reference(points)
            except ValueError:
                expected = None
            command = [str(executable), "seeds", str(width), str(height),
                       *[str(value) for pair in points for value in pair], str(output)]
            result = subprocess.run(command, capture_output=True)
            if expected is None:
                if result.returncode != 1:
                    raise ValueError("Native accepted invalid seeds: " + name)
                refused += 1
            else:
                if result.returncode != 0:
                    raise ValueError("Native refused valid seeds: " + name + ": " + result.stderr.decode())
                actual = np.frombuffer(output.read_bytes(), dtype=np.uint8).reshape(height, width)
                np.testing.assert_array_equal(actual, expected, err_msg="Seed parity: " + name)
                accepted += 1
    print(f"PASS {accepted} exact automatic seed masks and {refused} invalid seed rejections, both windings")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--sanitizers", action="store_true", help="Instrument native adapters; pinned OpenCV remains uninstrumented")
    args = parser.parse_args()
    verify_sources()
    if args.verify_only:
        return
    if sys.platform != "darwin":
        raise SystemExit("This checkpoint targets the pinned macOS archive")
    with tempfile.TemporaryDirectory(prefix="kenshiki-spatial-parity-") as temporary:
        directory = Path(temporary)
        executable = build(directory, args.sanitizers)
        for width, height, accepted in [(5, 5, True), (4032, 3024, True), (8064, 6048, True),
                                         (16384, 16384, True), (16400, 16400, False),
                                         (2147483647, 5, False), (-1, 5, False)]:
            result = subprocess.run([str(executable), "graph-extent", str(width), str(height)])
            if result.returncode != (0 if accepted else 1):
                raise ValueError(f"Graph-index arithmetic refusal mismatch: {width}x{height}")
        print("PASS allocation-free graph arithmetic: 12MP/48MP admitted, signed boundaries checked")
        compare(executable, directory)
        compare_masks(executable, directory)
        compare_seeds(executable, directory)
    run(sys.executable, ROOT / "scripts/verify_capture_bridge.py")
    run(sys.executable, HERE / "check_abi.py")


if __name__ == "__main__":
    main()
