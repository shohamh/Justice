import { useEffect, useState } from "react";
import { BlockMath, InlineMath } from "react-katex";
import { useAuth } from "../auth/AuthContext";
import { authenticated, canApprove, canPlan, PermissionUser } from "../auth/permissions";
import { BurdenShareBreakdown, getBurdenShareBreakdown } from "../api/scoring";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { useModalBackClose } from "../hooks/useModalBackClose";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { ShiftTemplate, listTemplates } from "../api/shiftTemplates";
import AlgorithmModeExplainer from "./AlgorithmModeExplainer";

interface Props {
  onClose: () => void;
  gimelimEnabled?: boolean;
  hakpazaEnabled?: boolean;
  initialTab?: string;
}

interface HelpTabDef {
  id: string;
  label: string;
  visible: (user: PermissionUser | null, gimelimEnabled: boolean, hakpazaEnabled: boolean) => boolean;
}

const TAB_DEFS: HelpTabDef[] = [
  { id: "swaps", label: "🔄 החלפות", visible: (u) => authenticated(u) },
  { id: "algorithm", label: "⚙️ האלגוריתם", visible: (u) => authenticated(u) },
  { id: "scoring", label: "🏅 ניקוד", visible: (u) => authenticated(u) },
  { id: "active_days", label: "❔ ימים פעילים", visible: (u) => authenticated(u) },
  { id: "fairness", label: "⚖️ הוגנות ושקיפות", visible: (u) => authenticated(u) },
  { id: "deep", label: "🔬 מאחורי הקלעים", visible: (u) => authenticated(u) },
  { id: "approvals", label: "✅ אישורים", visible: (u) => canApprove(u) },
  { id: "hierarchy", label: "🌳 היררכיה וכשירות", visible: (u) => authenticated(u) },
  { id: "hakpaza", label: "📣 הקפצה פיקודית", visible: (u, _gimelimEnabled, hakpazaEnabled) => canApprove(u) && hakpazaEnabled },
  { id: "gimelim", label: "🏥 גימלים", visible: (u, gimelimEnabled) => authenticated(u) && gimelimEnabled },
  { id: "import", label: "📥 ייבוא", visible: (u) => canPlan(u) },
];

function buildTabs(user: PermissionUser | null, gimelimEnabled: boolean, hakpazaEnabled: boolean): HelpTabDef[] {
  return TAB_DEFS.filter((t) => t.visible(user, gimelimEnabled, hakpazaEnabled));
}

function FlowStep({
  icon, text, color = "indigo", detail, expanded, onToggle,
}: {
  icon: string; text: string; color?: string; detail?: string; expanded?: boolean; onToggle?: () => void;
}) {
  const colors: Record<string, string> = {
    indigo: "bg-indigo-50 dark:bg-indigo-950 border-indigo-200 dark:border-indigo-800 text-indigo-800 dark:text-indigo-200",
    green: "bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800 text-green-800 dark:text-green-200",
    red: "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200",
    amber: "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200",
    blue: "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-800 dark:text-blue-200",
    gray: "bg-gray-50 dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300",
  };
  const clickable = !!detail;
  return (
    <div>
      <div
        className={`border rounded-lg px-3 py-2 text-sm font-medium text-center ${colors[color] ?? colors.indigo} ${clickable ? "cursor-pointer hover:opacity-80" : ""}`}
        onClick={clickable ? onToggle : undefined}
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
      >
        {icon} {text} {clickable && (expanded ? "▲" : "▼")}
      </div>
      {clickable && expanded && (
        <div className="mt-1 text-xs bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg p-2 text-gray-600 dark:text-gray-300">
          {detail}
        </div>
      )}
    </div>
  );
}

function Arrow({ split }: { split?: boolean }) {
  if (split) {
    return (
      <div className="flex items-start gap-1 my-1">
        <div className="flex flex-col items-center flex-1">
          <div className="text-gray-400 text-xs mb-0.5">פתוח לכולם</div>
          <div className="text-gray-300 text-lg">↓</div>
        </div>
        <div className="flex flex-col items-center flex-1">
          <div className="text-gray-400 text-xs mb-0.5">חייל ספציפי</div>
          <div className="text-gray-300 text-lg">↓</div>
        </div>
      </div>
    );
  }
  return <div className="text-center text-gray-300 text-lg my-0.5">↓</div>;
}

