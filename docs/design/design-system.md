# Design System

## Design direction

A calm, cinematic creative workspace: near-black layered surfaces, restrained chrome, strong media focus, and typography that creates hierarchy without visual noise. The system takes inspiration from the principles of modern generative-media tools, not their proprietary visual identity.

### Core principles

1. **Media first** — generated media gets the highest visual weight.
2. **Calm chrome** — controls recede until needed.
3. **Progressive disclosure** — secondary controls should not compete with the prompt/result.
4. **Consistent geometry** — 4px spacing grid, predictable radii and borders.
5. **International by default** — no fixed-width labels; Russian, Indonesian, CJK and Latin must wrap safely.
6. **Accessible contrast** — primary/secondary text and semantic states target WCAG AA contrast against their intended surfaces.
7. **Motion with restraint** — short transitions, no essential information conveyed only by animation.

## Color tokens

### Dark theme

| Token | Value | Role |
|---|---|---|
| `--ds-bg` | #0b0b0d | Application background |
| `--ds-surface-1` | #131316 | Primary surface |
| `--ds-surface-2` | #1b1b20 | Elevated surface |
| `--ds-surface-3` | #24242b | Strong/elevated control surface |
| `--ds-border` | rgba(255,255,255,.10) | Low-contrast border |
| `--ds-border-strong` | rgba(255,255,255,.16) | Focus/active border |
| `--ds-accent` | #9aa7ff | Restrained interactive accent |
| `--ds-success` | #62d39b | Success |
| `--ds-warning` | #e7bd68 | Warning |
| `--ds-error` | #ef737d | Error |
| `--ds-text-1` | #f4f4f6 | Primary text |
| `--ds-text-2` | #b5b6bf | Secondary text |
| `--ds-text-3` | #777985 | Disabled/muted text |

The accent is intentionally cool and desaturated; it should identify interaction, not become a decorative gradient.

### Light theme

The light theme mirrors the same hierarchy rather than simply inverting every value:

- background: #f5f5f7
- surface 1: #ffffff
- surface 2: #f0f0f3
- surface 3: #e7e7ec
- border: rgba(20,20,25,.12)
- strong border: rgba(20,20,25,.20)
- accent: #5867d8
- success: #18794e
- warning: #8a5a00
- error: #b4232f
- primary text: #16161a
- secondary text: #555762
- disabled text: #858792

## Theme behavior

- Default theme follows `prefers-color-scheme`.
- A manual `data-theme="light"` or `data-theme="dark"` override is supported by the CSS layer.
- The application can persist a user choice in local storage without touching backend APIs.
- Reduced-motion users receive effectively instantaneous transitions.

## Typography

Use one stack throughout:

`Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", "Noto Sans CJK SC", "Noto Sans CJK JP", sans-serif`

No external font dependency is required.

| Token | Size | Typical use |
|---|---:|---|
| `--ds-text-xs` | 12px | metadata, helper text |
| `--ds-text-sm` | 14px | controls, body secondary |
| `--ds-text-md` | 16px | body, primary controls |
| `--ds-text-lg` | 20px | card/section titles |
| `--ds-text-xl` | 28px | page headings |
| `--ds-text-2xl` | 40px | hero/display headings |

Headings use tight line-height and modest negative tracking; body copy uses comfortable 1.5–1.6 line-height.

## Spacing

All spacing is based on a 4px grid:

`4 / 8 / 12 / 16 / 20 / 24 / 28 / 32 / 40 / 48 / 64`px.

## Shape

- `--ds-radius-sm`: 8px
- `--ds-radius-md`: 12px
- `--ds-radius-lg`: 16px
- `--ds-radius-xl`: 24px
- `--ds-radius-pill`: 999px

Borders are normally 1px and deliberately low contrast.

## Elevation

Use layered, soft shadows rather than hard drop shadows:

- small: 0 4px 16px rgba(0,0,0,.16)
- medium: 0 12px 40px rgba(0,0,0,.20)
- large: 0 24px 80px rgba(0,0,0,.24)

Light theme reduces opacity and uses neutral shadows.

## Motion

- fast: 120ms
- standard: 200ms
- slow: 320ms
- easing: `cubic-bezier(.2,.8,.2,1)`
- all nonessential motion is disabled/reduced under `prefers-reduced-motion: reduce`.

## Components

### Buttons

- Primary: filled accent, strong text contrast.
- Secondary: elevated neutral surface.
- Ghost: transparent, border appears on hover/focus.
- Icon: square/circular hit target with visible focus state.
- Minimum interactive target: 40px; touch-friendly surfaces should prefer 44px.

### Inputs / textarea / select

- Same surface/border system.
- Clear focus ring using accent at low opacity.
- Never rely on placeholder text as the only label.
- Long localized values may wrap in surrounding layouts; controls use min-width: 0.

### Segmented control

- Single container with equal visual weight options.
- Active segment uses elevated surface + accent boundary.
- Labels must be content-driven rather than fixed-width.

### Toggle

- Pill track with a clear active state.
- Semantic state must remain understandable without color alone.

### Slider

- 4px track, 16px thumb, visible focus ring.
- Value remains available as text where precision matters.

### Tabs

- Low-noise text tabs with active indicator.
- Tab list can scroll horizontally rather than wrapping into broken rows.

### Cards

- Layered surfaces, 1px border, 16–24px radius.
- Avoid excessive card nesting; use cards to group decisions, not every field.

### Chips

- Compact metadata/status treatment.
- Semantic colors supplement, rather than replace, text.

### Tooltips

- Short, contextual, nonessential information.
- Keyboard focus and hover support.
- Never use a tooltip for required instructions.

### Modals

- Backdrop with restrained blur.
- Elevated surface, 16–24px radius.
- Clear title/action hierarchy and keyboard-dismiss behavior when implemented.

### Toasts

- Compact, high-contrast transient feedback.
- Semantic variants for success/warning/error.
- Never contain the only copy of a critical error.

### Progress

- Track uses a low-contrast neutral surface.
- Fill uses accent or semantic success.
- Numeric/prose progress remains visible for long-running generation.

### Skeleton loaders

- Match final component geometry.
- Subtle opacity animation only when motion is permitted.

### Empty states

- Clear statement of current state.
- One useful next action.
- No decorative clutter.

## Responsive / localization rules

- Use fluid widths and `minmax(0, 1fr)`.
- Never depend on English word lengths.
- Allow labels and chips to wrap.
- Mobile layouts collapse columns rather than shrinking controls below usable touch targets.
- CJK and Cyrillic text use the same typographic stack and inherit the same line-height rules.

## Implementation boundary for Task 1

This system is implemented as shared tokens and base component primitives only. Individual screen redesign belongs to later tasks. Existing element IDs, JavaScript hooks, API endpoints, request fields and task/WebSocket contracts remain unchanged.
