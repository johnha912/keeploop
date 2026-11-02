# Social-listening data for the Fieldnote Apparel example

Public social data about fast-fashion brands, crawled and analysed by `../listen.py`. Every number the report may cite is in `metrics.json`; this file explains where it comes from and what it cannot say. Nothing here is invented; where a source failed, the metric says so.

| File | Content |
|---|---|
| `metrics.json` | All numbers, with base sizes, 95% CIs and formula names |
| `quotes.json` | Up to 3 short quotes per brand x attribute cell, chosen by rule |
| `validation_labels.json` | Hand labels (sentence hash -> pos/neu/neg) for the VADER check |
| `../listen.py` | `collect`, `analyze`, `selfcheck` (assert-based, runs before every command) |

Raw data is outside the repo, in the folder named by the `KLM_SANDBOX` environment variable (default: `keeploop-mr-social` in the system temp folder). Authors are stored only as a salted hash (salt not committed). No usernames, permalinks or URLs are in any committed file.

## Collection

- **Window:** 2025-11-01 to 2026-10-31 (UTC), months 2025-11 .. 2026-10.
- **Collection timestamps (UTC):** started 2026-11-02T05:08:41; Reddit crawl stopped by the operator at its time limit; last collection step finished 2026-11-02T07:24:21; analysis run 2026-11-02T07:26:26 (`meta.analysis_utc`). Wikipedia pulled 2026-11-02T05:08Z; iTunes lookup 2026-11-02T07:20Z.
- **Reddit** via the Arctic Shift archive API (`/api/posts/search`, `/api/comments/search`), about 1 request per second, descriptive User-Agent, back-off on errors. Reddit's own JSON is blocked (403).
- **Wikipedia** monthly pageviews (en, all-access, user) for 11 brand articles. Complete (12 months each).
- **App Store:** app IDs from the iTunes Search API (US): Aritzia 6742152082, ZARA 547951480, H&M 834465911, SHEIN 878577184, UNIQLO 1284609872. Store-level rating aggregates per storefront (US, CA) come from the iTunes lookup API. **Review text failed:** the customer-review RSS returned empty feeds for every app and storefront in the final runs (an earlier run returned 200 reviews, which were lost when a later run overwrote the file). So there is no App Store review sample, rating distribution or review sentiment. Only the all-time store averages and counts are reported.

### What was actually crawled (honest coverage)

The crawl was time-boxed (the server often answered "Timeout. Maybe slow down a bit" and some tasks took minutes). Order of work and result:

| Stage | Done | Caps |
|---|---|---|
| Brand subreddits (Aritzia, shein, uniqlo, BrandyMelville, OldNavy, lululemon), full year by month | 6 of 6 | 125 posts + 250 comments per month each |
| Recommendation-thread discovery (title search "recommend" in the 10 general subs; "where" and "brands" for femalefashionadvice and malefashionadvice only) | 14 of 30 planned tasks | 100 titles per half-year per task |
| Replies to selected threads (top-level comments) | 60 threads (48 malefashionadvice, 12 femalefashionadvice) | 60 threads; 300 comments per thread |
| Keyword search for core brands in general subs | femalefashionadvice for Aritzia, Zara, H&M, Shein, Uniqlo; malefashionadvice for Aritzia only | 100 posts + 200 comments per half-year per sub and term |
| Keyword search for wider brands (Forever 21, Lululemon, Old Navy, ...) | none | |

Consequences:
- Cross-brand comparisons use general subs only (per the comparability rule). That sample is essentially **femalefashionadvice keyword search + recommendation-thread replies**. Keyword-sourced items from malefashionadvice are dropped in `analyze` so that Aritzia is not favoured. Other general subs (OUTFITS, PetiteFashionAdvice, femalefashion, FrugalFemaleFashion, PlusSizeFashion, findfashion, frugalmalefashion, CanadaFashion) contribute only a few posts from thread discovery.
- 10 time windows (of 14 days or less) were given up after retries (femalefashion 4, PlusSizeFashion 4, malefashionadvice 2); Arctic Shift coverage is not guaranteed.
- Wider-brand numbers come only from incidental mentions, and most fall under n = 30.
- No Reddit subreddit with data was found for Zara, H&M or a Canadian fashion community (r/Zara and r/HM return nothing; r/CanadaFashion has about 3 posts per month). Brand subreddits therefore exist for Aritzia, Shein, Uniqlo, Brandy Melville, Old Navy and Lululemon, but not for Zara or H&M.

