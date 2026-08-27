#!/usr/bin/env python3
import base64
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


SCRIPT = Path(__file__).with_name("generate_image.py")


def load_module():
    spec = importlib.util.spec_from_file_location("generate_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def encoded(value):
    return base64.b64encode(value).decode("ascii")


class FakeResponse:
    def __init__(self, body, content_type="application/json"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class GenerateImageTests(unittest.TestCase):
    def test_json_response_saves_multiple_images_and_sends_defaults(self):
        module = load_module()
        payload = json.dumps({"data": [{"b64_json": encoded(b"one")}, {"b64_json": encoded(b"two")}], "created": 7}).encode()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"GLOBALAI_API_KEY": "secret"}, clear=False), patch.object(module, "request_generation", return_value=(payload, "application/json")) as request:
            args = module.build_parser().parse_args(["--prompt", "studio poster", "--output-dir", temp_dir])
            output = module.run(args)

            body = request.call_args.args[2]
            self.assertEqual(body, {"model": "gpt-image-2", "prompt": "studio poster", "n": 1, "output_format": "png"})
            self.assertEqual(Path(output["files"][0]).read_bytes(), b"one")
            self.assertEqual(Path(output["files"][1]).read_bytes(), b"two")
            self.assertEqual(output["metadata"]["created"], 7)

    def test_forwards_native_parameters_and_extra_json(self):
        module = load_module()
        payload = json.dumps({"data": [{"b64_json": encoded(b"webp")}]}).encode()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"GLOBALAI_API_KEY": "secret"}, clear=False), patch.object(module, "request_generation", return_value=(payload, "application/json")) as request:
            args = module.build_parser().parse_args([
                "--prompt", "icon", "--model", "gpt-image-2-snapshot", "--background", "transparent",
                "--moderation", "low", "--n", "3", "--output-format", "webp",
                "--output-compression", "80", "--quality", "high", "--size", "1536x864",
                "--user", "end-user", "--extra-json", '{"vendor_option":true}', "--output-dir", temp_dir,
            ])
            module.run(args)
            body = request.call_args.args[2]
            self.assertEqual(body["model"], "gpt-image-2-snapshot")
            self.assertEqual(body["vendor_option"], True)
            self.assertEqual(body["output_compression"], 80)
            self.assertEqual(body["size"], "1536x864")

    def test_stream_response_saves_final_and_partial(self):
        module = load_module()
        events = (
            "data: " + json.dumps({"type": "image_generation.partial_image", "b64_json": encoded(b"partial"), "output_format": "png"}) + "\n\n"
            "data: " + json.dumps({"type": "image_generation.completed", "b64_json": encoded(b"final"), "output_format": "png"}) + "\n\n"
        ).encode()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"GLOBALAI_API_KEY": "secret"}, clear=False), patch.object(module, "request_generation", return_value=(events, "text/event-stream")):
            args = module.build_parser().parse_args([
                "--prompt", "stream", "--stream", "--partial-images", "1", "--save-partials", "--output-dir", temp_dir,
            ])
            output = module.run(args)
            self.assertEqual(Path(output["files"][0]).read_bytes(), b"final")
            self.assertEqual(Path(output["partial_files"][0]).read_bytes(), b"partial")

    def test_existing_file_is_not_overwritten(self):
        module = load_module()
        payload = json.dumps({"data": [{"b64_json": encoded(b"new")}]}).encode()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"GLOBALAI_API_KEY": "secret"}, clear=False), patch.object(module, "request_generation", return_value=(payload, "application/json")):
            existing = Path(temp_dir, "image-001.png")
            existing.write_bytes(b"old")
            args = module.build_parser().parse_args(["--prompt", "x", "--output-dir", temp_dir])
            output = module.run(args)
            self.assertEqual(existing.read_bytes(), b"old")
            self.assertEqual(Path(output["files"][0]).name, "image-002.png")

    def test_missing_key_fails_before_request(self):
        module = load_module()
        with patch.dict(os.environ, {}, clear=True):
            args = module.build_parser().parse_args(["--prompt", "x"])
            with self.assertRaisesRegex(module.GenerationError, "GLOBALAI_API_KEY"):
                module.run(args)

    def test_http_error_is_sanitized(self):
        module = load_module()
        secret = "super-private-token"
        detail = json.dumps({"error": {"message": f"bad token {secret}"}}).encode()

        def fail_urlopen(_request, timeout):
            self.assertEqual(timeout, 300)
            raise HTTPError("https://example.test", 401, "Unauthorized", {}, io.BytesIO(detail))

        with patch.object(module, "urlopen", fail_urlopen):
            with self.assertRaises(module.GenerationError) as caught:
                module.request_generation("https://example.test", secret, {"model": "gpt-image-2"})
        message = str(caught.exception)
        self.assertIn("HTTP 401", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn(secret, message)

    def test_rejects_invalid_parameter_combinations(self):
        module = load_module()
        cases = [
            (["--prompt", "x", "--n", "0"], "--n"),
            (["--prompt", "x", "--output-format", "png", "--output-compression", "80"], "output-compression"),
            (["--prompt", "x", "--background", "transparent", "--output-format", "jpeg"], "transparent"),
            (["--prompt", "x", "--partial-images", "1"], "partial-images"),
            (["--prompt", "x", "--size", "1000x1000"], "divisible by 16"),
            (["--prompt", "x", "--extra-json", "[]"], "JSON object"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                args = module.build_parser().parse_args(values)
                with self.assertRaisesRegex(module.GenerationError, expected):
                    extra = module.parse_extra_json(args.extra_json)
                    module.validate_request(args, extra)


if __name__ == "__main__":
    unittest.main()
