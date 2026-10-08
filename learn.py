"""Learn from every job description over time.

This is persistence and retrieval, not model retraining. Nothing here changes
any weights; what changes is the vocabulary the matcher weights and the notes
the drafting step reads back.

Three stores, all plain text under data/ so they stay inspectable:

  archive.jsonl   one record per JD ever pasted, append-only
  terms.json      derived term frequencies and observed outcomes
  patterns.md     what has actually worked, written in prose

The loop that matters: a JD says a term is *required*, a posting that got a
response confirms the term was real. Terms that appear across many postings are
signals about the market you are in, and they should sort higher than a term
that appeared once and might have been boilerplate.
"""

import json
import os
import re
import time
from pathlib import Path

import parse as jd_parse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ARCHIVE = DATA / "archive.jsonl"
TERMS = DATA / "terms.json"
PATTERNS = DATA / "patterns.md"

# Outcomes a user can report. Only "interview" and "offer" confirm a term was
# genuinely wanted; "ghosted" is weak evidence that something was off.
OUTCOMES = {
    "applied": "Applied, no response yet",
    "interview": "Got an interview",
    "offer": "Got an offer",
    "rejected": "Rejected",
    "ghosted": "No response",
    "withdrawn": "Withdrawn by me",
}

# A term seen in this many postings is a market signal, not a coincidence.
MARKET_SIGNAL_THRESHOLD = 3


def _ensure():
    DATA.mkdir(exist_ok=True)


def _load_archive():
    if not ARCHIVE.exists():
        return []
    records = []
    for line in ARCHIVE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # A torn line from an interrupted write must not lose the archive.
            continue
    return records


def _save_terms(state):
    _ensure()
    TERMS.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def load_terms():
    if not TERMS.exists():
        return {"counts": {}, "confirmed": {}, "by_role": {}, "updated": None}
    try:
        data = json.loads(TERMS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"counts": {}, "confirmed": {}, "by_role": {}, "updated": None}
    data.setdefault("counts", {})
    data.setdefault("confirmed", {})
    data.setdefault("by_role", {})
    data.setdefault("updated", None)
    return data


_ID_STATE = {"base": 0, "last": 0}


def _fingerprint(text):
    """Content hash for de-duplication. The UI re-parses on every button press,
    so the same posting arrives many times and must not inflate the counts."""
    import hashlib

    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def find_by_fingerprint(text):
    """An existing archive entry for this exact posting, or None."""
    fp = _fingerprint(text)
    for r in reversed(_load_archive()):
        if r.get("fingerprint") == fp:
            return r
    return None


def _next_id():
    """Timestamp plus a monotonic counter, so same-millisecond records cannot
    collide. Starts above any id already in the archive."""
    base = int(time.time() * 1000)
    if ARCHIVE.exists():
        for line in ARCHIVE.read_text(encoding="utf-8").splitlines():
            try:
                base = max(base, json.loads(line).get("id", 0))
            except (json.JSONDecodeError, AttributeError):
                continue
    if _ID_STATE["base"] != base:
        _ID_STATE["base"] = base
        _ID_STATE["last"] = base
    _ID_STATE["last"] += 1
    return _ID_STATE["last"]


_CONNECTORS = {"of", "the", "and", "for", "de", "la", "&"}

# Section headings are capitalized in most postings and sit right where a
# company name would be. "Requirements" is not an employer.
_NOT_A_COMPANY = {
    "requirements", "requirement", "qualifications", "qualification",
    "minimum", "preferred", "responsibilities", "skills", "experience",
    "education", "summary", "about", "benefits", "overview", "role", "roles",
    "job", "jobs", "position", "positions", "careers", "what you will do",
    "what you will need", "who you are", "nice to have", "bonus", "apply",
    "essential", "desired", "duties", "profile", "the role", "the team",
}


def _looks_like_org_name(text):
    """A company name is one to five capitalized words, optionally joined by
    a connector. 'Acme again.' fails on the lowercase word; 'Acme Payments'
    passes; a job title fails on length or on being a section heading."""
    stripped = text.strip().rstrip(".")
    if stripped.lower() in _NOT_A_COMPANY:
        return False
    if jd_parse._SECTION_RE.match(stripped):
        return False
    words = [w for w in re.split(r"\s+", stripped) if w]
    if not words or len(words) > 5:
        return False
    real = [w for w in words if w.lower() not in _CONNECTORS]
    if not real:
        return False
    return all(w[:1].isupper() for w in real)


