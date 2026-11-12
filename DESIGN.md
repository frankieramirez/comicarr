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
- **Non-Radix helpers kept deliberately**: `vaul` (drawer), `sonner` (toast),
  `react-day-picker` (calendar). The command palette is a Base UI dialog, not
  `cmdk`.

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

The app's dense control is a Button size, not a copied class string.
`components/ui/button.tsx` ships:

| Size | Geometry |
|------|----------|
| `compact` | `h-7 px-2.5 rounded-control text-[12px]` — inbox, scan, dense rows; icons 12px |
| `toolbar` | `h-8 px-3 rounded-control text-[12px]` — page-header and form actions; icons 14px |
| `mono` | uppercase mono label on either size |

The `default` variant is the neutral **act** button (`bg-act`, near-black in
light, near-white in dark), not orange. Use it for the one primary action on a
screen. `outline` is `border-border-strong bg-surface-2`; on `compact`/`toolbar`
it drops to a transparent fill, `--border`, no shadow. `ghost` is for quiet row
actions and header links. Do not size icons on callers; the size variant wins
over the base 16px svg rule.

Filters and view switches are the **segmented control**: `SEGMENTED_GROUP` on
the track and `SEGMENTED_ITEM` on each button, from `lib/segmented.ts`. Each
button sets `aria-pressed`, and the pressed look keys off that attribute, so
callers never choose classes by state. Use it for two to five mutually
exclusive options; use `TabRow` for page-level views.
`components/ui/toggle-chip.tsx` (`ToggleChip`) is the older mono chip and now
survives only in Settings' mobile section row; do not add new uses. Status banners are `components/ui/callout.tsx`
(`Callout`) with `tone` `error` | `warning` | `success` | `info` — `--status-*`
fill, a 30% `color-mix` border, and a tone-coloured icon. Body copy stays
`text-foreground`. Error and warning use `role="alert"`.

Disabled is `opacity-50` plus `pointer-events-none` from that one primitive.
Do not re-specify opacity or skip the focus ring on callers. The scaffold
`default` size (`h-9 rounded-md text-sm`) remains for shadcn-era surfaces
that have not moved yet.

## Tokens are the contract

Every color, radius, and font reaches a component through a CSS custom property
defined in `:root` and overridden in `.dark`. A component that hardcodes a color
is a component that cannot be themed, and Comicarr ships both themes.

### Brand

| Token | Light | Dark |
|-------|-------|------|
| `--primary` | `#d4520e` | `#ff6a1f` |
| `--primary-foreground` | `#ffffff` | `#ffffff` |
| `--destructive-foreground` | `#ffffff` | `#0b0d12` |
| `--gradient-brand` | 135° orange ramp | 135° orange ramp |

Orange is the brand, and v2 spends it sparingly: the logo dot, the active tab
underline, the active nav marker, and the focus ring (`--ring` tracks
`--primary` in both themes). Buttons, links and selection are neutral.

### v2 surfaces, borders and text

