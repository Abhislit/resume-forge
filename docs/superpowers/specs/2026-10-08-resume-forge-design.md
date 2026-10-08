# Resume Forge — Design Spec

Date: 2026-10-08
Status: approved in conversation, pending spec review

## Problem

Tailoring a resume to a job description is done by hand, every application, by
someone who cannot see how their resume will actually be read. Three failure modes
recur: keyword terms from the posting never make it into the resume, layout
choices silently break automated parsing, and unquantified bullets get skipped by
a human reading for 15 seconds.

Goal: paste a job description, see exactly how your experience maps to it, fill
the gaps yourself, and export a resume that both an automated parser and a human
recruiter can read correctly.

Non-goal: fooling a filter that has already decided against the candidate. No
output of this tool may contain a claim the user did not make.

## Approach

A pipeline with one LLM step, not a chat box.

Everything except prose drafting is deterministic string work: extracting
requirements from a posting, matching them against a stored profile, detecting
gaps, and linting the result against ATS rules. The LLM is called exactly once,
to turn the user's own facts into well-written bullets. Keeping the rest
deterministic makes the tool testable, fast, and honest — the LLM cannot
influence what the gap matrix says.

The user sits in the loop at the gap matrix. That is the product: the app is
honest about what it does not know about the user, and the user supplies it.

## Pipeline

```
JD (paste / .txt / .docx / URL fetch)
  -> parse.py   requirements[] : required vs preferred, skills, action verbs
  -> match.py   requirements[] x profile.md -> matrix (covered/partial/gap)
  -> UI         user reviews matrix, fills gaps, edits profile
  -> AI step    one call: requirements + profile + gaps -> draft bullets
  -> lint.py    ATS assertions on the draft -> violations with fixes
  -> export     DOCX (hand-written OOXML) + PDF (browser print dialog)
```

### parse.py — JD to requirements

Input: pasted text, an uploaded `.txt` or `.docx` (docx is a zip, so `zipfile`
plus `xml.etree` reads `word/document.xml` directly), or a URL fetched over
`urllib.request`.

Splits the posting into a `##`-delimited requirement list. Classifies each line
as **required** (must-have, "required", "you have", "minimum") or **preferred**
(nice-to-have, "bonus", "plus", "preferred"). Extracts a skill vocabulary
(canonicalized to lowercase, plurals stripped) and the action verbs the posting
uses, since those signal what the role actually emphasizes.

Heuristics, deliberately simple: a capitalized multi-word phrase or a token in a
known-skill lexicon becomes a skill candidate; the same token appearing in both
required and preferred sections is `required` (stronger signal wins). Line items
under 25 characters are dropped as noise. This is not a parser for every posting
in the world — it is a first pass whose output the user can correct in the UI,
which is why the matrix is editable.

### match.py — requirements against profile

`profile.md` is the canonical source of truth: roles with dates, domain, data
handled, scale, impact; skills; education; projects; preferences (page count,
target market, language). Read once per run, never written by the matcher.

Emits, per requirement, one of:

- `covered` — a profile entry asserts the skill or an equivalent synonym
- `partial` — adjacent or implied; user confirms or corrects
- `gap` — no supporting evidence in the profile

Synonym handling is a small explicit map (kubernetes/k8s, js/javascript,
postgres/postgresql). No embedding model. A gap that is really a cover is a
false negative the user fixes in one click; an embedding model would be a large
dependency to remove that same false negative.

Every row carries the evidence string it was matched from, so a `covered` claim
is always traceable to a line the user wrote.

### AI step — drafting

One Anthropic Messages API call. Key read from `ANTHROPIC_API_KEY` in the server
process environment only; never sent to the browser, never written to disk.

Input: the requirements matrix, the profile, the filled-in gaps. Output: JSON
containing professional summary, key skills ordering, and bullet rewrites per
role.

System prompt carries three rules verbatim from the source material, because they
are the ones an LLM will otherwise break:

1. Never introduce a claim, number, employer, or date absent from the input.
   Unknown quantities are emitted as `[confirm: <what to check>]`, never guessed.
2. Action verb, what was done, technical/domain context, business impact. No
   personal pronouns. No bullet ends with a period.
3. No superfluous verbs (spearheaded, orchestrated, utilized, leveraged) and no
   intensifiers (excellent, innovative, strategically).

The response is parsed and validated against the profile before display: any
number in the output that does not appear in the input is rejected and surfaced
to the user as a fabrication warning rather than silently rendered.

### lint.py — ATS rules as assertions

Operates on the draft only. Never writes to the profile.

Rules, from MIT CAPD's published ATS guidance and the resume-craft references:

Structure — no tables, text boxes, graphics, icons, or images; single column;
standard section names (Experience, Skills, Projects, Education); reverse
chronological order within each section.

Typography — body text 10.5pt or larger; font from the safe set (Arial, Calibri,
Cambria, Georgia, Helvetica, Times New Roman); no colored or stylized fonts.

Content — no personal pronouns; every bullet opens with a strong past-tense
action verb; no trailing periods on bullets; no superfluous verbs or
intensifiers; digits not spelled-out numbers; en dashes for date ranges with
spaces around them.

