# resume-forge internals

Only read this when you need the API surface or the file layout.

## Run

```sh
cd ~/resume-forge
export ANTHROPIC_API_KEY=sk-ant-...   # only for the server's own draft button
python3 server.py                     # binds 127.0.0.1:8770
python3 test_forge.py                 # 55 self-checks, writes to a temp dir
```

## Modules

| File | |
|---|---|
| `parse.py` | JD text → `requirements[]`, each `{text, kind, terms, verbs}`. Reads `.txt`, `.docx` (a zip), or a URL. |
| `match.py` | `requirements[]` × profile → matrix. Each row carries `status` (`covered`/`partial`/`gap`) and the evidence string it matched. |
| `learn.py` | The archive. Append-only `data/archive.jsonl`, derived `data/terms.json`, generated `data/patterns.md`. |
| `research.py` | Company profiler. Public sources plus the postings pattern. |
| `forge.py` | CLI for everything below. Works on first run with no profile. |
| `lint.py` | ATS rules as assertions. Named violations with fixes, no score. |
| `docx_writer.py` | OOXML written by hand into a zip. No `python-docx`. |
| `server.py` | stdlib `http.server`. Routes below. |

## CLI

```sh
python3 forge.py parse  jd.txt              # requirements JSON; archives the JD
python3 forge.py match  jd.txt [profile.md] # summary + gaps; refuses to guess
python3 forge.py lint   draft.md [jd.txt]   # violations; exit 1 if any
python3 forge.py brief  [role]              # what the archive has learned
python3 forge.py stats                     # counts and response rate
python3 forge.py role  [profile.md]         # guessed role family
python3 forge.py company brief     <name>  # employer profile, sources cited
python3 forge.py company pattern   <name>  # requirement frequency at that firm
python3 forge.py company attach    <name>  # file earlier postings under a name
python3 forge.py company list              # every profiled company

python3 research.py probe "<company>"      # try careers/blog URLs
python3 research.py add  "<company>" <url> --label <what>
python3 research.py brief "<company>"      # prompt paragraph
python3 research.py companies
```

`match` with no `profile.md` refuses to report coverage and prints what the
posting asks for instead. Matching against the example template would report
"covered" against content that is not the user's.

## Company signals

Two independent inputs:

1. **Their own postings**, filed automatically by `learn.guess_company` when you
   paste a JD. `posting_patterns` reports per-term frequency across postings —
   one posting is one vote per term, so a term listed twice in one ad cannot
   outrank genuine breadth. Terms required in more than one posting are
   "expected to be screened on"; terms in under a third are reported as ones
   they rarely ask for.

2. **Public pages** you add by URL. `terms_in` is restricted to the tech
   lexicon: a careers page is prose, and free-form phrase extraction turned it
   into junk ("aws. apply", "we"). A missed technology is fixable by adding it
   to the lexicon; a fabricated one is not.

Every signal carries its URL. Nothing is inferred about a named individual, and
an unknown company reports nothing rather than guessing.

## HTTP API

All POST, JSON in and out. Refuses cross-origin requests.

| Route | |
|---|---|
| `GET /api-health` | key present, profile exists, model |
| `POST /api/parse` | `{jd}` → requirements, archives it, returns `archive_id` |
| `POST /api/fetch` | `{url}` → posting text + requirements, archived |
| `POST /api/upload` | `{docx_base64}` → posting text + requirements, archived |
| `POST /api/match` | `{profile, requirements}` → matrix, summary, weighted open items, guessed role |
| `POST /api/tailor` | `{profile, requirements, jd}` → draft markdown, violations, fabrication warnings |
| `POST /api/lint` | `{markdown, requirements}` → violations, plain-text export |
| `POST /api/docx` | `{markdown, title}` → binary `.docx` |
| `POST /api/learn/brief` | `{role}` → the archive paragraph |
| `POST /api/learn/outcome` | `{id, outcome, note}` → records how it went |
| `POST /api/learn/patterns` | regenerates `data/patterns.md` |

## learn.py CLI

```sh
python3 learn.py stats                     # counts, outcomes, response rate
python3 learn.py signals                   # terms seen in 3+ postings
python3 learn.py proven                    # terms a posting confirmed
python3 learn.py recent                    # newest first, with ids
python3 learn.py record /path/to/jd.txt --role "Backend Engineer"
python3 learn.py outcome <id> interview
python3 learn.py brief --role "Backend Engineer"
python3 learn.py patterns                  # rewrite patterns.md
```

## How the "learning" actually works

Nothing retrains. Three stores under `data/`:

- **`archive.jsonl`** — one append-only record per unique posting, keyed by a
  content fingerprint so re-pasting the same JD does not inflate counts.
- **`terms.json`** — `counts` (how many postings asked for a term),
  `confirmed` (how many of those postings led to an interview or offer),
  `by_role`.
- **`patterns.md`** — generated from the above. Never hand-edit; it would drift.

`term_weights()` turns those into the ranking the gap report uses: a term seen in
five postings and confirmed twice outranks a term seen once. `brief()` is what
gets injected into the drafting prompt, including a negative signal — terms that
appeared *only* in postings that never got a response are flagged as
untrustworthy.

The loop that makes it real: a posting says a term is required, an interview
confirms the term was genuinely wanted, and it is promoted to "safe to lead
with". A rejection does not demote anything — it just fails to confirm.

## Guarantees worth keeping

- Every `covered` requirement links to the profile line supporting it.
- `server.fabrication_guard` rejects numbers in the draft that do not appear in
  the profile, before the user can send it.
- The linter flags keyword stuffing as a violation.
- The profile is written only by the user's own edit in the UI. The linter never
  writes to it.