#!/usr/bin/env python3
"""Check numbered final PNGs against numbered reference-image groups."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any


REFERENCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic"}
EXPECTED_DIMENSIONS = (1152, 1536)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def numbered_files(folder: Path, extensions: set[str]) -> dict[int, Path]:
    if not folder.is_dir():
        return {}
    result = {}
    for path in folder.iterdir():
        if path.is_file() and path.stem.isdigit() and path.suffix.lower() in extensions:
            result[int(path.stem)] = path
    return result


def read_png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("不是有效PNG")
    return struct.unpack(">II", header[16:24])


def check_project(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    reference_root = project / "参考图"
    final_root = project / "最终图片"
    result: dict[str, Any] = {
        "project": str(project),
        "expected_dimensions": list(EXPECTED_DIMENSIONS),
        "groups": [],
        "errors": [],
    }
    if not reference_root.is_dir():
        result["errors"].append(f"缺少参考图文件夹: {reference_root}")
        return result

    reference_groups = sorted((path for path in reference_root.iterdir() if path.is_dir()), key=lambda path: path.name)
    expected_names = {path.name for path in reference_groups}
    if final_root.is_dir():
        for extra_group in sorted(path.name for path in final_root.iterdir() if path.is_dir() and path.name not in expected_names):
            result["errors"].append(f"多出最终图片图组: {extra_group}")

    for reference_group in reference_groups:
        final_group = final_root / reference_group.name
        expected = numbered_files(reference_group, REFERENCE_EXTENSIONS)
        actual = numbered_files(final_group, {".png"})
        expected_pages = sorted(expected)
        actual_pages = sorted(actual)
        missing = sorted(set(expected_pages) - set(actual_pages))
        extra = sorted(set(actual_pages) - set(expected_pages))
        if missing:
            result["errors"].append(
                f"{reference_group.name}: 缺少最终图片编号: {', '.join(map(str, missing))}"
            )
        if extra:
            result["errors"].append(
                f"{reference_group.name}: 多出最终图片编号: {', '.join(map(str, extra))}"
            )

        dimensions = {}
        for number in actual_pages:
            path = actual[number]
            try:
                width, height = read_png_dimensions(path)
                dimensions[str(number)] = [width, height]
                if (width, height) != EXPECTED_DIMENSIONS:
                    result["errors"].append(
                        f"{reference_group.name}: {path.name} 尺寸不是 1152x1536，而是 {width}x{height}"
                    )
            except (OSError, ValueError):
                result["errors"].append(f"{reference_group.name}: {path.name} 不是有效PNG")

        result["groups"].append({
            "name": reference_group.name,
            "expected_pages": expected_pages,
            "actual_pages": actual_pages,
            "dimensions": dimensions,
            "passes": not any(error.startswith(f"{reference_group.name}:") for error in result["errors"]),
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="检查小红书项目最终图片的编号、数量、PNG格式和尺寸。")
    parser.add_argument("project_path")
    args = parser.parse_args()
    print(json.dumps(check_project(args.project_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
