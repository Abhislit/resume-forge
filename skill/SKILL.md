---
name: resume
description: Use when the user shares a job description, asks to tailor/optimize/build a resume or CV, asks about ATS or application tracking systems, asks to review or rewrite resume bullets, or asks for help preparing a job application. Triggers include pasting or uploading a JD, "tailor my resume", "make a resume for this job", "ATS friendly", "does my resume get past filters", "review my resume", "improve these bullets", "add metrics", "which version should I send", "I'm applying for X", or a pasted job posting. Uses the local resume-forge app, which archives every posting and learns which terms the market actually confirms.
---

# Resume

Tailoring is not writing. The document is a selection from a set of facts that
already exist, ordered for one specific reader. Most resumes fail on the second
half of that sentence, not the first.

## What exists

`~/resume-forge` — a local web app, Python stdlib only, no dependencies.

```sh
cd ~/resume-forge && python3 server.py     # → http://localhost:8770
```

It archives every posting you paste, in `~/resume-forge/data/`, and folds the
requirements into a learned vocabulary.

```sh
cd ~/resume-forge && python3 forge.py <command>
```

`parse` · `match` · `lint` · `brief` · `stats` · `role`. See
`references/forge.md` for the full API.

## The rule that outranks everything

**Never invent a claim, a number, an employer, a date, or a technology.** If a
metric is needed and the profile does not have one, write `[confirm: <what to
ask the user>]` and ask. A fabricated metric is discoverable in the interview
and it is falsification of an application — grounds for dismissal.

Reframe and emphasize. Never add.

## Workflow

### 1. Get the profile

Read `~/resume-forge/profile.md`. If it does not exist or is thin, interview —
see `references/interview.md`. Do not ask for information the file already has.

The profile is the career; a resume is a selection from it. Keep them separate
so one interview serves every application.

### 2. Parse the JD

```sh
cd ~/resume-forge && python3 forge.py parse /tmp/jd.txt
```

Required beats preferred. Show the user the extracted list before going further
— it is a first pass and they will spot what it got wrong.

### 3. Match, and surface the gaps honestly

```sh
cd ~/resume-forge && python3 forge.py match /tmp/jd.txt
```

Prints a summary, then every gap and partial with the missing terms, a learned
weight where the archive has one, and the closest line in the profile.

Tell the user which requirements have no support. Ask what they actually did.
Do not fill a gap by inference — a `partial` means adjacent experience, and the
user decides whether that is close enough.

### 3b. If they name a company, research it

```sh
cd ~/resume-forge && python3 forge.py company brief "Stripe"
python3 forge.py company pattern "Stripe"    # which requirements they repeat
```

Two sources, and the second is stronger:

**Their own postings.** Every JD you paste is filed under its company. Four
postings from one employer is a pattern of what they screen on — far better
evidence than one job ad, and it accumulates for free.

**Public pages.** `research.py probe <company>` finds careers pages and blogs;
`research.py add "<company>" <url> --label <what>` fetches one and extracts its
vocabulary. Every signal keeps its source URL.

Use the search tool to find URLs worth fetching (engineering blog posts, a
conference talk, a public GitHub org), then hand the URLs to `research.py`.

What this buys you: their vocabulary to phrase bullets in, and the knowledge
that they have never once asked for GraphQL while asking for Kubernetes every
time. Report that absence — it stops you from padding a resume with something
they do not care about.

Do not build a profile of a named individual. Aggregating one person's private
resume is not research, and one person's resume is a single sample anyway. The
postings pattern is better evidence and it is public.

Filing corrections:
```sh
python3 forge.py company attach "Acme"      # file earlier postings under a name
python3 learn.py record jd.txt --company "Acme" --role "Backend Engineer"
```

### 4. Draft

Follow `references/bullets.md`. Shape is: action verb, what, context, impact.

Order bullets by relevance to this posting. Put the two or three that map to its
top requirements first, inside each role. That is the tailoring.

### 5. Check before handing it over

```sh
cd ~/resume-forge && python3 forge.py lint /tmp/draft.md /tmp/jd.txt
```

Exit code is 1 when there are violations, 0 when clean.

The linter flags real ATS failures: tables, text boxes, small fonts, split
words, bullets ending in periods, pronouns, vague quantifiers, weak openers,
keyword stuffing. Report violations with their fixes. Do not summarize them into
a score — a self-scored number implies fidelity to a filter nobody can simulate.

Then check the one thing no linter can: **does every claim trace to the
profile?** Read the draft against `profile.md` yourself. If a bullet says
"reduced costs 30%" and the profile says nothing about cost, that is a bug you
introduced.

### 6. Report the outcome

```sh
cd ~/resume-forge && python3 learn.py outcome <id> interview
```

The id comes from `forge.py parse` or `python3 learn.py recent`.

Outcomes are `applied`, `interview`, `offer`, `rejected`, `ghosted`,
`withdrawn`. Only interview and offer mark terms as confirmed. **This is the
only step that makes the archive worth anything** — without it, every posting
looks equally important and nothing is learned.

## Keyword policy

Use the posting's words where the profile genuinely supports them. That is
legitimate: matching vocabulary, not claiming experience.

Do not abbreviate (`JS` → `JavaScript` at least once). Do not split a keyword
across a line break. Do not repeat a term more than twice in a document —
stuffing past that is falsification and reads as gaming to the reviewer.

## What not to promise

- No document format makes a resume past a filter where a human has already
  decided. Anyone selling that is lying.
- The tool raises your odds on a fair filter and makes your resume readable to
  a fair human. That is the whole claim.

When a user is applying somewhere and mentions no response, the highest-value
advice is a referral or a direct introduction — it goes around the filter
entirely. Say that once. Do not repeat it every time.

## Honest failure

If the profile genuinely does not support a required requirement, say so and let
the user decide whether to apply anyway. Do not quietly drop a requirement and
present a resume that looks tailored. If every resume is going to be a stretch,
that is useful information — but it has to come from the profile, not from you
hoping the reader will not notice.