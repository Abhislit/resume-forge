"""Markdown resume to PDF, via headless Chrome's own print engine.

No PDF library. Chrome renders the page and prints it, which is the same path
the browser's print dialog takes, so a PDF made here is identical to one a user
would produce by hand.

The layout lives in one place — the @media print block in web/style.css — so
the browser dialog and this command cannot drift apart. This file only decides
which element each markdown line becomes, and that mapping is deliberately thin:
no styling, no sizes, no fonts.

Output is a text-based PDF, never a raster, which is what a parser needs.
Verify with pdftotext.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSS = ROOT / "web" / "style.css"

# Chrome prints its own header and footer by default, which would put a URL and
# a page number into the resume.
CHROME_CANDIDATES = [
    "google-chrome-stable", "google-chrome", "chromium", "chromium-browser",
    "chrome",
]


def find_chrome():
    for name in CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _esc(s):
    return (
        str(s)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _inline(text):
    """Bold, italic and code only — nothing a parser would need to untangle.

    Code first so that ``**literal**`` inside backticks stays literal.
    """
    s = _esc(text)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(^|[^*])\*([^*\n]+)\*", r"\1<em>\2</em>", s)
    return s


def to_html(markdown):
    """Markdown -> the DOM the print stylesheet expects.

    Mirrors buildPrintSheet() in web/app.js. The duplication is deliberate and
    small: keeping the mapping in one language would mean reimplementing a
    Markdown parser to share forty lines.
    """
    out = []
    in_list = False
    seen_name = False
    seen_section = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in (markdown or "").split("\n"):
        line = raw.strip()
        if not line:
            close_list()
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue
        close_list()

        if re.match(r"^(-{3,}|={3,}|\*{3,})$", line):
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            if level == 1:
                out.append(f"<h1>{_inline(text)}</h1>")
                seen_name = True
                continue
            if level == 2:
                out.append(f"<h2>{_inline(text)}</h2>")
                seen_section = True
                continue

            # Role heading: a trailing date range is split off so the stylesheet
            # can right-align it with flexbox instead of a table.
            m = re.match(
                r"^(.*?)[\s|]+((?:19|20)\d{2}\s*[–—-]\s*"
                r"(?:(?:19|20)\d{2}|Present|Current|Now))$",
                text, re.IGNORECASE,
            )
            if m:
                out.append(
                    '<div class="role-meta">'
                    f"<span>{_inline(m.group(1).strip())}</span>"
                    f"<span>{_inline(m.group(2).strip())}</span></div>"
                )
            else:
                out.append(f"<h3>{_inline(text)}</h3>")
            continue

        # The first line after the name is the contact block.
        if seen_name and not seen_section:
            out.append(f'<div class="contact">{_inline(line)}</div>')
            seen_section = True
            continue

        out.append(f"<p>{_inline(line)}</p>")

    close_list()
    return "\n".join(out)


def build_page(markdown):
    """A complete standalone document. Inline CSS so there is no second request."""
    css = CSS.read_text(encoding="utf-8") if CSS.exists() else ""
    body = to_html(markdown)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        "<title>Resume</title>\n"
        f"<style>\n{css}\n</style>\n"
        "</head>\n"
        f'<body><article id="printSheet" aria-hidden="true">\n{body}\n'
        "</article></body></html>\n"
    )


def to_pdf(markdown, out_path, *, timeout=60, chrome=None):
    """Render markdown to a PDF. Returns the output Path."""
    chrome = chrome or find_chrome()
    if not chrome:
        raise RuntimeError(
            "No Chrome or Chromium found. Open the resume in a browser and use "
            "Print -> Save as PDF instead."
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "resume.html"
        page.write_text(build_page(markdown), encoding="utf-8")
        pdf = Path(tmp) / "resume.pdf"

        cmd = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=4000",
            f"--print-to-pdf={pdf}",
            f"file://{page}",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Chrome timed out after {timeout}s") from exc

        if not pdf.exists() or pdf.stat().st_size == 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")[-800:]
            raise RuntimeError(f"Chrome produced no PDF.\n{stderr}")

        out_path.write_bytes(pdf.read_bytes())

    return out_path


def verify_text(pdf_path, pdftotext="pdftotext"):
    """Extract the text a parser would see. None means the PDF is a scan.

    An image-only PDF parses as a blank page, which is the most common way a
    resume fails silently.
    """
    path = shutil.which(pdftotext)
    if not path:
        return None
    proc = subprocess.run(
        [path, str(pdf_path), "-"], capture_output=True, check=False
    )
    return proc.stdout.decode("utf-8", errors="replace")


def page_count(pdf_path):
    """Page count without a PDF library: count the page objects."""
    data = Path(pdf_path).read_bytes()
    counts = re.findall(rb"/Type\s*/Pages[^>]*?/Count\s+(\d+)", data)
    if counts:
        return max(int(c) for c in counts)
    return len(re.findall(rb"/Type\s*/Page[^s]", data)) or None


def main(argv):
    import argparse

    p = argparse.ArgumentParser(prog="pdf.py", description=__doc__.split("\n")[0])
    p.add_argument("markdown", help="resume markdown file, or - for stdin")
    p.add_argument("output", nargs="?", help="output .pdf path")
    p.add_argument("--verify", action="store_true",
                   help="extract the text and report whether it is text-based")
    args = p.parse_args(argv)

    markdown = (
        sys.stdin.read() if args.markdown == "-"
        else Path(args.markdown).read_text(encoding="utf-8", errors="replace")
    )
    out = args.output or str(Path(args.markdown).with_suffix(".pdf"))

    path = to_pdf(markdown, out)
    print(f"wrote {path} ({path.stat().st_size} bytes, "
          f"{page_count(path) or '?'} page(s))")

    if args.verify:
        text = verify_text(path)
        if text is None:
            print("pdftotext not installed; could not verify extractability")
            return 0
        stripped = text.strip()
        if not stripped:
            print("NO TEXT EXTRACTED — this PDF is a scan and will parse blank")
            return 1
        words = len(stripped.split())
        print(f"text-based: yes ({words} words extractable)")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))