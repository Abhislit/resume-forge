"""Self-check for resume-forge. Plain asserts, no framework.

    python3 test_forge.py

Covers the places where being wrong is silent: classification, synonym
matching, the ATS rules, and the fabrication guard. The DOCX test builds a real
file and reads it back, because a malformed zip fails at the recipient, not here.
"""

import io
import json
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import docx_writer
import learn
import lint
import match as matcher
import parse as jd_parse
import research
import server

PASSED = []


def check(name):
    def deco(fn):
        def wrapped():
            fn()
            PASSED.append(name)
            print(f"  ok  {name}")
        wrapped.__name__ = fn.__name__
        return wrapped
    return deco


# --- fixtures -------------------------------------------------------------

JD = """
We are looking for a backend engineer to join our payments platform team.

Minimum Qualifications
- 5+ years of professional experience with Python and PostgreSQL
- Production experience with Kubernetes and Docker
- Strong communication skills and experience mentoring engineers
- Experience with GraphQL or REST API design

Preferred Qualifications
- Familiarity with Terraform is a plus
- Exposure to Kafka and event-driven architecture
- Machine learning experience is a plus
"""

PROFILE = """\
# Jane Doe
jane@example.com | +1 555 0100 | Boston, MA | linkedin.com/in/janedoe

## Preferences
- pages: 2
- market: US

## Skills
Python, PostgreSQL, Kubernetes, Docker, GraphQL, AWS, Terraform, Kafka

## Experience

### Senior Backend Engineer | Acme Payments | 2021 - Present
- Led migration of a monolith to 12 Python microservices serving 4M requests/day
- Cut p99 latency from 840ms to 210ms by adding Redis caching and query tuning
- Mentored 4 engineers across 3 teams; 2 were promoted within 18 months
- Designed a Kafka-based event pipeline handling 1.2M events/day
- Shipped a GraphQL gateway in front of 14 REST services

### Software Engineer | Beta Labs | 2019 - 2021
- Built React dashboard used daily by 300 internal staff
- Owned CI/CD in GitHub Actions, cutting deploys from 40min to 4min

## Education
### B.S. Computer Science | State University | 2015 - 2019
"""

CLEAN_DRAFT = """\
# Jane Doe
jane@example.com | Boston, MA

## Summary
Backend engineer with 6 years building payment infrastructure under PCI scope.

## Experience

### Senior Backend Engineer | Acme Payments | 2021 – Present
- Led migration of a monolith to 12 Python microservices serving 4M requests/day
- Cut p99 latency from 840ms to 210ms by adding Redis caching
- Mentored 4 engineers; 2 promoted within 18 months
- Shipped a GraphQL gateway in front of 14 REST services
"""


# --- parse ----------------------------------------------------------------

@check("parse: classifies required vs preferred")
def t_parse_kinds():
    reqs = jd_parse.parse(JD)
    assert reqs, "no requirements extracted"

    by_text = {r["text"]: r for r in reqs}

    python = next(r for r in reqs if "Python and PostgreSQL" in r["text"])
    assert python["kind"] == jd_parse.REQUIRED, python

    terraform = next(r for r in reqs if "Terraform" in r["text"])
    assert terraform["kind"] == jd_parse.PREFERRED, terraform

    ml = next(r for r in reqs if "Machine learning" in r["text"])
    assert ml["kind"] == jd_parse.PREFERRED, ml

    assert len(by_text) == len(reqs), "duplicate requirement lines"


@check("parse: required wins when a term appears in both sections")
def t_parse_required_precedence():
    jd = """
## Required
- Hands-on experience with Terraform in production environments

## Preferred
- Familiarity with Kafka and streaming systems
"""
    reqs = jd_parse.parse(jd)
    tf = next(r for r in reqs if "Terraform" in r["text"])
    assert tf["kind"] == jd_parse.REQUIRED, tf

    kw = jd_parse.keywords(reqs)
    assert kw["terraform"] == jd_parse.REQUIRED, kw


@check("parse: extracts skill terms")
def t_parse_terms():
    reqs = jd_parse.parse(JD)
    terms = set()
    for r in reqs:
        terms.update(r["terms"])
    for expected in ("python", "postgresql", "kubernetes", "docker"):
        assert expected in terms, f"{expected} missing from {sorted(terms)}"


