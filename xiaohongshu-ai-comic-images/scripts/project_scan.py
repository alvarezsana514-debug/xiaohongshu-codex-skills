#!/usr/bin/env python3
"""Inventory every numbered reference-image group in a project folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic"}


def scan_project(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    reference_root = project / "参考图"
    result: dict[str, Any] = {
        "project": str(project),
        "reference_root": str(reference_root),
        "groups": [],
        "warnings": [],
        "errors": [],
    }

    if not project.is_dir():
        result["errors"].append(f"项目文件夹不存在: {project}")
        return result
    if not reference_root.is_dir():
        result["errors"].append(f"缺少参考图文件夹: {reference_root}")
        return result

    for group_dir in sorted((p for p in reference_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        numbered: dict[int, list[Path]] = {}
        for image in group_dir.iterdir():
            if not image.is_file() or image.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if not image.stem.isdigit():
                result["warnings"].append(f"{group_dir.name}: 忽略非数字文件名 {image.name}")
                continue
            numbered.setdefault(int(image.stem), []).append(image)

        pages = []
        for number in sorted(numbered):
            matches = sorted(numbered[number], key=lambda p: p.name)
            if len(matches) > 1:
                names = ", ".join(p.name for p in matches)
                result["errors"].append(f"{group_dir.name}: 编号 {number} 重复 ({names})")
            image = matches[0]
            pages.append({"number": number, "filename": image.name, "path": str(image.resolve())})

        if not pages:
            result["warnings"].append(f"{group_dir.name}: 没有可用的数字命名图片")
        else:
            present = {page["number"] for page in pages}
            missing = [number for number in range(1, max(present) + 1) if number not in present]
            if missing:
                missing_text = ", ".join(str(number) for number in missing)
                result["warnings"].append(f"{group_dir.name}: 缺少编号: {missing_text}")

        result["groups"].append({"name": group_dir.name, "path": str(group_dir.resolve()), "pages": pages})

    if not result["groups"]:
        result["errors"].append(f"参考图文件夹内没有图组: {reference_root}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描项目中的全部数字命名参考图组并输出 JSON。")
    parser.add_argument("project_path", help="包含“参考图”子文件夹的项目路径")
    args = parser.parse_args()
    print(json.dumps(scan_project(args.project_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
