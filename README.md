# Resume Forge

Paste a job description. See how your experience maps to it. Fill the gaps. Get
a resume that both an automated parser and a human recruiter can read.

Local web app. Python standard library only — nothing to install.

```sh
export ANTHROPIC_API_KEY=sk-ant-...     # only needed for the Draft step
python3 server.py                       # → http://localhost:8770
python3 test_forge.py                   # 65 self-checks
python3 test_pdf.py                     # 12 PDF export checks
```

Without the API key everything still works: parse, match, lint, export, and a
manual paste box on the Draft step.

## Install the skill

The repo ships the opencode skill alongside the app. To use it, copy the folder
into your opencode skills directory — globally so it works from any project:

```sh
git clone https://github.com/Abhislit/resume-forge.git
mkdir -p ~/.config/opencode/skills
cp -r resume-forge/skill ~/.config/opencode/skills/resume
```

Then paste a job description at it. The skill runs the tools in this repo
through `forge.py` and drafts with opencode's own model, so there is no second
API key to configure.

Your profile and posting archive stay local and are never committed — both
`profile.md` and `data/` are in `.gitignore`.

## The flow

```
JD (paste / upload / URL)
  → parse.py   requirements[], split required vs preferred
  → match.py   requirements × your profile → matrix
  → you        answer the gaps
  → one AI call → draft
  → lint.py    named violations, each with a fix
  → export     .docx and .pdf
```

Only the drafting step involves a model. Parsing, matching, and linting are
deterministic, which is why the gap report is trustworthy — a language model
cannot talk you into believing you're a match.

## What it will not do

It will not make you past a filter where a person has already decided. No
document format changes that, and any tool claiming otherwise is selling you a
score it cannot earn.

It will not invent. A number in the draft that is not traceable to your profile
is flagged before you can send it, and the system prompt forbids inventing one
in the first place. If you cannot source a metric, the tool asks rather than
guesses.

It will not stuff keywords. `lint.py` treats repetition past a reasonable
density as a *violation*. Keyword stuffing is falsification of application
materials, and it reads as gaming to the human on the other side of the filter.

## Where the ATS rules came from

`references/ats.md` distills MIT CAPD's published guidance into assertions the
linter can check. Not scraped at runtime — a scraper breaks the moment a site
reorganizes, and the article is their text. The rules worth knowing anyway:

- No tables, no text boxes, no images, one column. This is the big one.
- Body text 10.5pt or larger, font from Arial/Calibri/Cambria/Georgia/Helvetica/
  Times New Roman.
- Use the posting's words where you genuinely have the experience. Don't
  abbreviate — an ATS matching "JavaScript" may not expand "JS".
- "Save as .txt and read it" is a real self-test. This tool does it for you with
  the **Plain text self-test** button.

## Output

`.docx` is written by hand as a zip of OOXML (`docx_writer.py`, ~150 lines) so
there is no `python-docx` dependency.

`.pdf` is headless Chrome's own print engine (`pdf.py`), the same path the
browser print dialog takes — no PDF library, no font embedding, no LibreOffice.
The result is a text-based PDF, not a scan, which is what a parser needs.
`--verify` extracts the text and tells you which one you produced, because an
image-only PDF parses as a blank page and fails silently.

```sh
python3 forge.py pdf draft.md resume.pdf --verify
```

Page geometry lives in one place, the `@media print` block in `web/style.css`,
so the browser dialog and the headless command cannot drift apart.

## Company profiler

Name a company and the tool builds a profile from two independent sources.

**Their own postings** — every JD you paste is filed under its company, so the
pattern builds itself:

```sh
$ python3 forge.py company pattern Acme
2 posting(s) archived for Acme

  kubernetes             2/2 postings (100%) required
  python                 2/2 postings (100%) required
  graphql                1/2 postings (50%) preferred
  postgresql             1/2 postings (50%) required
```