@check("parse: sentence-initial words are not read as skills")
def t_parse_sentence_initial():
    # "Production", "Familiarity" and "Machine" start their lines and carry no
    # signal. The bullet marker must not defeat that check.
    reqs = jd_parse.parse(JD)
    terms = set()
    for r in reqs:
        terms.update(r["terms"])
    for noise in ("production", "familiarity", "exposure", "machine"):
        assert noise not in terms, f"{noise} treated as a skill: {sorted(terms)}"


@check("parse: multi-word phrases supersede their parts")
def t_parse_phrases():
    reqs = jd_parse.parse("## Required\n- Experience with GraphQL or REST API design\n")
    terms = set(reqs[0]["terms"])
    assert "rest api" in terms, terms
    assert "api" not in terms, f"bare 'api' left behind: {terms}"
    assert "graphql" in terms, terms

    reqs = jd_parse.parse("## Required\n- Machine learning experience required\n")
    terms = set(reqs[0]["terms"])
    assert "machine learning" in terms, terms
    assert "machine" not in terms, terms


@check("parse: JD preamble prose does not become a requirement")
def t_parse_preamble():
    reqs = jd_parse.parse(JD)
    for r in reqs:
        low = r["text"].lower()
        assert "passionate" not in low
        assert "looking for a backend engineer to join" not in low, r["text"]


@check("parse: docx round-trip reads word/document.xml")
def t_parse_docx():
    md = JD  # content only matters for the reader
    blocks = "\n".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>"
        for line in md.split("\n")
    )
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>' + blocks +
        "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc)
    text = jd_parse.read_docx(buf.getvalue())
    assert "PostgreSQL" in text, text[:200]


# --- match ----------------------------------------------------------------

@check("match: covered / synonym / gap")
def t_match_statuses():
    reqs = jd_parse.parse(JD)
    matrix = matcher.match(reqs, PROFILE)
    rows = {r["text"]: r for r in matrix["rows"]}

    python = next(r for r in matrix["rows"] if "Python and PostgreSQL" in r["text"])
    assert python["status"] == matcher.COVERED, python
    assert python["evidence"], "covered with no evidence string"

    # PostgreSQL in the JD is matched against "PostgreSQL" in the skills block.
    pg = python["term_status"].get("postgresql")
    assert pg == matcher.COVERED, python["term_status"]

    # Synonym: k8s in a posting must resolve against "kubernetes" in a profile.
    syn = matcher.match(
        [{"text": "5+ years of experience with k8s and js",
          "kind": "required", "terms": ["kubernetes", "javascript"],
          "verbs": []}],
        PROFILE,
    )
    assert syn["rows"][0]["term_status"]["kubernetes"] == matcher.COVERED
    assert syn["rows"][0]["term_status"]["javascript"] == matcher.GAP, \
        "profile has no JavaScript; must not report covered"

    # Adjacent concept becomes partial, never silently covered. The profile line
    # carries "across 3 teams" but no stakeholder cue, so this is genuinely a
    # gap — the matcher must not upgrade its own uncertainty to a match.
    gap = matcher.match(
        [{"text": "Strong communication skills and stakeholder management",
          "kind": "required", "terms": ["stakeholder management"], "verbs": []}],
        PROFILE,
    )
    assert gap["rows"][0]["status"] == matcher.GAP, gap
    assert not gap["rows"][0]["evidence"], "gap carried evidence"

    # With an actual cue word present, it is partial — never covered.
    part = matcher.match(
        [{"text": "Strong communication skills and stakeholder management",
          "kind": "required", "terms": ["stakeholder management"], "verbs": []}],
        PROFILE + "\n- Partnered with 3 cross-functional teams on roadmap delivery\n",
    )
    assert part["rows"][0]["status"] == matcher.PARTIAL, part
    assert part["rows"][0]["evidence"], "partial with no adjacent evidence"

    # Synonym resolution runs in both directions: the profile says k8s, the
    # posting says kubernetes.
    rev = matcher.match(
        [{"text": "Experience with k8s at scale", "kind": "required",
          "terms": ["kubernetes"], "verbs": []}],
        "# Jane Doe\n\n## Skills\nk8s, Docker\n",
    )
    assert rev["rows"][0]["term_status"]["kubernetes"] == matcher.COVERED, rev


