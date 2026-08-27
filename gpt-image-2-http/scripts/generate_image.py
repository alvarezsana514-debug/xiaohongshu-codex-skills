#!/usr/bin/env python3
"""Generate images through a GlobalAI-compatible GPT Image 2 endpoint."""

import argparse
import base64
import binascii
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://globalai.vip/v1/images/generations"
DEFAULT_OUTPUT_DIR = "gpt-image-2-output"
BLOCKED_EXTRA_KEYS = {
    "authorization", "api_key", "apikey", "api-key", "token",
    "endpoint", "url", "api_url", "api-url",
}


class GenerationError(Exception):
    pass


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate and save images using the gpt-image-2 HTTP endpoint.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--prompt", required=True, help="Image description (maximum 32,000 characters).")
    parser.add_argument("--model", default="gpt-image-2", help="GPT Image model or snapshot name.")
    parser.add_argument("--background", choices=("transparent", "opaque", "auto"))
    parser.add_argument("--moderation", choices=("low", "auto"))
    parser.add_argument("--n", type=int, default=1, help="Number of images, from 1 to 10.")
    parser.add_argument("--output-compression", type=int, help="JPEG/WebP compression from 0 to 100.")
    parser.add_argument("--output-format", choices=("png", "jpeg", "webp"), default="png")
    parser.add_argument("--partial-images", type=int, help="Streaming partial images, from 0 to 3.")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"))
    parser.add_argument(
        "--size",
        help="auto or WIDTHxHEIGHT; dimensions must be divisible by 16. Sizes above 2560x1440 are experimental.",
    )
    parser.add_argument("--stream", action="store_true", help="Request an SSE streaming response.")
    parser.add_argument("--user", help="Stable identifier for the end user.")
    parser.add_argument("--extra-json", default="{}", help="Additional request fields as a JSON object.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-prefix", default="image")
    parser.add_argument("--save-partials", action="store_true", help="Save streaming partial images as files.")
    return parser


def parse_extra_json(raw):
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenerationError("--extra-json must be valid JSON: {}".format(exc.msg))
    if not isinstance(extra, dict):
        raise GenerationError("--extra-json must contain a JSON object")
    for key in extra:
        if str(key).lower() in BLOCKED_EXTRA_KEYS:
            raise GenerationError("--extra-json cannot contain credential or endpoint field {!r}".format(key))
    if "prompt" in extra and not isinstance(extra["prompt"], str):
        raise GenerationError("--extra-json prompt must be a string")
    if "model" in extra and (not isinstance(extra["model"], str) or not extra["model"].strip()):
        raise GenerationError("--extra-json model must be a non-empty string")
    return extra


def validate_size(size):
    if size is None or size == "auto":
        return
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", size)
    if not match:
        raise GenerationError("--size must be auto or WIDTHxHEIGHT")
    width, height = (int(value) for value in match.groups())
    if width % 16 or height % 16:
        raise GenerationError("--size width and height must both be divisible by 16")
    ratio = width / height
    if ratio < 1 / 3 or ratio > 3:
        raise GenerationError("--size aspect ratio must be between 1:3 and 3:1")
    if max(width, height) > 3840 or width * height > 3840 * 2160:
        raise GenerationError("--size exceeds the gpt-image-2 maximum supported resolution")


def validate_request(args, extra):
    if not args.prompt.strip():
        raise GenerationError("--prompt must not be blank")
    if len(args.prompt) > 32000:
        raise GenerationError("--prompt must not exceed 32,000 characters")
    if not args.model.strip():
        raise GenerationError("--model must not be blank")
    if not 1 <= args.n <= 10:
        raise GenerationError("--n must be between 1 and 10")
    if args.output_compression is not None:
        if not 0 <= args.output_compression <= 100:
            raise GenerationError("--output-compression must be between 0 and 100")
        if args.output_format not in ("jpeg", "webp"):
            raise GenerationError("--output-compression requires --output-format jpeg or webp")
    if args.partial_images is not None:
        if not 0 <= args.partial_images <= 3:
            raise GenerationError("--partial-images must be between 0 and 3")
        if not args.stream:
            raise GenerationError("--partial-images requires --stream")
    if args.save_partials and not args.stream:
        raise GenerationError("--save-partials requires --stream")
    if args.background == "transparent" and args.output_format not in ("png", "webp"):
        raise GenerationError("transparent background requires --output-format png or webp")
    validate_size(args.size)


def build_request_body(args, extra):
    body = {
        "model": args.model,
        "prompt": args.prompt,
        "n": args.n,
        "output_format": args.output_format,
    }
    optional = {
        "background": args.background,
        "moderation": args.moderation,
        "output_compression": args.output_compression,
        "partial_images": args.partial_images,
        "quality": args.quality,
        "size": args.size,
        "user": args.user,
    }
    body.update({key: value for key, value in optional.items() if value is not None})
    if args.stream:
        body["stream"] = True
    body.update(extra)
    return body


