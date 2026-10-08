"""PDF export — markdown to a text-based PDF via headless Chrome.

Runs as a module (python3 pdf.py draft.md out.pdf --verify), and is also wired
into forge.py (`pdf`), server.py (POST /api/pdf) and the web export button.

The test covers: markdown-to-HTML mapping, the no-Chrome fallback, an empty
document, and that page geometry lives in the stylesheet rather than the code.
"""

import unittest
from pathlib import Path

import lint
import pdf


SAMPLE = """\
# Jane Doe
jane@example.com | Boston, MA

## Summary
Backend engineer with 6 years in payments.

## Experience

### Senior Backend Engineer | Acme | 2021 – Present
- Led migration to 12 Python microservices
- Cut p99 latency from 840ms to 210ms
"""


class PdfHtml(unittest.TestCase):
    def test_name_contact_and_sections(self):
        html = pdf.to_html(SAMPLE)
        self.assertIn("<h1>Jane Doe</h1>", html)
        self.assertIn('class="contact"', html)
        self.assertIn("jane@example.com", html)
        self.assertIn("<h2>Summary</h2>", html)
        self.assertIn("<h2>Experience</h2>", html)

    def test_role_date_is_split_for_right_alignment(self):
        html = pdf.to_html(SAMPLE)
        self.assertIn('class="role-meta"', html)
        self.assertIn("<span>Senior Backend Engineer | Acme</span>", html)
        self.assertIn("<span>2021 – Present</span>", html)
        # A table would be the wrong tool for this, and would break parsers.
        self.assertNotIn("<table", html)

    def test_bullets_become_a_list(self):
        html = pdf.to_html(SAMPLE)
        self.assertIn("<ul>", html)
        self.assertIn("<li>Led migration to 12 Python microservices</li>", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_markup_is_escaped(self):
        html = pdf.to_html("# A & B\n\n- 5 < 6 and \"quotes\"\n")
        self.assertIn("A &amp; B", html)
        self.assertNotIn("<h1>A & B", html)

    def test_inline_formatting_kept_simple(self):
        html = pdf.to_html("- Built **fast** pipelines with `go`\n")
        self.assertIn("<strong>fast</strong>", html)
        self.assertIn("<code>go</code>", html)

    def test_horizontal_rules_dropped(self):
        html = pdf.to_html(SAMPLE + "\n---\n")
        self.assertNotIn("<hr", html)

    def test_empty_input_is_not_a_crash(self):
        self.assertEqual(pdf.to_html("").strip(), "")


class PageAssembly(unittest.TestCase):
    def test_page_embeds_the_print_stylesheet(self):
        page = pdf.build_page(SAMPLE)
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("id=\"printSheet\"", page)
        self.assertIn("font-size: 10.5pt", page)
        self.assertIn("Jane Doe", page)

    def test_geometry_lives_in_css_not_in_python(self):
        """Margins belong to @page in the stylesheet, so the browser dialog and
        headless Chrome cannot drift. If this fails, someone hardcoded a size."""
        css = pdf.CSS.read_text()
        self.assertIn("@page", css)
        self.assertIn("size: Letter", css)
        self.assertIn("margin: 0.75in", css)
        self.assertNotIn("0.75in", Path(pdf.__file__).read_text())


class Fallbacks(unittest.TestCase):
    def test_missing_chrome_gives_an_actionable_error(self):
        real = pdf.find_chrome
        pdf.find_chrome = lambda: None
        try:
            with self.assertRaises(RuntimeError) as ctx:
                pdf.to_pdf(SAMPLE, "/tmp/should-not-exist.pdf")
        finally:
            pdf.find_chrome = real
        self.assertIn("browser", str(ctx.exception).lower())
        self.assertFalse(Path("/tmp/should-not-exist.pdf").exists())

    def test_verify_text_absent_tool_returns_none(self):
        real = __import__("shutil").which
        __import__("shutil").which = lambda name: None
        try:
            self.assertIsNone(pdf.verify_text("/tmp/anything.pdf"))
        finally:
            __import__("shutil").which = real


class Agreement(unittest.TestCase):
    def test_pdf_and_lint_agree_the_source_is_clean(self):
        """The same markdown the exporter renders must pass the linter. A
        divergence means the two halves of the tool disagree."""
        self.assertEqual(
            [v for v in lint.lint(SAMPLE) if v["rule"] != "keyword-coverage"],
            [],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)