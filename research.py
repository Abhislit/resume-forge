"""Company profiler — what a company asks for, learned from public sources.

Two independent inputs, and the second is the stronger one:

1. **Their own job postings.** Every posting you paste is filed under its
   company. Six postings from one employer is a pattern of what they screen
   on, which is far better evidence than any one job ad.

2. **Public sources you hand it.** Careers pages, engineering blog posts,
   conference talks, a public GitHub org. These are things the company chose to
   publish.

Every signal recorded here carries the URL it came from. Nothing is inferred
from a person, and nothing is asserted without a source: an empty result is
reported as empty rather than filled in.

Scraping resumes of individuals is deliberately out of scope. Aggregating
private documents about named people is not research, it is a privacy problem,
and one person's resume is a single sample of what got one person through a
door. The postings pattern is better evidence anyway.
"""

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import parse as jd_parse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
COMPANIES = DATA / "companies"

USER_AGENT = "Mozilla/5.0 (compatible; resume-forge/1.0; local research tool)"

# Public engineering surfaces worth checking. These are guesses at where a
# company publishes, not facts — a 404 is a normal outcome, never an error.
PROBE_PATHS = [
    ("careers", "/careers"),
    ("jobs", "/jobs"),
    ("engineering", "/engineering"),
    ("blog", "/blog"),
    ("engineering-blog", "/engineering/blog"),
]

# Terms that mean nothing on a company page. Filtering them out is what keeps
# a careers page from contributing "careers" as a technology.
_NOISE = jd_parse._STOPWORDS | {
    "career", "careers", "job", "jobs", "apply", "application", "applications",
    "benefits", "salary", "compensation", "equity", "role", "roles", "team",
    "teams", "company", "culture", "values", "mission", "about", "contact",
    "privacy", "policy", "terms", "cookie", "cookies", "legal", "news",
    "press", "blog", "blogs", "events", "event", "resources", "resource",
    "home", "page", "pages", "search", "menu", "login", "sign", "account",
    "subscribe", "newsletter", "twitter", "linkedin", "github", "facebook",
    "instagram", "youtube", "copyright", "rights", "reserved", "inc",
    # Careers copy, not engineering signals. These describe how the company
    # talks about itself rather than what it builds on.
    "roadmap", "strategy", "analytics", "mission", "vision", "diversity",
    "inclusion", "perks", "remote", "hybrid", "impact", "opportunity",
    "passion", "growth", "trajectory", "onboarding", "recognition",
}


def _slug(company):
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")


def _ensure():
    COMPANIES.mkdir(parents=True, exist_ok=True)


def _load(company):
    path = COMPANIES / f"{_slug(company)}.json"
    if not path.exists():
        return {"company": company, "sources": [], "signals": {}, "first_seen": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"company": company, "sources": [], "signals": {}, "first_seen": None}


def _save(company, data):
    _ensure()
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (COMPANIES / f"{_slug(company)}.json").write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace"), resp.status


def _text_from(html):
    """Strip a page to readable text. Crude on purpose — an HTML parser is a
    dependency for something a regex handles fine here."""
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def terms_in(text):
    """Vocabulary a page mentions, restricted to the known tech lexicon.

    A careers page is prose, and the JD parser's free-form capitalized-phrase
    heuristic turns prose into junk — it reported "aws. apply" and "we" as
    technologies. Only lexicon hits survive here, and multi-word phrases
    suppress their own parts so "machine learning" does not also report
    "machine". If a real technology is missing from the lexicon it will not be
    detected, which is the correct failure: a missed signal is fixable, a
    fabricated one is not.
    """
    low = text.lower()
    terms = set()
    for skill in jd_parse._SKILL_LEXICON:
        if skill not in low:
            continue
        terms.add(skill)
        for word in skill.split():
            if len(skill.split()) > 1:
                terms.discard(word)
    return {
        t for t in terms
        if t not in _NOISE and len(t) > 1 and not t.isdigit()
    }


