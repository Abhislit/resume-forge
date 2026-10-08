"""ATS and craft rules as assertions.

Reads the draft, never writes the profile. Every violation carries the offending
line and a concrete fix, because "your resume has ATS problems" is useless to
someone trying to fix one.

Rule sources: MIT CAPD's published ATS guidance, and the craft references in
references/. Keyword stuffing is a violation, not a strategy.
"""

import re
from collections import Counter

# --- rule data ------------------------------------------------------------

SAFE_FONTS = {
    "arial", "calibri", "cambria", "georgia", "helvetica",
    "times new roman", "times", "courier new",
}

MIN_BODY_PT = 10.5

# Superfluous verbs and empty intensifiers. These inflate word count without
# adding information, and reviewers read them as padding.
SUPERFLUOUS = {
    "spearheaded", "spearhead", "orchestrated", "orchestrate", "utilized",
    "utilize", "leveraged", "leverage", "synergized", "synergy",
    "spear-heading", "pioneered", "revolutionized", "transformed",
    "dynamic professional", "results-driven", "detail-oriented",
    "team player", "self-starter", "hard worker", "go-getter",
    "proven track record", "track record", "best-in-class",
    "world-class", "cutting-edge", "next-level", "one-stop",
    "dynamic", "exceptional", "outstanding",
}

INTENSIFIERS = {
    "excellent", "innovative", "strategically", "highly", "extremely",
    "very", "really", "tremendously", "greatly", "significantly improved",
    "best", "amazing", "incredible", "fantastic", "remarkable",
}

# Vague words that mask a keyword you could have used instead.
VAGUE = {"various", "multiple", "several", "etc", "et cetera", "many",
         "various things", "assorted", "sundry", "numerous", "countless"}

PRONOUNS = re.compile(r"(?<![A-Za-z])(?:I|I'm|I've|I'll|my|My|me|we|We|our|Our|us)(?![A-Za-z])")

WEAK_OPENERS = {
    "responsible", "responsible for", "worked on", "worked with",
    "helped", "helps", "assisted", "participated", "involved in",
    "duties included", "tasked with", "in charge of", "did",
    "contributed to", "part of a team", "various tasks",
}

STRONG_VERBS = {
    "led", "led", "built", "built", "designed", "designed", "developed",
    "developed", "engineered", "engineered", "architected", "implemented",
    "implemented", "shipped", "shipped", "launched", "launched", "created",
    "created", "drove", "drove", "reduced", "reduced", "increased",
    "increased", "cut", "cut", "grew", "grew", "scaled", "scaled",
    "migrated", "migrated", "automated", "automated", "mentored",
    "mentored", "coached", "coached", "owned", "owned", "directed",
    "directed", "established", "established", "rebuilt", "rebuilt",
    "rewrote", "rewrote", "eliminated", "eliminated", "accelerated",
    "accelerated", "consolidated", "standardized", "standardized",
    "negotiated", "negotiated", "delivered", "delivered", "authored",
    "authored", "spearheaded", "orchestrated", "maintained", "maintained",
    "monitored", "monitored", "analyzed", "analyzed", "refactored",
    "refactored", "deployed", "deployed", "optimized", "optimized",
    "resolved", "resolved", "pioneered", "debugged", "benchmarked",
    "redesigned", "raised", "grew", "improved", "increased", "halved",
    "halved", "eliminated", "eliminated", "accelerated", "accelerated",
    "consolidated", "consolidated", "standardized", "standardized",
    "formalized", "instrumented", "quantified", "forecast", "projected",
}

STANDARD_SECTIONS = {
    "summary", "experience", "professional experience", "work experience",
    "skills", "technical skills", "projects", "education", "certifications",
    "awards", "publications", "summary of qualifications",
}

# Abbreviations an ATS may not resolve back to the posting's term.
BAD_ABBREVIATIONS = {
    "js": "javascript", "k8s": "kubernetes", "postgres": "postgresql",
    "pg": "postgresql", "ml": "machine learning", "ai": "artificial intelligence",
    "bi": "business intelligence", "ux": "user experience", "ui": "user interface",
    "qa": "quality assurance", "fe": "front end", "be": "back end",
    "aws": "aws", "gcp": "google cloud", "ci/cd": "ci/cd",
}

