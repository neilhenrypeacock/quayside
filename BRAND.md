# Quayside Brand Kit

Editorial/newspaper aesthetic. Warm, muted palette. Data-forward typography. No visual clutter.

## Colour Palette

| Token     | Hex       | Usage                                  |
|-----------|-----------|----------------------------------------|
| `--ink`   | `#0f0e0c` | Primary text, dark backgrounds         |
| `--paper` | `#f5f0e8` | Page background                        |
| `--tide`  | `#1a3a4a` | Primary brand (headers, nav, accents)  |
| `--salt`  | `#e8e0d0` | Secondary backgrounds, bar tracks      |
| `--catch` | `#c8401a` | CTA buttons, alerts, accent highlights |
| `--foam`  | `#f0ebe0` | Card backgrounds, section fills        |
| `--muted` | `#7a7060` | Secondary text, labels                 |
| `--rule`  | `#c8bfaa` | Borders, dividers                      |

### Semantic colours

| Token    | Hex       | Usage          |
|----------|-----------|----------------|
| `--up`   | `#6db88a` | Price increase |
| `--down` | `#e07060` | Price decrease |

## Typography

Three font families, loaded from Google Fonts (except in email templates).

| Role        | Family             | Weights       | Usage                                       |
|-------------|--------------------|---------------|---------------------------------------------|
| Headings    | Playfair Display   | 400, 700, 900 + italic | Page titles, section headings, species names in tables |
| Body        | IBM Plex Sans      | 300, 400, 500 | Body copy, descriptions, form labels        |
| Data/Labels | IBM Plex Mono      | 400, 500      | Prices, port codes, section labels, badges, buttons, metadata |

### Google Fonts link

```html
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet">
```

### Email fallbacks

Email templates cannot use Google Fonts. Use:
- Headings: `Georgia, 'Times New Roman', serif`
- Body: `'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif`
- Data: `'Courier New', monospace`

## Design Principles

1. **No rounded corners** — `border-radius: 2px` maximum. Sharp edges throughout.
2. **Borders, not shadows** — `1px solid var(--rule)` for separation. No `box-shadow` on cards.
3. **Monospace section labels** — IBM Plex Mono, 9-10px, uppercase, letter-spacing `0.2em`, with extending rule line (`::after` pseudo-element).
4. **Editorial spacing** — Marketing pages: 96px vertical, 48px horizontal padding. App pages: 24px padding.
5. **Full-width sections** — Marketing pages use full-bleed sections, no max-width container.
6. **Grid dividers** — Multi-column layouts use `gap: 1px` with a coloured background to create divider lines.
7. **Data is monospace** — All prices, percentages, dates, port codes rendered in IBM Plex Mono.
8. **Species names in serif italic** — Playfair Display italic for species names in tables and cards.

## Component Patterns

### Buttons

```css
/* Primary */
background: var(--catch);
color: white;
font-family: 'IBM Plex Mono', monospace;
font-size: 12px;
letter-spacing: 0.1em;
text-transform: uppercase;
padding: 14px 32px;
border-radius: 2px;

/* Ghost */
color: var(--muted);
font-family: 'IBM Plex Mono', monospace;
font-size: 11px;
letter-spacing: 0.1em;
text-transform: uppercase;
border-bottom: 1px solid var(--rule);
```

### Grade badges

```css
font-family: 'IBM Plex Mono', monospace;
font-size: 9px;
letter-spacing: 0.08em;
background: var(--salt);
color: #5a5040;
padding: 2px 6px;
border-radius: 2px;
border: 1px solid var(--rule);
```

### Section labels

```css
font-family: 'IBM Plex Mono', monospace;
font-size: 10px;
letter-spacing: 0.2em;
text-transform: uppercase;
color: var(--muted);
display: flex;
align-items: center;
gap: 16px;
/* ::after extends a 1px rule line */
```

### Cards (app pages)

```css
background: var(--foam);
border: 1px solid var(--rule);
border-radius: 2px;
padding: 20px;
```

## Logo

The Quayside logo is typographic: `Quay<span>side</span>` where "Quay" is in `--paper` (on dark) or `--ink` (on light) and "side" is in `--catch`.

- Marketing: Playfair Display, 22px, weight 700
- Email: Georgia, 24px, weight 700
- App nav: Playfair Display, 20px, weight 700
