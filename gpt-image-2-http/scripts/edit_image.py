#!/usr/bin/env python3
"""Edit a reference image through a GlobalAI-compatible GPT Image endpoint."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_ENDPOINT = "https://globalai.vip/v1/images/edits"
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class EditError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Edit and save one image using the gpt-image-2 HTTP endpoint.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--image", required=True, help="Local PNG, JPEG, or WebP reference image.")
    parser.add_argument("--prompt", required=True, help="Editing instructions, up to 32,000 characters.")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="1152x1536")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="high")
    parser.add_argument("--output-format", choices=("png", "jpeg", "webp"), default="png")
    parser.add_argument("--n", type=int, default=1, help="This client intentionally supports one output per page.")
    parser.add_argument("--output-file", required=True, help="Exact output path; existing files are never overwritten.")
    return parser


def sanitize(value: object, secret: str) -> str:
    text = str(value)
    return text.replace(secret, "[REDACTED]") if secret else text


def validate_size(size: str) -> None:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", size)
    if not match:
        raise EditError("--size must be WIDTHxHEIGHT")
    width, height = (int(value) for value in match.groups())
    if width % 16 or height % 16:
        raise EditError("--size width and height must both be divisible by 16")
    ratio = width / height
    if ratio < 1 / 3 or ratio > 3:
        raise EditError("--size aspect ratio must be between 1:3 and 3:1")
    if max(width, height) > 3840 or width * height > 3840 * 2160:
        raise EditError("--size exceeds the gpt-image-2 maximum supported resolution")


def validate_args(args: argparse.Namespace) -> tuple[Path, Path]:
    image_path = Path(args.image).expanduser().resolve()
    output_file = Path(args.output_file).expanduser().resolve()
    if not image_path.is_file():
        raise EditError(f"reference image does not exist: {image_path}")
    if image_path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
        raise EditError("reference image must be PNG, JPEG, or WebP")
    if not args.prompt.strip():
        raise EditError("--prompt must not be blank")
    if len(args.prompt) > 32000:
        raise EditError("--prompt must not exceed 32,000 characters")
    if not args.model.strip():
        raise EditError("--model must not be blank")
    if args.n != 1:
        raise EditError("--n must be 1 when --output-file is used")
    validate_size(args.size)
    expected_suffix = ".jpg" if args.output_format == "jpeg" else f".{args.output_format}"
    valid_suffixes = {".jpg", ".jpeg"} if args.output_format == "jpeg" else {expected_suffix}
    if output_file.suffix.lower() not in valid_suffixes:
        raise EditError(f"--output-file extension must match --output-format {args.output_format}")
    if output_file.exists():
        raise EditError(f"output file already exists: {output_file}")
    return image_path, output_file


def curl_quote(value: str) -> str:
    if "\x00" in value:
        raise EditError("curl config values cannot contain NUL bytes")
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def build_curl_config(endpoint: str, api_key: str, fields: dict[str, str], image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    lines = [
        f'url = "{curl_quote(endpoint)}"',
        'request = "POST"',
        f'header = "Authorization: Bearer {curl_quote(api_key)}"',
    ]
    lines.extend(f'form = "{curl_quote(name + "=" + value)}"' for name, value in fields.items())
    image_form = f"image=@{image_path};type={mime_type}"
    lines.append(f'form = "{curl_quote(image_form)}"')
    return "\n".join(lines)


def request_edit_with_curl(endpoint: str, api_key: str, fields: dict[str, str], image_path: Path) -> bytes:
    curl_path = Path("/usr/bin/curl")
    if not curl_path.is_file():
        raise EditError("required transport is missing: /usr/bin/curl")
    config = build_curl_config(endpoint, api_key, fields, image_path)
    try:
        result = subprocess.run(
            [str(curl_path), "--silent", "--show-error", "--fail-with-body", "--config", "-"],
            input=config,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise EditError("curl request timed out after 300 seconds") from exc
    if result.returncode:
        detail = (result.stderr + result.stdout).strip()
        raise EditError(f"curl request failed ({result.returncode}): {sanitize(detail, api_key)}")
    return result.stdout.encode("utf-8")


def parse_response(raw: bytes) -> list[bytes]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EditError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EditError("response JSON must be an object")
    if payload.get("error"):
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else error
        raise EditError(f"API error: {message}")
    items = payload.get("data")
    if not isinstance(items, list) or not items:
        raise EditError("response does not contain edited image data")
    images = []
    for item in items:
        value = item.get("b64_json") if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            raise EditError("response image is missing b64_json data")
        try:
            images.append(base64.b64decode(value, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise EditError("response contains invalid Base64 image data") from exc
    return images


def save_images(images: list[bytes], output_file: Path) -> list[str]:
    if len(images) != 1:
        raise EditError(f"expected exactly one edited image, received {len(images)}")
    if output_file.exists():
        raise EditError(f"output file already exists: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(images[0])
    return [str(output_file.resolve())]


def run(args: argparse.Namespace) -> dict[str, object]:
    image_path, output_file = validate_args(args)
    api_key = os.environ.get("GLOBALAI_API_KEY", "").strip()
    if not api_key:
        raise EditError("GLOBALAI_API_KEY is not set or is blank")
    endpoint = os.environ.get("GLOBALAI_IMAGE_EDIT_API_URL", DEFAULT_ENDPOINT).strip()
    if not endpoint:
        raise EditError("GLOBALAI_IMAGE_EDIT_API_URL is blank")
    fields = {
        "model": args.model,
        "prompt": args.prompt,
        "size": args.size,
        "quality": args.quality,
        "output_format": args.output_format,
        "n": str(args.n),
    }
    raw = request_edit_with_curl(endpoint, api_key, fields, image_path)
    files = save_images(parse_response(raw), output_file)
    return {
        "files": files,
        "metadata": {"model": args.model, "size": args.size, "quality": args.quality, "output_format": args.output_format},
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (EditError, OSError) as exc:
        secret = os.environ.get("GLOBALAI_API_KEY", "")
        print(f"error: {sanitize(exc, secret)}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