def guess_company(jd_text, role=None):
    """Best-effort company name from a posting.

    Deliberately conservative. A wrong company name poisons the pattern
    analysis, so anything that does not look like an organization name is
    rejected rather than guessed — and the caller can always override with
    --company.
    """
    text = jd_text or ""
    # A space, not \s: \s+ spans newlines and would capture
    # "Stripe\nRequirements" as one company name.
    word = r"[A-Z][\w&.'-]*(?:[ ][A-Z][\w&.'-]*)*"
    patterns = [
        rf"(?:at|@|with)[ ]+({word})",
        rf"^({word})[ ]+(?:is|was)[ ]+(?:hiring|looking)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text[:4000], re.MULTILINE):
            name = m.group(1).strip()
            if name.lower() not in jd_parse._STOPWORDS and _looks_like_org_name(name):
                return name

    for line in text.split("\n")[:4]:
        s = line.strip().lstrip("#").strip().rstrip(".")
        if not s or len(s) > 40 or s.endswith(":"):
            continue
        # A title line is a title, not a company.
        if role and role.lower() in s.lower():
            continue
        if _looks_like_org_name(s):
            return s
    return None


def record(jd_text, requirements, *, title=None, company=None, role=None,
           outcome=None, note=None):
    """Archive one posting and fold its terms into the learned vocabulary.

    Called on every paste, so it must be cheap and never raise on bad input.
    """
    _ensure()
    text = (jd_text or "").strip()
    terms = sorted({
        t for r in (requirements or []) for t in r.get("terms", [])
    })

    # A millisecond timestamp collides when two postings are recorded in the
    # same tick, which silently makes one outcome overwrite another. A
    # monotonic counter is unique by construction.
    record_ = {
        "id": _next_id(),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fingerprint": _fingerprint(text),
        "title": title or _guess_title(text),
        "company": company or guess_company(text, role),
        "role": role,
        "outcome": outcome,
        "note": note,
        "requirements": [
            {"text": r.get("text", ""), "kind": r.get("kind", "required"),
             "terms": r.get("terms", [])}
            for r in (requirements or [])
        ],
        "terms": terms,
        "jd_length": len(text),
    }

    with ARCHIVE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record_, ensure_ascii=False) + "\n")

    state = load_terms()
    for term in terms:
        state["counts"][term] = state["counts"].get(term, 0) + 1
    if role:
        state["by_role"].setdefault(role.lower(), {})
        for term in terms:
            state["by_role"][role.lower()][term] = (
                state["by_role"][role.lower()].get(term, 0) + 1
            )
    state["updated"] = record_["at"]
    _save_terms(state)

    return record_


def set_outcome(record_id, outcome, note=None):
    """Record how a posting went and re-fold its terms as confirmed evidence."""
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(
            f"Unknown outcome {outcome!r}. Use one of: "
            + ", ".join(sorted(OUTCOMES))
        )

    records = _load_archive()
    target = None
    for r in records:
        if r.get("id") == record_id:
            target = r
            break
    if target is None:
        raise KeyError(f"No archived posting with id {record_id}")

    target["outcome"] = outcome
    if note is not None:
        target["note"] = note

    with ARCHIVE.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    if outcome in ("interview", "offer"):
        state = load_terms()
        for term in target.get("terms", []):
            state["confirmed"][term] = state["confirmed"].get(term, 0) + 1
        state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_terms(state)

    return target


def _guess_title(text):
    """Best-effort posting title from the first few lines."""
    for line in (text or "").split("\n")[:6]:
        s = line.strip().lstrip("#").strip()
        if s and len(s) > 3 and not s.endswith(":"):
            return s[:120]
    return "Untitled posting"


def term_weights():
    """Term -> weight, for ordering the gap report.

    Weight combines how often a term has appeared with whether a posting
    requiring it ever produced an interview. A term seen once and never
    confirmed is weak; a term seen five times, twice confirmed, is a signal
    about the market rather than one posting's boilerplate.
    """
    state = load_terms()
    weights = {}
    for term, count in state["counts"].items():
        confirmed = state["confirmed"].get(term, 0)
        weight = min(count / MARKET_SIGNAL_THRESHOLD, 3.0) * (1.0 + confirmed)
        weights[term] = round(weight, 3)
    return weights


def market_signals(limit=15):
    """The recurring terms worth seeing before drafting."""
    state = load_terms()
    rows = []
    for term, count in state["counts"].items():
        if count < MARKET_SIGNAL_THRESHOLD:
            continue
        rows.append({
            "term": term,
            "postings": count,
            "confirmed": state["confirmed"].get(term, 0),
        })
    rows.sort(key=lambda r: (-r["postings"], -r["confirmed"], r["term"]))
    return rows[:limit]