_STUFFING_RATIO = 0.20
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")


class Violation(dict):
    """A named failure with a fix. Subclasses dict so it serializes as-is."""

    def __init__(self, rule, line, fix, severity="high"):
        super().__init__(rule=rule, line=line, fix=fix, severity=severity)


def _bullets_of(draft):
    """Bullet lines out of the markdown draft."""
    out = []
    for raw in (draft or "").split("\n"):
        line = raw.strip()
        if line.startswith("- ") or line.startswith("* "):
            body = line[2:].strip()
            if body:
                out.append(body)
    return out


def _plain_text(draft):
    """Strip markdown to what a parser would see."""
    text = re.sub(r"^#{1,6}\s*", "", draft or "", flags=re.MULTILINE)
    text = re.sub(r"[*_`>#]", "", text)
    return text


# --- individual rules -----------------------------------------------------

def check_structure(draft):
    v = []
    text = draft or ""

    if re.search(r"^\s*\|.*\|\s*$", text, re.MULTILINE):
        v.append(Violation(
            "table-layout",
            "A markdown table row",
            "Delete the table. ATS parsers routinely drop or misorder table "
            "cells; use one item per line instead.",
        ))

    if re.search(r"!\[[^\]]*\]\([^)]+\)", text):
        v.append(Violation(
            "images",
            "A markdown image link",
            "Remove images and icons. They are ignored or garbled by parsers.",
        ))

    if re.search(r"<!--.*?-->", text, re.DOTALL):
        v.append(Violation(
            "hidden-text",
            "An HTML comment",
            "Delete HTML comments. Hidden text is invisible to a human reader "
            "and is a falsification risk.",
        ))

    return v


def check_sections(draft):
    v = []
    headings = re.findall(r"^(#{1,6})\s*(.+)$", draft or "", re.MULTILINE)
    for hashes, h in headings:
        name = h.strip().rstrip(":").lower()

        # A level-1 heading is the candidate's name, not a section.
        if len(hashes) == 1:
            continue

        # Level-3+ headings are job titles under a role. A title carries a date
        # range, a pipe, or a company name — none of which a real section does.
        if len(hashes) >= 3 and (
            re.search(r"(?:19|20)\d{2}", name)
            or "|" in h
            or " at " in name
        ):
            continue

        if name in STANDARD_SECTIONS:
            continue
        # Be lenient about modifiers like "Technical Skills & Tools".
        core = re.sub(r"[^a-z ]", "", name).split()
        if any(w in {"summary", "experience", "skills", "projects",
                     "education", "certifications", "awards"} for w in core):
            continue
        v.append(Violation(
            "non-standard-section",
            f"Section heading: {h.strip()}",
            "Use a standard heading an ATS recognizes — 'Summary', "
            "'Experience', 'Skills', 'Projects', 'Education'. Recruiters also "
            "scan for these labels.",
        ))
    return v


def check_content(draft):
    v = []

    for bullet in _bullets_of(draft):
        if PRONOUNS.search(bullet):
            found = PRONOUNS.search(bullet).group(0)
            v.append(Violation(
                "pronoun",
                bullet,
                f"Remove '{found}'. Resume bullets take the implied subject; "
                "'I led' becomes 'Led'.",
            ))

        if bullet.endswith("."):
            v.append(Violation(
                "bullet-period",
                bullet,
                "Drop the trailing period. Bullets are fragments, not "
                "sentences — consistency reads as deliberate.",
            ))

        first = bullet.split()[0].lower().strip(",") if bullet.split() else ""
        if first in WEAK_OPENERS:
            v.append(Violation(
                "weak-opener",
                bullet,
                f"Replace '{first}' with a concrete past-tense verb: Led, "
                "Built, Reduced, Shipped. 'Responsible for' hides what you did.",
            ))

        words = _WORD_RE.findall(bullet.lower())
        # A past-tense -ed form is already a verb. Chasing every one of them
        # down a fixed list only produces false positives on "Redesigned" and
        # "Raised" while a noun-phrase opener still slips through.
        if (words and len(words) > 2 and not first.endswith("ed")
                and first not in WEAK_OPENERS
                and not any(w in STRONG_VERBS for w in words[:3])):
            v.append(Violation(
                "weak-action",
                bullet,
                "Open with a strong action verb (Led, Built, Reduced, "
                "Designed, Migrated). Recruiters read the first word.",
                severity="medium",
            ))

    return v