@check("match: every row carries traceable evidence")
def t_match_evidence():
    reqs = jd_parse.parse(JD)
    matrix = matcher.match(reqs, PROFILE)
    for row in matrix["rows"]:
        if row["status"] == matcher.COVERED:
            assert row["evidence"], f"covered with no evidence: {row['text']}"
            for ev in row["evidence"]:
                assert ev.strip(), "empty evidence string"


@check("match: summary counts add up")
def t_match_summary():
    reqs = jd_parse.parse(JD)
    matrix = matcher.match(reqs, PROFILE)
    s = matcher.summary(matrix)
    assert s["total"] == s["covered"] + s["partial"] + s["gap"], s
    assert s["required_total"] >= 1, s


@check("match: empty profile yields gaps, not crashes")
def t_match_empty_profile():
    reqs = jd_parse.parse(JD)
    matrix = matcher.match(reqs, "")
    s = matcher.summary(matrix)
    assert s["covered"] == 0, s
    assert s["gap"] > 0, s


# --- lint -----------------------------------------------------------------

def rules_fired(markdown, requirements=None, **kw):
    return {v["rule"] for v in lint.lint(markdown, requirements or [], **kw)}


@check("lint: clean draft is clean")
def t_lint_clean():
    reqs = jd_parse.parse(JD)
    fired = rules_fired(CLEAN_DRAFT, reqs)
    hard = fired - {"keyword-coverage"}
    assert not hard, f"unexpected violations on a clean draft: {sorted(hard)}"


@check("lint: catches tables")
def t_lint_table():
    bad = CLEAN_DRAFT + "\n| Skill | Level |\n| --- | --- |\n| Python | 5 yrs |\n"
    assert "table-layout" in rules_fired(bad)


@check("lint: catches images and hidden text")
def t_lint_images():
    assert "images" in rules_fired(CLEAN_DRAFT + "\n![headshot](me.png)\n")
    assert "hidden-text" in rules_fired(CLEAN_DRAFT + "\n<!-- senior engineer -->\n")


@check("lint: catches font under 10.5pt")
def t_lint_font_size():
    assert "font-too-small" in rules_fired(CLEAN_DRAFT, body_pt=8)
    assert "font-too-small" not in rules_fired(CLEAN_DRAFT, body_pt=11)


@check("lint: catches unsafe fonts")
def t_lint_unsafe_font():
    bad = '<span style="font-family: Papyrus">\n\n' + CLEAN_DRAFT
    assert "unsafe-font" in rules_fired(bad)


@check("lint: catches personal pronouns")
def t_lint_pronouns():
    bad = CLEAN_DRAFT.replace(
        "- Led migration", "- I led migration"
    )
    assert "pronoun" in rules_fired(bad)


@check("lint: catches trailing periods on bullets")
def t_lint_bullet_period():
    bad = CLEAN_DRAFT + "\n- Deployed the new billing service.\n"
    assert "bullet-period" in rules_fired(bad)


@check("lint: catches weak openers")
def t_lint_weak_opener():
    bad = CLEAN_DRAFT + "\n- Responsible for the payments migration\n"
    assert "weak-opener" in rules_fired(bad)


@check("lint: catches vague quantifiers")
def t_lint_vague():
    bad = CLEAN_DRAFT + "\n- Improved latency for various services across several regions\n"
    assert "vague-quantifier" in rules_fired(bad)


@check("lint: catches superfluous phrases")
def t_lint_superfluous():
    bad = CLEAN_DRAFT + "\n- Leveraged Kubernetes to utilize container orchestration\n"
    assert "superfluous-phrase" in rules_fired(bad)


@check("lint: catches non-standard section headings")
def t_lint_sections():
    bad = CLEAN_DRAFT.replace("## Summary", "## Professional Background")
    assert "non-standard-section" in rules_fired(bad)


@check("lint: catches hyphen date ranges")
def t_lint_date_range():
    bad = CLEAN_DRAFT.replace("2021 – Present", "2021-Present")
    assert "hyphen-date-range" in rules_fired(bad)


@check("lint: catches a word split across a line break")
def t_lint_split_word():
    bad = (
        CLEAN_DRAFT
        + "\n### Research\n"
        + "- Benchmarked the mole-\n"
        + "  cule release pipeline under load\n"
    )
    assert "hyphen-split-word" in rules_fired(bad)


