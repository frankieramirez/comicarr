# DESIGN.md

Design-system contract for the Comicarr frontend. `CLAUDE.md` governs backend and
repo-wide conventions; this file governs everything a user can see.

Same rule as `CLAUDE.md`: **prefer retrieval-led reasoning.** The system of record
is `frontend/src/index.css`, not this file's summary of it and not general
Tailwind/shadcn knowledge. When the two disagree, the stylesheet wins and this
file is stale — fix it.

## Scope

| Concern | Lives in |
|---------|----------|
| Tokens, theming, light/dark | `frontend/src/index.css` |
| Primitive components | `frontend/src/components/ui/` |
| Domain components | `frontend/src/components/<domain>/` |
| shadcn generator config | `frontend/components.json` |
| Tailwind content globs | `frontend/tailwind.config.js` |

`frontend/tailwind.config.js` is a near-empty v4 stub — it carries content globs
only. Do not add a `theme.extend` block there; tokens are CSS-first via
`@theme inline` in `index.css`.

## The stack

- **Tailwind CSS v4**, CSS-first config (`@import "tailwindcss"` + `@theme inline`).
- **shadcn/ui**, `new-york` style, `neutral` base, `cssVariables: true`.
- **Base UI** (`@base-ui/react`) for headless primitives. This is the standard.
- **lucide-react** for icons.
- **Non-Radix helpers kept deliberately**: `vaul` (drawer), `cmdk` (command),
  `sonner` (toast), `react-day-picker` (calendar).

### Primitives: Base UI, not Radix

`frontend/.migration/project.md` records the 2026-07-13 Radix → Base UI
conversion. Its claim that all Radix imports are gone is **no longer accurate** —
`avatar.tsx`, `bubble.tsx`, and `marker.tsx` still import `@radix-ui/*`, and
three `@radix-ui/react-*` entries remain in `frontend/package.json`.

New primitives use Base UI. Base UI is not a drop-in for Radix:

- `render` prop, not `asChild`
- Positioner/Popup parts for portalled overlays
- transition hooks, not `data-state` animation conventions
- Tooltip timing is `delay`, not `delayDuration`

## Tokens are the contract

Every color, radius, and font reaches a component through a CSS custom property
defined in `:root` and overridden in `.dark`. A component that hardcodes a color
is a component that cannot be themed, and Comicarr ships both themes.

### Brand

| Token | Light | Dark |
|-------|-------|------|
| `--primary` | `#e04a0a` | `#ff6a1f` |
| `--primary-foreground` | `#ffffff` | `#ffffff` |
| `--gradient-brand` | 135° orange ramp | 135° orange ramp |

Orange is the brand. Note that `--ring` tracks `--primary` in dark but is a
neutral grey in light — the two themes focus differently. Nothing in the repo
records whether that was a decision or a drift; treat it as unsettled rather than
as a pattern to copy.

### Status

`--status-{active,wanted,downloaded,paused,ended,error,skipped}` and their
`-bg` pairs are **the** semantic color set — ~163 usages across the app, and the
only vocabulary `StatusBadge` understands. Reach for these whenever the meaning
is "this item is in state X".

That list is exhaustive. There is no `--status-success` and no
`--status-warning`; both were invented at call sites and neither ever resolved.
Success is `--status-active`, warning is `--status-paused`. `check_design_tokens.py`
now rejects either name.

### Typography

- **UI**: `Inter Tight`, with a system fallback stack. `letter-spacing: -0.005em`
  on `:root`.
- **Numeric / metadata**: `JetBrains Mono` via `--font-mono`, with
  `font-feature-settings: "tnum" 1` so columns of numbers align.
- **Headings**: `h1`–`h3` are styled in `@layer base`. Don't re-specify size and
  weight on a heading that the base layer already covers.
- **No serif fonts.** Not in the app, not in mockups, not in generated assets.

Two utilities exist for the dense mono-label idiom that appears throughout the
tables and detail pages:

| Utility | Renders |
|---------|---------|
| `.mono-label` | 10px mono, uppercase, `0.08em` tracking, muted |
| `.mono-meta` | 11px mono, muted |

Use them. Hand-rolling `font-mono text-[10px] uppercase tracking-wider
text-muted-foreground` reproduces `.mono-label` inline and is the single largest
source of style drift in the codebase (see *Known drift*).

