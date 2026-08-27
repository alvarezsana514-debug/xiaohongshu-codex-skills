#!/usr/bin/env python3
"""Build and query a compact incremental Word/PDF knowledge index."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".docx", ".pdf"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_text(text: str, source: str, page: int | None = None, limit: int = 800) -> list[dict[str, Any]]:
    paragraphs = [re.sub(r"\s+", " ", item).strip() for item in re.split(r"\n+", text) if item.strip()]
    chunks: list[dict[str, Any]] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph[i : i + limit] for i in range(0, len(paragraph), limit)] or [paragraph]
        for piece in pieces:
            if current and len(current) + 1 + len(piece) > limit:
                chunks.append({"source": source, "page": page, "text": current})
                current = piece
            else:
                current = f"{current}\n{piece}".strip()
    if current:
        chunks.append({"source": source, "page": page, "text": current})
    return chunks


def docx_text_blocks(document: Any) -> list[str]:
    """Extract top-level paragraphs and table rows in document order."""
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            text = Paragraph(child, document).text.strip()
            if text:
                blocks.append(text)
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            for row in table.rows:
                cells = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                row_text = " | ".join(cell for cell in cells if cell)
                if row_text:
                    blocks.append(row_text)
    return blocks


def extract_docx(path: Path, source: str) -> tuple[list[dict[str, Any]], list[str]]:
    document = Document(path)
    text = "\n".join(docx_text_blocks(document))
    return chunk_text(text, source), ([] if text.strip() else [f"{source}: empty_document"])


def extract_pdf(path: Path, source: str) -> tuple[list[dict[str, Any]], list[str]]:
    reader = PdfReader(str(path))
    chunks: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.extend(chunk_text(text, source, page=page_number))
    warnings = [] if chunks else [f"{source}: needs_ocr"]
    return chunks, warnings


def load_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {"version": 1, "sources": {}}
    with index_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("version") != 1 or not isinstance(payload.get("sources"), dict):
        raise ValueError(f"不支持的索引格式: {index_path}")
    return payload


def iter_sources(knowledge_root: Path, index_path: Path) -> Iterable[Path]:
    index_dir = index_path.parent.resolve()
    for path in sorted(knowledge_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if index_dir in path.resolve().parents:
            continue
        yield path


def build_index(knowledge_root: str | Path, index_path: str | Path) -> dict[str, Any]:
    root = Path(knowledge_root).expanduser().resolve()
    output = Path(index_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"知识库文件夹不存在: {root}")

    previous = load_index(output)
    next_sources: dict[str, Any] = {}
    updated_files: list[str] = []
    warnings: list[str] = []

    for path in iter_sources(root, output):
        source = path.relative_to(root).as_posix()
        fingerprint = sha256_file(path)
        cached = previous["sources"].get(source)
        if cached and cached.get("sha256") == fingerprint:
            next_sources[source] = cached
            warnings.extend(cached.get("warnings", []))
            continue

        if path.suffix.lower() == ".docx":
            chunks, source_warnings = extract_docx(path, source)
        else:
            chunks, source_warnings = extract_pdf(path, source)
        next_sources[source] = {
            "sha256": fingerprint,
            "chunks": chunks,
            "warnings": source_warnings,
        }
        updated_files.append(source)
        warnings.extend(source_warnings)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump({"version": 1, "sources": next_sources}, handle, ensure_ascii=False, indent=2)

    return {
        "index_path": str(output),
        "source_count": len(next_sources),
        "chunk_count": sum(len(item.get("chunks", [])) for item in next_sources.values()),
        "updated_files": updated_files,
        "removed_files": sorted(set(previous["sources"]) - set(next_sources)),
        "warnings": warnings,
    }


def normalized_units(text: str) -> set[str]:
    normalized = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower()))
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def source_priority(source: str) -> int:
    """Use project rules as the deterministic tie-breaker for equal relevance."""
    if source.startswith("03_项目规范/"):
        return 0
    if source.startswith("02_资料库/"):
        return 1
    return 2


def search_index(index_path: str | Path, query: str, top_k: int = 8) -> list[dict[str, Any]]:
    index = load_index(Path(index_path).expanduser().resolve())
    query_units = normalized_units(query)
    matches: list[dict[str, Any]] = []
    for source, source_data in index["sources"].items():
        for chunk in source_data.get("chunks", []):
            text_units = normalized_units(chunk["text"])
            overlap = len(query_units & text_units)
            score = overlap / max(1, len(query_units))
            matches.append(
                {
                    "source": source,
                    "page": chunk.get("page"),
                    "text": chunk["text"],
                    "score": round(score, 6),
                }
            )
    matches.sort(
        key=lambda item: (
            -item["score"],
            source_priority(item["source"]),
            item["source"],
            item.get("page") or 0,
        )
    )
    return matches[: max(1, top_k)]


def main() -> int:
    parser = argparse.ArgumentParser(description="建立或检索固定 Word/PDF 图片文案知识库索引。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="增量建立索引")
    build_parser.add_argument("knowledge_root")
    build_parser.add_argument("--index", required=True, dest="index_path")

    search_parser = subparsers.add_parser("search", help="检索相关原文片段")
    search_parser.add_argument("query")
    search_parser.add_argument("--index", required=True, dest="index_path")
    search_parser.add_argument("--top-k", type=int, default=8)

    args = parser.parse_args()
    if args.command == "build":
        payload = build_index(args.knowledge_root, args.index_path)
    else:
        payload = search_index(args.index_path, args.query, args.top_k)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