@check("lint: reports missing posting terms instead of a score")
def t_lint_coverage():
    reqs = jd_parse.parse(JD)
    coverage = [
        v for v in lint.lint(CLEAN_DRAFT, reqs)
        if v["rule"] == "keyword-coverage"
    ]
    assert coverage, "no coverage report emitted"
    assert "Missing posting terms" in coverage[0]["fix"], coverage[0]


@check("lint: keyword stuffing is a violation")
def t_lint_stuffing():
    stuffed = (
        "# Jane Doe\n\n## Experience\n\n"
        "### Engineer | Acme | 2021 – Present\n"
        + "".join(
            f"- Kubernetes Kubernetes Kubernetes Kubernetes "
            f"Kubernetes Kubernetes Kubernetes Kubernetes bullet {i}\n"
            for i in range(12)
        )
    )
    assert "keyword-stuffing" in rules_fired(stuffed)


@check("lint: abbreviated keyword is flagged")
def t_lint_abbrev():
    bad = CLEAN_DRAFT + "\n- Used k8s for orchestration across the fleet\n"
    fired = rules_fired(bad)
    assert "abbreviated-keyword" in fired, fired


@check("lint: unconfirmed placeholders surface as open items")
def t_lint_confirm():
    bad = CLEAN_DRAFT + "\n- Cut costs [confirm: annual spend figure]\n"
    assert "unconfirmed-claim" in rules_fired(bad)


@check("lint: every violation carries a rule, a line, and a fix")
def t_lint_shape():
    reqs = jd_parse.parse(JD)
    violations = lint.lint(CLEAN_DRAFT + "\n- Responsible for the data.", reqs)
    assert violations
    for v in violations:
        assert v["rule"] and v["fix"], v
        assert "line" in v, v
        assert v["severity"] in ("high", "medium", "low"), v


# --- docx -----------------------------------------------------------------

@check("docx: produces a valid zip with every part parsing as XML")
def t_docx_parts():
    data = docx_writer.build_docx(CLEAN_DRAFT, title="Jane Doe")
    assert data[:2] == b"PK", "not a zip"

    zf = zipfile.ZipFile(io.BytesIO(data))
    bad = zf.testzip()
    assert bad is None, f"corrupt member: {bad}"

    names = set(zf.namelist())
    for required in (
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/_rels/document.xml.rels",
    ):
        assert required in names, f"missing {required}: {sorted(names)}"

    for name in names:
        ET.fromstring(zf.read(name))  # raises if malformed


@check("docx: resume text survives into document.xml")
def t_docx_content():
    data = docx_writer.build_docx(CLEAN_DRAFT, title="Jane Doe")
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert "Jane Doe" in xml
    assert "4M requests/day" in xml
    assert "p99 latency" in xml
    assert "b: " not in xml, "bullet text should not carry markdown markers"


@check("docx: bullets become real list paragraphs")
def t_docx_bullets():
    data = docx_writer.build_docx(CLEAN_DRAFT, title="Jane Doe")
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert 'w:numId w:val="1"' in xml, "no numbering applied to bullets"


@check("docx: layout is ATS-safe (letter, 0.75in margins, no tables)")
def t_docx_layout():
    data = docx_writer.build_docx(CLEAN_DRAFT, title="Jane Doe")
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert 'w:w="12240"' in xml, "not US Letter width"
    assert 'w:top="1080"' in xml, "not 0.75in margin"
    assert "<w:tbl>" not in xml, "table found in output"


@check("docx: empty input still yields a valid file")
def t_docx_empty():
    data = docx_writer.build_docx("", title="Empty")
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.testzip() is None
    ET.fromstring(zf.read("word/document.xml"))


# --- fabrication guard ----------------------------------------------------

@check("guard: flags a number absent from the profile")
def t_guard_flags():
    payload = {
        "roles": [{
            "title": "Engineer",
            "bullets": ["Led migration of 87 Python microservices"],
        }]
    }
    found = server.fabrication_guard(payload, PROFILE)
    assert found, "invented number 87 was not caught"
    assert found[0]["number"] == "87", found