def proven_terms(limit=40):
    """Terms a posting actually confirmed, strongest first."""
    state = load_terms()
    rows = [
        {"term": t, "confirmed": c}
        for t, c in state["confirmed"].items() if c > 0
    ]
    rows.sort(key=lambda r: (-r["confirmed"], r["term"]))
    return rows[:limit]


def role_profile(role, limit=15):
    """Terms this specific role family keeps asking for."""
    state = load_terms()
    bucket = state["by_role"].get((role or "").strip().lower())
    if not bucket:
        return []
    rows = [{"term": t, "postings": c} for t, c in bucket.items()]
    rows.sort(key=lambda r: (-r["postings"], r["term"]))
    return rows[:limit]


def brief(role=None, limit=12):
    """The short paragraph the drafting step reads.

    This is the part that makes the archive useful: what this market keeps
    asking for, and what it has already confirmed as true about the candidate.
    """
    state = load_terms()
    records = _load_archive()

    confirmed_outcomes = [r for r in records
                          if r.get("outcome") in ("interview", "offer")]
    failed = [r for r in records
              if r.get("outcome") in ("rejected", "ghosted")]

    lines = []
    total = len(records)
    if total:
        lines.append(
            f"Archive: {total} posting(s) seen, "
            f"{len(confirmed_outcomes)} produced an interview or offer, "
            f"{len(failed)} did not."
        )
    else:
        lines.append("Archive: empty, this is the first posting.")

    signals = market_signals(limit=limit)
    if signals:
        top = ", ".join(
            f"{s['term']} ({s['postings']} postings"
            + (f", {s['confirmed']} confirmed)" if s["confirmed"] else ")")
            for s in signals
        )
        lines.append(f"Terms recurring across postings: {top}.")

    proven = proven_terms(limit=limit)
    if proven:
        lines.append(
            "Terms a posting has already confirmed as wanted: "
            + ", ".join(f"{p['term']} ({p['confirmed']})" for p in proven)
            + ". These are safe to lead with when the profile supports them."
        )

    rp = role_profile(role, limit=limit)
    if rp:
        lines.append(
            f"For {role}: " + ", ".join(f"{r['term']} ({r['postings']})" for r in rp)
        )

    ghosted_gaps = _ghosted_terms(records, failed)
    if ghosted_gaps:
        lines.append(
            "Terms that appeared only in postings that never got a response, "
            "and were not confirmed elsewhere: "
            + ", ".join(ghosted_gaps)
            + ". Do not weight these heavily."
        )

    return " ".join(lines)


def _ghosted_terms(records, failed, limit=10):
    """Terms seen only in postings that never got a response.

    A term that also appears in a posting which did get a response is not dead
    — the requirement is real, that particular application just did not land.
    """
    if not failed:
        return []
    state = load_terms()
    alive = set()
    for r in records:
        if r.get("outcome") != "rejected" and r.get("outcome") != "ghosted":
            alive.update(r.get("terms", []))
    # Anything a posting confirmed is positive evidence regardless.
    alive.update(state["confirmed"].keys())

    dead_only = {}
    for r in failed:
        for term in r.get("terms", []):
            if term not in alive:
                dead_only[term] = dead_only.get(term, 0) + 1
    rows = sorted(dead_only.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in rows[:limit]]


def stats():
    records = _load_archive()
    state = load_terms()
    outcomes = {}
    for r in records:
        o = r.get("outcome") or "unreported"
        outcomes[o] = outcomes.get(o, 0) + 1
    return {
        "postings": len(records),
        "unique_terms": len(state["counts"]),
        "confirmed_terms": len(state["confirmed"]),
        "outcomes": outcomes,
        "response_rate": (
            round(
                len([r for r in records
                     if r.get("outcome") in ("interview", "offer")])
                / len([r for r in records if r.get("outcome")]),
                3,
            )
            if any(r.get("outcome") for r in records) else None
        ),
        "updated": state.get("updated"),
    }


def recent(limit=10):
    return list(reversed(_load_archive()))[:limit]


