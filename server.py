"""resume-forge — local server.

Python stdlib only. The Anthropic API key is read from the environment of this
process and never sent to the browser or written to disk.

Run:  python3 server.py        then open http://localhost:8770
"""

import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import docx_writer
import learn
import lint
import match as matcher
import parse as jd_parse
import research

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
PROFILE_PATH = ROOT / "profile.md"
PROFILE_TEMPLATE = ROOT / "references" / "profile-template.md"

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8770"))

API_URL = "https://api.anthropic.com/v1/messages"
API_MODEL = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = 8000

# Guard rails for the local-only posture: reject requests carrying an API key
# or an Origin the browser would have set, so a random page cannot drive this
# server from the user's machine.
_ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}


SYSTEM_PROMPT = """\
You write resume bullets. You are given the user's own profile and a job \
description's requirements. Your only job is to phrase what the user actually \
did so a reader can match it to the posting.

Non-negotiable rules:

1. NEVER introduce a claim the user did not make. No invented employer, job \
title, date, degree, technology, team size, or metric. If a number is needed \
and none was supplied, write it as [confirm: what to check] and nothing more. \
A made-up number is worse than a missing one.
2. One bullet = action verb, what was done, technical or domain context, \
business impact. Past tense for completed work.
3. No personal pronouns (I, my, we, our). No bullet ends with a period.
4. No superfluous verbs (spearheaded, orchestrated, utilized, leveraged) and \
no empty intensifiers (excellent, innovative, strategically, highly).
5. Do not repeat a keyword more than twice across the whole document. \
Keyword stuffing is falsification and risks disqualification.
6. Never use vague quantifiers (various, multiple, several, etc.) — name the \
specific thing instead.
7. If a requirement is not supported by the profile, do not paper over it. \
Leave it out of the resume; it appears in the gaps report instead.

Return ONLY a JSON object with this shape:

{
  "summary": "2-3 sentence professional summary, no pronouns",
  "key_skills": ["ordered skill list, posting terms first"],
  "roles": [
    {
      "title": "as written in the profile",
      "company": "as written in the profile",
      "dates": "as written in the profile",
      "bullets": ["up to 6 bullets"]
    }
  ],
  "warnings": ["anything you declined to write, and why"]
}
"""


class ForgeError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status
        self.message = message


# --- profile ---------------------------------------------------------------

def read_profile():
    if PROFILE_PATH.exists():
        return PROFILE_PATH.read_text(encoding="utf-8")
    if PROFILE_TEMPLATE.exists():
        return PROFILE_TEMPLATE.read_text(encoding="utf-8")
    return ""


def write_profile(text):
    """Profile writes are the user's own edit from the UI. Only this writes it."""
    PROFILE_PATH.write_text(text, encoding="utf-8")
    return {"saved": True, "bytes": len(text)}


# --- AI -------------------------------------------------------------------