def check_filler(draft):
    v = []
    for bullet in _bullets_of(draft):
        low = bullet.lower()
        for word in SUPERFLUOUS:
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low):
                v.append(Violation(
                    "superfluous-phrase",
                    bullet,
                    f"Remove '{word}'. It adds length without information.",
                ))
                break
        for word in INTENSIFIERS:
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low):
                v.append(Violation(
                    "intensifier",
                    bullet,
                    f"Remove '{word}'. Adjectives cannot be verified; a "
                    "number can.",
                    severity="medium",
                ))
                break
    return v


def check_vague(draft):
    v = []
    for bullet in _bullets_of(draft):
        low = bullet.lower()
        for word in VAGUE:
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", low):
                v.append(Violation(
                    "vague-quantifier",
                    bullet,
                    f"Replace '{word}' with the specific thing it hides. These "
                    "words mask keywords an ATS is searching for.",
                ))
                break
    return v


def check_typography(draft, body_pt=None):
    v = []
    text = draft or ""

    # Font declarations in inline HTML comments or css blocks.
    fonts = set(re.findall(r"font-family\s*:\s*([^;\n]+)", text, re.IGNORECASE))
    for decl in fonts:
        for family in decl.split(","):
            name = family.strip().strip("'\" ")
            if not name or name.lower() in ("inherit", "initial"):
                continue
            if name.lower() not in SAFE_FONTS:
                v.append(Violation(
                    "unsafe-font",
                    f"font-family: {name}",
                    f"Use one of {', '.join(sorted(SAFE_FONTS))}. An unusual "
                    "font may be substituted during parsing and take adjacent "
                    "text with it.",
                ))

    pts = [float(p) for p in re.findall(r"(?:font-size\s*:\s*([\d.]+)pt|([\d.]+)\s*pt\b)", text, re.IGNORECASE) for p in [p[0] or p[1]] if p]
    effective = body_pt if body_pt is not None else (min(pts) if pts else MIN_BODY_PT)
    if effective < MIN_BODY_PT:
        v.append(Violation(
            "font-too-small",
            f"Body font {effective}pt",
            f"Body text must be {MIN_BODY_PT}pt or larger. Small text is the "
            "first thing a parser drops.",
        ))

    if re.search(r"color\s*:\s*(?!#000\b|black\b|#000000\b|rgb\(0,\s*0,\s*0\))", text, re.IGNORECASE):
        v.append(Violation(
            "non-black-text",
            "A non-black color declaration",
            "Use black text. Color is not preserved and can be read as an "
            "unreadable contrast region.",
            severity="medium",
        ))

    # Hyphens where an en dash belongs in date ranges, including the
    # open-ended form "2021-Present".
    for line in text.split("\n"):
        if re.search(
            r"\b(?:19|20)\d{2}\s*-\s*(?:(?:19|20)\d{2}|Present|Current|Now)\b",
            line,
            re.IGNORECASE,
        ):
            v.append(Violation(
                "hyphen-date-range",
                line.strip(),
                "Use an en dash (–) with spaces around it: 2021 – 2023. A "
                "hyphen range can be misread as a minus sign.",
                severity="medium",
            ))
            break

    return v


