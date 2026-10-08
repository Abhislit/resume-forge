# ATS rules — the checkable version

Distilled from MIT CAPD's published ATS guidance. Stated as assertions because a
rule you cannot check is a rule you cannot follow.

## Why this is all about parsing, not filtering

An ATS is a database plus, sometimes, a scorer. It parses your document into
fields, then queries and ranks those fields. So the failure mode is rarely "the
ATS decided you were unqualified" — it is "the parser never saw your React
experience because it was inside a text box."

That distinction decides every rule below: **anything a parser might drop,
misorder, or misread is the bug.**

## File type

- `.docx` or `.pdf` unless the posting specifies otherwise. Both are accepted by
  Greenhouse, Workday, iCIMS, and Lever.
- A PDF from a browser's print dialog is a *text-based* PDF, not a scan. That is
  what you want. A scanned or image-only PDF has no extractable text and the
  parse yields nothing.
- Pay attention to the file type the posting asks for, and use that one even if
  the portal would have accepted another.

## Structure — the highest-yield rules

- **No tables.** This is the single most common cause of scrambled resumes.
  Content in table cells is reordered or dropped on parse. One item per line.
- **No text boxes.** Same failure, harder to notice.
- **No graphics, icons, images, or logos.** Ignored or garbled.
- **One column.** Multi-column layouts interleave text in the wrong order, and
  the parser does not know which column to read first.
- **Standard section headings.** `Summary`, `Experience`, `Skills`, `Projects`,
  `Education`. Recruiters scan for these labels, and parsers map content to them.
- **No HTML comments or hidden text.** Invisible to the human reading the
  rendered page, visible to the parser. This is falsification, and it is the
  kind that gets caught.
- **No text in headers or footers.** Many parsers ignore them entirely.

## Typography

- Body text **10.5pt or larger**. Small text is the first thing dropped.
- Font from the cross-platform safe set: **Arial, Calibri, Cambria, Georgia,
  Helvetica, Times New Roman**. A font the system does not have gets
  substituted, and substitution can drop adjacent text.
- Black text only. Color is not preserved, and a light color on white can read
  as an empty region to a heuristic scanner.
- No stylized, decorative, or display fonts.

## Keywords

This is the part people get wrong in the direction that hurts them.

- **Use the posting's words where you genuinely have the experience.** If the
  posting says "CI/CD" and you have done it, write "CI/CD". This is the
  legitimate version of keyword matching: matching vocabulary, not claiming
  experience.
- **Do not abbreviate.** An ATS matching "JavaScript" may not expand "JS". Write
  the full form at least once.
- **Do not split a word across a line break.** If the renderer breaks
  "molecule" into "mole-" / "cule", the parser sees two fragments and credits
  neither. This one is silent — nothing errors, the keyword just quietly fails.
- **Replace vague quantifiers with the specific thing.** "Various", "multiple",
  "several", "etc." are masking keywords you could have used. Say what you mean.
- **Do not stuff.** Repeating a term past a reasonable density is a signal to a
  human reviewer that something is being gamed, and it is falsification of
  application materials. The source is explicit that this risks dismissal.

## The self-test

Save your resume as a plain `.txt` file and read it start to finish. Formatting
strips away; what remains is what a parser gets. Look for:

- **Missing text** — a conversion problem. You have text boxes or tables.
- **Wrong order** — a layout problem. You have columns or text boxes.
- **Split words** — a wrapping problem.

## What this cannot fix

The reference guide is right to be blunt about it: if you feel like you are
throwing resumes into a black hole, some of it is the filter, and the lever is
not the document.

- **Get a referral.** Someone inside can check whether the ATS swallowed your
  application and flag it to HR. This is worth more than any keyword change.
- **Talk to people at the company.** Campus visits, alumni, informational
  interviews. A human who has seen your resume is a human who will look for it.
- **Build the network before you need it.** Not the week of the deadline.

And the honest version of the whole thing: no tool makes a resume get past a
filter where a person has already decided. What a good document does is make
sure that when a fair filter or a fair human looks, they see what you actually
did.

## Source

MIT Career Advising & Professional Development, "Make your resume ATS-friendly."
The above is a paraphrase of checkable rules, not a reproduction of the article.