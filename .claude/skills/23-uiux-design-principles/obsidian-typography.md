# Obsidian Intelligence — Typography System

The Obsidian Intelligence design system uses a strict **four-step type scale**. Every font size decision maps to exactly one semantic role. Deviating from this scale collapses the visual hierarchy.

## The Four-Step Scale

| Step | Token                  | Size | Weight  | Font                          | Role                                                                 |
| ---- | ---------------------- | ---- | ------- | ----------------------------- | -------------------------------------------------------------------- |
| 1    | `text-page-title`      | 22px | 700     | Plus Jakarta Sans             | Page/screen title (one per page)                                     |
| 2    | `text-section-heading` | 15px | 600     | Plus Jakarta Sans             | Card, panel, modal headings                                          |
| 3    | `text-body-default`    | 13px | 400–500 | Plus Jakarta Sans             | Everything else: body, inputs, buttons, labels, errors, empty states |
| 4    | `text-label-nav`       | 11px | 500–600 | Plus Jakarta Sans (uppercase) | Table column headers, nav items, filter chip labels, ALL-CAPS labels |

**Data layer** (always paired with `font-mono`):

| Token             | Size | Weight  | Font    | Role                                                       |
| ----------------- | ---- | ------- | ------- | ---------------------------------------------------------- |
| `text-data-value` | 13px | 400–500 | DM Mono | Numbers, prices, percentages, timestamps, IDs, URL strings |

**Permitted exceptions** (do not expand this list):

| Pattern                        | Size    | When                                  |
| ------------------------------ | ------- | ------------------------------------- |
| `text-[12px] font-medium`      | 12px    | Tab bar navigation only (design spec) |
| `text-[10px]` or `text-[11px]` | 10–11px | Compact status badges only            |

## The `text-sm` Anti-Pattern

`text-sm` in Tailwind CSS resolves to **14px**. This is **not in the scale**.

Using `text-sm` as a general body size inserts a phantom 14px band between step 2 (15px) and step 3 (13px), creating an indistinguishable 15–14–13 cluster that reads as visually identical. The subtitle collides with the section heading. Form inputs look heavier than table cells showing the same data.

```tsx
// ❌ WRONG — breaks hierarchy
<p className="text-sm text-text-muted">Description</p>
<input className="text-sm text-text-primary" />
<button className="text-sm font-semibold">Save</button>
<span className="text-sm text-alert">Error message</span>

// ✅ CORRECT — step 3 for all body content
<p className="text-body-default text-text-muted">Description</p>
<input className="text-body-default text-text-primary" />
<button className="text-body-default font-semibold">Save</button>
<span className="text-body-default text-alert">Error message</span>
```

## UI Text vs. Data Text

The two fonts carry distinct meanings. Never cross-contaminate.

```tsx
// Plus Jakarta Sans (text-body-default) — for UI labels and prose
<td className="text-body-default text-text-primary">{user.name}</td>
<td className="text-body-default text-text-muted">{user.email}</td>

// DM Mono (font-mono text-data-value) — for data values only
<td className="font-mono text-data-value text-text-muted">{formatDate(row.created_at)}</td>
<td className="font-mono text-data-value text-text-primary">${row.price.toFixed(6)}</td>
<td className="font-mono text-data-value text-text-muted truncate max-w-[200px]">{row.endpoint_url}</td>

// ❌ WRONG — font-mono on non-data text (names, labels)
<td className="font-mono text-[11px]">{tenant.name}</td>

// ❌ WRONG — data value without font-mono
<td className="text-body-default">{price}</td>
```

## Helper Text and Captions

Helper text under inputs and captions should use the label floor (11px), not go below it:

```tsx
// ❌ Too small — below minimum legible floor
<p className="text-[10px] text-text-faint">Leave blank to keep existing key</p>

// ✅ Correct — at label floor, sentence case (no uppercase)
<p className="text-[11px] text-text-faint">Leave blank to keep existing key</p>
// or
<p className="text-label-nav normal-case text-text-faint">Leave blank to keep existing key</p>
```

## Audit Checklist

When reviewing or implementing any screen, check each text element against this list:

- [ ] No `text-sm` in body copy, inputs, buttons, labels, or errors
- [ ] No `text-[14px]` (same problem as `text-sm`)
- [ ] No `text-[12px]` except tab bars
- [ ] No `text-[13px]` — use `text-body-default` token instead
- [ ] Data columns (`font-mono`) are using `text-data-value`, not `text-[11px]`
- [ ] Helper text is `text-[11px]` minimum, never `text-[10px]`
- [ ] Tenant names, user names, plain labels do NOT have `font-mono`
- [ ] Page has at most one `text-page-title`

## Full Implementation Reference

Full design system spec (colors, spacing, components, layout, banned patterns):
→ `.claude/rules/design.md`

Tailwind token definitions:
→ `src/web/tailwind.config.ts`
