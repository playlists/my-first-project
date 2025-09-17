import unittest
from pathlib import Path

from prompt_oneshot.replacer import (
    ConfigError,
    MarkdownDocument,
    ReplacementPlan,
    SourceSpec,
    replace_oneshots,
)


class MarkdownDocumentTests(unittest.TestCase):
    def test_section_extraction(self) -> None:
        text = """# Title

## Section One
Line A

## Section Two
Line B
"""
        doc = MarkdownDocument(text)
        self.assertEqual(doc.section("Section One", level=2), "## Section One\nLine A")
        self.assertEqual(
            doc.section("Section Two", level=2, include_heading=False),
            "Line B",
        )
        with self.assertRaises(ConfigError):
            doc.section("Missing")


class ReplacementFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_dir = Path.cwd()

    def test_literal_replacement(self) -> None:
        prompt = "Intro\nSTART\nold content\nEND\nOutro"
        example = "# Example\n\nBody"
        plan = ReplacementPlan(
            start_marker="START",
            end_marker="END",
            source=SourceSpec(type="literal", text="new content", strip=False),
        )
        updated = replace_oneshots(prompt, example, [plan], base_dir=self.base_dir)
        self.assertIn("START\nnew content\nEND", updated)

    def test_heading_list_source(self) -> None:
        prompt = "Intro\nSTART\nold\nEND\nOutro"
        example = """# Title

## First
Alpha

## Second
Beta
"""
        plan = ReplacementPlan(
            start_marker="START",
            end_marker="END",
            source=SourceSpec(
                type="heading_list",
                headings=[
                    {"heading": "First", "level": 2, "include_heading": False},
                    {"heading": "Second", "level": 2, "include_heading": False},
                ],
                separator="\n---\n",
            ),
        )
        updated = replace_oneshots(prompt, example, [plan], base_dir=self.base_dir)
        self.assertIn("START\nAlpha\n---\nBeta\nEND", updated)

    def test_marker_source(self) -> None:
        prompt = "Intro\nSTART\nold\nEND\nOutro"
        example = "BEGIN\nValue\nFINISH"
        plan = ReplacementPlan(
            start_marker="START",
            end_marker="END",
            source=SourceSpec(
                type="markers",
                start_marker="BEGIN",
                end_marker="FINISH",
                strip=True,
            ),
        )
        updated = replace_oneshots(prompt, example, [plan], base_dir=self.base_dir)
        self.assertIn("START\nValue\nEND", updated)


if __name__ == "__main__":
    unittest.main()
