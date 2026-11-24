# Human review — translation quality (template)

Pair this review with one run of the automatic evaluation harness
(`training/evaluation/evaluate_translation.py`). Automatic metrics
(SacreBLEU, chrF++) measure surface overlap only; they are **not**
proof of exact meaning. This template records the linguistic judgement
that the metrics cannot make.

## Run identification (fill in from the harness report)

| Field | Value |
|---|---|
| Language profile | |
| Engine under review | |
| Model version / artifact sha256 | |
| Test split + pair count | |
| Harness report file | |
| Reviewer | |
| Date | |

## Rubric — score each sampled verse 1 (poor) to 5 (excellent)

- **Semantic accuracy** — does the English carry the source's meaning?
- **Historical vocabulary** — are terms rendered with period-appropriate
  senses rather than modern or anachronistic ones?
- **Grammatical correctness** — is the English grammatical, and does it
  preserve the source's grammatical relationships (subject/object,
  construct chains, verbal aspect) as far as English allows?
- **Faithfulness to the source** — nothing omitted, nothing added;
  names and distinctions preserved.
- **Unjustified interpretation** — 5 means no interpretive additions
  beyond the source; lower scores mark places where the output decides
  an ambiguity the source leaves open, without flagging it.

## Sampled verses (copy rows from the harness failure examples plus a
## random sample; leave scores blank until a reviewer fills them)

| Reference | Semantic accuracy | Historical vocabulary | Grammatical correctness | Faithfulness | Unjustified interpretation | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |
| | | | | | | |

## Summary (reviewer fills in after scoring)

- Overall judgement:
- Systematic errors observed:
- Verses that must be quoted in the evaluation report as known failures:
- Recommendation (keep / retrain / reject this engine for this profile):
