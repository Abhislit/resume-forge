# Discovery interview

Used when you have no profile yet, or when the match report shows gaps you can
actually fill.

The rule: **surface what happened, do not invent it.** Your problem is never
that you lack experience — it is that you have never written the sentence that
describes it.

## When to run it

After the match report shows gaps. Not before, and not for requirements you
already clearly cover. Interviewing someone about things the JD does not care
about wastes the one thing that makes this worth doing: their attention.

## How it goes

Open with what you found, not with questions:

> Of the 9 requirements, 5 have support in your profile. These 4 don't:
> Kubernetes, GraphQL, a metrics/Prometheus requirement, and one about leading
> a migration. Some of these you may have done without writing it down. Want to
> spend 10 minutes on those four?

Then, per gap, one open probe — never a checklist:

| Gap type | Open probe |
|---|---|
| Hard skill (Kubernetes) | "Have you deployed anything to Kubernetes? Even a small service." |
| Practice (metrics) | "Tell me about a time you had to know whether something was healthy." |
| Leadership | "Tell me about a time you had to get other people to do something." |
| Domain (payments) | "Have you worked on anything where getting the money movement wrong was the risk?" |

**Branch on the answer.** The follow-up depends entirely on what came back:

- **Strong yes** → go for scale, obstacles, and a number. "How many? What broke?"
- **Indirect** → the transferable part is the story. "That's not the same
  thing, but what did you do there that transfers?"
- **Adjacent** → name the bridge yourself. "That's the same skill under a
  different word. How would you describe it?"
- **Old** → check whether it still holds. "That was 2018. Would you still reach
  for it now?"
- **No** → do not push. Move on. A gap you fill honestly is not a gap.

Then the systematic follow-ups, which are the part people skip:

1. What exactly did you do — your part, not the team's?
2. How did you do it?
3. Why that approach over the alternative?
4. Scale: users, volume, money, time, team size?
5. Was it in production, or planned? *(This distinction matters enormously and
   people blur it constantly. Planned work gets written as shipped work.)*
6. What happened after — did it work, what changed?

## Capture, immediately

Write it down as you go, in resume-bullet shape, then confirm with the user:

> Let me make sure I have that right: "Led the migration of 12 services off the
> legacy monolith, cut p99 from 840ms to 210ms." Accurate?

And ask for the missing piece every time:

> Do you have a number for that? If not, what would you put — "improved
> significantly" gets cut, so either a number or a different sentence.

## After each one

Ask what to do with it:

1. **Use it here** — goes into this resume
2. **Save to profile** — not needed now, keep it for the next one
3. **Dig further** — there's more there
4. **Drop it** — not worth the words

Default to 1 and 2 together. Save everything real; include only what this
posting needs. That split is the whole point of a profile file: the profile is
your career, the resume is a selection from it.

## Know when to stop

Ten minutes, or when the answers start repeating. If you have been drilling on
the fourth gap for a while, the first two were probably the easy wins.

## The one thing not to do

Do not let a good-sounding phrase through without a source. "Spearheaded a
company-wide transformation" is the kind of sentence that reads well, survives
no follow-up question, and gets you caught in the interview. The tool flags
numbers it cannot trace to your profile; the part it cannot flag is the one where
you have to be honest with yourself before you start optimizing.