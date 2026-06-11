# Justice Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand the app as "Justice" — vendored Cinzel font, SVG scales logo component, favicon, and wired into the header and login page.

**Architecture:** A reusable `JusticeLogo` React component holds the scales SVG and Cinzel-styled name. The Cinzel woff2 files are committed to `frontend/public/fonts/` and declared via `@font-face` in `globals.css`. The component drops into `Layout.tsx` (header center) and `LoginPage.tsx` (above the form).

**Tech Stack:** React 18, TypeScript, Tailwind CSS v3, Vite, Vitest + @testing-library/react

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `frontend/public/fonts/Cinzel-400.woff2` | Create | Vendored Cinzel Regular |
| `frontend/public/fonts/Cinzel-600.woff2` | Create | Vendored Cinzel SemiBold |
| `frontend/public/fonts/Cinzel-700.woff2` | Create | Vendored Cinzel Bold |
| `frontend/src/styles/globals.css` | Modify | Add `@font-face` declarations for Cinzel |
| `frontend/tailwind.config.cjs` | Modify | Register `cinzel` font family |
| `frontend/src/components/JusticeLogo.tsx` | Create | Reusable logo: scales SVG + "Justice" in Cinzel |
| `frontend/src/components/JusticeLogo.test.tsx` | Create | Unit tests for JusticeLogo |
| `frontend/public/favicon.svg` | Create | Scales icon on purple circle for browser tab |
| `frontend/index.html` | Modify | Title → "Justice", add favicon link |
| `frontend/src/i18n/he.json` | Modify | `app.title` → `"Justice"` |
| `frontend/src/components/Layout.tsx` | Modify | Replace `<h1>{t("app.title")}</h1>` with `<JusticeLogo size="md" />` |
| `frontend/src/pages/LoginPage.tsx` | Modify | Add `<JusticeLogo size="lg" />` above the form |
| `frontend/public/font-demo.html` | Delete | Temporary design exploration file |

---

## Task 1: Download and vendor Cinzel font files

**Files:**
- Create: `frontend/public/fonts/Cinzel-400.woff2`
- Create: `frontend/public/fonts/Cinzel-600.woff2`
- Create: `frontend/public/fonts/Cinzel-700.woff2`
- Modify: `frontend/src/styles/globals.css`
- Modify: `frontend/tailwind.config.cjs`

- [ ] **Step 1: Create the fonts directory**

Run from `frontend/`:
```powershell
New-Item -ItemType Directory -Force "public/fonts" | Out-Null
```

- [ ] **Step 2: Download Cinzel woff2 files from Google Fonts**

Run from `frontend/`:
```powershell
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
$css = (Invoke-WebRequest -Uri "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&display=swap" -Headers @{"User-Agent"=$ua}).Content

New-Item -ItemType Directory -Force "public/fonts" | Out-Null

$blocks = [regex]::Split($css, '(?=@font-face)')
foreach ($block in $blocks) {
    if ($block -notmatch "font-family.*Cinzel") { continue }
    $weightMatch = [regex]::Match($block, 'font-weight:\s*(\d+)')
    $urlMatch = [regex]::Match($block, 'url\((https://[^)]+\.woff2)\)')
    if ($weightMatch.Success -and $urlMatch.Success) {
        $weight = $weightMatch.Groups[1].Value
        $url = $urlMatch.Groups[1].Value
        $outFile = "public/fonts/Cinzel-$weight.woff2"
        Invoke-WebRequest -Uri $url -OutFile $outFile
        Write-Host "Downloaded $outFile"
    }
}
```

Expected output:
```
Downloaded public/fonts/Cinzel-400.woff2
Downloaded public/fonts/Cinzel-600.woff2
Downloaded public/fonts/Cinzel-700.woff2
```

- [ ] **Step 3: Verify the files exist and are non-empty**

```powershell
Get-ChildItem "public/fonts/" | Select-Object Name, Length
```

Expected: three `.woff2` files, each at least 30 KB.

- [ ] **Step 4: Add `@font-face` declarations to `globals.css`**

In `frontend/src/styles/globals.css`, insert after the first line (`@import url("https://fonts.googleapis.com/...")`):

```css
@font-face {
  font-family: 'Cinzel';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts/Cinzel-400.woff2') format('woff2');
}

@font-face {
  font-family: 'Cinzel';
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url('/fonts/Cinzel-600.woff2') format('woff2');
}

@font-face {
  font-family: 'Cinzel';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url('/fonts/Cinzel-700.woff2') format('woff2');
}
```

