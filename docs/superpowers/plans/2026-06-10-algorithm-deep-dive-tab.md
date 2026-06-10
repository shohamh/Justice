# Algorithm Deep-Dive Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "🔬 מאחורי הקלעים" tab to `HelpModal` that explains the L1 effort-score objective with a math warning, every term defined, and a complete worked example.

**Architecture:** Single `DeepDiveTab` function component added to `HelpModal.tsx` in the l1-effort-objective worktree. Pure static content — no API calls, no state, no new dependencies. Tab registered in `buildTabs()` unconditionally (all roles).

**Tech Stack:** React, TypeScript, Tailwind CSS. All work is in `frontend/src/components/HelpModal.tsx`.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `frontend/src/components/HelpModal.tsx` | Modify | Add `DeepDiveTab` component; register tab in `buildTabs()`; add render case; add `overflow-x-auto` to tab row |

No other files change. No backend changes.

---

### Task 1: Register tab + skeleton component

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`

- [ ] **Step 1: Add the deep tab to `buildTabs()`**

In `buildTabs()`, add the new entry **before** the optional gimelim push (so it always appears):

```tsx
function buildTabs(gimelimEnabled: boolean) {
  const tabs = [
    { id: "swaps", label: "🔄 החלפות" },
    { id: "algorithm", label: "⚙️ האלגוריתם" },
    { id: "fairness", label: "⚖️ הוגנות ושקיפות" },
    { id: "deep", label: "🔬 מאחורי הקלעים" },
  ];
  if (gimelimEnabled) {
    tabs.push({ id: "gimelim", label: "🏥 גימלים" });
  }
  return tabs;
}
```

- [ ] **Step 2: Add `overflow-x-auto` to the tab row**

Five tabs can overflow on small screens. Find the tab row div (line ~440) and add `overflow-x-auto`:

```tsx
<div className="flex border-b dark:border-gray-600 px-2 pt-1 overflow-x-auto" dir="rtl">
```

- [ ] **Step 3: Add the skeleton `DeepDiveTab` component**

Add this function before `HelpModal` (e.g. right after `GimelimTab`):

```tsx
function DeepDiveTab() {
  return (
    <div className="space-y-5 text-sm leading-relaxed" dir="rtl">
      <p className="text-gray-400 text-xs">טוען...</p>
    </div>
  );
}
```

- [ ] **Step 4: Wire up the render case**

In the content section of `HelpModal` (the block with `{activeTab === "swaps" && <SwapsTab />}` etc.), add:

```tsx
{activeTab === "deep" && <DeepDiveTab />}
```

- [ ] **Step 5: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: register deep-dive tab skeleton in HelpModal"
```

---

### Task 2: Math warning banner + section 1 (הבעיה)

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` — replace the skeleton body of `DeepDiveTab`

- [ ] **Step 1: Replace the skeleton with warning banner + section 1**

Replace the entire body of `DeepDiveTab` with:

```tsx
function DeepDiveTab() {
  return (
    <div className="space-y-5 text-sm leading-relaxed" dir="rtl">

      {/* ── Math warning ── */}
      <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 text-amber-800 dark:text-amber-300 text-xs">
        ⚠️ <strong>הסבר מתמטי</strong> — הסעיף הזה מכיל נוסחאות. כל מושג מוסבר גם במילים פשוטות — קראו לפי הנוח לכם.
      </div>

      {/* ── Section 1: הבעיה ── */}
      <section className="space-y-2">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">⚖️ הבעיה: למה לספור תורנויות לא מספיק?</h3>
        <p className="text-gray-700 dark:text-gray-300">
          נניח ששני חיילים עשו כל אחד 10 תורנויות השנה. האם הם שוויוניים?
          לא בהכרח — אחד שירת 300 ימים, השני רק 30. ביחס לזמן שכל אחד היה זמין,
          השני נשא עומס כפול פי 10.
        </p>
        <p className="text-gray-700 dark:text-gray-300">
          ספירת תורנויות גולמית מתעלמת משלושה גורמים:
        </p>
        <ul className="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-400 pr-2">
          <li><strong>זמן שירות</strong> — חייל חדש לא ניתן להשוות לוותיק ישירות.</li>
          <li><strong>משקל התורנות</strong> — תורנות ארוכה שווה יותר מקצרה.</li>
          <li><strong>גודל היחידה</strong> — אם היחידה צמחה, מאגר התורנויות גדל איתה.</li>
        </ul>
        <p className="text-gray-700 dark:text-gray-300">
          הפתרון: במקום לספור, מודדים <strong>חלק יחסי</strong> — איזה אחוז מסך עומס היחידה נשא החייל,
          יחסית לכמה זמן הוא היה פעיל.
        </p>
      </section>

    </div>
  );
}
```

- [ ] **Step 2: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: deep-dive tab — math warning and problem statement"
```

