# Corpus Expansion — Sources Studied (and their verdicts)

*Record of non-arXiv source options investigated for the corpus, so we don't re-study them. Updated
2026-07-18. Full research reports were written to scratch (ephemeral); the durable conclusions are here.*

The corpus is arXiv-only today (causal inference / causal ML / econometrics / treatment-effect
estimation). Two expansion routes were researched. **Both are recorded as studied; neither is being
built now**, for the reasons below.

---

## 1. Publisher TDM APIs (Elsevier, Wiley, Springer, …) — STUDIED & DROPPED (no access)

**Why it's attractive:** the owner's core topics (statistics, econometrics, causal inference, ML/DL)
have deep coverage in Elsevier/Wiley/Springer journals that arXiv lacks — e.g. *Journal of
Econometrics* (Elsevier), *Econometrica* (Wiley). Strong content case.

**The only compliant automated route is the publishers' official TDM (Text & Data Mining) APIs** for
institutional subscribers — NOT scraping via login credentials (that violates ToS and can get an
institution's access revoked; we will not build it).

**Ranked (if access existed):**
- **Wiley** — cheapest: TDM API returns full-text **PDF** → drops into the existing MinerU pipeline
  unchanged, real citation anchors for free.
- **Elsevier** — best content, but returns full-text **XML** → needs a render-to-PDF step to satisfy
  the frozen provenance/anchor contract. More work.
- **Springer** — XML like Elsevier, thinner econometrics.

**Compliance boundary:** TDM licenses grant the *subscriber's own non-commercial research use*, NOT
redistribution. A local single-user RAG cache plausibly fits "own use" (V0 is not public/multi-tenant),
but this is not legal advice.

**DECISION 2026-07-18 — DROPPED.** The owner has institutional **read access only**, not a TDM-API
entitlement. A TDM API key requires (a) the institution's subscription to be TDM-enabled and (b)
registering on the publisher's developer portal — neither confirmed. Without it, the compliant path is
unavailable, and login-scraping is off the table. **Revisit only if a real TDM API key is obtained.**

## 2. Big-tech engineering/research blogs & RSS — STUDIED, DEFERRED to V3

**Verified real feeds** (relevance = fraction genuinely causal/experimentation):
- **Booking.com Data Science** — `medium.com/feed/booking-com-data-science` — ~50% relevant (best).
- **Lyft Engineering** — `eng.lyft.com/feed` — ~20–30%.
- **Netflix Tech Blog** — `netflixtechblog.com/feed` — ~10–15%.
- **Airbnb** — `medium.com/feed/airbnb-engineering` — the classic experimentation archive.
- Google/Microsoft/Amazon/Apple — live but ~5% (low-signal firehoses).

**Dead ends among requested companies:** **Uber has no working RSS feed** (retired blog domain);
DoorDash / LinkedIn are bot-blocked → would need scraping, a bigger lift than feed-polling.

**Technical note:** the frozen `Anchor` contract need NOT change — render a cleaned blog post → a PDF
snapshot → the existing MinerU pipeline unchanged. (A native web-anchor would be a foundation change;
avoidable.)

**Verdict: V3-scoped** (the roadmap already places non-arXiv sources at "Proactive Research Radar").
Not worth pulling forward now given the "use V0 first" posture.

---

## Common prerequisites either route would need first (worth doing independently)

Both routes surfaced the same two "declared but not wired" gaps — both cheap, both useful for arXiv
breadth on their own:

- **OG-36 — `relevance_filter` is dead code.** `Config.relevance_filter` = `"off"|"embedding"` and a
  `relevance_score` is computed per paper, but nothing gates ingestion on it. Any unfiltered source
  (blog feeds are 5–15% on-topic) needs this. **The one near-term win either route pointed at.**
- **OG-38 — `Config.sources` is inert.** `config.yaml` declares `sources: ["arxiv"]` but
  `app/assembly.py` hardcodes `Harvester(ArxivSource(), …)`. Adding any 2nd source needs a
  source-registry wiring in the composition root, not just a config edit.

## Bottom line
Neither expansion is being built now. Publishers = blocked on TDM access (revisit if a key is
obtained). Blogs = deferred to V3. If corpus breadth becomes a priority, the first concrete step is
**OG-36 (the relevance gate)** — useful regardless of source.
