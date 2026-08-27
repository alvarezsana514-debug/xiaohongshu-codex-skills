#!/usr/bin/env python3
"""Deterministic helpers for page-copy length, number slots, and wording overlap."""

from __future__ import annotations

import argparse
import json
import re
from typing import Iterable


DEFAULT_IGNORED_TERMS = ("AI视频", "漫剧", "分镜")

RISK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("income_or_price", r"(?:月入|日入|年入|收益|收入|报价|价格|稿费|薪资|工资|赚(?:钱|到)?)"),
    ("currency_amount", r"(?:[¥￥]\s*\d+(?:\.\d+)?|人民币\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:元|万元|万/月|元/分钟))"),
    ("commercial_metric", r"(?:GMV|分成|曝光量|推流|商单(?:数量|不断|做不完)?|外包量)"),
    ("market_claim", r"(?:千亿|百亿|市场规模|年产值|薪资涨幅|人才缺口)"),
    ("guaranteed_result", r"(?:保证|稳赚|必赚|一定能|确保你|包接单|真派单|直接派单|零门槛赚钱|学完就能赚)"),
    ("misleading_outcome", r"(?:(?:轻松|快速|轻易)?回本|副业(?:收入)?翻倍|零基础接单自由|躺赚)"),
)

STRUCTURE_NUMBER_SUFFIX = re.compile(r"^(?:个|种|大|条|步|类|阶段|部分|要点|技巧|方法|流程)")


def visible_text(text: str) -> str:
    """Remove Markdown-only syntax while preserving reader-visible copy."""
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    cleaned_lines: list[str] = []
    for line in value.splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", line)
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", line)
        line = re.sub(r"[*_`~]", "", line)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def visible_length(text: str) -> int:
    """Count reader-visible non-whitespace characters, excluding Markdown syntax."""
    return sum(1 for character in visible_text(text) if not character.isspace())


def number_details(text: str) -> list[dict[str, str]]:
    """Classify non-list numbers as structural or factual information."""
    details: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", raw_line)
        line = re.sub(r"^\s*\d+[.)、]\s*", "", line)
        line = re.sub(r"[*_`~]", "", line)
        for match in re.finditer(r"\d+(?:\.\d+)?%?", line):
            suffix = line[match.end() :].lstrip()
            kind = "structure" if STRUCTURE_NUMBER_SUFFIX.match(suffix) else "fact"
            details.append({"value": match.group(0), "kind": kind})
    return details


def number_slots(text: str) -> list[str]:
    """Return non-list numeric information positions in reading order."""
    return [item["value"] for item in number_details(text)]


def normalize(text: str, ignored_terms: Iterable[str] = DEFAULT_IGNORED_TERMS) -> str:
    value = visible_text(text).lower()
    for term in ignored_terms:
        value = value.replace(term.lower(), "")
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", value))


def ngrams(text: str, size: int = 3) -> set[str]:
    if not text:
        return set()
    if len(text) <= size:
        return {text}
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def overlap_ratio(reference: str, candidate: str, ignored_terms: Iterable[str] = DEFAULT_IGNORED_TERMS) -> float:
    """Measure how much of the reference wording is reused by the candidate."""
    reference_ngrams = ngrams(normalize(reference, ignored_terms))
    candidate_ngrams = ngrams(normalize(candidate, ignored_terms))
    if not reference_ngrams:
        return 0.0
    return len(reference_ngrams & candidate_ngrams) / len(reference_ngrams)


def risk_matches(text: str) -> list[dict[str, str]]:
    """Return public-platform risk terms in reading order without duplicates."""
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for category, pattern in RISK_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            item = (category, match.group(0))
            if item not in seen:
                seen.add(item)
                matches.append({"category": category, "text": match.group(0)})
    return matches


def page_structure(text: str) -> dict[str, int]:
    """Measure Markdown-oriented copy structure used by image pages."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    title = re.sub(r"^#{1,6}\s*", "", title)
    title = re.sub(r"^(?:[-*+]\s+|\d+[.)、]\s*)", "", title)
    title = title.strip("*_` ")
    paragraphs = [block for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    list_items = sum(
        1
        for line in text.splitlines()
        if re.match(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)\S", line)
    )
    return {
        "title_visible_length": visible_length(title),
        "paragraph_count": len(paragraphs),
        "list_item_count": list_items,
        "nonempty_line_count": len(lines),
    }


def check_page(reference: str, candidate: str, threshold: float = 0.2) -> dict[str, object]:
    reference_length = visible_length(reference)
    candidate_length = visible_length(candidate)
    reference_numbers = number_slots(reference)
    candidate_numbers = number_slots(candidate)
    reference_number_details = number_details(reference)
    candidate_number_details = number_details(candidate)
    overlap = overlap_ratio(reference, candidate)
    risks = risk_matches(candidate)
    reference_structure = page_structure(reference)
    candidate_structure = page_structure(candidate)
    structure_matches = all(
        reference_structure[key] == candidate_structure[key]
        for key in ("title_visible_length", "paragraph_count", "list_item_count", "nonempty_line_count")
    )
    quality_passes = overlap <= threshold and not risks
    return {
        "reference_visible_length": reference_length,
        "candidate_visible_length": candidate_length,
        "length_matches": reference_length == candidate_length,
        "reference_number_slots": reference_numbers,
        "candidate_number_slots": candidate_numbers,
        "reference_number_details": reference_number_details,
        "candidate_number_details": candidate_number_details,
        "number_slot_count_matches": len(reference_numbers) == len(candidate_numbers),
        "overlap_ratio": round(overlap, 6),
        "overlap_passes": overlap <= threshold,
        "risk_matches": risks,
        "risk_passes": not risks,
        "quality_passes": quality_passes,
        "reference_structure": reference_structure,
        "candidate_structure": candidate_structure,
        "structure_matches": structure_matches,
        "threshold": threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查单页仿写文案的字数、结构、数字位、文字重合度与公开发布风险。")
    parser.add_argument("reference", help="参考页文案")
    parser.add_argument("candidate", help="仿写页文案")
    parser.add_argument("--threshold", type=float, default=0.2, help="最大允许文字重合率，默认 0.2")
    args = parser.parse_args()
    print(json.dumps(check_page(args.reference, args.candidate, args.threshold), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