## Comparability rule

Brand subreddits are fan communities. Every cross-brand module (top-of-mind, penetration, positioning, perception, segmentation, trend, quotes) uses **general-subreddit rows only**. Brand-subreddit rows appear only in `within_brand_context_brand_subreddits` in `metrics.json`, labelled as such, and are never used to fill a cell.

## Brand dictionary and false positives

Core: Aritzia, Zara, H&M, Shein, Uniqlo. Wider: Forever 21, Garage, Abercrombie, Lululemon, Old Navy, Gap, Mango, Urban Outfitters, Brandy Melville, Princess Polly, Temu, Dynamite, Simons, Edikted, Hollister, American Eagle, Free People, Everlane, COS, Madewell, Reformation. Exact regexes are in `metrics.json` under `dictionaries.brands`.

Matching modes, applied per sentence with word boundaries:
- `ci`: case-insensitive (Aritzia, Zara, Shein, Uniqlo, Temu, Lululemon, Old Navy, ...).
- `cap`: exact case ("H&M", "H and M", "A&F").
- `ctx`: for ambiguous words (Gap, Garage, Mango, COS, Simons, Dynamite, Reformation, HM, UO, AE, Brandy). Requires exact capitalisation, a fashion word in the same sentence (jeans, dress, bought, store, size, ...), and a previous word that is not a determiner (my, a, an, our, your, his, her, this, that; plus "the"/"in" for Garage). Lowercase "gap", "garage", "mango", "cos" never match. Self-check cases cover "a gap in my teeth", "my Garage", "mango smoothie", "cos it was cheap", "Bought jeans from Gap".
- Limits: "Gap"/"Mango" at a sentence start with a fashion word may still be missed or over-matched; misspellings are not caught.

## Methods and formulas

Items are posts (title + body) and comments; quoted lines, links and `u/`/`r/` handles are stripped before analysis. Sentences are split on `.!?` and line breaks. A **mention row** is one brand in one sentence. Sentences naming 2 or more brands are excluded from sentiment and attributes (a comparison cannot be assigned to one brand) but kept for mentions, penetration and segmentation.

Percentages are reported only when the base n >= 30; otherwise `"status": "base too small"`. Wilson 95% interval: centre = (p + z²/2n) / (1 + z²/n), half-width = z sqrt(p(1-p)/n + z²/4n²) / (1 + z²/n), z = 1.96.