@check("guard: allows a number present in the profile")
def t_guard_allows():
    payload = {
        "roles": [{
            "title": "Senior Backend Engineer",
            "bullets": [
                "Led migration of a monolith to 12 Python microservices "
                "serving 4M requests/day"
            ],
        }]
    }
    found = server.fabrication_guard(payload, PROFILE)
    assert not found, f"profile-sourced numbers were flagged: {found}"


@check("guard: permits the [confirm: ...] escape hatch")
def t_guard_confirm():
    payload = {
        "roles": [{
            "title": "Engineer",
            "bullets": ["Cut infrastructure costs [confirm: annual figure]"],
        }]
    }
    assert not server.fabrication_guard(payload, PROFILE)


# --- markdown assembly ----------------------------------------------------

@check("render: draft JSON becomes markdown with the expected sections")
def t_render():
    draft = {
        "name": "Jane Doe",
        "contact": "jane@example.com | Boston, MA",
        "summary": "Backend engineer with 6 years in payments infrastructure",
        "key_skills": ["Python", "PostgreSQL", "Kubernetes"],
        "roles": [{
            "title": "Senior Backend Engineer",
            "company": "Acme Payments",
            "dates": "2021 – Present",
            "bullets": ["Led migration of 12 Python microservices"],
        }],
        "education": ["B.S. Computer Science, State University, 2019"],
    }
    md = server.render_markdown(draft)
    assert md.startswith("# Jane Doe")
    assert "## Summary" in md
    assert "## Skills" in md
    assert "### Senior Backend Engineer | Acme Payments | 2021 – Present" in md
    assert "- Led migration of 12 Python microservices" in md
    assert "## Education" in md
    assert "\n\n\n" not in md, "excess blank lines"


@check("render: an empty draft does not crash")
def t_render_empty():
    md = server.render_markdown({})
    assert isinstance(md, str)


# --- end to end -----------------------------------------------------------

@check("e2e: fixed JD + profile produces no unsourced number")
def t_e2e_no_fabrication():
    """The full deterministic path with a canned 'model' response.

    The draft is written from the profile's own facts, so the guard must find
    nothing. This is the honesty property the whole tool exists to hold.
    """
    reqs = jd_parse.parse(JD)
    matrix = matcher.match(reqs, PROFILE)

    instructions = server.build_instructions(PROFILE, matrix, JD)
    assert "CANDIDATE PROFILE" in instructions
    assert "REQUIREMENT MATCH REPORT" in instructions
    assert "do NOT claim these" in instructions

    canned = {
        "name": "Jane Doe",
        "contact": "jane@example.com | Boston, MA",
        "summary": "Backend engineer with 6 years building payment infrastructure",
        "key_skills": ["Python", "PostgreSQL", "Kubernetes", "GraphQL"],
        "roles": [{
            "title": "Senior Backend Engineer",
            "company": "Acme Payments",
            "dates": "2021 – Present",
            "bullets": [
                "Led migration of a monolith to 12 Python microservices "
                "serving 4M requests/day",
                "Cut p99 latency from 840ms to 210ms by adding Redis caching "
                "and query tuning",
                "Mentored 4 engineers across 3 teams",
                "Shipped a GraphQL gateway in front of 14 REST services",
            ],
        }],
        "warnings": [],
    }

    assert not server.fabrication_guard(canned, PROFILE), \
        "profile-sourced draft was falsely flagged"

    md = server.render_markdown(canned)
    tripped = [v for v in lint.lint(md, reqs) if v["rule"] != "keyword-coverage"]
    assert not tripped, [v["rule"] for v in tripped]


@check("e2e: an over-claiming draft is caught end to end")
def t_e2e_catches_overclaim():
    reqs = jd_parse.parse(JD)
    overclaiming = {
        "name": "Jane Doe",
        "roles": [{
            "title": "Senior Backend Engineer",
            "bullets": [
                "Led migration of a monolith to 87 Python microservices "
                "serving 4M requests/day",
                "Spearheaded a company-wide transformation of the platform",
            ],
        }],
    }
    warnings = server.fabrication_guard(overclaiming, PROFILE)
    assert warnings, "87 microservices was not caught"

    md = server.render_markdown(overclaiming)
    fired = rules_fired(md)
    assert "superfluous-phrase" in fired, fired