def probe(company, base_url=None):
    """Try the conventional public surfaces for a company.

    Returns a list of results; misses are reported, not hidden. The caller
    decides what to keep.
    """
    if not base_url:
        base_url = "https://" + re.sub(
            r"[^A-Za-z0-9.-]+", "", company.split()[0].lower()
        ) + ".com"

    found = []
    for label, path in PROBE_PATHS:
        url = base_url.rstrip("/") + path
        try:
            html, status = _fetch(url)
        except urllib.error.HTTPError as exc:
            found.append({"label": label, "url": url, "ok": False,
                          "status": exc.code})
            continue
        except Exception as exc:
            found.append({"label": label, "url": url, "ok": False,
                          "error": str(exc)})
            continue

        text = _text_from(html)
        terms = sorted(terms_in(text))
        found.append({
            "label": label,
            "url": url,
            "ok": True,
            "status": status,
            "bytes": len(text),
            "terms": terms,
        })
    return found


def add_source(company, url, label=None, timeout=15):
    """Fetch one URL and fold its vocabulary into the company profile."""
    try:
        html, status = _fetch(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": url, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}

    text = _text_from(html)
    terms = sorted(terms_in(text))

    data = _load(company)
    if not data.get("first_seen"):
        data["first_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data["sources"] = [
        s for s in data["sources"] if s.get("url") != url
    ]
    data["sources"].append({
        "url": url,
        "label": label or url,
        "status": status,
        "fetched": time.strftime("%Y-%m-%d %H:%M:%S"),
        "terms": terms,
    })

    # Signals are the union across sources, each keeping a source url. A term
    # seen on three pages is a better signal than one seen once, so keep the
    # count alongside it.
    signals = {}
    for src in data["sources"]:
        for term in src.get("terms", []):
            entry = signals.setdefault(term, {"count": 0, "urls": []})
            entry["count"] += 1
            if src["url"] not in entry["urls"]:
                entry["urls"].append(src["url"])
    data["signals"] = signals

    _save(company, data)
    return {"ok": True, "url": url, "terms": terms, "company": company}


def top_signals(company, limit=25, min_count=1):
    data = _load(company)
    rows = [
        {"term": t, "count": v["count"], "urls": v["urls"]}
        for t, v in data.get("signals", {}).items()
        if v["count"] >= min_count
    ]
    rows.sort(key=lambda r: (-r["count"], r["term"]))
    return rows[:limit]


def posting_patterns(company):
    """Requirements this company has listed across every posting you pasted.

    This is the strong signal: it comes from the employer rather than from a
    guess about the employer. Returns per-term posting counts and the split
    between required and only-preferred.
    """
    import learn

    records = [
        r for r in learn._load_archive()
        if (r.get("company") or "").strip().lower()
        == (company or "").strip().lower()
    ]
    if not records:
        return {"postings": 0, "terms": [], "recurring": []}

    counts = Counter()
    required = set()
    for r in records:
        # One posting = one vote per term. Counting requirement lines instead
        # lets a single ad list the same term twice and outrank real breadth.
        terms_in_this_posting = set()
        for req in r.get("requirements", []):
            kind = req.get("kind", "required")
            for term in req.get("terms", []):
                terms_in_this_posting.add(term)
                if kind == "required":
                    required.add(term)
        for term in terms_in_this_posting:
            counts[term] += 1

    rows = [
        {
            "term": t,
            "postings": n,
            "ever_required": t in required,
            "rate": round(n / len(records), 2),
        }
        for t, n in counts.items()
    ]
    rows.sort(key=lambda r: (-r["rate"], -r["postings"], r["term"]))

    recurring = [r for r in rows if r["postings"] >= 2]
    return {"postings": len(records), "terms": rows, "recurring": recurring}


def profile(company):
    """Everything known about one company, with sources intact."""
    data = _load(company)
    return {
        "company": company,
        "sources": data.get("sources", []),
        "signals": top_signals(company),
        "postings": posting_patterns(company),
        "first_seen": data.get("first_seen"),
        "updated": data.get("updated"),
    }


def brief(company, limit=12):
    """The paragraph the drafting step reads. Every claim carries its source.

    Says "nothing known" when nothing is known. An empty result is information;
    inventing one to fill the gap is not.
    """
    name = (company or "").strip()
    if not name:
        return ""

    pat = posting_patterns(name)
    sigs = top_signals(name, limit=limit)
    lines = [f"Company: {name}."]

    if pat["postings"]:
        ever = [r for r in pat["recurring"] if r["ever_required"]]
        never = [
            r["term"] for r in pat["terms"]
            if r["rate"] <= 0.34
        ][:8]
        lines.append(
            f"Their postings: {pat['postings']} archived."
        )
        if ever:
            lines.append(
                "Required in more than one of their postings: "
                + ", ".join(f"{r['term']} ({r['postings']}/{pat['postings']})"
                            for r in ever[:limit])
                + ". Expect these to be screened on."
            )
        if never:
            lines.append(
                "Rarely or never required by them: "
                + ", ".join(never)
                + ". Do not lead with these."
            )
    else:
        lines.append(
            "No postings from this company archived yet, so there is no "
            "evidence of what they screen on."
        )

    if sigs:
        cited = "; ".join(
            f"{s['term']} [{s['urls'][0]}]" for s in sigs[:limit]
        )
        lines.append(f"Vocabulary from their public pages: {cited}.")

    lines.append(
        "Use this only to phrase things in their vocabulary and to order what "
        "leads. It is not evidence that the candidate has any of it."
    )
    return " ".join(lines)


def companies():
    """Every company with a saved profile."""
    if not COMPANIES.exists():
        return []
    out = []
    for path in sorted(COMPANIES.glob("*.json")):
        data = _load(path.stem.replace("-", " "))
        out.append({
            "company": data.get("company", path.stem),
            "sources": len(data.get("sources", [])),
            "postings": posting_patterns(data.get("company", ""))["postings"],
            "updated": data.get("updated"),
        })
    return out


def attach_postings(company):
    """File already-archived postings under a company named just now.

    People paste a JD before deciding what to call the company. This backfills
    the company field so the pattern analysis can see them.
    """
    import learn

    records = learn._load_archive()
    changed = 0
    for r in records:
        if not r.get("company"):
            r["company"] = company
            changed += 1
    if changed:
        with learn.ARCHIVE.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"attached": changed}