1. **Top-of-mind (unaided awareness proxy).** Base: top-level replies (one per author per thread) in selected recommendation threads that name at least one brand. First mention = the brand with the earliest position in the reply; total mention = share of those replies naming the brand (multiple response). Caveat: recommenders answer for the asker, thread selection is by reply count, and 48 of the 60 threads are menswear (`sample_composition_warning`), so the result leans to menswear-friendly brands. Not an awareness measure for Gen Z or Millennial women.
2. **Penetration proxy.** Distinct authors with at least one ownership or purchase phrase in a sentence naming the brand ("I bought", "ordered from", "my ... from", "haul", ...) divided by distinct authors with any brand mention. A proxy, not penetration: the base is only authors who discussed brands, and phrase matching misses and over-catches. Values are small by construction.
3. **Profiling.** Self-reported age ("(24F)", "I'm 24", "24 y/o", "born in 1998"; accepted range 14-65), gender ("(24F)", "as a guy", "I'm a woman"), country (first-person cues such as "I live in Toronto", "here in Canada", "as an American"). First report by an author wins. Gen Z = 14-29, Millennial = 30-45, Older = 46+ (in 2026). Coverage is reported per group; it is very low (about 2% of brand-mentioning authors give an age), so generation results rest on tiny bases and are mostly "base too small".
4. **Positioning.** Brand x attribute matrix of single-brand sentences that hit an attribute keyword (a sentence can hit several). Attribute dictionaries are in `dictionaries.attributes` (price/value, quality/durability, fit/sizing, style/trend, sustainability/ethics, shipping/returns, customer service, store experience). Brands enter the matrix with at least 30 attribute hits. Correspondence analysis: P = N/n, S = (P - r cᵀ)/sqrt(r cᵀ), SVD of S, axis inertia = D², total inertia = chi²/n. Chi-square of independence with df = (R-1)(C-1); adjusted standardised residual = (O-E)/sqrt(E(1 - row/n)(1 - col/n)), flagged at |z| > 1.96 and separately at a Bonferroni threshold. Hits are not independent (one author can contribute several), so p-values are indicative.
5. **Perception.** VADER (Hutto and Gilbert, 2014, ICWSM) compound score per single-brand sentence; positive >= 0.05, negative <= -0.05, else neutral. Net sentiment = (pos - neg) / (pos + neg + neu), with Wilson intervals on the positive and negative shares, per brand and per brand x attribute.
6. **Segmentation.** Authors with at least 2 brand-mention sentences. Vector = share of the author's mention sentences per brand (brands with at least 50 mentions, plus "other") and share touching each attribute. k-means (scikit-learn, 10 starts, seed 0), k = 2..6 by silhouette. Segment names are mechanical: highest brand lift (at least 10% share) plus highest attribute lift. The silhouette is low (see `metrics.json`), so these are talk patterns, not validated shopper types.
7. **Trend.** Wikipedia monthly views per brand next to monthly counts of brand-mentioning items. Mention counts are bounded by collection caps and by which searches ran; use share of voice, not growth. Pearson r over 12 months is descriptive only.

## Quotes

`quotes.json`: for each brand x attribute cell with at least 10 single-brand sentences, the up-to-3 sentences (5 to 25 words) closest to the cell's median VADER compound, one per author, ties broken by the sha1 of the text. Sentences containing an age, gender or country self-report, an `@`, or a phone-like number are skipped. No usernames or permalinks. Quotes are verbatim, including typos.

## VADER validation (hand-labelled)

50 sentences were drawn deterministically (sha1 order) from the single-brand sentences of at least 4 words. One labeller (the engineer agent, not a domain expert) labelled each pos, neu or neg toward the brand, blind to the VADER output; labels are in `validation_labels.json`.

Result: agreement 64% (32 of 50; Wilson 95% CI 50.1% to 75.9%), Cohen's kappa 0.45 (moderate). VADER is weakest on negatives: of 14 human-negative sentences it labelled 4 negative, 5 neutral and 5 positive (sarcasm, "cheap/affordable" words, and criticism phrased politely). It also tags 5 of 20 neutral sentences as positive. Net sentiment from VADER therefore likely understates negativity on this data. Treat sentiment gaps between brands smaller than the CIs, and all brand x attribute sentiment, with caution. n = 50 and one rater: no inter-rater reliability.

## Limitations

- Social media is not a representative sample of North American Gen Z and Millennial shoppers; Reddit is self-selected, and who posts is barely measured here (gender is self-reported by 13 brand-mentioning authors, 11 of them female; age by 33). An earlier version of this line said Reddit "skews young, male and US" with no source; the audit of cycle 2 found it unsupported, so it was removed (see ../run/LOG.md). Canada cannot be separated (country is self-reported by under 1% of authors).
- The general-sub sample is mainly one subreddit (femalefashionadvice) plus recommendation threads, collected under a time limit. Brands were found by keyword search, so mention counts are not an unaided measure.
- Top-of-mind, penetration and positioning are proxies (see method notes). Do not read them as survey results.
- Arctic Shift is an archive: coverage gaps, delayed or missing content and timeouts occur; 10 windows were abandoned.
- App Store: the review RSS only returns recent reviews (at most 10 pages of 50 per storefront) and returned nothing in the final runs. Only store-level ratings are available.
- Age, gender and country coverage is under 3%; generation mix and country splits are mostly "base too small".
- VADER is a general-English lexicon; accuracy on this text is 64% against one rater.
- Multi-brand sentences are excluded from sentiment and attributes, which removes explicit comparisons.
- Brand subreddits (no Zara or H&M sub) are excluded from comparisons; they appear only as within-brand context.
- This file and `metrics.json` do not interpret the numbers; the analyst and content steps do.