That is stronger evidence than any single job ad, and it tells you something an
ad cannot: they have never asked for GraphQL, and they ask for Kubernetes every
time. Stop padding resumes with things an employer does not ask for.

**Public pages you add by URL:**

```sh
python3 research.py probe Stripe                     # find careers/blog URLs
python3 research.py add Stripe https://stripe.com/blog --label "engineering blog"
python3 forge.py company brief Stripe
```

Careers pages, engineering blogs, conference talks, a public GitHub org —
anything the company chose to publish. Every signal keeps its source URL, and
`terms_in` is restricted to the tech lexicon because a careers page is prose and
free-form extraction turned it into junk.

An unknown company reports nothing. That is the point.

Not included: profiles of named individuals. Aggregating one person's private
resume is a privacy problem, and it is worse research — one person's resume is a
single sample of what got one person through one door. The postings pattern is
public, broader, and actually predictive.

## The skill

Paste a JD in opencode and the skill takes over — no server needed.

```
~/.config/opencode/skills/resume/
  SKILL.md              routing, the truth rules, the workflow
  references/           bullets, ATS, format, interview, forge internals
```

It drives the same modules through a CLI:

```sh
cd ~/resume-forge
python3 forge.py parse  jd.txt
python3 forge.py match  jd.txt
python3 forge.py lint   draft.md jd.txt
```

The skill uses opencode's own model for drafting, so there is no second API key
to configure. The server's draft button is a convenience, not a requirement.

## What "learning" means here

Nothing retrains. No weights change. What accumulates is:

- **`data/archive.jsonl`** — every unique posting you paste, append-only,
  de-duplicated by content hash so re-parsing the same JD does not inflate the
  counts.
- **`data/terms.json`** — how many postings asked for each term, and how many of
  those postings produced an interview or offer.
- **`data/patterns.md`** — generated summary of the above.

Those counts change the tool's behaviour: a term seen in five postings and
confirmed twice outranks a term seen once in the gap report, and the drafting
prompt is told which terms this market has actually confirmed. Terms that
appeared *only* in postings that never got a response get flagged as
untrustworthy.

The loop that makes it real: **report your outcomes.** Interview and offer are
the only two that mark a term as confirmed. Skip that step and the archive is
just a pile of postings.

```sh
python3 learn.py outcome <id> interview
python3 learn.py brief          # what the archive currently believes
```

`forge.py match` refuses to report coverage when there is no profile — matching
against the example template would tell you the requirements are covered by
content that is not yours.

## Files

| File | |
|---|---|
| `server.py` | stdlib http.server, routes, the one API call |
| `forge.py` | CLI for the skill: parse, match, lint, brief, stats |
| `learn.py` | the archive — what past postings taught |
| `research.py` | company profiler — public sources + the postings pattern |
| `parse.py` | JD → requirements |
| `match.py` | requirements × profile → matrix |
| `lint.py` | ATS rules as assertions |
| `docx_writer.py` | OOXML by hand |
| `web/` | the four-step UI, no framework |
| `references/` | craft detail: `ats.md`, `bullets.md`, `format.md`, `interview.md` |
| `profile.md` | your canonical facts — gitignored, created in the UI |

## Your profile is the source of truth

`profile.md` is written once, read forever. The profile is your career; a resume
is a selection from it. Keeping them separate is what lets one interview serve
every application instead of re-interviewing you each time.

Roles want a date range, the domain, the scale, and the impact. That is what
makes the match traceable: every `covered` row links back to the line in your
profile that supports it.

## Security posture

The server binds to `127.0.0.1` only. It refuses cross-origin POSTs, so a random
web page cannot drive it from your machine, and it rejects path traversal. Your
API key is read from the environment of the server process — never sent to the
browser, never written to disk.

## Design

`docs/superpowers/specs/2026-10-08-resume-forge-design.md`

## Attribution

Built by merging three existing open-source resume skills plus MIT CAPD's ATS
guidance. The repos cloned alongside it are `resume-tailoring-skill`,
`ResumeSkills`, and `resume-builder-skill`.