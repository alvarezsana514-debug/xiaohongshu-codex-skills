#!/usr/bin/env python3
import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("edit_image.py")


def load_module():
    spec = importlib.util.spec_from_file_location("edit_image", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class EditImageTests(unittest.TestCase):
    def run_cli(self, args, key="test-secret"):
        env = os.environ.copy()
        if key is None:
            env.pop("GLOBALAI_API_KEY", None)
        else:
            env["GLOBALAI_API_KEY"] = key
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], env=env,
            capture_output=True, text=True, check=False,
        )

    def test_curl_transport_sends_reference_and_keeps_secret_out_of_argv(self):
        module = load_module()
        secret = "super-private-token"
        response = json.dumps({"data": [{"b64_json": base64.b64encode(b"edited-image").decode()}]})
        completed = SimpleNamespace(returncode=0, stdout=response, stderr="")
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(module.subprocess, "run", return_value=completed) as run:
            reference = Path(temp_dir, "reference.png")
            reference.write_bytes(b"reference")
            fields = {
                "model": "gpt-image-2", "prompt": "replace copy", "size": "1152x1536",
                "quality": "high", "output_format": "png", "n": "1",
            }
            raw = module.request_edit_with_curl("https://example.test/v1/images/edits", secret, fields, reference)

            argv = run.call_args.args[0]
            stdin_config = run.call_args.kwargs["input"]
            self.assertNotIn(secret, " ".join(argv))
            self.assertIn(secret, stdin_config)
            self.assertIn("https://example.test/v1/images/edits", stdin_config)
            self.assertIn("model=gpt-image-2", stdin_config)
            self.assertIn("prompt=replace copy", stdin_config)
            self.assertIn(f"image=@{reference};type=image/png", stdin_config)
            self.assertEqual(module.parse_response(raw), [b"edited-image"])

    def test_refuses_to_overwrite_existing_output(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir, "final.png")
            output_file.write_bytes(b"old")
            with self.assertRaisesRegex(module.EditError, "already exists"):
                module.save_images([b"new"], output_file)
            self.assertEqual(output_file.read_bytes(), b"old")

    def test_missing_key_and_missing_image_fail_before_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir, "reference.png")
            reference.write_bytes(b"reference")
            output_file = Path(temp_dir, "final.png")
            missing_key = self.run_cli([
                "--image", str(reference), "--prompt", "x", "--output-file", str(output_file)
            ], key=None)
            self.assertNotEqual(missing_key.returncode, 0)
            self.assertIn("GLOBALAI_API_KEY", missing_key.stderr)

            missing_image = self.run_cli([
                "--image", str(Path(temp_dir, "missing.png")), "--prompt", "x",
                "--output-file", str(output_file),
            ])
            self.assertNotEqual(missing_image.returncode, 0)
            self.assertIn("reference image", missing_image.stderr)

    def test_curl_error_is_sanitized(self):
        module = load_module()
        secret = "super-private-token"
        completed = SimpleNamespace(returncode=22, stdout="", stderr=f"bad token {secret}")
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(module.subprocess, "run", return_value=completed):
            reference = Path(temp_dir, "reference.png")
            reference.write_bytes(b"reference")
            with self.assertRaises(module.EditError) as caught:
                module.request_edit_with_curl("https://example.test", secret, {"model": "gpt-image-2"}, reference)
        message = str(caught.exception)
        self.assertIn("curl request failed", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn(secret, message)


if __name__ == "__main__":
    unittest.main()