---

### Task 3: Section 2 — effort_score formula

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` — append to `DeepDiveTab` body

- [ ] **Step 1: Add section 2 inside `DeepDiveTab`**

After the closing `</section>` of section 1, add:

```tsx
      {/* ── Section 2: effort_score ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">📐 ניקוד עומס — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">effort_score = A / D</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          לכל חייל מחושב ציון אחד — <strong>עומס רבעוני ממוצע</strong>. הוא מייצג: מתוך כל התורנויות שהיחידה עשתה,
          כמה אחוז נשא החייל בכל רבעון שהיה פעיל בו, בממוצע משוקלל.
        </p>

        {/* Term table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse" style={{ minWidth: "420px" }}>
            <thead>
              <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                <th className="text-right py-1 pr-2 font-medium w-20">סמל</th>
                <th className="text-right py-1 pr-2 font-medium w-32">שם</th>
                <th className="text-right py-1 font-medium">הסבר</th>
              </tr>
            </thead>
            <tbody className="text-gray-700 dark:text-gray-300">
              {[
                { sym: "shareq", name: "חלק רבעוני", def: "ניקוד החייל ברבעון q ÷ ניקוד כלל היחידה ברבעון q. מספר בין 0 ל-1." },
                { sym: "active_fracq", name: "שבר נוכחות", def: "חלק הרבעון שבו החייל היה פעיל (0–1). רבעון מלא = 1." },
                { sym: "A", name: "עומס שנצבר", def: "Σ(shareq × active_fracq) על כל הרבעונים ההיסטוריים. ממוצע משוקלל של החלקים." },
                { sym: "W", name: "היסטוריה כוללת", def: "Σ(active_fracq) על הרבעונים ההיסטוריים. סכום משקלי הנוכחות." },
                { sym: "C", name: "רבעון נוכחי", def: "תמיד 1. מייצג סיבוב התכנון הנוכחי. נכנס למכנה בלבד — אין לו עדיין תרומה לעומס שנצבר." },
                { sym: "D", name: "מכנה", def: "W + C" },
                { sym: "effort_score", name: "עומס רבעוני", def: "A / D — ממוצע החלק הרבעוני על פני כל התקופה שבה שירת החייל." },
              ].map(({ sym, name, def }) => (
                <tr key={sym} className="border-b border-gray-100 dark:border-gray-700">
                  <td className="py-1.5 pr-2 font-mono text-indigo-700 dark:text-indigo-300">{sym}</td>
                  <td className="py-1.5 pr-2 font-medium">{name}</td>
                  <td className="py-1.5">{def}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs space-y-1">
          <p className="font-medium text-indigo-800 dark:text-indigo-200">💡 למה C תמיד 1?</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            לפני כל סיבוב, המכנה של <em>כולם</em> גדל ב-1 — גם אם עוד לא שובצו תורנויות.
            זה "מדלל" את הציון הנוכחי של כולם, ומכריח ותיקים להרוויח מחדש את חלקם.
            חייל שישב בחופשה כל הרבעון לא יכול לנוח על ניקוד עבר.
          </p>
        </div>

        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-xs space-y-1">
          <p className="font-medium text-gray-800 dark:text-gray-200">📝 דוגמה</p>
          <p className="text-gray-600 dark:text-gray-300">
            חייל שירת 4 רבעונות מלאים, ותמיד נשא 5% מעומס היחידה:
          </p>
          <ul className="list-none space-y-0.5 text-gray-600 dark:text-gray-300 pr-2">
            <li>A = 4 × 0.05 = 0.20</li>
            <li>W = 4.0, C = 1.0, D = 5.0</li>
            <li className="font-semibold text-indigo-700 dark:text-indigo-300">effort_score = 0.20 / 5.0 = 0.04 (4%)</li>
          </ul>
        </div>
      </section>
```

- [ ] **Step 2: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: deep-dive tab — effort_score formula and term table"
```

---

### Task 4: Section 3 — effort_offset and effort_per_milli

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` — append to `DeepDiveTab` body

- [ ] **Step 1: Add section 3 after the closing `</section>` of section 2**

```tsx
      {/* ── Section 3: Integer bridge ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🔢 מהמספר לשלם — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">effort_offset</code> ו-<code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">effort_per_milli</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          פותר ה-CP-SAT עובד עם <strong>מספרים שלמים בלבד</strong> — לא עשרוניים.
          לכן לפני שמעבירים לו את הנתונים, מחשבים מראש שני קבועים שלמים לכל חייל:
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse" style={{ minWidth: "420px" }}>
            <thead>
              <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                <th className="text-right py-1 pr-2 font-medium w-36">שם</th>
                <th className="text-right py-1 pr-2 font-medium w-48">נוסחה</th>
                <th className="text-right py-1 font-medium">משמעות</th>
              </tr>
            </thead>
            <tbody className="text-gray-700 dark:text-gray-300">
              {[
                {
                  name: "EFFORT_SCALE",
                  formula: "10⁹",
                  meaning: "גורם קנה-מידה. ממיר עשרוניים לשלמים בלי אובדן דיוק.",
                },
                {
                  name: "effort_offset",
                  formula: "int(effort_score × EFFORT_SCALE)",
                  meaning: "ניקוד העומס ההיסטורי כשלם קבוע. לא משתנה בזמן הפתרון.",
                },
                {
                  name: "unit_score_milli",
                  formula: "Σ block_score(d) × 1000 לכל תורנויות החלון",
                  meaning: "סך ניקוד כל התורנויות שהפותר יכול לשבץ — קבוע.",
                },
                {
                  name: "C_over_D",
                  formula: "C / D",
                  meaning: "כמה מהמשקל הכולל מיוחס לסיבוב הנוכחי. גבוה לחיילים חדשים (W קטן), נמוך לוותיקים.",
                },
                {
                  name: "effort_per_milli",
                  formula: "int(C_over_D / unit_score_milli × EFFORT_SCALE)",
                  meaning: "כמה כל מילי-ניקוד אחד של תורנות מזיז את עומס החייל. קבוע — מחושב לפני הפתרון.",
                },
              ].map(({ name, formula, meaning }) => (
                <tr key={name} className="border-b border-gray-100 dark:border-gray-700">
                  <td className="py-1.5 pr-2 font-mono text-indigo-700 dark:text-indigo-300">{name}</td>
                  <td className="py-1.5 pr-2 font-mono text-gray-600 dark:text-gray-400">{formula}</td>
                  <td className="py-1.5">{meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs space-y-1">
          <p className="font-medium text-indigo-800 dark:text-indigo-200">💡 האינרציה של הוותיק</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            לחייל ותיק עם W=8 יש C_over_D = 1/(8+1) ≈ 0.11.
            לחייל חדש עם W=0 יש C_over_D = 1/(0+1) = 1.0.
            כלומר: אותה תורנות בדיוק מזיזה את ניקוד החדש פי 9 יותר מאשר את הוותיק.
            לחייל ותיק יש "עמידות" גבוהה יותר לשינויים — צריך הרבה תורנויות כדי להזיז אותו.
          </p>
        </div>
      </section>
```

- [ ] **Step 2: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: deep-dive tab — effort_offset and effort_per_milli"
```

---

### Task 5: Section 4 — projected_effort

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` — append to `DeepDiveTab` body

- [ ] **Step 1: Add section 4 after the closing `</section>` of section 3**

```tsx
      {/* ── Section 4: projected_effort ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🎯 הניקוד הצפוי — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">projected_effort</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          בתוך הפותר, לכל חייל נבנית <strong>ביטוי לינארי</strong> שמחשב מה יהיה ניקוד העומס שלו
          לאחר שיבוץ:
        </p>

        <pre className="font-mono text-xs bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto leading-relaxed text-gray-800 dark:text-gray-200 whitespace-pre">{`projected_effort[i] =
    effort_offset[i]
  + effort_per_milli[i] × Σ( block_score(d) × x[d,i] )`}</pre>

        <div className="space-y-2 text-xs text-gray-700 dark:text-gray-300">
          {[
            {
              term: "x[d, i]",
              desc: "משתנה בינארי של הפותר: 1 אם תורנות d שובצה לחייל i, 0 אחרת. זה מה שהפותר בוחר.",
            },
            {
              term: "block_score(d)",
              desc: "ניקוד תורנות d (משך ימים × משקל סוג התורנות), ביחידות מילי. קבוע.",
            },
            {
              term: "Σ block_score(d) × x[d,i]",
              desc: "סך הניקוד של כל התורנויות ששובצו לחייל i. ביטוי לינארי — סכום של קבועים כפול משתנים.",
            },
          ].map(({ term, desc }) => (
            <div key={term} className="flex gap-2 bg-gray-50 dark:bg-gray-700 rounded p-2 border border-gray-200 dark:border-gray-600">
              <code className="shrink-0 text-indigo-700 dark:text-indigo-300 font-mono">{term}</code>
              <span>{desc}</span>
            </div>
          ))}
        </div>

        <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800 text-xs space-y-1">
          <p className="font-medium text-green-800 dark:text-green-200">✅ למה זה חשוב — לינאריות</p>
          <p className="text-green-700 dark:text-green-300">
            <code>effort_per_milli</code> ו-<code>block_score(d)</code> הם קבועים שלמים — רק <code>x[d,i]</code> הם משתנים.
            הביטוי כולו לינארי לחלוטין — אין חילוק, אין ריבועים.
            CP-SAT פותר בעיות לינאריות מהר מאוד.
          </p>
          <p className="text-green-700 dark:text-green-300 mt-1">
            בגרסה הקודמת, הניקוד חולק ב-<code>active_days</code> בתוך הפותר — אילוץ חילוק שהאט את הפתרון.
            כאן, החילוק מתבצע פעם אחת מחוץ לפותר (בחישוב <code>effort_per_milli</code>) — וזה מה שהופך את הגישה לסקלאבילית.
          </p>
        </div>
      </section>
```

- [ ] **Step 2: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: deep-dive tab — projected_effort formula"
```

---

### Task 6: Sections 5–6 — L1 deviation + final objective

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` — append to `DeepDiveTab` body

- [ ] **Step 1: Add sections 5 and 6 after the closing `</section>` of section 4**

```tsx
      {/* ── Section 5: L1 ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">📏 מה זה L1? — מדיאנה, לא ממוצע</h3>
        <p className="text-gray-700 dark:text-gray-300">
          רוצים שכל הניקודים יהיו קרובים זה לזה. אבל "קרוב" ניתן להגדיר בשתי דרכים:
        </p>

        <div className="grid grid-cols-1 gap-2 text-xs">
          <div className="bg-orange-50 dark:bg-orange-950 rounded-lg p-3 border border-orange-200 dark:border-orange-800">
            <p className="font-semibold text-orange-800 dark:text-orange-200 mb-1">L2 — סכום ריבועי סטיות (הממוצע)</p>
            <p className="font-mono text-orange-700 dark:text-orange-300 mb-1">Σ (projected_effort[i] − mean)²</p>
            <p className="text-orange-700 dark:text-orange-300">
              ריבוע הסטייה מעניש קשות על חריגים. ערך חריג אחד יכול לדחוף את כל השיבוצים
              בניסיון להקטין אותו — גם כשזה לא הוגן לשאר.
            </p>
          </div>
          <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800">
            <p className="font-semibold text-green-800 dark:text-green-200 mb-1">L1 — סכום סטיות מוחלטות (המדיאנה) ✓</p>
            <p className="font-mono text-green-700 dark:text-green-300 mb-1">Σ |projected_effort[i] − target|</p>
            <p className="text-green-700 dark:text-green-300">
              כל סטייה נספרת באותו משקל, ללא קנס על חריגים. הפתרון האופטימלי מושך את
              <code className="mx-1">target</code> לכיוון <strong>המדיאנה</strong> — עמיד בפני ותיקים עם היסטוריה גבוהה מאוד.
            </p>
          </div>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs">
          <p className="font-medium text-indigo-800 dark:text-indigo-200 mb-1">💡 משתנה target חופשי</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            לא קובעים מראש מה המטרה. הפותר מוסיף משתנה שלם <code>target</code> ומוצא את ערכו יחד עם שאר המשתנים.
            מתמטית, הערך האופטימלי של <code>target</code> הוא תמיד המדיאנה של הניקודים הצפויים —
            הפותר "מגלה" זאת מעצמו.
          </p>
        </div>
      </section>

      {/* ── Section 6: Final objective ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🏁 המטרה הסופית</h3>
        <p className="text-gray-700 dark:text-gray-300">
          לכל חייל נוצר משתנה עזר <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">dev[i]</code> עם שני אילוצים:
        </p>

        <pre className="font-mono text-xs bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto text-gray-800 dark:text-gray-200 leading-relaxed whitespace-pre">{`dev[i] ≥  projected_effort[i] − target
dev[i] ≥  target − projected_effort[i]`}</pre>

        <p className="text-gray-700 dark:text-gray-300 text-xs">
          שני האילוצים האלה כופים ש-<code>dev[i] = |projected_effort[i] − target|</code>.
          הפותר ימזער את <code>dev[i]</code> כמה שניתן — כי הוא מופיע בפונקציית המטרה:
        </p>

        <pre className="font-mono text-xs bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto text-indigo-700 dark:text-indigo-300 font-bold leading-relaxed whitespace-pre">{`Minimize  Σ dev[i]  +  dist_term`}</pre>

        <p className="text-gray-600 dark:text-gray-400 text-xs">
          <code>dist_term</code> — קנס קטן על שיבוץ חיילי רזרבה ליחידות רחוקות בהיררכיה.
          משמש כשובר שוויון בלבד — משקלו קטן בהרבה מסכום הסטיות.
        </p>
      </section>
```

- [ ] **Step 2: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: deep-dive tab — L1 deviation and final objective"
```

---

### Task 7: Section 7 — Worked numerical example

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx` — append to `DeepDiveTab` body

- [ ] **Step 1: Add section 7 after the closing `</section>` of section 6**

The numbers use EFFORT_SCALE=1,000,000 (not the real 10⁹) to keep values readable.
Verification: unit_score_milli=5000, C_over_D_dan=0.20 → effort_per_milli_dan = int(0.20/5000×1,000,000) = 40. ✓

```tsx
      {/* ── Section 7: Worked example ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🧮 דוגמה מספרית מלאה</h3>

        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
          המספרים נבחרו לקריאות (EFFORT_SCALE=1,000,000 במקום 10⁹). היחסים בין הערכים זהים לייצור.
        </div>

        <p className="text-xs font-medium text-gray-700 dark:text-gray-300">הגדרה: 3 חיילים, 2 תורנויות זהות (score_milli=2,500 כל אחת → unit_score_milli=5,000)</p>

        {/* Soldier table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse" style={{ minWidth: "460px" }}>
            <thead>
              <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                {["חייל", "effort_score", "effort_offset", "C_over_D", "effort_per_milli"].map(h => (
                  <th key={h} className="text-right py-1 pr-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="text-gray-700 dark:text-gray-300">
              {[
                { name: "דן (ותיק)", score: "4%", offset: "40,000", cod: "0.20", epm: "40", color: "text-blue-700 dark:text-blue-300" },
                { name: "יעל (חדשה)", score: "0%", offset: "0", cod: "1.00", epm: "200", color: "text-purple-700 dark:text-purple-300" },
                { name: "רוני (ותיק)", score: "8%", offset: "80,000", cod: "0.20", epm: "40", color: "text-orange-700 dark:text-orange-300" },
              ].map(({ name, score, offset, cod, epm, color }) => (
                <tr key={name} className="border-b border-gray-100 dark:border-gray-700">
                  <td className={`py-1.5 pr-3 font-medium ${color}`}>{name}</td>
                  <td className="py-1.5 pr-3 font-mono">{score}</td>
                  <td className="py-1.5 pr-3 font-mono">{offset}</td>
                  <td className="py-1.5 pr-3 font-mono">{cod}</td>
                  <td className="py-1.5 font-mono">{epm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-gray-600 dark:text-gray-400">
          שים לב: <code>effort_per_milli</code> של יעל הוא 200 — פי 5 מהותיקים. כי C_over_D שלה = 1.0 (אין היסטוריה).
        </p>

        {/* Assignment A */}
        <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800 text-xs space-y-2">
          <p className="font-semibold text-green-800 dark:text-green-200">שיבוץ א׳ (הפותר יבחר בזה): תורנות 1→דן, תורנות 2→רוני</p>
          <pre className="font-mono text-green-700 dark:text-green-300 leading-relaxed whitespace-pre">{`projected[דן]  = 40,000 + 40  × 2,500 = 140,000  (14%)
projected[יעל] =      0 + 200 × 0     =       0   ( 0%)
projected[רוני]= 80,000 + 40  × 2,500 = 180,000  (18%)`}</pre>
          <pre className="font-mono text-green-700 dark:text-green-300 leading-relaxed whitespace-pre">{`target = מדיאנה = 140,000
dev[דן]  = |140,000 − 140,000| =       0
dev[יעל] = |      0 − 140,000| = 140,000
dev[רוני]= |180,000 − 140,000| =  40,000
──────────────────────────────────────────
סה"כ = 180,000`}</pre>
        </div>

        {/* Assignment B */}
        <div className="bg-red-50 dark:bg-red-950 rounded-lg p-3 border border-red-200 dark:border-red-800 text-xs space-y-2">
          <p className="font-semibold text-red-800 dark:text-red-200">שיבוץ ב׳ (גרוע יותר): תורנות 1→דן, תורנות 2→יעל</p>
          <pre className="font-mono text-red-700 dark:text-red-300 leading-relaxed whitespace-pre">{`projected[דן]  = 40,000 + 40  × 2,500 = 140,000  (14%)
projected[יעל] =      0 + 200 × 2,500 = 500,000  (50%)  ← זינוק!
projected[רוני]=      80,000           =  80,000  ( 8%)`}</pre>
          <pre className="font-mono text-red-700 dark:text-red-300 leading-relaxed whitespace-pre">{`target = מדיאנה = 140,000
dev[דן]  =       0
dev[יעל] = 360,000
dev[רוני]=  60,000
──────────────────────────────────────────
סה"כ = 420,000  ← פי 2.3 יותר גרוע!`}</pre>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs space-y-1">
          <p className="font-semibold text-indigo-800 dark:text-indigo-200">🔑 תובנה מפתח</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            הפותר <strong>לא</strong> פשוט משבץ את החייל עם הניקוד הנמוך ביותר.
            הוא שוקל כמה כל שיבוץ <em>מזיז</em> את הניקוד של כל חייל.
            יעל מתחילה ב-0%, אבל כל תורנות "שווה לה" פי 5 יותר מאשר לוותיקים —
            כי היא חדשה. שיבוץ אחד יזניק אותה ל-50% ויצור חריג גדול.
            עדיף לפזר בין שני הוותיקים ולאפשר ליעל להתכנס בהדרגה לאורך מספר סיבובים.
          </p>
        </div>
      </section>

```

- [ ] **Step 2: Verify lint passes**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "feat: deep-dive tab — complete worked numerical example"
```

---

### Task 8: Manual verification

- [ ] **Step 1: Start the dev stack**

```powershell
.\dev.ps1 -NoBot
```

- [ ] **Step 2: Open the app and trigger the help modal**

Navigate to `http://localhost:5173`. Click the help/question-mark button that opens `HelpModal`.

- [ ] **Step 3: Check all tabs still work**

Click "🔄 החלפות", "⚙️ האלגוריתם", "⚖️ הוגנות ושקיפות" — all should render normally.

- [ ] **Step 4: Check the new tab**

Click "🔬 מאחורי הקלעים". Verify:
- Amber warning banner visible at top
- All 7 sections render with Hebrew text
- Formula blocks in monospace
- Term tables scroll horizontally on narrow screens (resize browser to 375px width to verify)
- Green/red example boxes both visible in section 7
- Dark mode: toggle dark mode, confirm all color classes render correctly (no white-on-white or black-on-black)

- [ ] **Step 5: Check tab overflow on narrow modal**

Resize browser to ~400px. The tab row should scroll horizontally without wrapping.

