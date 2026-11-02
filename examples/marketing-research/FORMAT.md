# Format of report.md

This is the only spec the report writer gets. The scorer's code is not shared, so write for the
reader, not for the score. Workspace files: `brief.md` and `data/` (read-only), `report.md` (yours).
Samples: `samples/good.md` (scores about 1.0) and `samples/bad.md` (scores low).

## Structure, in this order

1. A title line (`# ...`).
2. `## Summary...` first: the answer in one or two sentences, then a line `Target segment: ...` naming
   the segment Fieldnote should target first (say `Segment N` or use the segment's name from metrics).
3. Six module sections, in the brief's order, each headed `## N. Name: takeaway` where N is 1 to 6 and
   the name holds the module's key word: top-of-mind, penetration, profiling, positioning, perception,
   segmentation. State the takeaway as a sentence, not a topic label.
4. `## Market context ...` (optional) and `## Method and limits`, after all six modules.

Inside each module, one label per line, each starting the line (a leading `- ` or bold is fine):
- `Question:` the business question this module answers.
- `Decision:` the client decision it informs.
- Evidence bullets.
- `So what:` what it means for the client.
- `Recommendation:` what Fieldnote should do; it must name Fieldnote.

## Evidence rules

- Modules 1, 2, 4 and 5 compare brands: mention all five core brands in each, treated alike.
- No hype, overclaiming or generalising words in headings or So what lines (examples: "clearly",
  "proves", "everyone", "explodes"). Say what was measured.
- Quotes: put one on its own line as `> "exact text" (Brand, attribute)`, copied whole from
  `data/quotes.json` from the cell it names. Add one line `Quote rule: ...` saying how quotes were chosen.
  Do not use any other wording of a quote, and do not use a `>` line for anything else.

## Measure rules

- Every percentage sits in the same line or bullet as its base (`n=217`) and a `95% CI` (or `95% interval`)
  with the interval's two ends.
- Never show a percentage for a base under 30. Say `base too small` and give no percentage.
- Penetration and top-of-mind percentages must say `proxy` in the same line or bullet.
- A shown percentage must come with an interval that metrics.json holds. If it has none (for example
  positioning shares), report counts instead.

## Claims must match their subject

- A line or bullet that names exactly one core brand, or exactly one segment ("Segment 2"), may only
  carry numbers that metrics.json files under that brand or segment. A real number belonging to another
  brand (Zara's share on a Shein line) fails, even though it exists in the data. A segment line may also
  name the brand its segment is named after.
- Keep one subject per line. A line naming two brands, a brand and a different segment, or comparing
  with "the other brands" is not checked, so write each comparison as one bullet per brand.
- A sentence that says the talk or audience skews, is predominantly, or is mostly one demographic or
  platform group needs support in the same sentence: a number from metrics.json, or a source in
  brackets with a year, such as (Pew Research Center, 2025). Source years must be 2025 or 2026, since
  any other number must trace to metrics.json. Without support, drop the claim. A report that makes no
  such claim is fully compliant: this is the one check where having nothing to test earns full credit.

## Number rule (hard)

Every number in report.md must be in `data/metrics.json`: equal to a value there when rounded to the
decimals shown, or equal to 100 times a value (a share stored as 0 to 1). Signs are ignored. Thousands
commas are fine. A number that cannot be traced makes the report invalid (the scorer prints no score and
exits 2), so it is never "low", only void. Do not derive, add up or round numbers yourself.

Exempt, and only these:
- the years 2025 and 2026 (not 2027) and full dates like 2026-07-27;
- the "95%" in "95% CI" or "95% interval";
- the module number in a heading (`## 1.`);
- numbers inside a quote line, which are checked word for word against `data/quotes.json` instead;
- the numbers 30 and 0.05 on a line that says "rule" or "threshold";
- every number in the `Market context` section, which must appear in `brief.md`'s market context.

Spell other numbers out as words ("five brands", "next year") when they are not in metrics.json.

## What is scored

100 points over five criteria; each check has one criterion and an id. A check with nothing to test
scores 0, never full credit, so an empty or missing part is not rewarded (the one exception is U1, above).

| Criterion | Weight | Checks |
|---|---|---|
| Clear research objectives | 20 | O1 Question line per module, O2 Decision line per module |
| Non-leading, unbiased evidence | 25 | E1 no slop words (5), E2 all five core brands in comparative modules (5), E3 quotes attributed to their cell (4), E4 stated quote rule (3), B1 numbers match their brand or segment (5), U1 supported skew claims (3) |
| Correct measure choice | 20 | M1 base and interval on every percentage, M2 no percentage on a base under 30, M3 proxy named |
| Logical flow | 15 | F1 summary first, F2 modules in brief order, F3 method and limits last |
| Decision-ready insight output | 20 | D1 So what per module, D2 Recommendation naming Fieldnote, D3 summary names the target segment |

The score measures rule compliance, not whether the insight is right. It is not validated against
client decisions (see `metric_validation` in the pack).
