# Justice — Branding Design Spec

**Date:** 2026-06-08  
**Status:** Approved

---

## Overview

Rename and rebrand the app from "ניהול תורנויות" to **Justice**. The brand name appears in English as a proper noun. The visual identity uses a purple scales-of-justice SVG illustration and the Cinzel typeface.

---

## Visual Identity

- **Name:** Justice (English, always)
- **Icon:** SVG scales of justice — Option A style (vertical pole, horizontal crossbeam, two hanging pans, triangular base, purple pivot circle)
- **Colors:** Purple palette — `#a78bfa` (arms/details), `#7c3aed` (fills/accent), matching the existing indigo-adjacent theme
- **Font:** [Cinzel](https://fonts.google.com/specimen/Cinzel) — vendored in the repo, served locally (no external dependency)

---

## Files Changed

### `frontend/public/fonts/` *(new directory)*
- Download Cinzel woff2 files (weights 400, 600, 700) from Google Fonts and commit them to the repo
- These are served statically by Vite alongside other public assets

### `frontend/src/styles/globals.css`
- Add `@font-face` declarations for Cinzel 400, 600, 700 pointing to `/fonts/Cinzel-*.woff2`

### `frontend/index.html`
- `<title>` changes from `ניהול תורנויות` to `Justice`
- Remove any Google Fonts `<link>` tags (font is now local)

### `frontend/tailwind.config.cjs`
- Add `cinzel: ['Cinzel', 'serif']` to `theme.extend.fontFamily`

### `frontend/src/components/JusticeLogo.tsx` *(new file)*
- Reusable React component
- Props: `size?: 'sm' | 'md' | 'lg'` (default `'md'`)
- Renders the SVG scales icon + "Justice" text in Cinzel side-by-side
- Size mapping:
  - `sm`: SVG 28px, text `text-xl`
  - `md`: SVG 36px, text `text-2xl`
  - `lg`: SVG 52px, text `text-4xl`
- SVG uses currentColor-friendly fixed purple values to stay consistent across dark/light mode

### `frontend/src/i18n/he.json`
- `app.title` → `"Justice"`

### `frontend/src/components/Layout.tsx`
- Replace `<h1 className="text-lg font-bold">{t("app.title")}</h1>` in the header center with `<JusticeLogo size="md" />`

### `frontend/src/pages/LoginPage.tsx`
- Add `<JusticeLogo size="lg" />` centered above the login form card

### `frontend/public/font-demo.html`
- Delete (was a temporary design exploration file)

### `frontend/public/favicon.svg` *(new file)*
- SVG favicon: the scales icon from `JusticeLogo` on a purple circular background
- Replaces the default Vite favicon

### `frontend/index.html`
- Add `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />` (replaces any existing favicon link)

---

## Out of Scope

- No color palette change beyond what already exists (purple/indigo stays)
- No changes to navigation labels or Hebrew UI copy
- No backend changes

---

## Success Criteria

1. Browser tab shows "Justice"
2. App header displays the scales SVG + "Justice" in Cinzel, centered
3. Login page shows the logo prominently above the form
4. No existing layout or functionality broken
5. Works in both light and dark mode
6. Browser tab shows the scales SVG favicon