The v2 facelift (PR #1162) adds a small neutral ladder. Reach for these before
`--card`, `--secondary` or `--muted`, which remain for shadcn-era surfaces.

| Token | Use |
|-------|-----|
| `--surface-1` / `-2` / `-3` | Raised panels, inputs and pressed segments, in that order |
| `--border-subtle` / `-strong` / `-emphasis` | Row rules and panel edges, control edges, focus-within |
| `--foreground` / `--foreground-2` / `--muted-foreground` | Primary text, secondary text, metadata |
| `--text-muted` | Separators and decorative marks only (2.95:1) |
| `--act` / `--act-foreground` / `--act-hover` | The neutral primary button |
| `--in-flight` | Something moving right now: a download, a running search |
| `--selection` | Selected table rows |

Each is defined in `:root` and `.dark` and registered as `--color-*`, so
`bg-surface-1`, `border-border-subtle` and `text-foreground-2` work as classes.

### v2 layout

- **Gutter.** Page content sits on a 32px gutter (`px-8`). `PageHeader` is
  `px-8 pt-6 pb-4`; `TabRow` is `mx-8`.
- **Tables.** `DataTable` wraps itself in `px-8`, with cells `px-3 py-1.5
  first:pl-2 last:pr-2` and `group/row` on each row. Hand-built grid rows use
  `mx-8 px-2` so their text lines up with a DataTable on the same page.
  Headers are 11px uppercase sans, `tracking-[0.04em]`, muted.
- **Section headers.** `SectionHeader` from `components/dashboard/DashboardPanel`
  (`variant="main"` 15px semibold, `variant="rail"` 11px uppercase) with an
  optional mono meta and a `label ›` link.
- **Status.** A 6px dot plus plain text (`StatusBadge variant="dot"`), not a
  glowing pill, in dense rows.
- **Row actions.** `ghost` `compact` buttons at reduced opacity that brighten on
  `group-hover/row` and on focus. One `default` button per screen at most.
- **Kind badges.** `rounded-md border border-border-strong px-1.5 py-0.5
  text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`.
  Neutral; never colored by kind.
- **Command palette.** ⌘K opens `components/layout/CommandPalette`
  (`openCommandPalette()` from `lib/commandPalette`). New global actions belong
  there, not in a new header button.

The Pen mockups for every screen live in the project's `ux-redesign/` export
folders; a screen change is checked side by side against the newest round
before it merges.

### Status

`--status-{active,wanted,downloaded,paused,ended,error,skipped}` and their
`-bg` pairs are **the** semantic color set — ~163 usages across the app, and the
only vocabulary `StatusBadge` understands. Reach for these whenever the meaning
is "this item is in state X". `lib/statusTone.ts` is the lookup; `StatusBadge`
offers `variant="pill"` (glowing) and `variant="dot"` (dense rows). Do not
re-map Wanted to `--primary` or Downloaded to `--status-active` at a call site.

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
  weight on a heading that the base layer already covers. Every routed page
  exposes exactly one `h1`. `PageHeader` emits it; pages that hand-roll a
  header (Dashboard, Releases, Library) must too. Loading and error branches
  keep a visible or `sr-only` `h1` so the outline never disappears.
- **No serif fonts.** Not in the app, not in mockups, not in generated assets.

Two `@utility` classes exist for the dense mono-label idiom that appears
throughout the tables and detail pages. They sort with Tailwind utilities so a
sibling `text-*` colour or size can override them:

| Utility | Renders |
|---------|---------|
| `mono-label` | 10px mono, uppercase, `0.08em` tracking, muted |
| `mono-meta` | 11px mono, muted |

Use them. Hand-rolling `font-mono text-[10px] uppercase tracking-wider
text-muted-foreground` reproduces `.mono-label` inline and is the single largest
source of style drift in the codebase (see *Known drift*). Exact
`.mono-label` / `.mono-meta` token sets fail `check_mono_utilities.py`; remaining
`font-mono text-[10px] uppercase` near-variants (other tracking or colour) are a
shrink-only count.

### Radius

`--radius: 0.375rem` with a derived `sm`/`md`/`lg`/`xl`/`2xl`/`3xl`/`4xl` scale in
`@theme inline`. Use `rounded-md` etc.; don't write `rounded-[6px]`.
`--radius-control: 5px` is the sixth step (`rounded-control`) for dense
controls, chips, and compact/toolbar Buttons. `check_radius_literals.py`
rejects on-scale `2/4/6/10/14px` literals and leftover `rounded-[5px]`.

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
  cases. 42 such usages predated the gate (30 remain); `scripts/check_palette_classes.py` holds
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
  the value in the class layer. 190 inline `style={{` attributes across the
  frontend (down from 251 after the v2 facelift).

- **Do NOT add arbitrary font sizes outside the v2 steps.** v2 text is 11px
  (labels, metadata), 13px (rows, controls), 15px (section titles) and the
  Tailwind `text-sm`/`text-xs` steps. `text-[10px]` is for kind badges only. Half-pixel
  sizes (`text-[12.5px]`, `text-[11.5px]`, `text-[10.5px]`, 30 usages) are
  rounding noise, not design. Use the Tailwind scale or `.mono-label` / `.mono-meta`.

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
| Arbitrary `text-[Npx]` | 367 usages, 75 files | No typographic scale; v2 settled on 11/13/15px |
| Inline `style={{ }}` | 190 attributes, 49 files | Tokens bypass the class layer |
| Raw Tailwind palette classes | 30 usages, 6 files | Colors don't respond to theme — **gated, shrink-only** |
| Radix holdouts | `avatar.tsx`, `bubble.tsx`, `marker.tsx` + 3 deps | Two primitive libraries in one app |
| Dead `components/custom/` | 6 files, 0 importers | Unlinted, unreachable code |
| Dead `frontend/src/App.css` | 42 lines, imported nowhere | Vite scaffold leftover |
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
| Dead `border-card-border` / unregistered `text-destructive-foreground` | 12 leftover `border-card-border` classes; destructive buttons had no foreground rule | Repointed to `border-border`; `--destructive-foreground` registered in both themes. Color utilities whose stem is not a `--color-*` key now fail `check_design_tokens.py`. |

`--border-soft` is deliberately undefined. Its three call sites all write
`var(--border-soft, var(--border))`, which stays valid without it.

### Verifying

Both gates run under `npm run lint:guards`:

```bash
python3 scripts/check_design_tokens.py    # no var() resolves to nothing; --status-* is exhaustive; color utilities name a --color-* key
python3 scripts/check_palette_classes.py  # no new palette literals
python3 scripts/check_radius_literals.py  # no on-scale rounded-[2|4|5|6|10|14px]
python3 scripts/check_mono_utilities.py   # no exact .mono-label / .mono-meta duplicates
```

The remaining rows have no gate. Arbitrary font sizes are the obvious next
candidate now that v2 has named its steps (11/13/15px); the baseline is 367
across 75 files.

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
