# Veritas — Verdict Accuracy Verification Log

Manual accuracy evaluations of Veritas claim verdicts across real and synthetic fitness/health content.

**Methodology:** Each claim extracted by Veritas was compared against current scientific consensus. A verdict is marked accurate if the direction (supports / mixed / contradicts / insufficient) correctly reflects the state of the evidence, even if the exact confidence level differs.

---

## Summary

| Run | Video | Creator | Claims | Correct | Accuracy |
|-----|-------|---------|--------|---------|----------|
| 1 | How to Use Creatine *(before pipeline fixes)* | Jeff Nippard | 8 | 6 | 75% |
| 2 | How to Use Creatine *(after pipeline fixes)* | Jeff Nippard | 8 | 8 | 100% |
| 3 | How to Get Abs | Jeff Nippard | 8 | 8 | 100% |
| 4 | Should You Get 8 Hours of Sleep? | Huberman & Lex Fridman | 4 | 3 | 75% |
| 5 | Fat Burners — What Are They? | E-Fitness | 8 | 8 | 100% |
| 6 | 10 Years of Brutally Honest Fat Loss Advice | Coach Viva | 8 | 6 | 75% |
| 7 | Synthetic transcript *(known false claims)* | N/A | 7 | 6 | 86% |

**Overall: 45 / 51 correct — 88.2% accuracy**

---

## Run 1 — How to Use Creatine *(before fixes)*
**Creator:** Jeff Nippard · **Credibility score:** not recorded · **Date:** 2026-05-12

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| Creatine increases strength by 5–15% | Mixed | ✗ | Well replicated — should be Supported |
| 20–30% of people are creatine non-responders | Insufficient | ✗ | Stat exists but Tavily didn't surface it |
| Creatine is safe for kidneys in healthy adults | Supported | ✓ | |
| Loading phase saturates muscles faster | Supported | ✓ | |
| Creatine causes water retention | Supported | ✓ | |
| DHT increase ~40% linked to creatine | Mixed | ✓ | Contested, not replicated |
| Creatine improves high-intensity exercise | Supported | ✓ | |
| Monohydrate is the most researched form | Supported | ✓ | |

**6 / 8 correct — 75%**
**Root cause of misses:** No Tavily key configured; search returned no sources for two claims, forcing insufficient/mixed verdicts.

---

## Run 2 — How to Use Creatine *(after fixes)*
**Creator:** Jeff Nippard · **Credibility score:** 100/100 · **Date:** 2026-05-12

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| Creatine increases strength by 5–15% | Supported | ✓ | |
| 20–30% are non-responders | Partly supported | ✓ | Stat found; slight uncertainty on exact % |
| Creatine is safe for kidneys | Supported | ✓ | |
| Loading phase saturates faster | Supported | ✓ | |
| Creatine causes water retention | Supported | ✓ | |
| DHT increase ~40% | Mixed | ✓ | Correctly flagged as contested |
| "700 human studies" on creatine | Partly supported | ✓ | Source found ~685 — slight overstatement caught |
| Monohydrate most researched form | Supported | ✓ | |

**8 / 8 correct — 100%**
**Pipeline fixes that made the difference:** Tavily + PubMed in parallel; OpenAI as primary LLM; adjacent verdict grouping fix.

---

## Run 3 — How to Get Abs
**Creator:** Jeff Nippard · **Credibility score:** 56/100 · **Date:** 2026-05-19

*Note: Only the intro section was analyzed due to the 12,000 character transcript limit. The actual science and supplement claims deeper in the video were not reached.*

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| Visible abs at 20% body fat | Partly supported | ✓ | Correct for women; too high for men (~15%) |
| Six-pack visible at 10% body fat | Mixed | ✓ | Sources say 10–12% — reasonable range |
| Natural bodybuilder achieved 6.2% via DEXA | Insufficient | ✓ | Unverifiable specific anecdote |
| Men: visible abs 10–20% body fat | Mixed | ✓ | Sources say 10–15%; 20% is too generous |
| Women: visible abs 18–28% body fat | Partly supported | ✓ | Sources say 18–22%; 28% is high |
| Structured diet can "mathematically guarantee" fat loss | Mixed | ✓ | Correct — individual variation prevents guarantees |
| Science-based methods work regardless of genetics | Mixed | ✓ | Correct — genetics affect but don't block results |
| Ab training effective for muscle definition | Supported | ✓ | Well established |