def _extract_json(text):
    """Pull a JSON object out of a model response, fenced or not."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ForgeError("The model returned no JSON object.", 502)
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ForgeError(f"Model returned malformed JSON: {exc}", 502) from exc


_NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d,]*\.?\d*)\s*(%|x|k|m|b|bn|million|billion|thousand)?")


def fabrication_guard(payload, profile_text):
    """Reject numbers in the draft that do not appear in the profile.

    This is the honesty backstop: the system prompt asks for truth, and this
    verifies it. A number is allowed if it appears in the profile, if it is an
    allowed placeholder, or if it is a year that predates the profile's own
    vocabulary (dates are copyable facts, not claims).
    """
    profile_nums = set()
    for m in _NUMBER_RE.finditer(profile_text or ""):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        profile_nums.add(value)
        profile_nums.add(int(value) if value.is_integer() else value)

    suspicious = []
    for role in payload.get("roles", []):
        for bullet in role.get("bullets", []):
            if "[confirm:" in bullet:
                continue
            for m in _NUMBER_RE.finditer(bullet):
                raw = m.group(1).replace(",", "")
                try:
                    value = float(raw)
                except ValueError:
                    continue
                if value not in profile_nums:
                    suspicious.append({
                        "number": m.group(0).strip(),
                        "bullet": bullet,
                        "role": role.get("title", ""),
                    })
    return suspicious


def call_model(payload):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ForgeError(
            "ANTHROPIC_API_KEY is not set. Export it and restart, or use the "
            "manual draft box on the Draft step.",
            400,
        )

    body = json.dumps({
        "model": API_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": payload["instructions"]}],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise ForgeError(f"Anthropic API returned {exc.code}: {detail}", 502) from exc
    except urllib.error.URLError as exc:
        raise ForgeError(f"Could not reach the Anthropic API: {exc.reason}", 502) from exc

    chunks = [
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    if not chunks:
        raise ForgeError("The model returned an empty response.", 502)

    return _extract_json("".join(chunks))


# --- markdown assembly -----------------------------------------------------

def build_instructions(profile_text, matrix, jd_text):
    """The one prompt. Everything the model needs, nothing it does not."""
    lines = []
    lines.append("TARGET JOB DESCRIPTION (for context only — do not copy claims from it):")
    lines.append(jd_text.strip()[:6000])
    lines.append("")
    lines.append("CANDIDATE PROFILE — the ONLY source of truth. Every claim must come from here:")
    lines.append(profile_text.strip()[:12000])
    lines.append("")
    lines.append("REQUIREMENT MATCH REPORT:")
    for row in matrix["rows"]:
        mark = {"covered": "OK", "partial": "PARTIAL", "gap": "GAP"}[row["status"]]
        lines.append(f"- [{mark}] ({row['kind']}) {row['text']}")
        if row["evidence"]:
            lines.append(f"    profile evidence: {'; '.join(row['evidence'][:2])}")
        if row["status"] != "covered":
            missing = [t for t, s in row["term_status"].items() if s != "covered"]
            if missing:
                lines.append(
                    f"    unsupported terms: {', '.join(missing)} — do NOT "
                    "claim these; the user will answer for them"
                )
    lines.append("")
    brief = learn.brief(matcher.guess_role(profile_text) or None)
    company = learn.guess_company(jd_text or "")
    if company:
        company_brief = research.brief(company)
        if company_brief:
            lines.append("WHAT IS KNOWN ABOUT THE EMPLOYER:")
            lines.append(company_brief)
            lines.append("")
    if brief:
        lines.append("WHAT THE ARCHIVE SAYS ABOUT THIS MARKET:")
        lines.append(brief)
        lines.append(
            "Treat confirmed terms as safe to lead with. Do not add a term just "
            "because it appears here — the archive says the market wants it, not "
            "that the candidate has it."
        )
    lines.append("")
    lines.append(
        "Write the resume now. Prefer terms the posting uses where the profile "
        "genuinely supports them. Keep it to two pages of content."
    )
    return "\n".join(lines)


def render_markdown(draft, title="Resume"):
    """Draft JSON -> markdown for editing, DOCX, and print-to-PDF."""
    out = []

    name = (draft.get("name") or "").strip()
    contact = (draft.get("contact") or "").strip()
    if name or contact:
        out.append(f"# {name or 'Resume'}")
        if contact:
            out.append(contact)
        out.append("")

    if draft.get("summary"):
        out.append("## Summary")
        out.append(draft["summary"].strip())
        out.append("")

    if draft.get("key_skills"):
        out.append("## Skills")
        out.append(" · ".join(s.strip() for s in draft["key_skills"]))
        out.append("")

    for role in draft.get("roles", []):
        title_line = role.get("title", "").strip()
        company = role.get("company", "").strip()
        dates = role.get("dates", "").strip()
        heading = title_line
        if company:
            heading += f" | {company}"
        if dates:
            heading += f" | {dates}"
        out.append(f"### {heading}")
        if role.get("context"):
            out.append(role["context"].strip())
        for bullet in role.get("bullets", []):
            out.append(f"- {bullet.strip()}")
        out.append("")

    for section_key, heading in (
        ("projects", "Projects"),
        ("education", "Education"),
        ("certifications", "Certifications"),
    ):
        items = draft.get(section_key) or []
        if items:
            out.append(f"## {heading}")
            for item in items:
                if isinstance(item, str):
                    out.append(f"- {item.strip()}")
                elif isinstance(item, dict):
                    label = " — ".join(
                        str(v).strip() for v in item.values() if v
                    )
                    out.append(f"- {label}")
            out.append("")

    text = "\n".join(out).rstrip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", text)


# --- request handling ------------------------------------------------------

def read_body(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ForgeError(f"Request body is not valid JSON: {exc}", 400) from exc


def _archive(jd, requirements, role=None):
    """Archive a posting, de-duplicating by content hash.

    Returns (record_or_None, already_seen). Never raises: a read-only home
    directory should degrade the learning, not break the app.
    """
    try:
        existing = learn.find_by_fingerprint(jd)
        if existing is not None:
            return existing, True
        return learn.record(jd, requirements, role=role), False
    except OSError:
        return None, False


def _archive_fields(jd, requirements, role=None):
    rec, seen = _archive(jd, requirements, role)
    return {
        "archived": rec is not None,
        "archive_id": rec["id"] if rec else None,
        "already_seen": seen,
        "stats": learn.stats(),
    }


def handle_api(handler, path, body):
    if path == "/api/profile":
        if body.get("profile") is not None:
            return write_profile(body["profile"])
        return {"profile": read_profile()}

    if path == "/api/parse":
        jd = body.get("jd", "")
        if not jd.strip():
            raise ForgeError("Paste or upload a job description first.", 400)
        requirements = jd_parse.parse(jd)

        # Archive on every paste. Re-parsing the same posting must not inflate
        # the learned counts, so this de-duplicates by content hash.
        return {
            "requirements": requirements,
            "jd_length": len(jd),
            **_archive_fields(jd, requirements, body.get("role")),
        }

    if path == "/api/fetch":
        url = (body.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ForgeError("Enter a full http(s) URL.", 400)
        try:
            text = jd_parse.fetch_url(url)
        except Exception as exc:  # network failures are expected, not bugs
            raise ForgeError(f"Could not fetch that URL: {exc}", 400) from exc
        reqs = jd_parse.parse(text)
        return {"jd": text, "requirements": reqs,
                **_archive_fields(text, reqs, body.get("role"))}

    if path == "/api/upload":
        data = body.get("docx_base64")
        if not data:
            raise ForgeError("No file content received.", 400)
        import base64
        raw = base64.b64decode(data)
        try:
            text = jd_parse.read_docx(raw)
        except Exception as exc:
            raise ForgeError(
                f"That file could not be read as a .docx: {exc}", 400
            ) from exc
        reqs = jd_parse.parse(text)
        return {"jd": text, "requirements": reqs,
                **_archive_fields(text, reqs, body.get("role"))}

    if path == "/api/match":
        profile = body.get("profile")
        if profile is None:
            profile = read_profile()
        requirements = body.get("requirements") or []
        if not requirements:
            raise ForgeError("Parse a job description first.", 400)
        matrix = matcher.match(requirements, profile)
        return {
            "matrix": matrix,
            "summary": matcher.summary(matrix),
            "open_items": matcher.open_items(matrix, learn.term_weights()),
            "role": matcher.guess_role(profile),
        }

    if path == "/api/learn/stats":
        return {"stats": learn.stats(), "role": body.get("role")}

    if path == "/api/learn/brief":
        return {"brief": learn.brief(body.get("role"))}

    if path == "/api/learn/outcome":
        try:
            record_ = learn.set_outcome(
                int(body.get("id")), body.get("outcome"), body.get("note")
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ForgeError(str(exc), 400) from exc
        return {"record": record_, "stats": learn.stats()}

    if path == "/api/learn/patterns":
        return {"path": learn.render_patterns(), "stats": learn.stats()}

    if path == "/api/tailor":
        profile = body.get("profile")
        if profile is None:
            profile = read_profile()
        if not profile.strip():
            raise ForgeError(
                "Your profile is empty. Fill in step 2, or paste an existing "
                "resume.",
                400,
            )
        requirements = body.get("requirements") or []
        jd_text = body.get("jd", "")
        matrix = matcher.match(requirements, profile)

        instructions = build_instructions(profile, matrix, jd_text)
        draft = call_model({"instructions": instructions})

        draft.setdefault("name", _first_line_name(profile))
        draft.setdefault("contact", _contact_line(profile))

        suspicious = fabrication_guard(draft, profile)
        markdown = render_markdown(draft)

        violations = lint.lint(markdown, requirements)

        return {
            "draft": draft,
            "markdown": markdown,
            "violations": violations,
            "fabrication_warnings": suspicious,
            "model_warnings": draft.get("warnings", []),
        }

    if path == "/api/lint":
        markdown = body.get("markdown", "")
        requirements = body.get("requirements") or []
        return {
            "violations": lint.lint(markdown, requirements),
            "plain_text": lint.plain_text_export(markdown),
        }

    if path == "/api/docx":
        markdown = body.get("markdown", "")
        if not markdown.strip():
            raise ForgeError("Nothing to export.", 400)
        data = docx_writer.build_docx(markdown, title=body.get("title") or "Resume")
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", (body.get("title") or "Resume")).strip("-")
        return {
            "__bytes__": data,
            "__filename__": f"{name}.docx",
            "__content_type__":
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
        }

    if path == "/api/pdf":
        markdown = body.get("markdown", "")
        if not markdown.strip():
            raise ForgeError("Nothing to export.", 400)
        try:
            out = ROOT / "exports"
            out.mkdir(exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "-",
                          (body.get("title") or "Resume")).strip("-")
            target = out / f"{safe or 'Resume'}.pdf"
            import pdf as pdf_mod
            pdf_mod.to_pdf(markdown, str(target))
        except RuntimeError as exc:
            raise ForgeError(str(exc), 500) from exc
        return {
            "__bytes__": target.read_bytes(),
            "__filename__": target.name,
            "__content_type__": "application/pdf",
        }

    raise ForgeError(f"Unknown endpoint {path}", 404)


def _first_line_name(profile):
    for raw in (profile or "").split("\n"):
        line = raw.strip()
        if line.startswith("# "):
            return line[2:].strip()
        if line and not line.startswith(("#", "-", "*", ">", "|")):
            return line.strip()
    return ""


def _contact_line(profile):
    """Second line of the profile if it looks like contact info."""
    lines = [l.strip() for l in (profile or "").split("\n")[:12]]
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if "@" in line or "http" in line or re.search(r"\+?\d[\d ()-]{7,}", line):
            return line.lstrip("-* ").strip()
    return ""


class Handler(SimpleHTTPRequestHandler):
    server_version = "resume-forge"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    # --- helpers
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, content_type, filename):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"',
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _check_origin(self):
        """Refuse cross-origin POSTs so a random web page cannot drive this."""
        origin = self.headers.get("Origin")
        if origin and origin not in _ALLOWED_ORIGINS:
            raise ForgeError("Cross-origin request refused.", 403)

    # --- verbs
    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            return self._json({"error": "GET is not supported on API routes."}, 405)
        if path == "/":
            path = "/index.html"
        if path == "/api-health":
            return self._json({
                "ok": True,
                "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "profile_exists": PROFILE_PATH.exists(),
                "model": API_MODEL,
            })
        target = (WEB / path.lstrip("/")).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
            return self._json({"error": "Not found"}, 404)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = self.path.split("?")[0]
        if not path.startswith("/api/"):
            return self._json({"error": "Not found"}, 404)
        try:
            self._check_origin()
            body = read_body(self)
            result = handle_api(self, path, body)
            if "__bytes__" in result:
                return self._bytes(
                    result["__bytes__"],
                    result["__content_type__"],
                    result["__filename__"],
                )
            return self._json(result)
        except ForgeError as exc:
            return self._json({"error": exc.message}, exc.status)
        except Exception as exc:  # unexpected: report, do not leak a traceback
            return self._json({"error": f"Unexpected server error: {exc}"}, 500)

    def log_message(self, fmt, *args):
        # Quiet by default; noisy output buries the app's own messages.
        if os.environ.get("FORGE_VERBOSE"):
            super().log_message(fmt, *args)


def main():
    if not WEB.is_dir():
        sys.exit(f"Missing web/ directory at {WEB}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("warning: ANTHROPIC_API_KEY is not set.")
        print("         The Draft step needs it. Everything else works offline,")
        print("         and the Draft step has a manual paste fallback.\n")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"resume-forge  →  http://{HOST}:{PORT}")
    print(f"profile: {PROFILE_PATH}")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.server_close()


if __name__ == "__main__":
    main()