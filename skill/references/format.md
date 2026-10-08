# Structure and format

## Section order

Most common first. The order encodes what the reader cares about.

**For engineers and most technical roles:**

1. Name and contact
2. Skills
3. Experience
4. Projects
5. Education

Skills go high because that is what the 5-second scan is looking for. Education
goes last once you have real experience — the experience section is the
centerpiece.

**For students, new grads, and academics:**

1. Name and contact
2. Education
3. Experience / internships
4. Projects
5. Skills

Education is the credential being evaluated, so it leads.

**For senior leaders:** drop Skills to a short block, keep the summary tight.
Experience dominates; scope and outcomes are the point.

## Length

- 0–2 years: one page.
- 3–7 years: one or two.
- 7+ years, or roles with real scope: two pages.
- Academic CV: as long as the field requires, with publications.

Two pages is not a penalty for an experienced engineer. One page of padded
junior work is.

## The summary

Two or three sentences, no pronouns. What you do, at what scale, in what
domain, aimed at what kind of role.

> Backend engineer with 6 years building payment infrastructure. Led the
> migration from a monolith to 12 Python microservices handling 4M requests/day
> under PCI scope. Looking for platform work at scale.

Cut: adjectives, "passionate about", "results-driven", anything you cannot
support with a number.

## Typography

| Element | Spec |
|---|---|
| Name | 16pt, bold |
| Section headings | 11.5pt, bold, uppercase, thin rule under |
| Body / bullets | 10.5pt |
| Font | Calibri, Arial, Helvetica, Cambria, Georgia, Times New Roman |
| Margins | 0.75in all sides |
| Line spacing | 13pt exact |
| Color | Black |
| Layout | Single column |

Do not mix more than one font family.

## Dates

En dash, spaces around it: `2021 – 2023`, `2019 – Present`.

Use `Present` for a current role. Not `Current`, not `Now`.

Right-align dates. In the DOCX writer this is a tab stop, not a table — tables
break parsers.

## Contact

Plain text. No `Email:` prefixes, no `https://www.`, no underlines. The reader's
ATS reads the string.

Name on one line at 16pt. If your name is long enough to wrap, drop to 15pt
rather than letting it break.

## What to leave out

- Photo (and in the US, it actively hurts — it invites bias the resume cannot
  answer)
- Date of birth, marital status, nationality, gender
- Social handles that are not professional
- "References available on request"
- Anything in a text box, table, or graphic
- A skills section listing every language you have ever touched — it dilutes
  the ones you have actually used

## Bullets and the exported files

Export both `.docx` (editable, for your next revision) and `.pdf` (what you send
or upload). A `.docx` can render differently on the recipient's machine and Word
version; a PDF shows exactly what you designed.

The `.pdf` from this tool is a browser print — text-based, never rasterized,
which is what a parser needs. If you ever export a PDF another way, verify it is
text-based by opening it and selecting text, or by running `pdftotext` on it. An
image-only PDF parses as a blank page.