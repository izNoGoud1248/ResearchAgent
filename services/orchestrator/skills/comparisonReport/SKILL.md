---
name: comparisonReport
title: Comparison report
description: For questions that compare methods or models, or ask which is best, fastest or cheapest.
---

Write a comparison report of at most 700 words.

- Open with a `## Verdict`: which option wins for which need, in 2 to 4 sentences. Say plainly when the evidence does not pick a winner.
- The verdict must agree with the table. Never name a winner on a measure where that option's value is missing, not reported or only described in words.
- Follow with `## At a glance`: one Markdown table, one row per method or model, and columns for what was asked (for example approach, reported result, benchmark, cost or requirements). Every filled cell that states a fact carries its citation, such as `2.8x [arXiv:2302.01318v2]`. Write `not reported` for gaps; never guess a value.
- Only compare numbers measured on the same benchmark and setting. When they differ, keep them in separate columns or say so in a note under the table.
- Then one short `###` section per option: how it works, where it is strong, where it is weak.
- Add `## When to use which`: 2 to 4 bullets mapping situations to options.
- End with `## Limitations`, then `## References`.

## Checklist

- Has a verdict that answers the comparison and agrees with the table.
- Has a table with one row per option compared.
- Every fact in the table is cited; gaps say "not reported".
- Numbers from different benchmarks are not compared as if equal.
- Has a "When to use which" section.