Keyword handling — target terms appear as written in the posting, unabbreviated;
no "various", "multiple", "several", "etc."; keyword density is reported as
coverage with a warning above roughly 20% repeated occurrences of one term in a
single document.

Keyword stuffing is treated as a **failure**, not a strategy: exceeding the
coverage threshold is a violation. The MIT source is explicit that falsifying
application materials is grounds for dismissal, and repeated identical keywords
is both dishonest signalling and detectable.

Self-test affordance: `lint.py` also renders the draft as plain text and reports
words the parser would join across a line break, since "mole-/cule" is the
specific silent failure the source calls out.

Output is a list of violations, each with the offending line and a concrete fix,
not a score.

### Export

**DOCX** written by hand as a zip of OOXML. A resume needs only paragraphs and
runs plus a handful of named styles, so this is roughly 150 lines and removes the
`python-docx` dependency entirely. Standard Open XML packaging: `[Content_Types].xml`,
`_rels/.rels`, `word/document.xml`, `word/styles.xml`, `word/_rels/document.xml.rels`.
Bullets use `numbering.xml` with a single bullet definition.

**PDF** is the browser's own print dialog against `print.css`. No PDF library, no
headless Chrome, no font embedding, no LibreOffice. The print stylesheet is the
ATS-safe resume: one column, 0.75in margins, 10.5pt body, black text, no
decoration. One button opens print, the user picks "Save as PDF". The result is a
text-based PDF with no rasterization, which is exactly what an ATS needs.

**Markdown** is emitted alongside as the diffable source of truth and for reuse.

## Interface

Four steps, one page, no framework — vanilla HTML/CSS/JS, matching the
`samvaad-pos` house style already in this home directory.

1. **Job** — paste, upload, or fetch a URL. Parse shows the extracted requirement
   list for correction before anything else happens.
2. **Profile** — loads `profile.md`, shows the match matrix. Gaps are editable
   inline and write back to the profile on save.
3. **Draft** — one AI call produces bullets and summary. Validation warnings,
   if any, appear above the draft.
4. **Export** — lint results, then download DOCX, print to PDF, or copy Markdown.

Also on this screen, as a static nudge rather than a feature: MIT's advice that a
referral or direct introduction to a recruiter is worth more than any keyword
strategy, since it bypasses the automated filter entirely.

## Truth rules

Non-negotiable, stated once, applies at every layer:

- Reframe and emphasize. Never invent. No fabricated employer, date, degree,
  technology, or metric.
- Quantities that cannot be sourced become `[confirm: ...]` markers and are listed
  in the export as open items, so nothing ships half-asserted.
- The profile is authoritative and read-only to the AI; the user's own edits in
  the UI are the only writes.
- Every `covered` requirement links back to the profile line that supports it.

## Scope cuts

Stated here so they are decisions rather than oversights.

- **No web scraping of the source article.** MIT's guidance is distilled into
  checkable rules in `references/ats.md`. Scraping would be brittle and would
  redistribute copyrighted text.
- **No multi-job batching.** Single JD per run. Adding it later means looping
  the same pipeline, which the architecture already allows.
- **No cover letters, LinkedIn, portfolios, or interview prep.** One job.
- **No ATS-simulation scores.** Named commercial services exist; a self-scored
  number would imply a fidelity this tool does not have. Named violations with
  fixes are honest; a score is not.
- **No dependency on a rigged-filter bypass.** If a filter has pre-decided, no
  document format changes that.

## Files

```
resume-forge/
  server.py             stdlib http.server; serves UI, /api/tailor, /api/fetch
  parse.py              JD -> requirements[]
  match.py              requirements[] x profile -> matrix
  lint.py               ATS assertions -> violations
  profile.md            canonical user facts (gitignored, UI-created)
  templates/docx/       OOXML parts
  web/index.html        four-step UI
  web/app.js            fetch + render + print
  web/style.css         screen styles
  web/print.css         ATS-safe resume stylesheet
  references/           craft detail: bullets, format, ats, interview
  test_forge.py         assert-based self-check
```

Zero third-party dependencies. Python 3.14 stdlib only: `http.server`, `zipfile`,
`xml.etree`, `json`, `urllib.request`, `os`, `re`.

## Testing

`test_forge.py`, plain asserts, no framework. Covers the parts where being wrong
is silent and expensive:

- `parse.py` classifies required vs preferred, and required wins on conflict.
- `match.py` reports `covered` for an exact skill, `covered` for a synonym, and
  `gap` for an absent one, and carries the evidence string in all cases.
- `lint.py` catches a table marker, an under-10.5pt font declaration, a personal
  pronoun, a trailing period on a bullet, an abbreviated keyword, a stuffed
  keyword term, and a hyphen-split word across a line break.
- The DOCX writer produces a zip whose entries all parse as XML and which
  contains `word/document.xml`.
- End-to-end: a fixed JD and a fixed profile produce a draft containing no
  number absent from the profile — the fabrication guard.

Run: `python3 test_forge.py`