def render_patterns():
    """Rewrite patterns.md as a human-readable summary of what the data says.

    Generated, not hand-written, so it cannot drift from the archive.
    """
    s = stats()
    lines = [
        "# What the postings say",
        "",
        "Generated by learn.py from the archive. Do not hand-edit.",
        "",
        f"- Postings seen: **{s['postings']}**",
        f"- Unique terms extracted: **{s['unique_terms']}**",
        f"- Terms confirmed by an interview or offer: **{s['confirmed_terms']}**",
    ]
    if s["response_rate"] is not None:
        pct = round(s["response_rate"] * 100)
        lines.append(f"- Response rate on reported postings: **{pct}%**")
    lines.append("")

    signals = market_signals(limit=25)
    if signals:
        lines += ["## Recurring terms", "",
                  "Seen in three or more postings, so a market signal rather",
                  "than one posting's boilerplate.", "",
                  "| Term | Postings | Confirmed |", "|---|---|---|"]
        for row in signals:
            lines.append(f"| {row['term']} | {row['postings']} | {row['confirmed']} |")
        lines.append("")

    proven = proven_terms()
    if proven:
        lines += ["## Confirmed terms", "",
                  "A posting asking for this led to an interview or an offer.",
                  "These are worth leading with when the profile supports them.", ""]
        for row in proven:
            lines.append(f"- **{row['term']}** — confirmed {row['confirmed']}×")
        lines.append("")

    records = _load_archive()
    done = [r for r in records if r.get("outcome")]
    if done:
        lines += ["## Postings", "", "| Date | Role | Outcome |", "|---|---|---|"]
        for r in records:
            if r.get("outcome"):
                lines.append(
                    f"| {r.get('at', '')[:10]} | {r.get('role') or r.get('title', '')[:40]} "
                    f"| {OUTCOMES.get(r['outcome'], r['outcome'])} |"
                )
        lines.append("")
    else:
        lines += [
            "## No outcomes recorded yet",
            "",
            "Report outcomes with `learn.py outcome <id> interview` and this",
            "table becomes the most useful file in the project: it tells you",
            "which terms the market actually confirms about you.",
            "",
        ]

    _ensure()
    PATTERNS.write_text("\n".join(lines), encoding="utf-8")
    return str(PATTERNS)


# --- command line ---------------------------------------------------------

def main(argv):
    import argparse

    p = argparse.ArgumentParser(prog="learn.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="archive counts and response rate")
    sub.add_parser("signals", help="terms recurring across postings")
    sub.add_parser("proven", help="terms a posting confirmed")
    sub.add_parser("recent", help="most recent archived postings")
    sub.add_parser("patterns", help="regenerate patterns.md")

    rb = sub.add_parser("record", help="archive a JD file")
    rb.add_argument("path")
    rb.add_argument("--role")
    rb.add_argument("--company")
    rb.add_argument("--outcome", choices=sorted(OUTCOMES))

    ob = sub.add_parser("outcome", help="report how a posting went")
    ob.add_argument("id", type=int)
    ob.add_argument("outcome", choices=sorted(OUTCOMES))
    ob.add_argument("--note")

    bb = sub.add_parser("brief", help="the paragraph the drafting step reads")
    bb.add_argument("--role")

    args = p.parse_args(argv)

    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "signals":
        rows = market_signals()
        print("\n".join(
            f"{r['term']:<24} {r['postings']} postings, {r['confirmed']} confirmed"
            for r in rows
        ) or "nothing yet")
    elif args.cmd == "proven":
        rows = proven_terms()
        print("\n".join(f"{r['term']:<24} confirmed {r['confirmed']}x" for r in rows)
              or "nothing confirmed yet")
    elif args.cmd == "recent":
        for r in recent():
            o = OUTCOMES.get(r.get("outcome"), "no outcome yet")
            print(f"{r['id']}  {r['at'][:16]}  {r.get('role') or r.get('title', '')[:50]}  — {o}")
    elif args.cmd == "patterns":
        print(render_patterns())
    elif args.cmd == "record":
        import parse as jd_parse
        jd = Path(args.path).read_text(encoding="utf-8", errors="replace")
        reqs = jd_parse.parse(jd)
        rec = record(jd, reqs, role=args.role, company=args.company,
                     outcome=args.outcome)
        print(f"archived {len(reqs)} requirements, {len(rec['terms'])} terms "
              f"(id {rec['id']})")
    elif args.cmd == "outcome":
        rec = set_outcome(args.id, args.outcome, args.note)
        print(f"{rec['id']} → {OUTCOMES[args.outcome]}")
        if args.outcome in ("interview", "offer"):
            print("terms from this posting are now marked as confirmed evidence")
    elif args.cmd == "brief":
        print(brief(args.role))

    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))