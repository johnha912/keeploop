# Taste — UI/UX design

The anti-slop standard. Generated design defaults to the same purple
gradient, the same three cards, the same hero. This file is how the team
refuses:

- **One idea per screen.** If everything is emphasized, nothing is.
  Hierarchy is decided before decoration.
- **Typography does the talking.** A disciplined scale (e.g. 12/14/16/20/
  24/32), two weights per family at most, line-height 1.4–1.6 for body.
- **Spacing is a system, not a vibe.** One base unit (4 or 8 px); every gap
  is a multiple. Whitespace is the cheapest luxury.
- **Color with restraint.** One accent, neutrals with a temperature,
  contrast ≥ 4.5:1 for text. Gradients are a decision, not a default.
- **Motion explains.** 150–300 ms, ease-out, only when it shows cause and
  effect. Nothing bounces for attention.
- **Real content, real lengths.** Design with the longest plausible label
  and the empty state, not with lorem ipsum and the happy path.
- **Judge the rendered page, not the source.** Open it in a real browser
  at phone width (375 px) and desktop, in light and dark: no horizontal
  scroll, no console errors, every control reachable by keyboard with a
  visible focus ring. A screenshot beats a description.
- **Borrow from the reference base before inventing.** Search `data/`
  (styles, palettes, font pairings) for the product type first.

Anti-patterns the Auditor flags on sight: gradient hero + glass cards +
three identical feature tiles; five font weights; centered everything;
shadows on every surface; color as the only state signal (accessibility).