### Radius

`--radius: 0.375rem` with a derived `sm`/`md`/`lg`/`xl`/`2xl`/`3xl`/`4xl` scale in
`@theme inline`. Use `rounded-md` etc.; don't write `rounded-[6px]`.

### Effects

`.glass-nav`, `.gradient-brand`, `.page-transition`, `.scroll-fade-b`,
`.shimmer`, `.custom-scrollbar`, `.scrollbar-hide` are the sanctioned effect
utilities. `.shimmer` already honours `prefers-reduced-motion` — any new motion
utility must do the same.

## Anti-Patterns / What NOT to Do

- **Do NOT use raw Tailwind palette classes** — `text-green-400`, `bg-red-500`,
  `border-yellow-500`. They are fixed sRGB values that ignore `.dark` entirely, so
  a component using them is legible in one theme and wrong in the other. Use a
  `--status-*` token, or `--destructive` / `--muted-foreground` for the generic
  cases. 58 such usages predate the gate; `scripts/check_palette_classes.py` holds
  a per-file baseline that only ever shrinks, so new ones fail CI and fixes must
  lower the number.

- **Do NOT reintroduce `--success` / `--warning` / `--error` / `--info`.** These
  were mislabeled leftovers from a pre-token shadcn scaffold — *surface* values
  wearing *text* names. `--success` was `hsl(210 40% 96.1%)` in light, near-white,
  and being registered in `@theme inline` meant `text-success` compiled clean and
  rendered near-invisible; `ImportTable.tsx` printed "Saved" in near-white on a
  white page. All four are deleted, along with their `--color-*` registrations.
  Semantic color is `--status-*`.

- **Do NOT define a token in `.dark` only.** A `var()` naming an undefined
  property makes the whole declaration invalid, so the style vanishes silently
  instead of failing loudly. Seven tokens were dark-only; `var(--text-muted)` was
  live in 25 lines across 6 files and did nothing in light mode. A token that
  genuinely doesn't vary by theme (`--radius`, `--font-mono`,
  `--glassmorphism-blur`) belongs in `:root` alone, but a `.dark`-only token is
  always a bug. `scripts/check_design_tokens.py` enforces this, with no allowlist.

- **Do NOT `var()` a token you haven't defined.** Same failure, different cause:
  `--status-success` and `--status-warning` were never tokens, and 17 call sites
  asked for them. Most sat inside `color-mix(in oklab, var(--status-success) 36%,
  transparent)`, where an invalid inner var voids the entire color — those borders
  and backgrounds were missing in *both* themes, not one. The guard covers this
  too. `var(--x, var(--fallback))` is the sanctioned way to reference an optional
  token and is deliberately not flagged.

- **Do NOT reach for `style={{ }}` to apply a token.** Inline styles are how the
  dark-only-token bug got in and stayed in: they bypass Tailwind, so nothing at
  build time can tell you the property doesn't resolve. Prefer a utility class;
  where a token isn't yet Tailwind-registered, `text-[var(--token)]` at least keeps
  the value in the class layer. 288 inline `style={{` attributes across 50 files.

- **Do NOT add arbitrary font sizes.** `text-[10px]`, `text-[11px]`, `text-[12px]`,
  and `text-[13px]` account for 369 of the 432 arbitrary sizes in the codebase —
  four values doing the work of a scale that was never written down. Half-pixel
  sizes (`text-[12.5px]`, `text-[11.5px]`, `text-[10.5px]`, 30 usages) are
  rounding noise, not design. Use the Tailwind scale or `.mono-label` / `.mono-meta`.

- **Do NOT add components under `frontend/src/components/custom/`.** All six files
  there have zero importers, and the directory is in the ESLint `ignores` list — so
  nothing in it is linted, type-checked in CI, or reachable. New primitives go in
  `components/ui/`; new domain components go in `components/<domain>/`.

- **Do NOT define a utility around an undefined variable.** `.card-shadow` applied
  `box-shadow: var(--card-shadow)` with `--card-shadow` defined nowhere — a no-op
  that read like a working one, on two live card components. It was deleted rather
  than given a value: removing it is provably no visual change, whereas inventing
  a shadow would be a design decision. If cards should have shadows, that is a
  deliberate change to make, not a variable to backfill.

- **Do NOT reintroduce Radix for new work.** See *Primitives* above. The three
  remaining Radix files are holdouts to migrate, not precedent to follow.