def sanitize(text, secret):
    value = str(text)
    return value.replace(secret, "[REDACTED]") if secret else value


def request_generation(endpoint, api_key, body):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer {}".format(api_key),
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if body.get("stream") else "application/json",
    }
    request = Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=300) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GenerationError("HTTP {}: {}".format(exc.code, sanitize(detail, api_key)))
    except URLError as exc:
        raise GenerationError("request failed: {}".format(sanitize(exc.reason, api_key)))


def decode_image(value):
    if not isinstance(value, str) or not value:
        raise GenerationError("response image is missing b64_json data")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GenerationError("response contains invalid Base64 image data: {}".format(exc))


def parse_json_response(raw):
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationError("response is not valid JSON: {}".format(exc))
    if not isinstance(payload, dict):
        raise GenerationError("response JSON must be an object")
    if payload.get("error"):
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else error
        raise GenerationError("API error: {}".format(message))
    items = payload.get("data")
    if not isinstance(items, list) or not items:
        raise GenerationError("response does not contain generated image data")
    return payload, items


def parse_sse_response(raw, save_partials):
    finals, partials = [], []
    for block in re.split(rb"\r?\n\r?\n", raw):
        data_lines = []
        for line in block.splitlines():
            if line.startswith(b"data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        joined = b"\n".join(data_lines)
        if joined == b"[DONE]":
            continue
        try:
            event = json.loads(joined.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GenerationError("stream contains invalid JSON event: {}".format(exc))
        if not isinstance(event, dict):
            continue
        if event.get("error"):
            raise GenerationError("API stream error: {}".format(event["error"]))
        event_type = event.get("type", "")
        if event_type.endswith("partial_image") and save_partials and event.get("b64_json"):
            partials.append(event)
        elif event_type.endswith("completed") and event.get("b64_json"):
            finals.append(event)
        elif isinstance(event.get("data"), list):
            finals.extend(item for item in event["data"] if isinstance(item, dict))
    if not finals:
        raise GenerationError("stream completed without a final image")
    return finals, partials


def safe_prefix(value):
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not prefix:
        raise GenerationError("--output-prefix must contain a letter, number, underscore, or hyphen")
    return prefix


def choose_path(output_dir, prefix, extension):
    index = 1
    while True:
        candidate = output_dir / "{}-{:03d}.{}".format(prefix, index, extension)
        if not candidate.exists():
            return candidate
        index += 1


def save_items(items, output_dir, prefix, fallback_format):
    paths = []
    for item in items:
        if not isinstance(item, dict):
            raise GenerationError("response image entry must be an object")
        extension = item.get("output_format") or fallback_format
        if extension not in ("png", "jpeg", "webp"):
            extension = fallback_format
        path = choose_path(output_dir, prefix, extension)
        path.write_bytes(decode_image(item.get("b64_json")))
        paths.append(str(path.resolve()))
    return paths


def run(args):
    extra = parse_extra_json(args.extra_json)
    validate_request(args, extra)
    api_key = os.environ.get("GLOBALAI_API_KEY", "").strip()
    if not api_key:
        raise GenerationError("GLOBALAI_API_KEY is not set or is blank")
    endpoint = os.environ.get("GLOBALAI_IMAGE_API_URL", DEFAULT_ENDPOINT).strip()
    if not endpoint:
        raise GenerationError("GLOBALAI_IMAGE_API_URL is blank")
    body = build_request_body(args, extra)
    raw, content_type = request_generation(endpoint, api_key, body)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = safe_prefix(args.output_prefix)

    if body.get("stream") or "text/event-stream" in content_type.lower():
        final_items, partial_items = parse_sse_response(raw, args.save_partials)
        metadata = {"model": body["model"], "output_format": body["output_format"], "stream": True}
    else:
        payload, final_items = parse_json_response(raw)
        partial_items = []
        allowed_metadata = ("created", "background", "output_format", "quality", "size", "usage")
        metadata = {key: payload[key] for key in allowed_metadata if key in payload}
        metadata.setdefault("model", body["model"])
        metadata.setdefault("output_format", body["output_format"])

    files = save_items(final_items, output_dir, prefix, body["output_format"])
    partial_files = save_items(partial_items, output_dir, prefix + "-partial", body["output_format"])
    return {"files": files, "partial_files": partial_files, "metadata": metadata}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (GenerationError, OSError) as exc:
        secret = os.environ.get("GLOBALAI_API_KEY", "")
        print("error: {}".format(sanitize(exc, secret)), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
