# SKILL: Evidence Grounding Anchors (`[evidence]`)

This skill defines the mandatory protocol for grounding key claims, figures, requirements, and findings in any document or report generated or modified within the AI Factory pipeline.

Attaching evidence anchors makes the output provably verifiable against the source context (by both human reviewers and automated audit tools).

---

## EVIDENCE ANCHORS (mandatory)

Each **key claim** must be immediately followed by one short verbatim quote from the source context that supports it. Quoting is an *extractive copy* from the `CONTEXT` in front of you, not recall: find the supporting text first, then make the claim.

### What Requires an Anchor (Key Claims)
- A numeric result, empirical finding, or quantitative metric (returns, metrics, t-/p-values, coefficients, %, performance figures).
- A formula, technical model, algorithm specification, or formal definition.
- A data fact, source specification, sample period, frequency, or environment detail.
- Each core system improvement, requirement, stated hypothesis, or paper-derived assumption.

### What Is NOT Anchored
- Your own analyst judgments, synthesis, future recommendations, or verdicts. These need no quote, but must rest on facts already anchored above.

---

## Format

On its own line, directly beneath the claim:

    [evidence] "exact words copied from CONTEXT"

---

## Rules (prevent fabrication and quote-drift)

1. **Exact Character-for-Character Copy**: Copy character-for-character from `CONTEXT`, *including any OCR artifacts or formatting specifics*. Do **not** correct, normalize, or re-punctuate — the quote must be findable as an exact substring of the source text.
2. **Continuous Single Span**: A quote must be **one or two continuous sentences copied verbatim** — a single unbroken span (~20–50 words, or a single equation).
3. **No Ellipses (`...`) or Splicing**: **Never** stitch fragments together with an ellipsis (`...`) or any other joining characters. If you cannot copy a clean continuous span, choose a shorter one that you can copy exactly. (Spliced quotes cannot be verified and will be rejected.)
4. **Quantity Limit**: **One quote per claim; two maximum.** Do not quote whole paragraphs.
5. **Source Attribution**: The quote must come from the **source context (CONTEXT)**, never from these instructions or prompts.
6. **No Supporting Span -> No Claim**: If no exact supporting span exists, do not make the claim. Omit it or write `Not specified in source.` Never invent or paraphrase a quote to fill the slot.
7. **Quote Quote Escaping**: If the exact span itself contains a double-quote (`"`) character, trim the fragment to exclude it (keeps the single-line format unambiguous).
8. **OCR Uncertainty**: An OCR-damaged equation or text block may be quoted as your best reading with `(OCR-uncertain)` appended after the line.
9. **Tag Discipline**: Write **only** the `[evidence]` tag. **Never** write `[validated]`, `[fixed]`, or `[unsupported]` — tag promotion and re-labeling are performed exclusively by the deterministic validator (`aider-validate`).
10. **Preservation**: Never delete an existing quote anchor when making targeted text edits.

---

## Usage in Pair Programming

To load these rules into your active Aider session:

```text
/read .aider_factory/markdown/skills/evidence_tags.md
```

Then instruct Aider:

> "Draft `output/lit_reviews_temp/response_template.md` following the evidence anchor rules loaded from `evidence_tags.md`."