function SwapsTab() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const toggle = (id: string) => setExpanded((cur) => (cur === id ? null : id));

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">איך עובדות החלפות?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        מנגנון ההחלפות מאפשר לשני חיילים להחליף ביניהם תורנויות, בכפוף לאישור. לחצו על כל שלב כדי לראות מה קורה בפועל ולמה:
      </p>

      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600">
        <FlowStep
          icon="🙋" text="חייל מגיש בקשת החלפה" color="indigo"
          detail="החייל בוחר תורנות שלו ומבקש שמישהו אחר יבצע אותה במקומו. הבקשה יכולה להיות פתוחה (כל חייל יכול להציע עצמו) או ממוקדת לחייל ספציפי."
          expanded={expanded === "request"} onToggle={() => toggle("request")}
        />
        <Arrow split />
        <div className="grid grid-cols-2 gap-2">
          <FlowStep
            icon="📢" text="מתפרסם בלוח ההחלפות" color="blue"
            detail="כל חייל ביחידה יכול לראות את הבקשה ולהציע את עצמו כמחליף — שימושי כשלא ידוע מראש מי פנוי."
            expanded={expanded === "board"} onToggle={() => toggle("board")}
          />
          <FlowStep
            icon="📩" text="נשלחת הודעה לחייל המבוקש" color="blue"
            detail="רק החייל שצוין רואה את הבקשה ומחליט אם לאשר או לדחות אותה."
            expanded={expanded === "targeted"} onToggle={() => toggle("targeted")}
          />
        </div>
        <Arrow />
        <FlowStep
          icon="🤝" text="חייל מציע להחליף ושני הצדדים מאשרים" color="indigo"
          detail="שני החיילים חייבים להסכים לפני שהבקשה ממשיכה לשלב האישור הפיקודי."
          expanded={expanded === "agree"} onToggle={() => toggle("agree")}
        />
        <Arrow />
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">נדרש אישור</div>
            <FlowStep
              icon="👮" text="מפקד אחד מהשרשרת מאשר" color="amber"
              detail="מספיק אישור אחד ממפקד רלוונטי לאחד הצדדים; אם אותו מפקד אחראי על שני הצדדים, האישור שלו מכסה את שניהם בבת אחת."
              expanded={expanded === "cmd-approve"} onToggle={() => toggle("cmd-approve")}
            />
            <FlowStep
              icon="🗂️" text="אחראי תורנויות מאשר" color="amber"
              detail="נדרש גם אישור נפרד של אחראי תורנויות — מפקד יכול לדחות גם אם אחראי התורנויות כבר אישר, וההפך."
              expanded={expanded === "dm-approve"} onToggle={() => toggle("dm-approve")}
            />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
          <div className="space-y-1">
            <div className="text-center text-xs text-gray-400">ללא אישור</div>
            <div className="h-16" />
            <Arrow />
            <FlowStep icon="✅" text="ההחלפה בוצעה!" color="green" />
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="bg-blue-50 dark:bg-blue-950 rounded-lg p-3 border border-blue-200 dark:border-blue-800">
          <p className="font-medium text-blue-800 dark:text-blue-200 mb-1">📌 בקשה פתוחה</p>
          <p className="text-blue-700 dark:text-blue-300">לא יודעים מי יחליף? כל חייל ביחידה יכול לראות את הבקשה ולהציע עצמו.</p>
        </div>
        <div className="bg-purple-50 dark:bg-purple-950 rounded-lg p-3 border border-purple-200 dark:border-purple-800">
          <p className="font-medium text-purple-800 dark:text-purple-200 mb-1">📌 בקשה ממוקדת</p>
          <p className="text-purple-700 dark:text-purple-300">יש מישהו ספציפי? ציינו אותו — הוא יקבל התראה ויאשר או ידחה.</p>
        </div>
        <div className="bg-amber-50 dark:bg-amber-950 rounded-lg p-3 border border-amber-200 dark:border-amber-800">
          <p className="font-medium text-amber-800 dark:text-amber-200 mb-1">⚠️ חשוב לדעת</p>
          <ul className="text-amber-700 dark:text-amber-300 space-y-1 list-disc list-inside">
            <li>החלפה אינה משפיעה על הניקוד — הניקוד נשאר על מי שסיפק את התורנות בפועל.</li>
            <li>המפקד רשאי לדחות גם אם שני הצדדים הסכימו.</li>
            <li>אם אותו מפקד או אותו אחראי תורנויות אחראים על שני הצדדים, אישור אחד שלו מספיק לשניהם.</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function AlgorithmTab({ user }: { user: PermissionUser | null }) {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">איך האלגוריתם מחלק תורנויות?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        האלגוריתם פותר את <strong>כל המשמרות בבת אחת</strong> — לא אחת אחרי השנייה — ומחפש שיבוץ שמכסה את כולן תוך שמירה על כל הכללים:
      </p>

      {/* Flow diagram */}
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="📋" text="כל המשמרות והחיילים נאספים; נבנה גרף כשירות" color="gray" />
        <Arrow />
        <FlowStep icon="🔗" text="חלוקה לרכיבים קשורים — קבוצות משמרות+חיילים עצמאיות" color="gray" />
        <Arrow />
        <FlowStep icon="0️⃣" text="שלב 0: ניסיון לכסות את כל הרכיב בבת אחת" color="blue" />
        <Arrow />
        <FlowStep icon="1️⃣" text="שלב 1: חיילים ממוינים לפי חלק בנטל, נפתרים קבוצה-קבוצה" color="indigo" />
        <Arrow />
        <FlowStep icon="2️⃣" text="שלב 2: כל החיילים — כיסוי רך על מה שנשאר" color="indigo" />
        <Arrow />
        <FlowStep icon="🪜" text="עדיין חסרות? חיפוש בינארי על סולם ההרפיה (R/T)" color="amber" />
        <Arrow />
        <FlowStep icon="🎯" text="שבירת שוויון: פינוי L1 → מזעור טווח חלקי בנטל" color="blue" />
        <Arrow />
        <FlowStep icon="🔄" text="מעבר החלפות גריד'י — העברת תורנויות לשיפור הוגנות" color="indigo" />
        <Arrow />
        <FlowStep icon="✅" text="שיבוץ בוצע!" color="green" />
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 מה האלגוריתם לוקח בחשבון?</p>
        {[
          { icon: "📊", title: "חלק בנטל", desc: "מי שחלקו בתורנויות ברבעונים האחרונים נמוך מחבריו מקבל עדיפות. חייל חדש בעל חלק בנטל אפס יזכה בתורנויות עד שישתווה לשאר. ראו הסבר מלא בטאב הוגנות." },
          { icon: "🚫", title: "פטורים ואילוצים", desc: "חיילים עם פטור רלוונטי מוסרים. אילוצים אישיים (תאריכים) גם מסננים." },
          { icon: "🎖️", title: "דרישות המשמרת", desc: "חוגרים/קצינים, בה\"ד 1, מין — כל משמרת מגדירה את הדרישות שלה." },
          { icon: "🌳", title: "תת-יחידה כשירה", desc: "כל משמרת יכולה להיות מוגבלת לתת-עץ יחידה ספציפי. האלגוריתם בודק אם הצומת של החייל נמצא בתוך עץ המשנה של הצמתים הכשירים — בדיקת עצמו או אב-קדמון. משמרת ללא הגבלה פתוחה לכולם." },
          { icon: "🔒", title: "איזון חלקי בנטל", desc: "האלגוריתם ממזער את סכום הסטיות המוחלטות מהממוצע (נורמת L1): כל חייל תורם |חלקו הצפוי − ממוצע| למטרה. פתרון שמפזר תורנויות בהפרשים שווים תמיד מנצח פתרון שיוצר חריגים. אם אין מספיק חיילים כשירים, האלגוריתם עושה מיטבו בתוך האילוצים." },
          { icon: "⏱️", title: "מגבלת עומס (T/W)", desc: "חייל לא יכול לקבל יותר מ-T ימי תורנות בכל חלון W ימים ברצף. זה מונע עומס יתר על חייל אחד." },
          { icon: "🗺️", title: "רזרבה", desc: "חיילי רזרבה משובצים כגיבוי לאותה משמרת — האלגוריתם מעדיף רזרבה מהיחידה הקרובה ביותר בהיררכיה." },
          { icon: "🎖️", title: "פטור פיקודי", desc: "פטור שניתן בשלב אחד בלבד על ידי מפקד בדרגת רס\"ן ומעלה, מפקד תת-יחידה ברמת מדור ומעלה, או קצין תורן. הפטור פוטר את החייל הבודד מתורנויות מסוימות, אך לא מפחית את הפוטנציאל של יחידתו — כלומר אותה כמות תורנויות תתחלק על פחות חיילים ביחידה. יש להשתמש בכלי זה בצמצום ובמקרים חריגים בלבד." },
          { icon: "📈", title: "פוטנציאל", desc: "מספר החיילים הכשירים לפחות לסוג תורנות אחד בכל תת-יחידה. פטורים רשמיים מפחיתים פוטנציאל אם הם מכסים את כל סוגי התורנות של החייל; פטורים פיקודיים ואילוצים אישיים לא משפיעים על הפוטנציאל. הפוטנציאל קובע את חלוקת האחריות היחסית בין תת-יחידות במשמרות חדשות, וניתן לבקר אותו לפי חייל ולראות התאמות ידניות מתועדות." },
          { icon: "🔁", title: "רענון מכסות תת-יחידה", desc: "אם סולם ההרפיה הרגיל (R/T) כבר הצליח למצוא פתרון (מלא או חלקי), האלגוריתם מנסה בנוסף לרענן את מכסות תת-היחידה — כדי לנצל עוד קצת גמישות, כשההגדרה auto_relax_node_quotas מופעלת." },
          { icon: "🧩", title: "אסטרטגיות פתרון חלופיות", desc: "בנוסף לפירוק הרגיל לפי סבבי-חלק-בנטל, קיימות אסטרטגיות פתרון חלופיות (למשל פתרון משולב על פני כמה משמרות בבת אחת) שהפותר עשוי להשתמש בהן במקרים מסוימים." },
          { icon: "⏹️", title: "עצירה מוקדמת", desc: "אם הפותר לא משפר את הפתרון במשך כ-15 שניות רצופות, הוא עוצר ומחזיר את הטוב ביותר שנמצא — במקום לנצל את כל זמן הריצה המוקצב." },
          { icon: "♻️", title: "גורל הרזרבה בגימלים", desc: "הגדרת מערכת קובעת מה קורה לרזרבה המקורית של חייל שעבר גימלים: נשארת משויכת אליו (\"keep\") או משוחררת (\"release\")." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>

      {canPlan(user) && (
        <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-3">
          <p className="font-semibold text-gray-800 dark:text-gray-200">🚦 מצבי הרצה (למי שמריץ את האלגוריתם)</p>
          <AlgorithmModeExplainer />
        </div>
      )}

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📝 דוגמה מספרית</p>
        <p className="text-indigo-700 dark:text-indigo-300 text-xs leading-relaxed">
          נניח שיש 3 חיילים: דן (חלק בנטל 3%), יעל (5%), ורוני (8%).
          משמרת חדשה צריכה מישהו — יעל פטורה ממנה.
          האלגוריתם בוחר מדן ורוני; מכיוון שדן בעל חלק בנטל נמוך יותר הוא יקבל עדיפות.
          כך ברמה העולמית, ההפרש בין רוני (8%) לדן ייצטמצם עם הזמן.
        </p>
        <div className="grid grid-cols-3 gap-2 text-xs text-center">
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן</p>
            <p>חלק בנטל: 3%</p>
            <p className="text-green-600">⬆ עדיפות גבוהה</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל</p>
            <p>חלק בנטל: 5%</p>
            <p className="text-gray-500">✗ פטור חל</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-orange-700 dark:text-orange-300">רוני</p>
            <p>חלק בנטל: 8%</p>
            <p className="text-orange-600">⬇ עדיפות נמוכה</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ActiveDaysTab() {
  return (
    <div className="space-y-3 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">איך מחושבים ימים פעילים?</h3>
      <p>ימים פעילים הם הימים שחלפו מנקודת ההתחלה המאוחרת מבין תאריך הייחוס של המערכת ותאריך הכניסה ליחידה, ועד היום (או עד השחרור/עזיבה, אם הם מוקדמים יותר).</p>
      <p>החישוב כולל לפחות יום פעיל אחד עבור חייל שכבר הגיע לנקודת ההתחלה. פטור מלא מתורנויות מפחית ימים רק אם הוא חל בפועל בתוך התקופה הזו; פטור לפני תחילת התקופה או אחרי היום אינו נספר.</p>
      <p>אילוצים אישיים אינם מפחיתים את המכנה של ימים פעילים. הם משפיעים על בדיקת ההתאמה והשיבוץ לתורנויות, בעוד שימים פעילים משמשים להשוואת ניקוד לאורך זמן.</p>
    </div>
  );
}

function ScoringTab({ onNavigateToFairness }: { onNavigateToFairness: () => void }) {
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);

  useEffect(() => {
    listDutyTypes().then(setDutyTypes).catch(() => setDutyTypes([]));
  }, []);

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">מה זה ניקוד?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        לכל סוג תורנות יש <strong>ניקוד ליום</strong> (score_per_day) — כמה &quot;שווה&quot; יום אחד
        של אותה תורנות. ניקוד התורנות עצמה הוא הניקוד ליום כפול מספר הימים שלה:
      </p>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-2">
        <p className="font-medium text-indigo-800 dark:text-indigo-200 font-mono text-xs">
          ניקוד התורנות = ניקוד ליום × מספר ימים
        </p>
        <p className="text-indigo-700 dark:text-indigo-300 text-xs">
          לדוגמה: תורנות &quot;שמירה&quot; עם ניקוד ליום 1.5, שאורכה יומיים, שווה 1.5 × 2 = 3.0 נקודות.
        </p>
      </div>

      <p className="text-gray-700 dark:text-gray-300">
        להלן סוגי התורנות המוגדרים כרגע במערכת וניקוד היום שלהם:
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
              <th className="text-right py-1 pr-2 font-medium">סוג תורנות</th>
              <th className="text-right py-1 pr-2 font-medium">ניקוד ליום</th>
              <th className="text-right py-1 font-medium">תיאור</th>
            </tr>
          </thead>
          <tbody>
            {dutyTypes.map((dt) => (
              <tr
                key={dt.id}
                className={`border-b border-gray-100 dark:border-gray-700 ${dt.active ? "" : "opacity-50"}`}
              >
                <td className="py-1.5 pr-2 font-medium text-gray-800 dark:text-gray-200">{dt.name}</td>
                <td className="py-1.5 pr-2 font-mono text-indigo-700 dark:text-indigo-300">{dt.score_per_day}</td>
                <td className="py-1.5 text-gray-600 dark:text-gray-300">{dt.description ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
        📌 הניקוד שנצבר מכל התורנויות משמש לחישוב חלק הבנטל שלך, שקובע את סדר העדיפויות
        בשיבוץ הבא — ראו טאב{" "}
        <button
          type="button"
          onClick={onNavigateToFairness}
          data-testid="scoring-tab-fairness-link"
          className="underline font-medium hover:text-amber-900 dark:hover:text-amber-100"
        >
          ⚖️ הוגנות ושקיפות
        </button>{" "}
        להסבר המלא.
      </div>
    </div>
  );
}

function FairnessTab() {
  const { user } = useAuth();
  const [myBreakdown, setMyBreakdown] = useState<BurdenShareBreakdown | null>(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(false);
  const [extraDuties, setExtraDuties] = useState(0);

  useEffect(() => {
    if (!user) return;
    setLoadingBreakdown(true);
    getBurdenShareBreakdown(user.id)
      .then(setMyBreakdown)
      .catch(() => setMyBreakdown(null))
      .finally(() => setLoadingBreakdown(false));
  }, [user]);

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">הוגנות ושקיפות</h3>
      <p className="text-gray-700 dark:text-gray-300">
        המערכת מודדת הוגנות על פי <strong>חלק בנטל</strong> — כמה מסך תורנויות היחידה ברבעון נשא כל חייל, בממוצע על פני הרבעונים שבהם שירת.
      </p>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📊 איך מחשבים את חלק הבנטל?</p>

        <div className="space-y-2 text-indigo-700 dark:text-indigo-300">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-medium text-sm">שלב 1 — חלק רבעוני</p>
            <div className="flex items-center justify-center gap-3 text-xs">
              <div className="flex flex-col items-center">
                <div className="bg-indigo-100 dark:bg-indigo-900 rounded px-2 py-1 font-medium text-center">ניקוד החייל ברבעון</div>
                <div className="w-full h-px bg-gray-400 my-1" />
                <div className="bg-purple-100 dark:bg-purple-900 rounded px-2 py-1 font-medium text-center">ניקוד כלל היחידה ברבעון</div>
              </div>
              <div className="text-gray-500 font-bold text-base">=</div>
              <div className="bg-green-100 dark:bg-green-900 rounded px-2 py-1 font-medium">חלק%</div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-medium text-sm">שלב 2 — ממוצע משוקלל לפי נוכחות</p>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              רבעונים בהם שירתת פחות ימים (הצטרפת באמצע, חופשה ממושכת) מקבלים משקל פחות בממוצע. רבעון שלם = משקל מלא. רבעונות שבהם לא הייתה שום פעילות ביחידה אינם נספרים כלל — הם לא תורמים לא ל-A ולא ל-W.
            </p>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-2">
            <p className="font-medium text-sm">שלב 3 — חישוב הממוצע הסופי</p>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              סכום החלקים המשוקללים (A) מחולק בסכום הנוכחות הכולל (W):
            </p>
            <div className="text-xs space-y-1.5">
              <div className="flex gap-2 items-start">
                <span className="shrink-0 bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300 rounded px-1 font-medium">W</span>
                <span className="text-gray-600 dark:text-gray-300"><strong>היסטוריה כוללת</strong> — סכום הנוכחות ברבעונות שבהם הייתה פעילות ביחידה. 4 רבעונות מלאים עם תורנויות = W=4. רבעונות ריקים מדולגים.</span>
              </div>
            </div>
            <div className="bg-indigo-50 dark:bg-indigo-900 rounded p-2 text-indigo-800 dark:text-indigo-200">
              <BlockMath math="\text{חלק בנטל} = \dfrac{A}{W} = \dfrac{\sum_{q:\,U_q>0} s_q \times f_q}{\sum_{q:\,U_q>0} U_q \times f_q}" />
              <p className="text-xs text-center text-gray-500 dark:text-gray-400 mt-1" dir="rtl">
                לכל רבעון <InlineMath math="q" /> : <InlineMath math="s_q" /> = ניקוד החייל, <InlineMath math="U_q" /> = ניקוד כלל היחידה, <InlineMath math="f_q" /> = אחוז הנוכחות ברבעון
              </p>
            </div>
          </div>
        </div>

        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
          <p className="font-medium mb-1">🔑 למה זה פותר את בעיית הוותיקות?</p>
          <p>אם ביחידה היו מעט תורנויות לפני 5 שנים — כולם קיבלו חלק קטן. זה לא פוגע בחייל ותיק, כי היחס (חלק/כלל) נשאר הוגן בכל רבעון. חייל חדש מושווה <em>רק לתקופה שהוא שירת בה</em>.</p>
        </div>
      </div>

      <div className="bg-gray-50 dark:bg-gray-800/60 rounded-xl p-4 border border-gray-200 dark:border-gray-700 space-y-2 text-xs text-gray-700 dark:text-gray-300">
        <p className="font-semibold text-gray-800 dark:text-gray-200">🗓️ מה זה &quot;ימים פעילים&quot; בדף השקיפות?</p>
        <p>
          <strong>ניקוד ליום</strong> בדף השקיפות מחושב כ<em>ניקוד מצטבר ÷ ימים פעילים</em>. &quot;ימים פעילים&quot; הם הימים שחלפו מאז שהצטרפת ליחידה, בניכוי ימים שבהם היית פטור לגמרי מתורנויות. זה מדד שונה מה<strong>חלק הבנטל</strong> שמוסבר למעלה — האלגוריתם עצמו משבץ לפי חלק בנטל, וניקוד-ליום משמש רק להשוואה מהירה בדף השקיפות.
        </p>
        <p>
          <strong>חייל שבדיוק הצטרף</strong> מתחיל עם מספר ימים פעילים קטן מאוד (מינימום יום אחד) — כך שאפילו תורנות בודדת יכולה להראות ניקוד-ליום גבוה יחסית בימיו הראשונים. זה צפוי ולא מעיד על אי-הוגנות: המספר מתייצב ככל שצוברים עוד ימים פעילים, ובכל מקרה סדר העדיפויות בשיבוץ נקבע על ידי חלק הבנטל (A/W) ולא על ידי המדד הזה.
        </p>
      </div>

      {/* Personal breakdown */}
      <div className="bg-green-50 dark:bg-green-950 rounded-xl p-4 border border-green-200 dark:border-green-800 space-y-2">
        <p className="font-semibold text-green-800 dark:text-green-200">🔢 הנתונים שלי</p>
        {loadingBreakdown && (
          <p className="text-xs text-gray-500 dark:text-gray-400">טוען...</p>
        )}
        {!loadingBreakdown && myBreakdown && myBreakdown.quarters.length === 0 && (
          <p className="text-xs text-gray-600 dark:text-gray-400">אין היסטוריה — חייל חדש. חלק הבנטל שלך הוא 0%.</p>
        )}
        {!loadingBreakdown && myBreakdown && myBreakdown.quarters.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse" style={{ minWidth: "320px" }}>
                <thead>
                  <tr className="text-gray-500 dark:text-gray-400 border-b dark:border-green-800">
                    <th className="text-right py-1 pb-1.5 font-medium">רבעון</th>
                    <th className="text-right py-1 pb-1.5 font-medium px-2">ניקוד חייל</th>
                    <th className="text-right py-1 pb-1.5 font-medium px-2">ניקוד יחידה</th>
                    <th className="text-right py-1 pb-1.5 font-medium px-2">% נוכחות</th>
                    <th className="text-right py-1 pb-1.5 font-medium">חלק בנטל</th>
                  </tr>
                </thead>
                <tbody>
                  {myBreakdown.quarters.map((q) => {
                    const unitScore = parseFloat(q.unit_score);
                    return (
                      <tr key={q.quarter_label} className={`border-b border-green-200 dark:border-green-800 ${q.is_partial ? "bg-indigo-50/40 dark:bg-indigo-950/20" : ""}`}>
                        <td className="py-1.5 text-gray-700 dark:text-gray-300 font-medium">
                          <span className={q.is_partial ? "italic" : ""}>{q.quarter_label}</span>
                          {q.is_partial && <span className="mr-1 text-indigo-500 dark:text-indigo-300 font-normal not-italic">(חלקי)</span>}
                        </td>
                        <td className="py-1.5 text-right px-2 text-gray-700 dark:text-gray-300 tabular-nums">
                          <span>{parseFloat(q.soldier_score).toFixed(3)}</span>
                          {parseFloat(q.adjustment_delta ?? "0") !== 0 && (
                            <span className={`block text-xs ${parseFloat(q.adjustment_delta) > 0 ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
                              {parseFloat(q.adjustment_delta) > 0 ? "+" : ""}{parseFloat(q.adjustment_delta).toFixed(3)} התאמה
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 text-right px-2 text-gray-500 dark:text-gray-400 tabular-nums">
                          {unitScore > 0 ? unitScore.toFixed(3) : "—"}
                        </td>
                        <td className="py-1.5 text-right px-2 text-gray-500 dark:text-gray-400 tabular-nums">{(parseFloat(q.active_frac) * 100).toFixed(0)}%</td>
                        <td className="py-1.5 text-right font-semibold text-green-700 dark:text-green-300 tabular-nums">{(parseFloat(q.share) * 100).toFixed(2)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {(() => {
                const partialQ = myBreakdown.quarters.find((q) => q.is_partial);
                if (!partialQ) return null;
                const endFormatted = new Date(partialQ.quarter_end + "T00:00:00").toLocaleDateString("he-IL");
                return (
                  <p className="mt-1.5 text-xs text-indigo-700 dark:text-indigo-300">
                    ℹ️ <strong>רבעון חלקי</strong> — התורנות האחרונה המפורסמת מסתיימת ב-{endFormatted}, לפני סוף הרבעון. ניקוד חייל/יחידה הוא ניקוד רבעוני בלבד — לא מצטבר.
                  </p>
                );
              })()}
            </div>
            {/* Derivation with real numbers */}
            {(() => {
              const A = parseFloat(myBreakdown.A_i);
              const W = parseFloat(myBreakdown.W_i);
              const effort = parseFloat(myBreakdown.burden_share);
              return (
                <div className="mt-1 pt-2 border-t border-green-200 dark:border-green-800 space-y-1 text-xs">
                  {[
                    { label: "חלק בנטל שנצבר (A)", sub: "סכום (חלק×נוכחות) לכל רבעון", value: `${(A * 100).toFixed(2)}%`, cls: "text-indigo-700 dark:text-indigo-300" },
                    { label: "היסטוריה כוללת (W)", sub: "סכום % נוכחות לרבעונות עם תורנויות", value: W.toFixed(3), cls: "text-amber-700 dark:text-amber-300" },
                  ].map(({ label, sub, value, cls }) => (
                    <div key={label} className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="text-gray-700 dark:text-gray-300 font-medium">{label}</span>
                        {sub && <span className="text-gray-400 dark:text-gray-500"> — {sub}</span>}
                      </div>
                      <span className={`shrink-0 font-semibold tabular-nums ${cls}`}>{value}</span>
                    </div>
                  ))}
                  <div className="border-t border-green-200 dark:border-green-800 pt-1">
                    <p className="text-gray-600 dark:text-gray-400 font-medium"><InlineMath math="\text{חלק בנטל} = \dfrac{A}{W}" /></p>
                    <p className="font-bold text-green-700 dark:text-green-300 tabular-nums">
                      <InlineMath math={`\\dfrac{${(A * 100).toFixed(2)}\\%}{${W.toFixed(3)}} = ${(effort * 100).toFixed(2)}\\%`} />
                    </p>
                  </div>
                </div>
              );
            })()}
            <div className="flex justify-between items-center pt-1 border-t border-green-200 dark:border-green-800">
              <span className="text-xs text-gray-500 dark:text-gray-400">חלק בנטל מצטבר:</span>
              <span className="text-lg font-bold text-green-700 dark:text-green-300">
                {(parseFloat(myBreakdown.burden_share) * 100).toFixed(2)}%
              </span>
            </div>
          </>
        )}
      </div>

      {myBreakdown && (
        <div className="bg-blue-50 dark:bg-blue-950 rounded-xl p-4 border border-blue-200 dark:border-blue-800 space-y-2">
          <p className="font-semibold text-blue-800 dark:text-blue-200">🎚️ מה אם אקבל עוד תורנויות?</p>
          <label className="block text-xs text-blue-700 dark:text-blue-300">
            תורנויות נוספות היפותטיות: {extraDuties}
            <input
              aria-label="תורנויות נוספות היפותטיות"
              type="range" min={0} max={10} value={extraDuties}
              onChange={(e) => setExtraDuties(Number(e.target.value))}
              className="w-full"
            />
          </label>
          {(() => {
            const A = parseFloat(myBreakdown.A_i);
            const W = parseFloat(myBreakdown.W_i);
            // Each hypothetical duty is treated as one full-weight duty this quarter (active_frac = 1),
            // contributing 1 unit to both the numerator's share and the denominator's weight — a
            // simplified, illustrative approximation of the real per-block calculation shown in the
            // Deep Dive tab, not the exact solver math.
            const projected = W + extraDuties > 0 ? (A + extraDuties) / (W + extraDuties) : 0;
            return (
              <p className="text-xs text-blue-700 dark:text-blue-300">
                חלק בנטל לאחר התוספת (הערכה): <span className="font-bold">{(projected * 100).toFixed(2)}%</span>
              </p>
            );
          })()}
        </div>
      )}

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📝 דוגמה מספרית</p>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-2 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן — 3 שנים בשירות</p>
            <p>ניקוד ממוצע ברבעון: 4</p>
            <p>ניקוד יחידה ממוצע: 100</p>
            <p className="text-green-700 dark:text-green-400 font-medium">חלק בנטל: 4% לרבעון</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg p-2 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל — חדשה, רבעון ראשון</p>
            <p>ניקוד ברבעון עד כה: 0</p>
            <p>ניקוד יחידה: 100</p>
            <p className="text-red-600 dark:text-red-400 font-medium">חלק בנטל: 0% — תקבל עדיפות!</p>
          </div>
        </div>
        <p className="text-xs text-indigo-700 dark:text-indigo-300">האלגוריתם יעדיף את יעל כי יש לה חלק בנטל אפסי — היא תצבור תורנויות עד שהיא מגיעה לרמת דן.</p>
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 שקיפות</p>
        {[
          { icon: "📊", title: "דף השקיפות", desc: "כל חייל רואה את חלק הבנטל שלו ושל שאר חברי היחידה — כולל טבלה שניתן למיין לפי חלק בנטל. לחץ על הערך לפירוט רבעוני." },
          { icon: "📅", title: "טווח ההיסטוריה ותאריך איפוס", desc: "כברירת מחדל החישוב כולל את כל הרבעונים הרלוונטיים — החל מהרבעון שבו בוצעה התורנות הראשונה של כל חיילי היחידה. מנהל המערכת יכול לקבוע תאריך איפוס שמצמצם את ההיסטוריה: אז רק רבעונים מתאריך זה ואילך נחשבים. אותו תאריך משפיע גם על עמודות \"ימים פעילים\" ו\"ניקוד ליום\" — חייל לא נספר כפעיל לפני תאריך זה, גם אם הצטרף ליחידה קודם. מומלץ: תחילת רבעון." },
          { icon: "⚖️", title: "הגינות לחדשים", desc: "חייל שהצטרף לאחרונה מושווה רק לתקופה שבה שירת — הוא לא נפגע מכך שהיחידה הייתה פחות עסוקה לפני שהצטרף." },
          { icon: "✏️", title: "התאמות ניקוד ידניות", desc: "מפקד רשאי להוסיף התאמה ידנית לניקוד חייל (חיובית או שלילית). ההתאמה משפיעה גם על ניקוד חלק הבנטל — היא מתווספת לניקוד החייל וליחידה באותו רבעון, ומשפיעה בהתאם על חלקו היחסי. הפירוט הרבעוני מציין מה מגיע מהתאמה ידנית." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GimelimTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-red-700 dark:text-red-400">🏥 מה זה גימלים?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        גימלים הוא שחרור רפואי זמני מתורנות. כדי למנוע ניצול לרעה, המערכת מגלגלת את החייל שוחרר לתורנות העתידית הקרובה המתאימה — ומחליפה חייל ראשוני קרוב היררכית.
      </p>
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="🏥" text="חייל מדווח גימלים — מפקד מפעיל שחרור גימלים" color="red" />
        <Arrow />
        <FlowStep icon="📋" text="המערכת מציגה הצעה: מי מוקפץ, לאיזו תורנות ישובץ החייל" color="blue" />
        <Arrow />
        <FlowStep icon="✅" text="המפקד מאשר" color="indigo" />
        <Arrow />
        <FlowStep icon="⬆️" text="הרזרבה מוקפצת לכיסוי התורנות הנוכחית" color="amber" />
        <Arrow />
        <FlowStep icon="🔄" text="חייל קרוב היררכית ממומר לרזרבה בתורנות העתידית, החייל שוחרר נכנס כראשוני" color="amber" />
        <Arrow />
        <FlowStep icon="📲" text="כל הצדדים מקבלים הודעה" color="green" />
      </div>
      <ul className="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-300">
        <li>הסיבה הרפואית גלויה רק למי שרשאי: מנהל תורנויות או מפקד שבתחום אחריותם נמצא החייל, והחייל עצמו. חיילים אחרים לא רואים אותה.</li>
        <li>אם לא נמצאת תורנות עתידית מתאימה, הגימלים מבוצע בלי שיבוץ מחדש.</li>
        <li>החייל שמומר לרזרבה שומר את הרזרבה המקורית שלו כרזרבה כללית.</li>
      </ul>
    </div>
  );
}

function DeepDiveTab() {
  const [shownAssignment, setShownAssignment] = useState<"a" | "b">("a");
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
          השני נשא חלק בנטל כפול פי 10.
        </p>
        <p className="text-gray-700 dark:text-gray-300">
          ספירת תורנויות גולמית מתעלמת משלושה גורמים:
        </p>
        <ul className="list-disc list-inside space-y-1 text-gray-600 dark:text-gray-400 pr-2">
          <li><strong>זמן שירות</strong> — חייל חדש לא ניתן להשוואה לוותיק ישירות.</li>
          <li><strong>משקל התורנות</strong> — תורנות ארוכה שווה יותר מקצרה.</li>
          <li><strong>גודל היחידה</strong> — אם היחידה צמחה, מאגר התורנויות גדל איתה.</li>
        </ul>
        <p className="text-gray-700 dark:text-gray-300">
          הפתרון: במקום לספור, מודדים <strong>חלק יחסי</strong> — איזה אחוז מסך חלק בנטל היחידה נשא החייל,
          יחסית לכמה זמן הוא היה פעיל.
        </p>
      </section>

      {/* ── Section 2: burden_share ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">📐 חלק בנטל — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">burden_share = A / W</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          לכל חייל מחושב ציון אחד — <strong>חלק בנטל</strong>. הוא מייצג: מה חלקך מסך כל הניקוד שצברה היחידה,
          משוקלל לפי שיעור הנוכחות שלך בכל רבעון. ערך הוגן = 1/N (N = מספר החיילים).
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
                { sym: "s_q", name: "ניקוד אישי ברבעון", def: "הניקוד שצבר החייל בתורנויות ברבעון q." },
                { sym: "U_q", name: "ניקוד יחידה ברבעון", def: "סכום ניקוד כלל החיילים ביחידה ברבעון q." },
                { sym: "active_fracq", name: "שבר נוכחות", def: "חלק הרבעון שבו החייל היה פעיל (0–1). רבעון מלא = 1." },
                { sym: "A", name: "ניקוד אישי משוקלל", def: <><InlineMath math="\sum_q (s_q \times \text{active\_frac}_q)" /> — ניקוד החייל משוקלל לפי נוכחות.</> },
                { sym: "W", name: "ניקוד יחידה משוקלל", def: <><InlineMath math="\sum_{q:\,U_q>0} (U_q \times \text{active\_frac}_q)" /> — ניקוד היחידה משוקלל, <strong>רק ברבעונות שבהם הייתה פעילות</strong>.</> },
                { sym: "burden_share", name: "חלק בנטל", def: <><InlineMath math="\dfrac{A}{W}" /> — חלקך מסך הניקוד המשוקלל של היחידה. עולה כשרבעונות חדשים נצברים — ממיר עיוותי-סקאלה של הנוסחה הישנה.</> },
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

        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-xs space-y-1">
          <p className="font-medium text-gray-800 dark:text-gray-200">📝 דוגמה</p>
          <p className="text-gray-600 dark:text-gray-300">
            חייל שירת 4 רבעונות מלאים, ותמיד נשא 5% מחלק בנטל היחידה:
          </p>
          <ul className="list-none space-y-0.5 text-gray-600 dark:text-gray-300 pr-2">
            <li>A = 4 × 0.05 = 0.20</li>
            <li>W = 4.0</li>
            <li className="font-semibold text-indigo-700 dark:text-indigo-300">burden_share = 0.20 / 4.0 = 0.05 (5%)</li>
          </ul>
        </div>
      </section>

      {/* ── Section 2.5: Pending-quarter denominator inflation ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🛡️ תיקון רבעון דק — ניפוח המכנה</h3>
        <p className="text-gray-700 dark:text-gray-300">
          <strong>הבעיה:</strong> בתחילת רבעון, אם היחידה עדיין ביצעה מעט תורנויות, המכנה <InlineMath math="U_q" /> (ניקוד יחידה ברבעון) קטן מאוד.
          כתוצאה, חלקו היחסי של כל חייל (<InlineMath math="s_q / U_q" />) מתנפח — ויוצר רושם שהם כבר נשאו חלק בנטל גדול, גם אם עשו כמה תורנויות בלבד.
          הפותר יקבל אות מוטעה ויימנע מלשבץ את אותם חיילים לתורנויות שלפניו — בעוד שבמציאות הרבעון עוד רחוק מסיומו.
        </p>
        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs space-y-2">
          <p className="font-medium text-amber-800 dark:text-amber-200">🔑 הפתרון: ניפוח מוקדם של המכנה</p>
          <p className="text-amber-700 dark:text-amber-300">
            לפני חישוב ניקוד חלק הבנטל ההיסטורי (<code>effort_score</code>) של כל חייל, המערכת מוסיפה לניקוד היחידה ברבעון הנוכחי (<InlineMath math="U_q" />) את סך ניקוד התורנויות שהפותר עומד לשבץ בסיבוב הנוכחי.
            כלומר: גם אם הרבעון עדיין דק, המכנה כבר &quot;יודע&quot; שעוד תורנויות עומדות להגיע — והחלק היחסי נשאר הוגן.
          </p>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-amber-200 dark:border-amber-700 space-y-1 font-mono text-amber-700 dark:text-amber-300">
            <div>U_q_inflated = U_q + pending_run_score</div>
            <div>share_q = s_q / U_q_inflated</div>
          </div>
          <p className="text-amber-700 dark:text-amber-300">
            תיקון זה חל רק על הרבעון שבו מתבצע הסיבוב (&quot;רבעון נוכחי&quot;). רבעונות עבר אינם מושפעים — הם כבר סגורים ומלאים.
          </p>
        </div>
      </section>

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
                  meaning: "ניקוד חלק הבנטל ההיסטורי כשלם קבוע — כולל תיקון ניפוח מכנה לרבעון הנוכחי. לא משתנה בזמן הפתרון.",
                },
                {
                  name: "unit_score_milli",
                  formula: "Σ block_score(d) × 1000 לכל תורנויות הסיבוב",
                  meaning: "סך ניקוד כל התורנויות שהפותר עומד לשבץ בסיבוב הנוכחי — כולל תורנויות של כל הבאצ'ים. ניקוד זה הוא גם הניקוד שמנופח לתוך המכנה (ראו סעיף הקודם).",
                },
                {
                  name: "C_over_D",
                  formula: "1 / W (או 1 אם W=0)",
                  meaning: "כמה מהמשקל הכולל מיוחס לסיבוב הנוכחי. גבוה לחיילים חדשים (W קטן), נמוך לוותיקים.",
                },
                {
                  name: "effort_per_milli",
                  formula: "int(C_over_D / unit_score_milli × EFFORT_SCALE)",
                  meaning: "כמה כל מילי-ניקוד אחד של תורנות מזיז את חלק בנטל החייל. קבוע — מחושב לפני הפתרון.",
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
            לחייל ותיק עם W=8 יש C_over_D = 1/8 = 0.125.
            לחייל חדש עם W=0 יש C_over_D = 1/1 = 1.0.
            כלומר: אותה תורנות בדיוק מזיזה את ניקוד החדש פי 8 יותר מאשר את הוותיק.
            לחייל ותיק יש &quot;עמידות&quot; גבוהה יותר לשינויים — צריך הרבה תורנויות כדי להזיז אותו.
          </p>
        </div>
      </section>

      {/* ── Section 4: projected_effort ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🎯 הניקוד הצפוי — <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">projected_effort</code></h3>
        <p className="text-gray-700 dark:text-gray-300">
          בתוך הפותר, לכל חייל נבנית <strong>ביטוי לינארי</strong> שמחשב מה יהיה ניקוד חלק הבנטל שלו
          לאחר שיבוץ:
        </p>

        <div
          dir="ltr"
          className="bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto text-gray-800 dark:text-gray-200"
        >
          <BlockMath math="\begin{aligned}\text{projected\_effort}[i] &= \text{effort\_offset}[i] \\ &\quad + \text{effort\_per\_milli}[i] \times \sum_d \bigl(\text{block\_score}(d) \times x_{d,i}\bigr)\end{aligned}" />
        </div>

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

      {/* ── Section 5: L1 ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">📏 מה זה L1? — ממוצע קבוע, לא חופשי</h3>
        <p className="text-gray-700 dark:text-gray-300">
          רוצים שכל הניקודים יהיו קרובים זה לזה. אבל &quot;קרוב&quot; ניתן להגדיר בשתי דרכים:
        </p>

        <div className="grid grid-cols-1 gap-2 text-xs">
          <div className="bg-orange-50 dark:bg-orange-950 rounded-lg p-3 border border-orange-200 dark:border-orange-800">
            <p className="font-semibold text-orange-800 dark:text-orange-200 mb-1">L2 — סכום ריבועי סטיות</p>
            <div className="text-orange-700 dark:text-orange-300 mb-1">
              <BlockMath math="\sum_i \bigl(\text{projected\_effort}[i] - \mu\bigr)^2" />
            </div>
            <p className="text-orange-700 dark:text-orange-300">
              ריבוע הסטייה מעניש קשות על חריגים. ערך חריג אחד יכול לדחוף את כל השיבוצים
              בניסיון להקטין אותו — גם כשזה לא הוגן לשאר.
            </p>
          </div>
          <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800">
            <p className="font-semibold text-green-800 dark:text-green-200 mb-1">L1 — סכום סטיות מוחלטות ✓</p>
            <div className="text-green-700 dark:text-green-300 mb-1">
              <BlockMath math="\sum_i \bigl|\text{projected\_effort}[i] - \mu\bigr|" />
            </div>
            <p className="text-green-700 dark:text-green-300">
              כל סטייה נספרת באותו משקל, ללא קנס על חריגים. עמיד בפני ותיקים עם היסטוריה גבוהה מאוד.
            </p>
          </div>
        </div>

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs">
          <p className="font-medium text-indigo-800 dark:text-indigo-200 mb-1">💡 μ — ממוצע קבוע שנקבע מראש</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            המטרה <code>μ</code> אינה משתנה חופשי — היא מחושבת לפני הפעלת הפותר כ<strong>ממוצע</strong> של הניקודים הצפויים
            (סכום ה-effort_offset של כל החיילים הכשירים, בתוספת אומדן חלק הבנטל מהתורנויות החדשות, חלקי מספר החיילים).
            הפותר לא &quot;מגלה&quot; את המטרה — היא קבועה מראש, והוא רק מחפש שיבוץ שממזמינם את הסטיות ממנה.
          </p>
        </div>
      </section>

      {/* ── Section 6: Final objective ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🏁 המטרה הסופית</h3>
        <p className="text-gray-700 dark:text-gray-300">
          לכל חייל נוצר משתנה עזר <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1 rounded">dev[i]</code> עם שני אילוצים:
        </p>

        <div className="bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto text-gray-800 dark:text-gray-200">
          <BlockMath math="\begin{aligned}\text{dev}[i] &\geq \text{projected\_effort}[i] - \mu \\ \text{dev}[i] &\geq \mu - \text{projected\_effort}[i]\end{aligned}" />
        </div>

        <p className="text-gray-700 dark:text-gray-300 text-xs">
          שני האילוצים האלה כופים ש-<code>dev[i] = |projected_effort[i] − μ|</code>.
          פונקציית המטרה היא <strong>ממוזגת</strong> מארבעה רכיבים עם משקולות היררכיים:
        </p>

        <div className="bg-gray-100 dark:bg-gray-800 rounded-lg p-3 overflow-x-auto text-indigo-700 dark:text-indigo-300">
          <BlockMath math="\text{Maximize}\!\left(\begin{array}{l} {-}10^{11} \times \displaystyle\sum_i \text{dev}[i] \\[6pt] {-}10^{6} \times \text{prior\_term} \\[6pt] {-}10^{4} \times \text{count\_spread} \\[6pt] {-}\text{dist\_term} \end{array}\right)" />
        </div>

        <div className="space-y-1.5 text-xs text-gray-700 dark:text-gray-300">
          {[
            { term: "Σ dev[i]", desc: "סכום הסטיות המוחלטות מ-μ — רכיב האיזון הראשי. משקלו 1×10¹¹ גורם לו להיות דומיננטי לחלוטין." },
            { term: "prior_term", desc: "ממזמין חריגה מהניקוד ההיסטורי של כל חייל — מונע שינויים חדים מסבב לסבב. משקל 1×10⁶." },
            { term: "count_spread", desc: "ממזמין פיזור גולמי של מספר התורנויות (בלי משקל). משקל 1×10⁴ — שובר שוויון עדין." },
            { term: "dist_term", desc: "קנס קטן על שיבוץ חיילי רזרבה ליחידות רחוקות בהיררכיה. משקל קטן בהרבה." },
          ].map(({ term, desc }) => (
            <div key={term} className="flex gap-2 bg-gray-50 dark:bg-gray-700 rounded p-2 border border-gray-200 dark:border-gray-600">
              <code className="shrink-0 text-indigo-700 dark:text-indigo-300 font-mono">{term}</code>
              <span>{desc}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Section 7: Subtree eligibility ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🌳 כשירות לפי תת-עץ היררכיה</h3>
        <p className="text-gray-700 dark:text-gray-300">
          כל משמרת יכולה להיות מוגבלת לרשימת צמתים (&quot;תת-יחידה אחראית&quot;). האלגוריתם מסנן מועמדים לפי מבנה העץ ההיררכי ולא לפי שיוך ישיר בלבד:
        </p>
        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-xs space-y-2">
          <p className="font-medium text-gray-800 dark:text-gray-200">🔎 כיצד נבדקת הכשירות</p>
          <p className="text-gray-600 dark:text-gray-300">
            לכל צומת בהיררכיה שמור מסלול אבות-קדמונים (<code>path_ids</code>) — רשימה מהשורש ועד לצומת עצמו.
            חייל נחשב כשיר למשמרת המוגבלת לצמתים <code>eligible_node_ids</code> אם:
          </p>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-gray-200 dark:border-gray-700 font-mono text-indigo-700 dark:text-indigo-300 text-xs">
            {"eligible_node_ids ∩ soldier.path_ids ≠ ∅"}
          </div>
          <p className="text-gray-600 dark:text-gray-300">
            כלומר: אם אחד מהצמתים הכשירים הוא הצומת של החייל עצמו <strong>או</strong> אחד מאבות-הקדמונים שלו, החייל כשיר.
            כך, הגבלה ל&quot;פלוגה א&apos;&quot; כוללת אוטומטית גם חיילים של &quot;כיתה 1 / פלוגה א&apos;&quot; — ללא צורך לפרט כל תת-יחידה.
          </p>
        </div>
        <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800 text-xs space-y-1">
          <p className="font-medium text-green-800 dark:text-green-200">📝 דוגמה</p>
          <p className="text-green-700 dark:text-green-300">
            היררכיה: <code>גדוד → פלוגה א → כיתה 1</code>.
            חייל משויך ל&quot;כיתה 1&quot;, כך שה-<code>path_ids</code> שלו הוא <code>[גדוד, פלוגה א, כיתה 1]</code>.
            משמרת עם <code>eligible_node_ids = [פלוגה א]</code> תכלול אותו — כי &quot;פלוגה א&quot; נמצאת ב-<code>path_ids</code> שלו.
            משמרת ללא <code>eligible_node_ids</code> פתוחה לכלל היחידה.
          </p>
        </div>
      </section>

      {/* ── Section 8: Worked example ── */}
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
                {["חייל", "burden_share", "effort_offset", "C_over_D", "effort_per_milli"].map(h => (
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
          שים לב: <code>effort_per_milli</code> של יעל הוא 200 — פי 5 מהותיקים. כי C_over_D שלה = 1/1 = 1.0 (אין היסטוריה).
          בקוד האמיתי μ מחושב פעם אחת לפני הפותר (ולא לכל שיבוץ בנפרד) — הדוגמה מפשטת זאת לצורך הבנה.
        </p>

        {/* Assignment toggle */}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShownAssignment("a")}
            className={`text-xs px-2 py-1 rounded border ${shownAssignment === "a" ? "bg-green-600 text-white border-green-600" : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"}`}
          >
            שיבוץ א׳ (הפותר יבחר בזה)
          </button>
          <button
            type="button"
            onClick={() => setShownAssignment("b")}
            className={`text-xs px-2 py-1 rounded border ${shownAssignment === "b" ? "bg-red-600 text-white border-red-600" : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"}`}
          >
            שיבוץ ב׳ (גרוע יותר)
          </button>
        </div>

        {/* Assignment A */}
        {shownAssignment === "a" && (
          <div className="bg-green-50 dark:bg-green-950 rounded-lg p-3 border border-green-200 dark:border-green-800 text-xs space-y-2">
            <pre className="font-mono text-green-700 dark:text-green-300 leading-relaxed whitespace-pre">{`projected[דן]  = 40,000 + 40  × 2,500 = 140,000  (14%)
projected[יעל] =      0 + 200 × 0     =       0   ( 0%)
projected[רוני]= 80,000 + 40  × 2,500 = 180,000  (18%)`}</pre>
            <pre className="font-mono text-green-700 dark:text-green-300 leading-relaxed whitespace-pre">{`μ = ממוצע = (140,000 + 0 + 180,000) / 3 ≈ 106,667
dev[דן]  = |140,000 − 106,667| =  33,333
dev[יעל] = |      0 − 106,667| = 106,667
dev[רוני]= |180,000 − 106,667| =  73,333
──────────────────────────────────────────
סה"כ = 213,333`}</pre>
          </div>
        )}

        {/* Assignment B */}
        {shownAssignment === "b" && (
          <div className="bg-red-50 dark:bg-red-950 rounded-lg p-3 border border-red-200 dark:border-red-800 text-xs space-y-2">
            <pre className="font-mono text-red-700 dark:text-red-300 leading-relaxed whitespace-pre">{`projected[דן]  = 40,000 + 40  × 2,500 = 140,000  (14%)
projected[יעל] =      0 + 200 × 2,500 = 500,000  (50%)  ← זינוק!
projected[רוני]=      80,000           =  80,000  ( 8%)`}</pre>
            <pre className="font-mono text-red-700 dark:text-red-300 leading-relaxed whitespace-pre">{`μ = ממוצע = (140,000 + 500,000 + 80,000) / 3 = 240,000
dev[דן]  = |140,000 − 240,000| = 100,000
dev[יעל] = |500,000 − 240,000| = 260,000
dev[רוני]= | 80,000 − 240,000| = 160,000
──────────────────────────────────────────
סה"כ = 520,000  ← פי ~2.4 יותר גרוע!`}</pre>
          </div>
        )}

        <div className="bg-indigo-50 dark:bg-indigo-950 rounded-lg p-3 border border-indigo-200 dark:border-indigo-800 text-xs space-y-1">
          <p className="font-semibold text-indigo-800 dark:text-indigo-200">🔑 תובנה מפתח</p>
          <p className="text-indigo-700 dark:text-indigo-300">
            הפותר <strong>לא</strong> פשוט משבץ את החייל עם הניקוד הנמוך ביותר.
            הוא שוקל כמה כל שיבוץ <em>מזיז</em> את הניקוד של כל חייל.
            יעל מתחילה ב-0%, אבל כל תורנות &quot;שווה לה&quot; פי 5 יותר מאשר לוותיקים —
            כי היא חדשה. שיבוץ אחד יזניק אותה ל-50% ויצור חריג גדול.
            עדיף לפזר בין שני הוותיקים ולאפשר ליעל להתכנס בהדרגה לאורך מספר סיבובים.
          </p>
        </div>
      </section>

      {/* ── Section 9: Three phases ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🔬 שלושת שלבי הפתרון</h3>

        <p className="text-gray-700 dark:text-gray-300">
          לפני שמתחילים לפתור, האלגוריתם מחלק את הבעיה לחתיכות קטנות יותר.
          הוא בונה גרף בין משמרות לחיילים — קשר בין כל משמרת לכל חייל שכשיר לה.
          אם קיימות שתי קבוצות שאין ביניהן שום חיתוך (לדוגמה, תורנויות פלוגה א׳ שרק חיילי פלוגה א׳ יכולים לבצע, ותורנויות פלוגה ב׳ שרק חיילי פלוגה ב׳ יכולים לבצע), אין שום סיבה לפתור אותן יחד — הן עצמאיות לחלוטין.
          פירוק זה מאפשר לפותר לעבוד על מודלים קטנים ומהירים, במקום מודל ענק אחד שיכול לקחת עשרות שניות.
        </p>

        <p className="text-gray-700 dark:text-gray-300">לכל קבוצה כזו האלגוריתם מנסה שלושה שלבים לפי הסדר:</p>

        <div className="space-y-2">
          <div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-3 text-xs space-y-1.5">
            <p className="font-semibold text-blue-800 dark:text-blue-200">שלב א׳ — ניסיון כולל אחד</p>
            <p className="text-blue-700 dark:text-blue-300">
              הפותר מנסה לכסות את <em>כל</em> המשמרות בקבוצה בבת אחת. ברוב המקרים זה מצליח — וזהו המסלול המהיר.
              אם יש פתרון שמכסה הכל ועומד בכל האילוצים, הפותר ימצא אותו כאן ויעצור.
              הבעיה מתחילה רק כשמספר החיילים הכשירים קטן מדי ביחס לכמות המשמרות הנדרשות — אז הפותר מכריז שהמשימה בלתי אפשרית, ועוברים לשלב הבא.
            </p>
          </div>

          <div className="bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 text-xs space-y-1.5">
            <p className="font-semibold text-indigo-800 dark:text-indigo-200">שלב ב׳ — חיילים לפי תור, חלק בנטל נמוך ראשון</p>
            <p className="text-indigo-700 dark:text-indigo-300">
              שלב א׳ נכשל, כלומר אי אפשר לכסות הכל בבת אחת.
              כדי שלא לוותר סתם, האלגוריתם ממיין את החיילים לפי חלק בנטלם ההיסטורי — מי שעשה הכי פחות ראשון — ומחלק אותם לקבוצות קטנות.
              כל קבוצה מקבלת הזדמנות לקחת את המשמרות שנשארו פתוחות עד כה, כשהפותר מנסה לכסות כמה שיותר אך אינו מחויב לכסות הכל.
              כך החיילים שנשאו פחות חלק בנטל ב&quot;תור&quot; הראשון ולא &quot;יפלו בין הכיסאות&quot; אחרי ששאר הקבוצות לקחו את המשמרות הנגישות להן.
            </p>
          </div>

          <div className="bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 text-xs space-y-1.5">
            <p className="font-semibold text-indigo-800 dark:text-indigo-200">שלב ג׳ — סיום עם כל המאגר</p>
            <p className="text-indigo-700 dark:text-indigo-300">
              לאחר שלב ב׳ ייתכן שנשארו משמרות שאף קבוצה לא כיסתה — למשל, משמרת שדורשת שני חיילים מקבוצות שונות בו-זמנית.
              שלב ג׳ מריץ ניסיון אחרון עם <em>כל</em> החיילים יחד, רק על המשמרות שלא כוסו עדיין.
              הפותר כעת &quot;רואה&quot; את כל האפשרויות ויכול למצוא שיבוץ שחוצה גבולות הקבוצות מהשלב הקודם.
            </p>
          </div>
        </div>

        <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-xs space-y-1">
          <p className="font-medium text-gray-800 dark:text-gray-200">📌 חלק בנטל עובר בין השלבים</p>
          <p className="text-gray-600 dark:text-gray-300">
            כל שיבוץ שנעשה בשלב מסוים מיד מעדכן את חלק בנטל החייל שקיבל אותו, וגם חוסם את התאריכים שלו לשלבים הבאים.
            כך, חייל שקיבל תורנות בשלב א׳ לא יוכל לקבל תורנות חופפת בשלב ב׳ — וגם חלק הבנטל שלו ייחשב גבוה יותר בחישוב ההוגנות.
          </p>
        </div>
      </section>

      {/* ── Section 10: Relaxation ladder ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🪜 הרפיה הדרגתית — כשהיחידה קטנה מדי</h3>

        <p className="text-gray-700 dark:text-gray-300">
          גם אחרי שלושת השלבים, ייתכן שנשארו משמרות לא מכוסות.
          הסיבה הנפוצה: מגבלת הצפיפות — כל חייל מוגבל במספר ימי התורנות שהוא יכול לקבל בכל תקופה — אינה מאפשרת לבצע כיסוי שלם.
          האלגוריתם לא מוותר; הוא <strong>מרפה את המגבלה בהדרגה</strong> ומנסה מחדש מהתחלה.
        </p>

        <div className="space-y-2 text-xs">
          <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 space-y-2">
            <p className="font-medium text-amber-800 dark:text-amber-200">🔑 שני סוגי מגבלת צפיפות</p>
            <div className="text-amber-700 dark:text-amber-300 space-y-1.5">
              <p><strong>T — מגבלת ימי שירות אמיתיים:</strong> מספר ימי התורנות שחייל יכול לקבל בכל חלון של Wt ימים. מונעת מחייל לשרת כל השבוע.</p>
              <p><strong>R — מגבלה כוללת (כולל רזרבה):</strong> גם ימי רזרבה נספרים. מגבלה זו מרפה ראשונה, כי רזרבה קלה יותר מתורנות אמיתית.</p>
              <p>ההרפיה מגדילה את R בשניים ראשונה (עד לתקרה), ורק אז מגדילה את T. כך נשמר ההיגיון: קודם נרפה את מה שפחות פוגע בחיילים.</p>
            </div>
          </div>

          <div className="bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg p-3 space-y-1.5">
            <p className="font-medium text-gray-800 dark:text-gray-200">⚡ חיפוש חכם — לא ניסוי וטעייה</p>
            <p className="text-gray-600 dark:text-gray-300">
              לכל רמת הרפיה צריך להריץ מחדש את שלושת השלבים — מה שיכול לקחת זמן רב אם יש הרבה רמות.
              לכן האלגוריתם לא עובר על הסולם רמה אחרי רמה; הוא קודם בודק את <em>הרמה הגבוהה ביותר</em> (הכי מרוחקת): אם גם בה אי אפשר לכסות הכל, אין טעם לחפש. אם כן אפשר — הוא מחפש בינארית את הרמה <em>הנמוכה ביותר</em> שמספיקה.
              כך מגיעים לתשובה לאחר מספר ניסיונות שהוא לוגריתמי בגודל הסולם, לא ליניארי.
            </p>
          </div>

          <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-lg p-3 space-y-1">
            <p className="font-medium text-green-800 dark:text-green-200">✅ תמיד מוחזר הטוב ביותר שנמצא</p>
            <p className="text-green-700 dark:text-green-300">
              אפילו אם לא הגענו לכיסוי מלא, האלגוריתם מחזיר את הפתרון שכיסה הכי הרבה משמרות.
              כל הרפיה שהופעלה מתועדת ומוצגת בטאב ״ריצות״ — כך ניתן לראות האם הצורך בהרפיה נובע ממחסור אמיתי בחיילים או ממגבלות לא אופטימליות.
            </p>
          </div>
        </div>
      </section>

      {/* ── Section 11: Lexicographic tiebreaker ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🎯 שבירת שוויון — כשהוגנות לא מספיקה לבדה</h3>

        <p className="text-gray-700 dark:text-gray-300">
          מטרת ההוגנות — מזעור סכום הסטיות מהממוצע — יכולה להשאיר <em>ענן של פתרונות שקולים</em>:
          אם שני חיילים שניהם מתחת לממוצע, חלוקה 8:0 ביניהם נותנת בדיוק אותו ניקוד כמו חלוקה 4:4 — כי ה-L1 לא &quot;רואה&quot; את ההבדל בתוך אותו צד של הממוצע.
          זה פגם ידוע בנורמת L1, והאלגוריתם פותר אותו עם שלב שני נפרד.
        </p>

        <div className="space-y-2 text-xs">
          <div className="flex gap-3 bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3">
            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-600 text-white flex items-center justify-center font-bold text-xs mt-0.5">1</div>
            <div className="text-indigo-700 dark:text-indigo-300 space-y-0.5">
              <p className="font-semibold text-indigo-800 dark:text-indigo-200">נועל את רמת ההוגנות שהושגה</p>
              <p>מוסיפים אילוץ: סכום כל הסטיות לא יעלה על מה שהשלב הראשון השיג. כך השלב השני לא יכול להיות <em>פחות</em> הוגן, רק שווה או יותר.</p>
            </div>
          </div>

          <div className="flex gap-3 bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3">
            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-600 text-white flex items-center justify-center font-bold text-xs mt-0.5">2</div>
            <div className="text-indigo-700 dark:text-indigo-300 space-y-0.5">
              <p className="font-semibold text-indigo-800 dark:text-indigo-200">ממזמין את הטווח בין הגבוה לנמוך</p>
              <p>המטרה החדשה: להקטין את ההפרש בין החייל שקיבל הכי הרבה לבין זה שקיבל הכי מעט. כך 4:4 מנצח 8:0 גם כשה-L1 שלהם זהה.</p>
            </div>
          </div>

          <div className="flex gap-3 bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3">
            <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-600 text-white flex items-center justify-center font-bold text-xs mt-0.5">3</div>
            <div className="text-indigo-700 dark:text-indigo-300 space-y-0.5">
              <p className="font-semibold text-indigo-800 dark:text-indigo-200">פותר נפרד, בלי סיכון</p>
              <p>השלב הזה רץ בפותר נפרד עם תקציב זמן קצר יותר. אם לא מצא פתרון שיפור בזמן — הפתרון של השלב הראשון נשמר ללא שינוי. אין סיכון להידרדרות.</p>
            </div>
          </div>
        </div>

        <div className="bg-purple-50 dark:bg-purple-950 border border-purple-200 dark:border-purple-800 rounded-lg p-3 text-xs space-y-1">
          <p className="font-medium text-purple-800 dark:text-purple-200">🗺️ גם קרבת היררכיה לרזרבות נשמרת</p>
          <p className="text-purple-700 dark:text-purple-300">
            בשלב השני, בנוסף לטווח, הפותר מעדיף לשבץ תורנות רזרבה לחיילים <em>קרובים</em> לפלוגה שצריכה גיבוי.
            אם שני שיבוצים שקולים לחלוטין על ההוגנות ועל הטווח — יגבר זה שממקם את הרזרבות קרוב יותר היררכית.
          </p>
        </div>
      </section>

      {/* ── Section 12: Swap pass ── */}
      <section className="space-y-3">
        <h3 className="font-semibold text-gray-800 dark:text-gray-200">🔄 מעבר איזון סופי — העברות בין חיילים</h3>

        <p className="text-gray-700 dark:text-gray-300">
          הפותר עבד על כל קבוצה בנפרד — ומה שהוגן בתוך קבוצה אחת אינו בהכרח הוגן כשרואים את כל היחידה יחד.
          לדוגמה, חייל בקבוצה א׳ אולי קיבל תורנויות רבות, ואילו חייל דומה בקבוצה ב׳ קיבל מעט — אך הפותר לא ראה אותם ביחד.
          לכן, בסיום, האלגוריתם מריץ <strong>מעבר איזון</strong> שבוחן את כל החיילים יחד ומעביר תורנויות כדי לאזן.
        </p>

        <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1 text-sm">
          <FlowStep icon="📊" text="מחשבים חלק בנטל סופי לכל חייל על פי כל מה שקיבל" color="gray" />
          <Arrow />
          <FlowStep icon="🔝" text="מזהים תורמים (חלק בנטל מעל ממוצע) וקולטים (חלק בנטל מתחת ממוצע)" color="indigo" />
          <Arrow />
          <FlowStep icon="🔍" text="לכל תורם: מחפשים את התורנות הכבדה ביותר שניתן להעביר לקולט כשיר" color="blue" />
          <Arrow />
          <FlowStep icon="✅" text="מעבירים רק אם ההעברה מקטינה את פער חלקי הבנטל הכולל" color="green" />
          <Arrow />
          <FlowStep icon="🔁" text="חוזרים עד שאין עוד העברה שמשפרת, עד לתקרה של 3 × מספר חיילים" color="gray" />
        </div>

        <div className="space-y-2 text-xs">
          <div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-3 space-y-1">
            <p className="font-medium text-blue-800 dark:text-blue-200">🔒 כל האילוצים נשמרים גם בהעברה</p>
            <p className="text-blue-700 dark:text-blue-300">לפני כל העברה נבדקים ארבעה תנאים: הקולט כשיר לסוג המשמרת ולתת-היחידה שלה; אין לו כבר תורנות באותם תאריכים; הוא לא חורג ממכסת ימי השירות שלו (T); והוא לא חורג ממכסת הימים הכוללת כולל רזרבה (R). רק אם כל ארבעתם מתקיימים — ההעברה מתבצעת.</p>
          </div>
        </div>
      </section>

    </div>
  );
}

function HakpazaTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-red-700 dark:text-red-400">📣 מה זו הקפצה פיקודית?</h3>
      <p className="text-gray-700 dark:text-gray-300">
        הקפצה פיקודית מאפשרת למפקד למשוך חייל מתורנות קיימת ולהחליף אותו במועמד אחר — ללא תלות בבקשת החלפה הדדית. שימושי כשצריך מענה מיידי (למשל חייל שלא הגיע).
      </p>
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="🙋" text="מפקד בוחר תורנות וחייל שנמשך ממנה" color="red" />
        <Arrow />
        <FlowStep icon="📋" text="המערכת מציעה עד 8 מועמדים מדורגים" color="blue" />
        <Arrow />
        <FlowStep icon="✅" text="מפקד בוחר מועמד ומגיש בקשה" color="indigo" />
        <Arrow />
        <FlowStep icon="👮" text="נדרש אישור נוסף לפני שההקפצה נכנסת לתוקף" color="amber" />
        <Arrow />
        <FlowStep icon="📲" text="שני הצדדים מקבלים הודעה" color="green" />
      </div>
      <div className="space-y-2">
        {[
          { icon: "📏", title: "דירוג המועמדים", desc: "המועמדים מדורגים לפי קרבה היררכית לחייל שנמשך, עומס נוכחי (score_per_day), ומספר ימי התורנות שנותרו לו — כך שהעומס הנוסף מתחלק בצורה סבירה." },
          { icon: "⚖️", title: "מניעת שימוש חוזר באותו חייל", desc: "המערכת עוקבת אחרי הקפצות פיקודיות קודמות של כל חייל (עם דעיכה לאורך זמן) ומורידה את הדירוג שלו כמועמד ככל שהוקפץ יותר לאחרונה — כדי למנוע הישענות על אותם חיילים שוב ושוב." },
          { icon: "🔒", title: "צריך אישור", desc: "הקפצה לא נכנסת לתוקף מיידית — היא ממתינה לאישור נפרד (לרוב של גורם פיקודי נוסף) בדיוק כמו בקשת החלפה, ורק לאחריו התורנות בפועל מתחלפת." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ApprovalsTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">תיבת האישורים</h3>
      <p className="text-gray-700 dark:text-gray-300">
        כל הבקשות שמחכות לאישור שלכם מרוכזות בעמוד <strong>אישורים</strong>, מחולקות לטאבים. אישור או דחייה כאן משפיעים מיידית על שיבוץ החייל — כדאי להבין את ההשפעה לפני שמחליטים:
      </p>
      <div className="space-y-2">
        {[
          { icon: "🔄", title: "בקשות החלפה", desc: "אישור מבצע את ההחלפה בפועל: מעביר את התורנות בין שני החיילים. דחייה משאירה את השיבוץ המקורי כפי שהיה — שני הצדדים מקבלים הודעה." },
          { icon: "🚫", title: "בקשות פטור", desc: "אישור מסיר את החייל משיבוץ עתידי לסוגי התורנות שבפטור. פטור רשמי גם מפחית את פוטנציאל היחידה (ראו טאב האלגוריתם) — כלומר אותו מספר תורנויות מתחלק בין פחות חיילים ביחידה." },
          { icon: "✏️", title: "עדכוני פרופיל", desc: "חייל ביקש לשנות פרט אישי (למשל טלפון או דרגה). אישור מעדכן את הרשומה מיד; דחייה משאירה את הערך הישן." },
          { icon: "🎓", title: "הצטרפויות/קליטה", desc: "חייל חדש שממתין לשיבוץ ליחידה. אישור קובע את היחידה שלו וממנו והלאה הוא נכנס לחישובי חלק הבנטל וההוגנות." },
          { icon: "🔀", title: "העברות", desc: "העברת חייל בין תתי-יחידות. אישור מעביר את החייל וההיסטוריה שלו נשארת אך חלק הבנטל העתידי נספר תחת היחידה החדשה." },
          { icon: "📅", title: "בקשות אילוץ אישי", desc: "חייל ביקש שלא לשבץ אותו בתאריכים מסוימים. אישור מחריג אותו מהתאריכים שביקש; דחייה משאירה אותו זמין לשיבוץ כרגיל. זהו הטאב שנפתח כברירת מחדל בעמוד האישורים." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="bg-amber-50 dark:bg-amber-950 rounded-lg p-3 border border-amber-200 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-300">
        ⚠️ בקשות ממתינות זמן רב עלולות לחסום תכנון: תורנות שממתינה לאישור החלפה לא תיחשב &quot;סופית&quot; עד שהאישור יושלם.
      </div>
    </div>
  );
}

function ImportTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">📥 ייבוא מקובץ אקסל</h3>
      <p className="text-gray-700 dark:text-gray-300">
        ייבוא מאפשר להזין או לעדכן חיילים, שיבוצים והגדרות ממקור אקסל חיצוני, בשלושה שלבים:
      </p>
      <div className="bg-gray-50 dark:bg-gray-700 rounded-xl p-4 border border-gray-200 dark:border-gray-600 space-y-1">
        <FlowStep icon="📤" text="העלאת קובץ" color="indigo" />
        <Arrow />
        <FlowStep icon="🔍" text="סקירת שורות: חדש / עדכון / שגיאה / מחוץ לתחום / דילוג" color="blue" />
        <Arrow />
        <FlowStep icon="🛠️" text="מיפוי שמות ותיקוני שדות ידניים לפי הצורך" color="amber" />
        <Arrow />
        <FlowStep icon="✅" text="ביצוע (commit)" color="green" />
      </div>
      <div className="space-y-2">
        {[
          { icon: "🔄", title: "מה ההבדל בין \"חדש\" ל\"עדכון\"?", desc: "שורה מזוהה לפי מספר אישי קיים במערכת: אם נמצא — זו \"עדכון\" (שדות קיימים יידרסו בערכים מהקובץ); אם לא נמצא — \"חדש\" (רשומה נוצרת מאפס)." },
          { icon: "⚠️", title: "שורות שגיאה ומחוץ לתחום", desc: "שורה עם שגיאה לא תיובא כלל עד לתיקון. שורה \"מחוץ לתחום\" שייכת ליחידה שאין לכם הרשאה לנהל — היא מדולגת אוטומטית ולא תשפיע על היחידות שלכם." },
          { icon: "🗂️", title: "מיפוי שמות", desc: "אם שם סוג תורנות או שם צומת בקובץ לא תואם בדיוק למה שקיים במערכת, ניתן למפות אותו ידנית לפני הביצוע — כדי למנוע יצירת כפילויות בטעות." },
          { icon: "↩️", title: "לפני שמבצעים סופית", desc: "שום שינוי לא נכנס לתוקף עד לשלב הביצוע (commit) המפורש — סקירת השורות היא שלב תצוגה מקדימה בלבד וניתן לבטל בכל שלב לפני הביצוע." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function flattenNodes(nodes: NodeDTO[]): NodeDTO[] {
  const out: NodeDTO[] = [];
  for (const n of nodes) {
    out.push(n);
    if (n.children) out.push(...flattenNodes(n.children));
  }
  return out;
}

function HierarchyEligibilityTab({ user }: { user: PermissionUser | null }) {
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [templates, setTemplates] = useState<ShiftTemplate[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");

  useEffect(() => {
    fetchTree().then((tree) => setNodes(flattenNodes(tree))).catch(() => setNodes([]));
  }, []);

  useEffect(() => {
    if (!canPlan(user)) return;
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [user]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedTemplate = templates.find((t) => t.id === selectedTemplateId);
  const eligible = selectedNode && selectedTemplate
    ? !selectedTemplate.eligible_node_ids || selectedTemplate.eligible_node_ids.some((id) => selectedNode.path_ids.includes(id))
    : null;

  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">היררכיה וכשירות</h3>
      <p className="text-gray-700 dark:text-gray-300">
        כל משמרת יכולה להיות מוגבלת לתת-יחידה מסוימת. חייל כשיר אם אחד הצמתים הכשירים של המשמרת נמצא במסלול שלו מהשורש (<code>path_ids</code>) — כלומר הצומת שלו עצמו, או אחד מאבות-הקדמונים שלו.
      </p>

      <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 בדיקת כשירות חיה</p>
        <label className="block text-xs text-gray-600 dark:text-gray-300">
          בחר צומת
          <select
            aria-label="בחר צומת"
            className="mt-1 w-full border rounded px-2 py-1 dark:bg-gray-800 dark:border-gray-600"
            value={selectedNodeId}
            onChange={(e) => setSelectedNodeId(e.target.value)}
          >
            <option value="">— בחר —</option>
            {nodes.map((n) => (
              <option key={n.id} value={n.id}>{n.name}</option>
            ))}
          </select>
        </label>
        {canPlan(user) && (
          <label className="block text-xs text-gray-600 dark:text-gray-300">
            בחר סוג תורנות
            <select
              aria-label="בחר סוג תורנות"
              className="mt-1 w-full border rounded px-2 py-1 dark:bg-gray-800 dark:border-gray-600"
              value={selectedTemplateId}
              onChange={(e) => setSelectedTemplateId(e.target.value)}
            >
              <option value="">— בחר —</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </label>
        )}
        {eligible !== null && (
          <p className={eligible ? "text-green-700 dark:text-green-300 font-medium" : "text-red-600 dark:text-red-400 font-medium"}>
            {eligible ? "✅ כשיר" : "❌ לא כשיר"}
          </p>
        )}
        {!canPlan(user) && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            בדיקת כשירות מול סוגי תורנות ספציפיים זמינה למנהלי תורנויות ולמנהלי המערכת.
          </p>
        )}
      </div>
    </div>
  );
}

export default function HelpModal({ onClose, gimelimEnabled = false, hakpazaEnabled = true, initialTab }: Props) {
  useModalBackClose(onClose);
  const { user } = useAuth();
  const TABS = buildTabs(user as PermissionUser | null, gimelimEnabled, hakpazaEnabled);
  const [activeTab, setActiveTab] = useState(() =>
    initialTab && TABS.some((t) => t.id === initialTab) ? initialTab : (TABS[0]?.id ?? "swaps")
  );

  useEffect(() => {
    if (!TABS.some((t) => t.id === activeTab)) {
      setActiveTab(TABS[0]?.id ?? "swaps");
    }
  }, [TABS, activeTab]);

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b dark:border-gray-600" dir="rtl">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">מדריך המערכת</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b dark:border-gray-600 px-2 pt-1 overflow-x-auto overflow-y-hidden shrink-0" dir="rtl">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-3 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === "swaps" && <SwapsTab />}
          {activeTab === "algorithm" && <AlgorithmTab user={user as PermissionUser | null} />}
          {activeTab === "scoring" && <ScoringTab onNavigateToFairness={() => setActiveTab("fairness")} />}
          {activeTab === "active_days" && <ActiveDaysTab />}
          {activeTab === "fairness" && <FairnessTab />}
          {activeTab === "deep" && <DeepDiveTab />}
          {activeTab === "approvals" && <ApprovalsTab />}
          {activeTab === "hierarchy" && <HierarchyEligibilityTab user={user as PermissionUser | null} />}
          {activeTab === "hakpaza" && <HakpazaTab />}
          {activeTab === "gimelim" && <GimelimTab />}
          {activeTab === "import" && <ImportTab />}
        </div>
      </div>
    </div>
  );
}