- [ ] **Step 5: Register `cinzel` in Tailwind**

In `frontend/tailwind.config.cjs`, update `theme.extend.fontFamily`:

```js
fontFamily: {
  sans: ["Heebo", "Arial", "sans-serif"],
  cinzel: ["Cinzel", "serif"],
},
```

- [ ] **Step 6: Commit**

```bash
git add frontend/public/fonts/ frontend/src/styles/globals.css frontend/tailwind.config.cjs
git commit -m "feat: vendor Cinzel font and register in Tailwind"
```

---

## Task 2: Create JusticeLogo component (TDD)

**Files:**
- Create: `frontend/src/components/JusticeLogo.test.tsx`
- Create: `frontend/src/components/JusticeLogo.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/JusticeLogo.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import JusticeLogo from "./JusticeLogo";

describe("JusticeLogo", () => {
  test("renders the word Justice", () => {
    render(<JusticeLogo />);
    expect(screen.getByTestId("justice-logo-text")).toHaveTextContent("Justice");
  });

  test("contains an SVG element", () => {
    render(<JusticeLogo />);
    expect(screen.getByTestId("justice-logo").querySelector("svg")).not.toBeNull();
  });

  test("defaults to md size (text-2xl)", () => {
    render(<JusticeLogo />);
    expect(screen.getByTestId("justice-logo-text")).toHaveClass("text-2xl");
  });

  test("applies text-xl when size=sm", () => {
    render(<JusticeLogo size="sm" />);
    expect(screen.getByTestId("justice-logo-text")).toHaveClass("text-xl");
  });

  test("applies text-4xl when size=lg", () => {
    render(<JusticeLogo size="lg" />);
    expect(screen.getByTestId("justice-logo-text")).toHaveClass("text-4xl");
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

Run from `frontend/`:
```bash
pnpm test -- JusticeLogo
```

Expected: 5 failures — `JusticeLogo` module not found.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/JusticeLogo.tsx`:

```tsx
interface Props {
  size?: "sm" | "md" | "lg";
}

const SIZE_MAP = {
  sm: { svgSize: 28, textClass: "text-xl" },
  md: { svgSize: 36, textClass: "text-2xl" },
  lg: { svgSize: 52, textClass: "text-4xl" },
};

export default function JusticeLogo({ size = "md" }: Props) {
  const { svgSize, textClass } = SIZE_MAP[size];

  return (
    <div className="flex items-center gap-3" data-testid="justice-logo">
      <svg
        width={svgSize}
        height={svgSize}
        viewBox="0 0 52 52"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        {/* Pole */}
        <rect x="25" y="10" width="2" height="32" rx="1" fill="#a78bfa" />
        {/* Crossbeam */}
        <rect x="8" y="14" width="36" height="2.5" rx="1.25" fill="#a78bfa" />
        {/* Left chain */}
        <line x1="12" y1="16.5" x2="10" y2="25" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
        {/* Right chain */}
        <line x1="40" y1="16.5" x2="42" y2="25" stroke="#a78bfa" strokeWidth="1.5" strokeLinecap="round" />
        {/* Left pan */}
        <path d="M6 25 Q10 30 14 25" stroke="#a78bfa" strokeWidth="1.8" fill="#7c3aed33" strokeLinecap="round" />
        {/* Right pan */}
        <path d="M38 25 Q42 30 46 25" stroke="#a78bfa" strokeWidth="1.8" fill="#7c3aed33" strokeLinecap="round" />
        {/* Base strut */}
        <path d="M21 42 L26 10 L31 42" stroke="#a78bfa" strokeWidth="1.5" fill="none" strokeLinejoin="round" opacity="0.4" />
        {/* Base bar */}
        <rect x="18" y="42" width="16" height="2.5" rx="1.25" fill="#a78bfa" />
        {/* Center pivot circle */}
        <circle cx="26" cy="14" r="2.5" fill="#7c3aed" stroke="#a78bfa" strokeWidth="1" />
      </svg>
      <span
        className={`font-cinzel font-semibold tracking-widest text-indigo-700 dark:text-indigo-300 ${textClass}`}
        data-testid="justice-logo-text"
      >
        Justice
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pnpm test -- JusticeLogo
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/JusticeLogo.tsx frontend/src/components/JusticeLogo.test.tsx
git commit -m "feat: add JusticeLogo component with Cinzel font and scales SVG"
```

---

## Task 3: Create favicon and update index.html

**Files:**
- Create: `frontend/public/favicon.svg`
- Modify: `frontend/index.html`

