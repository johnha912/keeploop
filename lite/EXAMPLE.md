# keeploop-lite: an illustrative example

> **Illustrative example.** Mai is a fictional user, and this transcript
> was written by hand to show the shape of a cycle in fast mode. It is not
> a recording of a real chat. The scores are Mai's scorecard scores, not
> sales results. Some replies are shortened.

Mai sells homemade banana bread in her neighbourhood Facebook group. She
pasted `KEEPLOOP-LITE.md` into a new chat.

---

**AI:** Hi! Please paste the thing you want to improve, exactly as it is
now, and tell me who it is for.

**Mai:** My Facebook post for the neighbourhood group: "Banana bread for
sale. DM me."

**AI:** Thanks. What would a better version do for you? What bothers you
about it now?

**Mai:** Nobody notices it, people ask me the price every time, and I want
more orders. Keep it under 30 words, people scroll fast.

**AI:** "More orders" can't be seen from the text, so I suggest scoring
what makes ordering easy instead. Your word limit becomes a gate.

```
1. Hook: the first line makes a neighbour stop scrolling
2. Clear offer: price, size, pickup day and how to order are all stated
3. Trust: a concrete, true detail shows it is homemade and fresh
Gate: under 30 words
```

Team: Local marketer (propose), Copywriter (make), Busy neighbour
scrolling the group (check).

Is this the scorecard we keep for every cycle, and is the team OK?
(yes / change it)

**Mai:** yes

**AI:** **Busy neighbour, fresh pass.**

| Criterion | Score | Evidence (quoted) |
|---|---|---|
| Hook | 2/10 | "Banana bread for sale." is a plain label |
| Clear offer | 2/10 | "DM me." says how to order; no price, size or day |
| Trust | 0/10 | nothing shows it is homemade or fresh |
| Gate: under 30 words | PASS | 6 words |
| Total | 4/30 | |

*(The AI prints the full ledger here. The last one is shown in full at
the end.)*

The stronger option is to say **audit this**, so a new chat scores it
without knowing what we hope for.

Say **next cycle**, or **run 3 cycles** to run several in one reply.

---

**Mai:** run 3 cycles

**AI:**

```
CARD 1 (Local marketer): Add one line with price, size and pickup day.
Aims at: Clear offer, now 2/10, because people keep asking the price. Could hurt: nothing expected.
Need from you: the real price, size and pickup time
```

Paused at cycle 1: I need these facts first. The batch goes on after your
answer.

**Mai:** $8 a loaf, pickup Saturday 9 to 12.

**AI:** **Copywriter.**

> Banana bread for sale. $8 a loaf, pickup Saturday 9–12. DM me to order.

**Busy neighbour, fresh pass.**

| Criterion | Score | Evidence (quoted) |
|---|---|---|
| Hook | 2/10 | "Banana bread for sale." is unchanged |
| Clear offer | 8/10 | "$8 a loaf, pickup Saturday 9–12"; size is only "a loaf" |
| Trust | 0/10 | nothing shows it is homemade or fresh |
| Gate: under 30 words | PASS | 14 words |
| Total | 10/30 | |

**KEEP.** The gate passes and 10 beats the best so far (4).

```
| 1 | Added price, size and pickup line | 10/30 | KEEP |
Best so far: cycle 1, 10/30 (Hook 2, Clear offer 8, Trust 0)
No new lesson.
```

```
CARD 2 (Local marketer): Open with a short, true line about where the recipe comes from.
Aims at: Trust, now 0/10, because nothing shows it is homemade. Could hurt: the 30-word gate, if the line is long.
Need from you: a true detail about the recipe or the baking
```

Paused at cycle 2: I need a true detail. I won't make one up.

**Mai:** It's my grandma's recipe, I've made it every week for 10 years
and my kids fight over the last slice.

**AI:** **Copywriter.**

> Baked with my grandma's recipe. I've made it every week for 10 years,
> and my kids still fight over the last slice! Banana bread for sale. $8 a
> loaf, pickup Saturday 9–12. DM me to order.

**Busy neighbour, fresh pass.**

