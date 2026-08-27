#!/usr/bin/env python3
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillPackageTests(unittest.TestCase):
    def test_skill_has_discoverable_frontmatter_and_security_guidance(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?s)^---\nname: gpt-image-2-http\ndescription: Use when .+?\n---")
        self.assertIn("GLOBALAI_API_KEY", text)
        self.assertIn("scripts/generate_image.py", text)
        self.assertIn("Never print", text)

    def test_skill_documents_every_native_generation_parameter(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for option in (
            "--prompt", "--model", "--background", "--moderation", "--n",
            "--output-compression", "--output-format", "--partial-images",
            "--quality", "--size", "--stream", "--user",
        ):
            with self.subTest(option=option):
                self.assertIn(option, text)

    def test_ui_metadata_mentions_explicit_skill_invocation(self):
        text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "GPT Image 2 HTTP"', text)
        self.assertIn("$gpt-image-2-http", text)

    def test_skill_documents_reference_image_editing(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/edit_image.py", text)
        self.assertIn("--image", text)
        self.assertIn("GLOBALAI_IMAGE_EDIT_API_URL", text)
        self.assertIn("/v1/images/edits", text)
        self.assertIn("/usr/bin/curl", text)

    def test_package_does_not_embed_a_bearer_token(self):
        for path in (
            ROOT / "SKILL.md", ROOT / "agents" / "openai.yaml",
            ROOT / "scripts" / "generate_image.py", ROOT / "scripts" / "edit_image.py",
        ):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIsNone(re.search(r"Bearer\s+(?!\{)[A-Za-z0-9_-]{8,}", text), str(path))


if __name__ == "__main__":
    unittest.main()