- [ ] **Step 1: Create `frontend/public/favicon.svg`**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <!-- Purple circle background -->
  <circle cx="16" cy="16" r="16" fill="#7c3aed"/>
  <!-- Pole -->
  <rect x="15.25" y="5" width="1.5" height="22" rx="0.75" fill="#e9d5ff"/>
  <!-- Crossbeam -->
  <rect x="5" y="8.5" width="22" height="1.8" rx="0.9" fill="#e9d5ff"/>
  <!-- Pivot circle -->
  <circle cx="16" cy="9.4" r="2" fill="#4c1d95" stroke="#e9d5ff" stroke-width="0.8"/>
  <!-- Left chain -->
  <line x1="7.5" y1="10.3" x2="6.5" y2="16" stroke="#e9d5ff" stroke-width="1" stroke-linecap="round"/>
  <!-- Right chain -->
  <line x1="24.5" y1="10.3" x2="25.5" y2="16" stroke="#e9d5ff" stroke-width="1" stroke-linecap="round"/>
  <!-- Left pan -->
  <path d="M4 16 Q6.5 19.5 9 16" stroke="#e9d5ff" stroke-width="1.3" fill="#9333ea55" stroke-linecap="round"/>
  <!-- Right pan -->
  <path d="M23 16 Q25.5 19.5 28 16" stroke="#e9d5ff" stroke-width="1.3" fill="#9333ea55" stroke-linecap="round"/>
  <!-- Base bar -->
  <rect x="11" y="27" width="10" height="1.8" rx="0.9" fill="#e9d5ff"/>
</svg>
```

- [ ] **Step 2: Update `frontend/index.html`**

Change `<title>ניהול תורנויות</title>` to `<title>Justice</title>` and add the favicon link in `<head>`:

```html
<!DOCTYPE html>
<html lang="he" dir="rtl">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <title>Justice</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/public/favicon.svg frontend/index.html
git commit -m "feat: add Justice favicon and update page title"
```

---

## Task 4: Wire JusticeLogo into the app

**Files:**
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Delete: `frontend/public/font-demo.html`

- [ ] **Step 1: Update `app.title` in `he.json`**

In `frontend/src/i18n/he.json`, change line 3:
```json
"title": "Justice",
```

(was `"title": "ניהול תורנויות"`)

- [ ] **Step 2: Update `Layout.tsx` — swap the title for the logo**

In `frontend/src/components/Layout.tsx`:

Add import at the top:
```tsx
import JusticeLogo from "./JusticeLogo";
```

Replace:
```tsx
{/* Center: app title */}
<h1 className="text-lg font-bold">{t("app.title")}</h1>
```

With:
```tsx
{/* Center: app logo */}
<JusticeLogo size="md" />
```

- [ ] **Step 3: Update `LoginPage.tsx` — add logo above the form**

In `frontend/src/pages/LoginPage.tsx`:

Add import at the top:
```tsx
import JusticeLogo from "../components/JusticeLogo";
```

Replace the opening of the `<main>` content:
```tsx
<main className="min-h-screen flex items-center justify-center p-6 dark:bg-gray-900">
  <form onSubmit={onSubmit} className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4 dark:bg-gray-800" data-testid="login-form">
```

With:
```tsx
<main className="min-h-screen flex flex-col items-center justify-center p-6 gap-8 dark:bg-gray-900">
  <JusticeLogo size="lg" />
  <form onSubmit={onSubmit} className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4 dark:bg-gray-800" data-testid="login-form">
```

- [ ] **Step 4: Delete the font demo file**

```bash
git rm frontend/public/font-demo.html
```

- [ ] **Step 5: Run the full test suite**

```bash
cd frontend && pnpm test
```

Expected: all tests pass (JusticeLogo suite + existing suites).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/components/Layout.tsx frontend/src/pages/LoginPage.tsx
git commit -m "feat: wire JusticeLogo into header and login page, update app title to Justice"
```

---

## Manual Verification Checklist

After all tasks complete, start the dev server (`pnpm dev` in `frontend/`) and confirm:

- [ ] Browser tab reads "Justice" with the purple scales favicon
- [ ] App header shows the scales SVG + "Justice" in Cinzel, centered
- [ ] Login page shows the large logo above the white card
- [ ] No requests to `fonts.googleapis.com` in DevTools Network tab for Cinzel (Heebo still loads externally — that's expected and out of scope)
- [ ] Layout looks correct in dark mode (indigo-300 text on dark background)