## Supplementary analysis

Added after the audited report, from the same sandbox data (no new crawl). All of it is under the new top-level key `supplementary` in `metrics.json`; every other key is unchanged. `listen.py analyze` asserts that the existing content equals the new run before it writes (and writes the old content back byte-for-byte; the run timestamp in `meta` is kept), and refuses to write otherwise (`--rebuild` skips the check after a re-crawl). General subreddits only; Wilson 95% intervals; "base too small" when n < 30. The full regexes are in `metrics.json` (`supplementary.funnel`, `supplementary.brand_image.dictionary`); the exact test fixtures are in `selfcheck`.

### S1. Brand funnel (social-listening proxy, not a survey funnel)

Base: distinct authors mentioning the brand (equals `sample.authors_per_brand`). Stages are nested sets of authors:
- Aware: mentioned the brand.
- Considering: any sentence naming the brand with an intent phrase: "thinking of/about buying/getting/ordering/trying", "should I get/buy/order/try", "worth it", "worth the/buying", "considering", "on my list/wishlist", "want to buy/try/get", "planning to/on buy/get/order", "debating if/whether/getting/buying"; plus everyone in the later stages.
- Bought: the existing ownership/purchase phrases ("I bought/ordered/purchased/picked up/got/own/owned/returned", "my ... from", "haul", "ordered/bought ... from"), plus advocates.
- Advocate: a Bought author by an ownership phrase who also used a recommend/repeat phrase in a sentence naming the brand: "highly recommend", "would recommend", "buy(ing) again", "bought again", "always buy", "keep buying", "repurchase", "go-to", "obsessed with my". Someone who says "go-to" but never reports owning is not an advocate.
- Formulas: share of Aware = stage k / Aware k; conversion = stage k / previous stage k. Conversion is shown only if the previous stage has n >= 30. Multi-brand sentences credit every brand they name. Phrases are matched per sentence, so an advocate phrase in a different sentence from the ownership phrase still counts at author level.
- Limits: the stages are keyword proxies of talk in public threads. Authors who bought but never said so are missed, and "worth it" may be about something else in the sentence. Conversion rates and stage sizes are not survey funnel rates and must not be quoted as such.

### S2. Two-axis positioning map

For each brand in the positioning matrix (at least 30 attribute hits): x = price/value share of the brand's attribute hits, y = style/trend share (each with k, n and Wilson CI), bubble = the brand's mention sentences (general subs), colour = net sentiment from VADER (`net_sentiment_block` has the base and CIs on the positive and negative shares). Shares are over attribute hits (a sentence can hit several attributes), the same unit as the positioning matrix.

### S3. Brand image analysis

Unit: single-brand sentences carrying at least one image keyword (a sentence can carry several images). Brands with at least 30 image-coded sentences enter the grid; the rest are listed in `brands_base_too_small`. Keywords are lowercase stems, case-insensitive, word-bounded where it matters (so "unethical" does not match "ethical", "uncomfortable" does not match "comfortable"), and identical for every brand. Valence is used only to label strengths and weaknesses.