# --- command line ---------------------------------------------------------

def main(argv):
    import argparse

    p = argparse.ArgumentParser(prog="research.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("probe", help="try conventional public URLs")
    pb.add_argument("company")
    pb.add_argument("--base-url")

    ab = sub.add_parser("add", help="fetch one URL into the profile")
    ab.add_argument("company")
    ab.add_argument("url")
    ab.add_argument("--label")
    ab.add_argument("--timeout", type=int, default=15)

    rb = sub.add_parser("attach", help="file un-attributed postings under a company")
    rb.add_argument("company")

    for name in ("profile", "brief", "pattern"):
        b = sub.add_parser(name)
        b.add_argument("company")
        b.add_argument("--limit", type=int, default=12)

    sub.add_parser("companies", help="every company with a profile")

    args = p.parse_args(argv)

    if args.cmd == "probe":
        results = probe(args.company, args.base_url)
        for r in results:
            if r["ok"]:
                print(f"  hit  {r['label']:<16} {r['url']}  "
                      f"{len(r['terms'])} terms")
            else:
                print(f"  miss {r['label']:<16} {r['url']}  "
                      f"{r.get('status') or r.get('error')}")
        print("\nAdd the interesting ones:")
        print(f"  python3 research.py add \"{args.company}\" <url> --label <what>")
    elif args.cmd == "add":
        result = add_source(args.company, args.url, args.label, args.timeout)
        print(json.dumps(result, indent=2)[:1200])
    elif args.cmd == "attach":
        print(json.dumps(attach_postings(args.company), indent=2))
    elif args.cmd == "profile":
        print(json.dumps(profile(args.company), indent=2)[:3000])
    elif args.cmd == "brief":
        print(brief(args.company, args.limit))
    elif args.cmd == "pattern":
        print(json.dumps(posting_patterns(args.company), indent=2)[:2000])
    elif args.cmd == "companies":
        rows = companies()
        for r in rows:
            print(f"{r['company']:<28} {r['postings']} postings, "
                  f"{r['sources']} sources")
        if not rows:
            print("no company profiles yet")

    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))