| Criterion | Score | Evidence (quoted) |
|---|---|---|
| Hook | 5/10 | "Baked with my grandma's recipe." opens on something personal |
| Clear offer | 8/10 | "$8 a loaf, pickup Saturday 9–12" |
| Trust | 7/10 | "my grandma's recipe", "every week for 10 years" |
| Gate: under 30 words | **FAIL** | 36 words |
| Total | 20/30 | |

**DISCARD.** The total is higher, but the gate fails, and a version that
fails a gate is never kept. Discarded. We go back to the best version
(cycle 1).

Batch stopped after cycle 2: a gate failed, so you may want a say before
cycle 3. The batch ended, so here is the full ledger:

```
KEEPLOOP-LITE LEDGER
Artifact: Facebook post selling homemade banana bread, neighbourhood group
Scorecard (locked since cycle 0, max 30):
1. Hook: the first line makes a neighbour stop scrolling
2. Clear offer: price, size, pickup day and how to order are all stated
3. Trust: a concrete, true detail shows it is homemade and fresh
Gates (pass/fail): under 30 words
Team: Local marketer (propose), Copywriter (make), Busy neighbour (check)
Best so far: cycle 1, 10/30 (Hook 2, Clear offer 8, Trust 0)

| # | Change | Score | Verdict |
|---|---|---|---|
| 0 | Baseline (as pasted) | 4/30 | baseline |
| 1 | Added price, size and pickup line | 10/30 | KEEP |
| 2 | Opened with the grandma story (two sentences) | 20/30, gate FAIL | DISCARD |

Lessons:
- L1 (cycle 2): The family story raised Trust from 0 to 7 but took the
  post to 36 words. Next time, try it in one short line.

Best version (cycle 1):
Banana bread for sale. $8 a loaf, pickup Saturday 9–12. DM me to order.
```

The stronger option is to say **audit this**, so a new chat scores the
best version without knowing what we hoped for.

Say **next cycle**, **run 3 cycles**, **status**, **save**, **audit
this**, or **new baseline**.

---

**Mai:** next cycle

**AI:**

```
CARD 3 (Local marketer): Put the grandma detail in one short first line (lesson L1).
Aims at: Trust, now 0/10, because nothing shows it is homemade. Could hurt: the 30-word gate.
Need from you: nothing (you gave the detail in cycle 2)
```

**Copywriter.**

> My grandma's recipe, baked every week for 10 years. Banana bread for
> sale. $8 a loaf, pickup Saturday 9–12. DM me to order.

**Busy neighbour, fresh pass.**

| Criterion | Score | Evidence (quoted) |
|---|---|---|
| Hook | 5/10 | "My grandma's recipe" opens on something personal |
| Clear offer | 8/10 | "$8 a loaf, pickup Saturday 9–12"; size is only "a loaf" |
| Trust | 6/10 | "grandma's recipe", "every week for 10 years" |
| Gate: under 30 words | PASS | 23 words |
| Total | 19/30 | |

**KEEP.** The gate passes and 19 beats the best so far (10). The
discarded 20 from cycle 2 does not count.

This was cycle 3, so here is the full ledger:

```
KEEPLOOP-LITE LEDGER
Artifact: Facebook post selling homemade banana bread, neighbourhood group
Scorecard (locked since cycle 0, max 30):
1. Hook: the first line makes a neighbour stop scrolling
2. Clear offer: price, size, pickup day and how to order are all stated
3. Trust: a concrete, true detail shows it is homemade and fresh
Gates (pass/fail): under 30 words
Team: Local marketer (propose), Copywriter (make), Busy neighbour (check)
Best so far: cycle 3, 19/30 (Hook 5, Clear offer 8, Trust 6)

| # | Change | Score | Verdict |
|---|---|---|---|
| 0 | Baseline (as pasted) | 4/30 | baseline |
| 1 | Added price, size and pickup line | 10/30 | KEEP |
| 2 | Opened with the grandma story (two sentences) | 20/30, gate FAIL | DISCARD |
| 3 | Grandma's recipe as one short first line | 19/30 | KEEP |

Lessons:
- L1 (cycle 2): The family story raised Trust from 0 to 7 but took the
  post to 36 words. Next time, try it in one short line.

Best version (cycle 3):
My grandma's recipe, baked every week for 10 years. Banana bread for sale. $8 a loaf, pickup Saturday 9–12. DM me to order.
```

