# Judge audit

## Calibration summary

| Criterion | n | κ | Precision | Recall | Floors κ≥0.6 / P≥0.8 / R≥0.7 | Decision |
|---|---:|---:|---:|---:|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | pass | advisory only |
| helpful | 100 | 0.375 | 1.000 | 0.300 | fail | do not use as gate |

The tone replay passes the stated floors. Keep it only as a tone advisory metric; these results do not validate it for safety, approval or money decisions. The helpfulness replay fails calibration, especially recall: it misses 21 of 30 human-labeled failures. It must not be a release gate; the judge accepts polished replies whose stated refund differs from the ledger.

Run the reproducible calibration from `src/`:

```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
```

## Disagreement review — tone replay

| Case | Judge | Human | Decision | Rubric adjustment |
|---|---|---|---|---|
| H-008 | PASS | FAIL | Human | Treat `em`/`nha` as too casual in customer support; friendliness alone is insufficient. |
| H-017 | PASS | FAIL | Human | Avoid `bạn ơi` when the customer is identified as older; use the approved respectful address. |
| H-029 | PASS | FAIL | Human | Penalize directive phrasing such as “không cần nhắn thêm”; politeness markers do not cancel it. |
| H-042 | FAIL | PASS | Human | A concise, complete resolution need not contain an apology. |
| H-051 | FAIL | PASS | Human | “Refund” is approved vocabulary for this support team; do not reject it solely as English. |

## Decision

Use the tone judge only for a non-blocking advisory score, and re-calibrate on a fresh, held-out set before using it for release decisions. Do not use the helpfulness judge as a gate: its public disagreements include false PASS verdicts for wrong refund amounts (for example HL-015: reply 55,000đ while ledger is 40,000đ; HL-016: reply 55,000đ while ledger is 35,000đ). Amount correctness must be checked from the ledger with code. The published CSVs are replay data, so this audit does not establish generalization to new traffic.