- **Do NOT hand-build a table.** Row identity goes through
  `@/components/data-table/useTableState` — enforced by `no-restricted-imports` in
  `frontend/eslint.config.js`. `CLAUDE.md` carries the full rule.

- **Do NOT finish without linting.** `npm run lint` from `frontend/`, per `CLAUDE.md`.

## Known drift

Measured on the current tree. These are a work queue, not a description of the
target state — the rules above are the target state.

| Drift | Extent | Impact |
|-------|--------|--------|
| Arbitrary `text-[Npx]` | 432 usages, 63 files | No typographic scale |
| Inline `style={{ }}` | 288 attributes, 50 files | Tokens bypass the class layer |
| Raw Tailwind palette classes | 58 usages, 11 files | Colors don't respond to theme — **gated, shrink-only** |
| Radix holdouts | `avatar.tsx`, `bubble.tsx`, `marker.tsx` + 3 deps | Two primitive libraries in one app |
| Dead `components/custom/` | 6 files, 0 importers | Unlinted, unreachable code |
| Dead `frontend/src/App.css` | 42 lines, imported nowhere | Vite scaffold leftover |
| Dead `border-card-border` class | removed from 2 cards | `--color-card-border` was never registered, so the class never existed |
| `--text-muted` contrast | 2.95:1 both themes | Decorative only; see below |

`--text-muted` is for decorative separators (`/`, `·`) and 10px uppercase
micro-labels. It sits at 2.95:1 in both themes — that parity is deliberate (the
light value was tuned to the ratio dark already shipped). Real words use
`--muted-foreground` (AA-safe in light at `oklch(0.552 …)`). Raising
`--text-muted` itself to 4.5:1 would recolour every separator and is still a
design decision, not a bug fix.

### Fixed and now gated

| Was | Extent | Now |
|-----|--------|-----|
| `--text-muted` defined in `.dark` only | 25 lines, 6 files | `:root` value added at matching contrast |
| `--status-success` / `--status-warning` — never tokens | 17 usages, 2 files | Repointed to `--status-active` / `--status-paused` |
| `text-success` on a near-white token | `ImportTable.tsx` | Repointed to `--status-active` |
| `--info` on a toast that was otherwise `--status-*` | 2 lines | Repointed to `--status-wanted` |
| Mislabeled `--success`/`--warning`/`--error`/`--info` | 4 tokens x 2 themes | Deleted, with their `--color-*` registrations |
| 6 unused dark-only tokens | `--surface-*`, `--border-elevated`, `--text-tertiary`, `--text-disabled` | Deleted |
| Undefined `--card-shadow` | 1 utility, 2 components | Utility and usages deleted |
| Radix-era accordion keyframes | 2 keyframes, 2 registrations | Deleted; Base UI animates via `transition-[height]` |

`--border-soft` is deliberately undefined. Its three call sites all write
`var(--border-soft, var(--border))`, which stays valid without it.

### Verifying

Both gates run under `npm run lint:guards`:

```bash
python3 scripts/check_design_tokens.py    # no var() resolves to nothing; --status-* is exhaustive
python3 scripts/check_palette_classes.py  # no new palette literals
```

The remaining rows have no gate. Arbitrary font sizes are the obvious next
candidate, but a baseline of 432 across 63 files is worth less than agreeing the
scale first — gating a number nobody has decided how to reduce just freezes it.

```bash
cd frontend

# arbitrary font sizes, by value
grep -rhoE 'text-\[[0-9.]+px\]' --include='*.tsx' src | sort | uniq -c | sort -rn

# Radix holdouts
grep -rln '@radix-ui' --include='*.tsx' src
```

## Changing the design system

1. **Token first.** Add or change the value in `:root` **and** `.dark`.
2. **Register it** in `@theme inline` as `--color-*` if components should reach it
   by class name rather than `var()`. The `--status-*` family is currently
   unregistered, which is why every consumer writes
   `bg-[var(--status-active-bg)]` instead of `bg-status-active`.
3. **Check both themes.** Toggle light/dark before opening the PR. Most bugs in
   *Known drift* are things that look right in exactly one theme.
4. **Changeset?** Apply the `CLAUDE.md` test: a visible change an *operator* could
   notice earns one. A token rename with identical rendered output does not.