| Image | Valence | Keywords |
|---|---|---|
| premium/aspirational | + | luxur-, premium, high-end, aspirational, investment piece, upscale, designer, splurge, fancy, looks expensive, quiet luxury, polished, sophisticated, elevated |
| basic/everyday | neutral | basic(s), everyday, staple(s), workhorse, plain, simple, neutral(s), capsule, essential(s) |
| trendy/fashion-forward | + | trend/trendy/trending, fashion-forward, on-trend, runway, latest styles/looks/drops, new collection/drop, viral, tiktok, hype, cutting-edge |
| dated/frumpy | - | dated, frumpy, boring, outdated, old-fashioned, grandma, mumsy, stuffy, drab, matronly, bland, old lady |
| cheap/disposable | - | cheap(ly), cheaply made, disposable, throwaway, one-wear, ultra-fast fashion, falls/fell apart, flimsy, junk, trash, low quality, poorly made, landfill |
| comfortable | + | comfortable, comfy, cozy/cosy, soft(ness), stretchy, breathable, snug |
| uncomfortable | - | uncomfortable, itchy, scratchy, stiff, restrictive, rough fabric, clammy, suffocat- |
| ethical/responsible | + | ethical(ly), sustainab-, responsible, fair trade, fair wage(s), B-corp, transparen-, recycled, organic, eco-friendly, traceab-, living wage |
| unethical/exploitative | - | unethical, exploit-, sweatshop, child/forced labo(u)r, slave-, greenwash, union-busting, steals/stole designs, plagiar-, rip-off, overproduc- |
| reliable/consistent | + | reliab-, consistent(ly), dependable, never disappoints/fails/let me down, trustworthy, holds up, true to size, TTS, every time |
| inconsistent/hit-or-miss | - | inconsistent, hit or miss, hit and miss, unreliable, quality dropped/declined/gone down, gone downhill, varies, vary, lottery, gamble, not what it used to be |
| Canadian/local | neutral | Canada/Canadian, made in Canada, Vancouver, Toronto, Montreal, homegrown, local brand/made/business, small business |
| fun/young | + | fun, playful, youthful, young, teen-, Gen Z, college, quirky, bubbly, colo(u)rful, vibrant, girly, y2k |

I added "uncomfortable" and "dated/frumpy" to the suggested set so that every favourable image has an unfavourable pole (pairs: premium-cheap, trendy-dated, comfortable-uncomfortable, ethical-unethical, reliable-inconsistent; the selfcheck asserts this). "Canadian/local" also fires on shipping-to-Canada sentences and "Toronto" store mentions, so it is noisy.

Outputs in `supplementary.brand_image`:
- (a) `association_grid`: brand x image share = sentences with the image / the brand's image-coded sentences, with k, n and Wilson CI; `set_average_share_pct` is the pooled share over all brands in the grid.
- (b) Deviation vs the competitive-set average: adjusted standardised residual per cell on the brand x image hit matrix, z = (O - E) / sqrt(E (1 - row/n)(1 - col/n)), flagged only above the Bonferroni z over all cells (`bonferroni_z`). Reading rule: over-index on a favourable image or under-index on an unfavourable one = strength; the reverse = weakness; neutral images = distinctive. Each flagged cell carries its net sentiment and a caution: keyword association is not endorsement (for example a brand can be tagged "ethical" because people argue about its ethics).
- (c) `net_sentiment_by_cell`: (pos - neg) / (pos + neg + neu) per brand x image where n >= 30, else "base too small".
- (d) `priority_quadrant` for each core brand, only for cells with n >= 30. Strong = the brand's share of the image is at least the pooled set-average share (index >= 1.0), weak otherwise. Positive = net sentiment within the cell > 0. Strong + positive = defend; strong + negative = fix; weak + positive = hidden asset; weak + negative = low priority. A core brand with fewer than 30 image-coded sentences is marked "base too small" (Aritzia).
- (e) `chi_square_independence`: chi-square on the same brand x image hit matrix with df = (R-1)(C-1); `cells_expected_lt_5` counts weak cells, and one author can contribute several sentences, so the p-value is indicative only.

### What this cannot do without a survey

- No driver analysis (which images drive preference or purchase): there is no outcome variable, and 4 to 5 brands cannot support a regression.
- No aided image battery: respondents never rated each brand on a fixed list, so absence of mention is not absence of image, and loud topics are over-represented.
- No multidimensional scaling on brand-similarity ratings: there are no respondent similarity judgements, only keyword co-occurrence from a small sample.
- Image shares are shares of talk, not shares of consumers, and the thin general-sub sample (see Collection) leaves most brand x image cells under n = 30.