def check_keyword_coverage(draft, requirements, stuffing_ratio=_STUFFING_RATIO):
    """Coverage is reported. Stuffing is a violation.

    Named commercial ATS simulators exist; this is not one and returns no score.
    """
    v = []
    plain = _plain_text(draft).lower()
    words = _WORD_RE.findall(plain)

    if requirements:
        wanted = []
        for r in requirements:
            wanted.extend(t.lower() for t in r.get("terms", []))
        wanted = list(dict.fromkeys(wanted))
        missing = [t for t in wanted if t not in plain]
        present = [t for t in wanted if t in plain]
        v.append(Violation(
            "keyword-coverage",
            f"{len(present)} of {len(wanted)} posting terms present",
            ("Missing posting terms: " + ", ".join(missing[:20]) + ". "
             "Use them where they truthfully apply — if you have the "
             "experience, say it in the posting's words.")
            if missing else
            "All posting terms appear. Verify each is used in a truthful "
            "context, not just present.",
            severity="medium",
        ))

    # Abbreviations that a search may not resolve.
    for term, full in BAD_ABBREVIATIONS.items():
        if term == full:
            continue
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", plain):
            if full not in plain:
                v.append(Violation(
                    "abbreviated-keyword",
                    f"'{term}' used without '{full}'",
                    f"Write '{full}' at least once. An ATS matching "
                    f"'{full}' may not expand '{term}'.",
                    severity="medium",
                ))

    # Stuffing: one term repeated out of proportion. Repetition is a signal to
    # a reviewer that something is being gamed, and the source material treats
    # falsified application materials as grounds for dismissal.
    if words:
        counts = Counter(w.lower() for w in words if len(w) > 3)
        for term, n in counts.most_common(5):
            if n / len(words) > stuffing_ratio and n >= 4:
                v.append(Violation(
                    "keyword-stuffing",
                    f"'{term}' appears {n} times in {len(words)} words",
                    f"Cut it to 2-3 uses. Repeating a term past "
                    f"{int(stuffing_ratio * 100)}% reads as gaming the filter "
                    "and risks being read as falsification. Vary the "
                    "surrounding language instead.",
                ))
                break

    return v


def check_line_breaks(draft):
    """The molecule/mole-cule silent failure.

    Fires only on an actual split: a line ending in "mole-" whose next line
    begins with "cule". A line that merely ends in a word is not a split, so
    there is no upper bound on how many lines may end however they like.
    """
    v = []
    lines = (draft or "").split("\n")
    for i, line in enumerate(lines[:-1]):
        m = re.search(r"([A-Za-z]{2,})-\s*$", line)
        if not m:
            continue
        # A split word continues in lowercase on the next line. This avoids
        # false positives on a dash ending a line before a new bullet, which
        # starts with lowercase text too but follows a markdown marker.
        nxt = lines[i + 1]
        if not re.match(r"^\s+[a-z]{2,}", nxt):
            continue
        v.append(Violation(
            "hyphen-split-word",
            line.strip(),
            f"'{m.group(1)}' is broken across a line break. An ATS sees two "
            "fragments and matches neither. Reflow the paragraph so the word "
            "stays intact.",
        ))
        break
    return v


def check_open_items(draft):
    """Surface unconfirmed placeholders so nothing ships half-asserted."""
    v = []
    for raw in (draft or "").split("\n"):
        for m in re.finditer(r"\[confirm:[^\]]*\]", raw):
            v.append(Violation(
                "unconfirmed-claim",
                m.group(0),
                "Answer this before sending: the number or claim is not "
                "sourced from your profile. Delete it if you cannot verify it.",
            ))
    return v


# --- entry point ----------------------------------------------------------

def lint(draft, requirements=None, body_pt=None):
    """Run every rule. Returns a list of Violations (dicts)."""
    violations = []
    violations += check_structure(draft)
    violations += check_sections(draft)
    violations += check_content(draft)
    violations += check_filler(draft)
    violations += check_vague(draft)
    violations += check_typography(draft, body_pt=body_pt)
    violations += check_line_breaks(draft)
    violations += check_open_items(draft)
    violations += check_keyword_coverage(draft, requirements or [])

    order = {"high": 0, "medium": 1, "low": 2}
    violations.sort(key=lambda v: order.get(v["severity"], 3))
    return violations


def plain_text_export(draft):
    """The save-as-.txt self-test MIT recommends, done for the user."""
    return _plain_text(draft)