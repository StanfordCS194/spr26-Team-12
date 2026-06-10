# Veritas — User Test Plan

**Product:** Veritas Fitness Fact-Checker  
---

**Test videos selected by testers:**

| Video type | Suggested topic |
|---|---|
| Supplement | Creatine — safety, dosing, DHT/hair loss claims |
| Training/nutrition | Running, protein timing, or fat loss advice |

---

## 3. Tester Instructions

> "Go to the Veritas web app. Your task is to fact-check a fitness video you'd actually watch. You can paste a YouTube link directly, or paste text from a transcript we've provided. Work through the flow at your own pace and think out loud when something surprises or confuses you. Plan on about 5–8 minutes, but take as long as you need.
>
> After you've seen the results, feel free to explore the other tabs in the app."

**Do not explain how verdict labels work before they use the app.** Whether those labels are self-explanatory is one of the things being tested.

---

## 4. Observed Tasks & What We're Watching For

### Task 1 — Input a video
| Action | Signal to watch for |
|---|---|
| Tester pastes a YouTube URL | Do they find the input field without help? |
| Tester submits | Any errors? Does the loading state feel clear? |
| Waiting for transcript + claims | Do they stay on the page or assume it broke? |

### Task 2 — Review extracted claims
| Action | Signal to watch for |
|---|---|
| Reads the 8 extracted claims | Do the claims feel like an accurate summary of the video? |
| Edits or removes a claim | Do they understand they can customize before fact-checking? |
| Clicks "Fact-check selected claims" | Do they understand what's about to happen? |

### Task 3 — Read verdict results
| Action | Signal to watch for |
|---|---|
| Reads a "Supported" verdict | Do they trust it? Do they look at the sources? |
| Reads a "Mixed" verdict | Do they interpret it as contested science or as an app failure? Do they feel it's too non-committal? |
| Reads an "Insufficient" verdict | Do they understand what it means for evidence to be insufficient? |
| Sees the credibility score | Does the score feel meaningful, or arbitrary? |

### Task 4 — Explore sources
| Action | Signal to watch for |
|---|---|
| Clicks a source link | Do they verify sources or just trust the verdict? |
| Reads a source snippet | Does the source feel relevant to the specific claim, or too general / off-topic? |
| Notices quality scores (q0.92 vs q0.45) | Do they understand the difference between curated research and web results? |

### Task 5 — Explore Influencers and Products tabs
| Action | Signal to watch for |
|---|---|
| Finds the tabs without prompting | Is tab navigation discoverable? |
| Reads an influencer credibility score | Does the score feel useful or unexplained? |
| Reads a product recommendation | Does it feel trustworthy, or does it feel like advertising? |
| Notices "NSF Certified for Sport" | Do they recognize third-party certification without explanation? |

### Task 6 — Chrome Extension
| Action | Signal to watch for |
|---|---|
| Finds the Veritas icon in the Chrome toolbar | Is the extension discoverable? |
| Triggers a fact-check from within YouTube | Is the flow intuitive without visiting the web app? |
| Reads results in the extension panel | Are results clear in a smaller format? |

---

## 5. Key Hypotheses Being Tested

| # | Hypothesis | Pass condition |
|---|---|---|
| H1 | Users trust verdicts backed by PubMed/ISSN sources | Tester calls sources legitimate unprompted |
| H2 | "Mixed" is understood as contested science, not an app failure | Tester does not interpret Mixed as a bug or error |
| H3 | 20–30 second wait time is tolerable with visible loading feedback | Tester stays on page and completes the flow |
| H4 | Product recommendations don't feel like advertising | Tester notices third-party certification without being prompted |
| H5 | Claim extraction feels accurate to the video content | Tester agrees the 8 claims represent the video fairly |
| H6 | The Chrome Extension is more convenient than the web app for in-context checking | Tester prefers or sees value in the extension over switching tabs |

---

## 6. Post-Session Debrief (2–3 minutes)

Ask these questions verbally after the tester has finished exploring:

1. **"What would you use Veritas for in real life, if anything?"**
2. **"When you saw a 'Mixed' verdict, what did you think that meant? Did any verdicts feel like they weren't giving you a clear enough answer?"**
3. **"Did the sources feel relevant to the specific claim? Were any too broad, too technical, or not really related?"**
4. **"The app gave this video a credibility score of X/100 — does that feel right based on what you saw?"**
5. **"Are there any fitness influencers or YouTube channels you follow that you'd want to see in the Influencers tab?"**
6. **"Are there any supplement brands you use or are curious about that you'd want covered in the Products tab?"**
7. **"Would you use the Chrome Extension or the web app — or both? Why?"**
8. **"What one thing would make you actually use this regularly?"**

---

## 7. Known Weaknesses to Watch Specifically

- **Non-determinism:** The same video checked twice may produce slightly different claims or verdicts. If a tester notices this, log their reaction carefully.
- **Verdict conclusiveness:** "Mixed" verdicts may feel unhelpful to users who want a clear answer. Note any frustration with hedged results.
- **Source relevance:** Some sources may be topically related to a supplement but not directly address the specific claim. Note whether testers call this out.
- **Wait time:** Fact-checking 8 claims takes 20–30 seconds. Is the loading state clear enough, or do testers think the app is broken?
- **Chrome extension:** Only runs when the backend is live locally. External testers cannot use it without the backend deployed.

---