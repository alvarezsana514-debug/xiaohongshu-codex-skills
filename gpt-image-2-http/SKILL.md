---
name: gpt-image-2-http
description: Use when generating or editing images with GPT Image 2 through a GlobalAI-compatible HTTP endpoint, including local reference-image input, custom sizes, quality, transparency, compression, multiple outputs, or streaming.
---

# GPT Image 2 HTTP

Generate or edit images with bundled Python clients and return the saved absolute image paths. Generation uses Python's standard library; reference-image editing uses the system `/usr/bin/curl` multipart transport because this relay closes equivalent `urllib` multipart requests during TLS transfer.

## Workflow

1. Confirm `GLOBALAI_API_KEY` is available. If it is missing, tell the user how to set it; do not ask them to paste the key into chat.
2. Use `scripts/edit_image.py` when a local reference image must be visible to the model; otherwise use `scripts/generate_image.py`.
3. Translate the request into the smallest necessary set of options. Keep the default model `gpt-image-2` unless the user requests a snapshot.
4. Read the JSON result and present every path in `files`; mention `partial_files` only when partials were requested.

Never print, echo, log, or embed `GLOBALAI_API_KEY`. Do not pass it as a command-line argument. Generation can override `GLOBALAI_IMAGE_API_URL`; editing can override `GLOBALAI_IMAGE_EDIT_API_URL`. If `/v1/images/edits` rejects `gpt-image-2`, report the error and do not silently switch models.

## Generate

```bash
python3 scripts/generate_image.py \
  --prompt "A clean product poster with clear subject and soft studio lighting" \
  --size 1024x1024 \
  --quality low \
  --n 1 \
  --output-format png \
  --output-dir ./gpt-image-2-output
```

The command prints compact JSON with absolute paths. The default output directory is `./gpt-image-2-output`, and existing files are never overwritten.

## Edit from a reference image

The edit client uploads one PNG, JPEG, or WebP file as multipart form data to `https://globalai.vip/v1/images/edits`. It intentionally creates one output per call and refuses to overwrite the exact target path. The API key and form fields are passed to `/usr/bin/curl` through standard input, not command-line arguments or files.

```bash
python3 scripts/edit_image.py \
  --image /absolute/path/reference.png \
  --prompt "Keep the reference layout and visual style; replace its copy with the confirmed text" \
  --model gpt-image-2 \
  --size 1152x1536 \
  --quality high \
  --output-format png \
  --n 1 \
  --output-file /absolute/path/final/1.png
```

Run `python3 scripts/edit_image.py --help` for exact validation rules. Network access is required for real edits; local unit tests do not call the external service.

## Native generation parameters

| Option | Values or meaning |
|---|---|
| `--prompt` | Required text prompt, up to 32,000 characters |
| `--model` | Defaults to `gpt-image-2`; snapshots are accepted |
| `--background` | `transparent`, `opaque`, `auto` |
| `--moderation` | `low`, `auto` |
| `--n` | 1–10 |
| `--output-compression` | 0–100; only with `jpeg` or `webp` |
| `--output-format` | `png`, `jpeg`, `webp` |
| `--partial-images` | 0–3; requires `--stream` |
| `--quality` | `low`, `medium`, `high`, `auto` |
| `--size` | `auto` or `WIDTHxHEIGHT`; GPT Image 2 dimension rules are validated |
| `--stream` | Parse an SSE response and save its final image |
| `--user` | Stable end-user identifier |

Output-only controls are `--output-dir`, `--output-prefix`, and `--save-partials`. Use `--extra-json '{"field":"value"}'` only for compatible future or gateway-specific request fields; credential and endpoint fields are rejected. Run `python3 scripts/generate_image.py --help` for exact constraints.

## Common mistakes

- Transparent output requires PNG or WebP.
- Compression applies only to JPEG or WebP.
- `--partial-images` and `--save-partials` require streaming.
- Do not add `response_format`; GPT image models return Base64 image data.