**8 / 8 correct — 100%**

---

## Run 4 — Should You Get 8 Hours of Sleep?
**Creator:** Andrew Huberman & Lex Fridman · **Credibility score:** 5/100 · **Date:** 2026-05-19

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| No evidence 8h sleep is better than 6h | Needs review | ✓ | Misleading claim; mixed sources is fair |
| Cognitive performance peaks at end of 90-min ultradian cycle | Contradicted | ✓ | PubMed directly found no evidence for this |
| Waking after 6h (end of cycle) better than 7h (mid-cycle) | No verdict | ✓ | Evidence genuinely mixed |
| Apps track body movement to optimize wake time | Needs review | ✗ | Should be Supported — Sleep Cycle, Fitbit clearly exist |

**3 / 4 correct — 75%**

---

## Run 5 — Fat Burners — What Are They?
**Creator:** E-Fitness · **Credibility score:** 72/100 · **Date:** 2026-05-19

*Note: Creator was accurate and balanced about fat burners; high Veritas score correctly reflects honest content.*

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| Fat burners increase metabolic rate | Mixed | ✓ | Weak/inconsistent evidence |
| Fat burners reduce appetite | Mixed | ✓ | Ingredient dependent |
| Fat burners increase energy levels | Partly supported | ✓ | Caffeine component does this |
| Fat burners enhance fat oxidation | Needs review | ✓ | Evidence genuinely mixed |
| Caloric deficit needed for fat burners to work | Supported | ✓ | Well established |
| Exercise required for fat burners to be effective | Mixed | ✓ | Debated in literature |
| Minimal benefit without diet and exercise | Supported | ✓ | Well established |
| Fat burners lack sufficient empirical evidence | Supported | ✓ | Correct |

**8 / 8 correct — 100%**

---

## Run 6 — 10 Years of Brutally Honest Fat Loss Advice in 4 Minutes
**Creator:** Coach Viva · **Credibility score:** 50/100 · **Date:** 2026-05-19

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| Can lose fat without exercise eating 85% the same until 15–25% body fat | Insufficient | ✓ | Specific percentages unsubstantiated |
| Drastic changes lead to failure within weeks | Supported | ✓ | Well established |
| Cutting carbs/skipping meals is unsustainable | Mixed | ✓ | Varies by individual |
| Weight loss achievable regardless of self-control | Needs review | ✗ | Should be Contradicted — self-control strongly linked to success |
| Stress and exhaustion hurt weight loss | Mixed | ✗ | Verdict label reasonable but cited IF sources for a stress claim |
| You don't owe anyone an explanation for health choices | Insufficient | ✓ | Not a scientific claim |
| Prioritizing time management essential for weight loss | Needs review | ✓ | Some evidence supports |
| Setting social boundaries helps weight loss | Supported | ✓ | Social influence well documented |

**6 / 8 correct — 75%**

---

## Run 7 — Synthetic Transcript (Known False Claims)
**Creator:** N/A · **Credibility score:** 7/100 · **Date:** 2026-05-19

*Synthetic transcript written to contain well-known debunked fitness myths, used to verify Veritas correctly assigns low credibility to misinformation.*

| Claim | Veritas Verdict | Accurate? | Notes |
|-------|----------------|-----------|-------|
| Muscle soreness caused by lactic acid | Contradicted | ✓ | Correct — cleared within 1h, DOMS is micro-trauma |
| Eating every 2–3 hours boosts metabolism | Mixed | ✓ | Slightly lenient but defensible |
| Ab exercises burn belly fat (spot reduction) | Contradicted | ✓ | RCT directly debunks this |
| You only use 10% of your brain | Contradicted | ✓ | Thoroughly debunked |
| Body absorbs max 30g protein per meal | Insufficient | ✗ | Should be Contradicted — ISSN position stand directly refutes it |
| Cardio is best for building muscle | Contradicted | ✓ | Correct |
| Lifting over 50 damages joints | Contradicted | ✓ | Evidence shows opposite |

**6 / 7 correct — 86%**
**Key result:** Veritas correctly scored a misinformation-heavy transcript at 7/100, demonstrating the low-credibility detection works as intended.
