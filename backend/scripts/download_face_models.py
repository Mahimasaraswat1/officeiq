"""Download the OpenCV Zoo face models used for photo-vs-ID matching.

    python scripts/download_face_models.py

The models are Apache-2.0 licensed and live outside version control (SFace is
~37 MB). Checksums are pinned so a corrupted or substituted download is caught.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"

MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}

TARGET_DIR = Path(__file__).resolve().parent.parent / "models"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for name, (url, expected) in MODELS.items():
        target = TARGET_DIR / name

        if target.is_file() and sha256(target) == expected:
            print(f"✓ {name} already present")
            continue

        print(f"↓ downloading {name} …")
        try:
            urllib.request.urlretrieve(url, target)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ failed to download {name}: {exc}", file=sys.stderr)
            return 1

        actual = sha256(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            print(
                f"✗ checksum mismatch for {name}\n  expected {expected}\n  got      {actual}",
                file=sys.stderr,
            )
            return 1
        print(f"✓ {name} ({target.stat().st_size / 1_048_576:.1f} MB)")

    print(f"\nModels ready in {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