# --- learning archive ------------------------------------------------------

@check("learn: ids are unique even within the same millisecond")
def t_learn_unique_ids():
    ids = [learn.record("Minimum Qualifications\n- Python and PostgreSQL\n",
                        jd_parse.parse("Minimum Qualifications\n- Python and PostgreSQL\n"))["id"]
           for _ in range(3)]
    assert len(set(ids)) == 3, f"ids collided: {ids}"


@check("learn: the same posting is not counted twice")
def t_learn_dedupe():
    jd = "Minimum Qualifications\n- Experience with Kubernetes and Docker\n"
    reqs = jd_parse.parse(jd)
    assert learn.find_by_fingerprint(jd) is None
    first = learn.record(jd, reqs)
    found = learn.find_by_fingerprint(jd)
    assert found is not None and found["id"] == first["id"]
    # Whitespace differences are the same posting, not a new one.
    assert learn.find_by_fingerprint(jd + "\n\n") is not None


@check("learn: an interview confirms that posting's terms")
def t_learn_confirm():
    jd = "Minimum Qualifications\n- Expert Kafka and Kubernetes required\n"
    rec = learn.record(jd, jd_parse.parse(jd), role="Platform Engineer")
    assert {"kafka", "kubernetes"} <= set(rec["terms"]), rec["terms"]

    before = dict(learn.load_terms()["confirmed"])
    learn.set_outcome(rec["id"], "interview")
    after = learn.load_terms()["confirmed"]
    for term in ("kafka", "kubernetes"):
        assert after.get(term, 0) > before.get(term, 0), \
            f"{term} was not marked confirmed: {before} -> {after}"


@check("learn: a rejection does not confirm anything")
def t_learn_reject():
    jd = "Minimum Qualifications\n- Expert COBOL and Fortran required\n"
    rec = learn.record(jd, jd_parse.parse(jd))
    before = dict(learn.load_terms()["confirmed"])
    learn.set_outcome(rec["id"], "rejected")
    assert learn.load_terms()["confirmed"] == before, \
        "a rejection marked terms as proven"


@check("learn: recurring terms become market signals")
def t_learn_signals():
    line = "- Experience with Kafka and Kubernetes\n"
    for _ in range(3):
        learn.record("Minimum Qualifications\n" + line,
                     jd_parse.parse("Minimum Qualifications\n" + line))
    signals = {s["term"]: s["postings"] for s in learn.market_signals()}
    assert signals.get("kafka", 0) >= 3, signals
    assert signals.get("kubernetes", 0) >= 3, signals


@check("learn: a higher posting count means a higher weight")
def t_learn_weights():
    w = learn.term_weights()
    for term in w:
        assert w[term] > 0, w
    # kubernetes recurs across fixtures; assert the weighting is not flat.
    assert len(set(round(v, 2) for v in w.values())) > 1, "all weights identical"


@check("learn: role history is looked up without the seniority prefix")
def t_learn_role():
    line = "- Experience with Kafka and Kubernetes\n"
    jd = "Minimum Qualifications\n" + line
    for _ in range(2):
        learn.record(jd, jd_parse.parse(jd), role="Platform Engineer")
    assert learn.role_profile("Platform Engineer"), learn.role_profile("Platform Engineer")


@check("learn: guess_role strips seniority and company")
def t_guess_role():
    profile = ("# Jane\n\n## Experience\n\n"
               "### Senior Backend Engineer | Acme | 2021 - Present\n"
               "- Built things\n")
    assert matcher.guess_role(profile) == "Backend Engineer", matcher.guess_role(profile)
    assert matcher.guess_role("") == ""


@check("learn: brief says what is confirmed and what to distrust")
def t_learn_brief():
    jd = ("Minimum Qualifications\n- Expert Kafka and Kubernetes required\n"
          "- Terraform experience a plus\n")
    reqs = jd_parse.parse(jd)

    good = learn.record(jd, reqs)
    learn.set_outcome(good["id"], "interview")

    bad_jd = "Minimum Qualifications\n- Expert COBOL and Fortran required\n"
    bad = learn.record(bad_jd, jd_parse.parse(bad_jd))
    learn.set_outcome(bad["id"], "rejected")

    brief = learn.brief()
    assert "confirmed" in brief, brief
    assert "kafka" in brief, brief
    # A term only ever seen in a dead posting is flagged, not promoted.
    assert "cobol" in brief.lower(), brief


