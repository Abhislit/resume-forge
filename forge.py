"""One CLI for the things the resume skill needs to run.

    python3 forge.py parse   jd.txt
    python3 forge.py match   jd.txt [profile.md]
    python3 forge.py lint    draft.md [jd.txt]
    python3 forge.py pdf     draft.md [out.pdf]
    python3 forge.py brief  [role]
    python3 forge.py stats

Every command works on a first run, when no profile and no archive exist yet.
"""

import json
import sys
from pathlib import Path

import learn
import lint
import match
import parse as jd_parse

PROFILE = Path(__file__).resolve().parent / "profile.md"
TEMPLATE = Path(__file__).resolve().parent / "references" / "profile-template.md"


def _read(path, fallback_path=None):
    """Read a file, or fall back to a template, or return empty.

    A missing profile is the normal first-run state, not an error.
    """
    if path:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    if PROFILE.exists():
        return PROFILE.read_text(encoding="utf-8")
    if fallback_path and fallback_path.exists():
        return fallback_path.read_text(encoding="utf-8")
    return ""


def _read_jd(path):
    p = Path(path)
    if p.suffix.lower() == ".docx":
        return jd_parse.read_docx(str(p))
    return p.read_text(encoding="utf-8", errors="replace")


def main(argv):
    if not argv:
        print(__doc__)
        return 2

    cmd, rest = argv[0], argv[1:]

    if cmd == "parse":
        jd = _read_jd(rest[0]) if rest else sys.stdin.read()
        reqs = jd_parse.parse(jd)
        rec = learn.find_by_fingerprint(jd)
        seen = rec is not None
        if rec is None:
            try:
                rec = learn.record(jd, reqs)
            except OSError:
                rec = None
        print(json.dumps({
            "requirements": reqs,
            "archived_as": rec["id"] if rec else None,
            "already_seen": seen,
            "stats": learn.stats(),
        }, indent=2))
        return 0

    if cmd == "match":
        jd = _read_jd(rest[0]) if rest else sys.stdin.read()
        reqs = jd_parse.parse(jd)

        # Never match against the template. Reporting "covered" against example
        # content is precisely the false confidence this tool exists to avoid.
        if rest and len(rest) > 1:
            profile = _read(rest[1])
        elif PROFILE.exists():
            profile = PROFILE.read_text(encoding="utf-8")
        else:
            profile = ""

        if not profile.strip():
            print("No profile yet — create ~/resume-forge/profile.md first.")
            print("Here is what the posting asks for, which is what the "
                  "interview should cover:\n")
            for r in reqs:
                print(f"  {r['kind']:<9} {r['text'][:70]}")
                print(f"             terms: {', '.join(r['terms']) or '—'}")
            return 1

        m = match.match(reqs, profile)
        weights = learn.term_weights()
        print(json.dumps(match.summary(m), indent=2))
        print()
        for item in match.open_items(m, weights):
            strong = max(item["weights"].values(), default=0)
            print(
                f"{item['status']:<8} {item['kind']:<9} "
                f"missing={','.join(item['missing']) or '-'}"
                + (f" weight={strong}" if strong else "")
                + f"  {item['text'][:64]}"
            )
            for ev in item["adjacent_evidence"][:1]:
                print(f"         closest: {ev[:70]}")
        return 0

    if cmd == "lint":
        draft = _read(rest[0] if rest else None)
        reqs = jd_parse.parse(_read_jd(rest[1])) if len(rest) > 1 else []
        violations = lint.lint(draft, reqs)
        if not violations:
            print("clean — no named violations")
        for v in violations:
            print(f"[{v['severity']}] {v['rule']}")
            print(f"    line: {v['line'][:90]}")
            print(f"    fix:  {v['fix']}")
        return 0 if not violations else 1

    if cmd == "brief":
        print(learn.brief(rest[0] if rest else None) or "archive empty")
        return 0

    if cmd == "stats":
        print(json.dumps(learn.stats(), indent=2))
        return 0

    if cmd == "role":
        profile = _read(rest[0] if rest else None, TEMPLATE)
        print(match.guess_role(profile) or "(no role heading found)")
        return 0

    if cmd == "pdf":
        md = _read(rest[0] if rest else None)
        if not md.strip():
            print("nothing to convert", file=sys.stderr)
            return 1
        out = rest[1] if len(rest) > 1 else None
        import pdf as pdf_mod
        try:
            path = pdf_mod.to_pdf(md, out or "resume.pdf")
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {path} ({path.stat().st_size} bytes, "
              f"{pdf_mod.page_count(path) or '?'} page(s))")
        text = pdf_mod.verify_text(path)
        if text is not None:
            print("text-based:" + (" yes" if text.strip() else " NO — parses blank"))
        return 0

    if cmd == "company":
        return _company(argv[1:])

    print(f"unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
    return 2


def _company(rest):
    """Company profiler subcommands, kept here so the skill has one entry point."""
    import research

    if not rest:
        print("usage: forge.py company {brief|pattern|attach|list} [company]")
        return 2

    sub, name = rest[0], (rest[1] if len(rest) > 1 else "")

    if sub == "brief":
        print(research.brief(name) or f"nothing known about {name!r}")
    elif sub == "pattern":
        pat = research.posting_patterns(name)
        if not pat["postings"]:
            print(f"no postings archived for {name!r}")
            return 1
        print(f"{pat['postings']} posting(s) archived for {name}\n")
        for r in pat["terms"]:
            flag = "required" if r["ever_required"] else "preferred"
            print(f"  {r['term']:<22} {r['postings']}/{pat['postings']} postings "
                  f"({int(r['rate'] * 100)}%) {flag}")
    elif sub == "attach":
        print(json.dumps(research.attach_postings(name), indent=2))
    elif sub == "list":
        rows = research.companies()
        if not rows:
            print("no company profiles yet")
        for r in rows:
            print(f"{r['company']:<28} {r['postings']} postings, "
                  f"{r['sources']} sources")
    else:
        print(f"unknown company subcommand {sub!r}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))