Say **next cycle**, **run 3 cycles**, **status**, **save**, **audit
this**, or **new baseline**.

---

**Mai:** I'll go on tomorrow. save

**AI:**

```
KEEPLOOP-LITE STATE (after cycle 3)
Score (locked since cycle 0, max 30): Hook: the first line makes a neighbour stop scrolling; Clear offer: price, size, pickup day and how to order are all stated; Trust: a concrete, true detail shows it is homemade and fresh; Gates: under 30 words
Best so far: cycle 3, 19/30 (Hook 5, Clear offer 8, Trust 6)
Best version: My grandma's recipe, baked every week for 10 years. Banana bread for sale. $8 a loaf, pickup Saturday 9–12. DM me to order.
Discarded:
- cycle 2: Opened with the grandma story (two sentences) (20/30, gate FAIL: 36 words)
Lessons:
- L1 (cycle 2): The family story raised Trust from 0 to 7 but took the post to 36 words. Next time, try it in one short line.
```

To continue: open a new chat and paste this file, then this block.

*(The AI suggests this move by itself after about 6 cycles in one chat.
Mai saves after cycle 3 because she stops for the day. Every value in the
block comes from cycles 0 to 3 above.)*

---

*Next day, a new chat.* Mai pastes `KEEPLOOP-LITE.md`, then only the
state block above, and writes "next cycle".

**AI:** Picked up from the state block: the scorecard is locked (Hook,
Clear offer, Trust; gate under 30 words; max 30), the best is 19/30 from
cycle 3, one idea is discarded (cycle 2) and there is one lesson (L1).
Cycle 4 next.

```
CARD 4 (Local marketer): Change "DM me to order." to "Comment or DM me to order."
Aims at: Clear offer, now 8/10, because two ways to order may be easier. Could hurt: nothing expected.
Need from you: nothing
```

**Copywriter.**

> My grandma's recipe, baked every week for 10 years. Banana bread for
> sale. $8 a loaf, pickup Saturday 9–12. Comment or DM me to order.

**Busy neighbour, fresh pass.**

| Criterion | Score | Evidence (quoted) |
|---|---|---|
| Hook | 5/10 | "My grandma's recipe" opens on something personal |
| Clear offer | 8/10 | "Comment or DM me to order"; size is still only "a loaf" |
| Trust | 6/10 | "grandma's recipe", "every week for 10 years" |
| Gate: under 30 words | PASS | 25 words |
| Total | 19/30 | |

**DISCARD.** 19 ties the best so far, and a tie is a discard. We go back
to the best version (cycle 3).

```
| 4 | "Comment or DM me to order" | 19/30, tie | DISCARD |
Best so far: cycle 3, 19/30 (Hook 5, Clear offer 8, Trust 6)
- L2 (cycle 4): Clear offer stays at 8 while the size is only "a loaf". Raising it needs Mai's real loaf size.
```

```
KEEPLOOP-LITE STATE (after cycle 4)
Score (locked since cycle 0, max 30): Hook: the first line makes a neighbour stop scrolling; Clear offer: price, size, pickup day and how to order are all stated; Trust: a concrete, true detail shows it is homemade and fresh; Gates: under 30 words
Best so far: cycle 3, 19/30 (Hook 5, Clear offer 8, Trust 6)
Best version: My grandma's recipe, baked every week for 10 years. Banana bread for sale. $8 a loaf, pickup Saturday 9–12. DM me to order.
Discarded:
- cycle 2: Opened with the grandma story (two sentences) (20/30, gate FAIL: 36 words)
- cycle 4: "Comment or DM me to order" (19/30, tie)
Lessons:
- L1 (cycle 2): The family story raised Trust from 0 to 7 but took the post to 36 words. Next time, try it in one short line.
- L2 (cycle 4): Clear offer stays at 8 while the size is only "a loaf". Raising it needs Mai's real loaf size.
```

Say **next cycle**, **run 3 cycles**, **status**, **save**, **audit
this**, or **new baseline**.

---

Cycle 4 ran in a new chat on the state block alone: the same locked
scorecard, the best of 19/30 to beat, the discarded idea of cycle 2 not
tried again. Following lesson L2, the Local marketer's next card asks Mai
for the real size of a loaf.