@check("learn: stats count outcomes and the response rate")
def t_learn_stats():
    s = learn.stats()
    assert s["postings"] > 0, s
    assert s["unique_terms"] > 0, s
    assert s["response_rate"] is None or 0 <= s["response_rate"] <= 1, s
    assert sum(s["outcomes"].values()) == s["postings"], s


@check("learn: patterns.md regenerates and reflects the archive")
def t_learn_patterns():
    path = learn.render_patterns()
    body = Path(path).read_text()
    assert "Recurring terms" in body, body[:400]
    assert str(learn.stats()["postings"]) in body


@check("learn: an unknown outcome is rejected loudly")
def t_learn_bad_outcome():
    try:
        learn.set_outcome(1, "hired-immediately")
    except ValueError as exc:
        assert "Unknown outcome" in str(exc), exc
    else:
        raise AssertionError("a bogus outcome was accepted")


@check("learn: a missing record id raises rather than inventing one")
def t_learn_missing_id():
    try:
        learn.set_outcome(999999999, "interview")
    except KeyError:
        pass
    else:
        raise AssertionError("out-of-range id was accepted")


@check("learn: a torn archive line does not lose the rest")
def t_learn_torn_line():
    before = len(learn.recent(limit=100))
    with learn.ARCHIVE.open("a", encoding="utf-8") as fh:
        fh.write('{"id": 123, "at": "broke')  # no newline, no closing brace
    after = len(learn.recent(limit=100))
    assert after == before, f"archive records lost: {before} -> {after}"


# --- company research -----------------------------------------------------

@check("research: company names are read, section headings are not")
def t_research_guess():
    assert learn.guess_company(
        "Acme is hiring engineers.\nRequirements\n- Python\n") == "Acme"
    assert learn.guess_company(
        "Backend Engineer at Stripe\nRequirements\n- Python\n") == "Stripe"
    assert learn.guess_company(
        "Globex Corporation is looking for a Platform Engineer.\n"
        "Requirements\n- Go\n") == "Globex Corporation"
    # A heading in the company's name position is not a company.
    assert learn.guess_company("Minimum Qualifications\n- Python\n") is None
    assert learn.guess_company(
        "We are hiring a senior engineer with opinions about consensus\n"
        "Requirements\n- Go\n") is None


@check("research: a guess never spans a line break")
def t_research_no_newline():
    # \s+ would capture "Stripe\nRequirements" as a single name.
    assert learn.guess_company("Job at Stripe\nRequirements\n- Python\n") == "Stripe"


@check("research: employers and job titles are not extracted as skills")
def t_research_noise():
    terms = set()
    jd = ("Globex Corporation is looking for a Platform Engineer.\n"
          "Requirements\n- Terraform and AWS required\n")
    for r in jd_parse.parse(jd):
        terms.update(r["terms"])
    assert "globex corporation" not in terms, terms
    assert "platform engineer" not in terms, terms
    assert {"terraform", "aws"} <= terms, terms


@check("research: one posting is one vote per term")
def t_research_one_posting_one_vote():
    """A term listed twice in one ad must not outrank breadth."""
    jd = ("Vote Co is hiring.\nRequirements\n- Python required\n"
          "- Kubernetes in production\n- Kubernetes in production\n")
    learn.record(jd, jd_parse.parse(jd))
    jd2 = ("Vote Co is hiring again.\nRequirements\n"
           "- Kubernetes in production\n- Go experience\n")
    learn.record(jd2, jd_parse.parse(jd2))

    pat = research.posting_patterns("Vote Co")
    assert pat["postings"] == 2, pat
    rows = {r["term"]: r for r in pat["terms"]}
    assert rows["kubernetes"]["postings"] == 2, rows["kubernetes"]
    assert rows["python"]["postings"] == 1, rows["python"]
    assert rows["kubernetes"]["rate"] == 1.0, rows["kubernetes"]


