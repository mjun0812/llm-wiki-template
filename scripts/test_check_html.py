"""Check template integrity and navigation validation with generated pages."""

import re
import tempfile
import unittest
from pathlib import Path

from check_html import TEMPLATE_PATH, check_file


class HtmlTemplateTest(unittest.TestCase):
    """Exercise accepted pages and malformed generated HTML."""

    def setUp(self) -> None:
        """Render a minimal index page without optional external libraries."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "index.html"
        self.page = TEMPLATE_PATH.read_text()
        values = {
            "TITLE": "検査用ページ",
            "CREATED": "2026-09-21",
            "UPDATED": "2026-09-21",
            "MODEL": "test",
            "LEDE": "検査用の本文。",
            "SUMMARY": "<li>要約</li>",
            "SOURCE_META": "",
            "INDEX": '<ul><li><a href="index.html" aria-current="page">索引</a></li></ul>',
            "BODY": '<h2 id="intro">概要</h2><p><a href="#term-example">用語</a></p>',
            "GLOSSARY": '<dt id="term-example">用語</dt><dd>定義。</dd>',
            "SOURCES": "",
        }
        for key, value in values.items():
            self.page = self.page.replace(f"{{{{{key}}}}}", value)
        for name in ("mathjax", "shiki", "mermaid"):
            self.page = re.sub(
                rf"<!-- exhtml:{name}\b.*?<!-- /exhtml:{name} -->",
                "",
                self.page,
                flags=re.DOTALL,
            )

    def codes(self, page: str) -> set[str]:
        """Return error codes emitted for the supplied page.

        Args:
            page: Complete generated HTML.

        Returns:
            Set of diagnostic codes.
        """
        self.path.write_text(page)
        return {diagnostic.code for diagnostic in check_file(self.path)}

    def test_valid_page(self) -> None:
        """Accept the actual template after all placeholders are expanded."""
        self.assertEqual(self.codes(self.page), set())

    def test_modified_fixed_blocks(self) -> None:
        """Reject changed CSS and code hidden inside a trusted block marker."""
        self.assertIn("HTML004", self.codes(self.page.replace("#141414", "#ffffff")))
        self.assertIn(
            "HTML002",
            self.codes(self.page.replace('const KEY = "exhtml-theme";', 'alert("x");')),
        )

    def test_extra_script_and_external_image(self) -> None:
        """Reject page scripts and external images outside template blocks."""
        self.assertIn("HTML002", self.codes(self.page + "<script>alert(1)</script>"))
        self.assertIn(
            "HTML001", self.codes(self.page + '<img src="https://example.com/a.png">')
        )

    def test_broken_glossary_and_missing_sidebar(self) -> None:
        """Reject unresolved glossary links and a missing sidebar region."""
        self.assertIn(
            "HTML009",
            self.codes(self.page.replace('id="term-example"', 'id="term-other"')),
        )
        self.assertIn(
            "HTML009", self.codes(self.page.replace('class="ex-sidebar"', 'class="x"'))
        )

    def test_optional_blocks(self) -> None:
        """Allow exact optional blocks but reject modifications inside them."""
        template = TEMPLATE_PATH.read_text()
        for name in ("mathjax", "shiki", "mermaid"):
            with self.subTest(name=name):
                match = re.search(
                    rf"<!-- exhtml:{name}\b.*?<!-- /exhtml:{name} -->",
                    template,
                    re.DOTALL,
                )
                assert match is not None
                block = match.group()
                self.assertEqual(
                    self.codes(self.page.replace("</body>", block + "</body>")), set()
                )
                changed = block.replace("<script", "<script data-custom", 1)
                self.assertIn(
                    "HTML002",
                    self.codes(self.page.replace("</body>", changed + "</body>")),
                )


if __name__ == "__main__":
    unittest.main()