@check("research: recurring requirements are separated from one-offs")
def t_research_recurring():
    line = "- Kubernetes in production\n"
    for _ in range(3):
        jd = "Recur Inc is hiring.\nRequirements\n" + line
        learn.record(jd, jd_parse.parse(jd))
    jd = "Recur Inc is hiring.\nRequirements\n- COBOL experience a plus\n"
    learn.record(jd, jd_parse.parse(jd))

    pat = research.posting_patterns("Recur Inc")
    recurring = {r["term"] for r in pat["recurring"]}
    assert "kubernetes" in recurring, recurring
    assert "cobol" not in recurring, recurring


@check("research: a term required at least once is marked as such")
def t_research_required_flag():
    jd = ("Flag Ltd is hiring.\nPreferred\n- Rust experience a plus\n"
          "Requirements\n- Python required\n")
    learn.record(jd, jd_parse.parse(jd))
    rows = {r["term"]: r for r in research.posting_patterns("Flag Ltd")["terms"]}
    assert rows["python"]["ever_required"] is True, rows
    assert rows["rust"]["ever_required"] is False, rows


@check("research: an unknown company reports nothing rather than guessing")
def t_research_unknown():
    assert research.posting_patterns("Nobody Ltd")["postings"] == 0
    assert research.top_signals("Nobody Ltd") == []
    brief = research.brief("Nobody Ltd")
    assert "No postings from this company archived" in brief, brief
    assert research.brief("") == ""


@check("research: page text yields terms, not navigation words")
def t_research_terms_in():
    html = """
    <html><head><title>Acme Careers</title><script>var x=1</script></head>
    <body><h1>Join us</h1><p>We build payment infrastructure in Python,
    Go and Kubernetes on AWS. Apply now. Equal opportunity employer.
    Read our privacy policy and cookie policy.</p></body></html>
    """
    text = research._text_from(html)
    assert "payment infrastructure" in text
    terms = research.terms_in(text)
    for expected in ("python", "go", "kubernetes", "aws"):
        assert expected in terms, f"{expected} missing from {sorted(terms)}"
    for noise in ("privacy", "cookies", "policy", "apply", "careers", "equal"):
        assert noise not in terms, f"{noise} not filtered: {sorted(terms)}"


@check("research: the brief cites where every signal came from")
def t_research_brief_cites():
    for _ in range(2):
        jd = "Cite Inc is hiring.\nRequirements\n- Python and Kubernetes required\n"
        learn.record(jd, jd_parse.parse(jd))
    brief = research.brief("Cite Inc")
    assert "python" in brief and "kubernetes" in brief, brief
    assert "not evidence that the candidate has" in brief, brief


@check("research: un-attributed postings can be filed under a company")
def t_research_attach():
    jd = "Requirements\n- Elixir experience required\n"
    learn.record(jd, jd_parse.parse(jd))
    assert research.posting_patterns("Nowhere Inc")["postings"] == 0
    result = research.attach_postings("Nowhere Inc")
    assert result["attached"] >= 1, result
    pat = research.posting_patterns("Nowhere Inc")
    assert pat["postings"] == result["attached"], pat
    assert "elixir" in {r["term"] for r in pat["terms"]}, pat
    # Attaching twice must not double-count.
    research.attach_postings("Nowhere Inc")
    assert research.posting_patterns("Nowhere Inc")["postings"] == pat["postings"]


# --- run ------------------------------------------------------------------

def main():
    print("resume-forge self-check\n")

    # The learning tests write files. Point the archive at a temp directory so a
    # test run never touches the user's real postings.
    tmp = tempfile.mkdtemp(prefix="forge-test-")
    learn.DATA = Path(tmp)
    learn.ARCHIVE = learn.DATA / "archive.jsonl"
    learn.TERMS = learn.DATA / "terms.json"
    learn.PATTERNS = learn.DATA / "patterns.md"
    research.DATA = Path(tmp)
    research.COMPANIES = Path(tmp) / "companies"
    learn._ID_STATE.update(base=0, last=0)

    tests = [
        (k, v) for k, v in sorted(globals().items())
        if k.startswith("t_") and callable(v)
    ]
    failures = []
    for _, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((fn.__name__, exc))
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append((fn.__name__, exc))
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")

    print(f"\n{len(PASSED)} passed, {len(failures)} failed")
    if failures:
        print("\nfailures:")
        for name, exc in failures:
            print(f"  {name}: {exc}")
        raise SystemExit(1)
    print("all green")


if __name__ == "__main__":
    main()