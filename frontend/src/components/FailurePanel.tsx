interface Props {
  relaxed: string[];
  reasons: string[];
}

function describeRelaxation(step: string): string {
  const matchT = step.match(/T→(\d+)/);
  if (matchT) {
    return `הוגמשה מגבלת צפיפות: מותר כעת ${matchT[1]} ימי תורנות בכל 14 יום`;
  }
  const matchK = step.match(/K→(\d+)/);
  if (matchK) {
    return `הוגמשה מגבלת מינימום: מינימום ימים בין תורנויות הוקטן ל-${matchK[1]}`;
  }
  return step;
}

export default function FailurePanel({ relaxed, reasons }: Props) {
  return (
    <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4 space-y-3 text-sm" dir="rtl">
      <div className="flex items-center gap-2">
        <span className="text-red-600 dark:text-red-400 text-base">❌</span>
        <h3 className="font-semibold text-red-700 dark:text-red-300">האלגוריתם לא הצליח למצוא פתרון</h3>
      </div>

      {relaxed.length > 0 && (
        <div>
          <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">ניסיונות שבוצעו:</p>
          <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
            {relaxed.map((step, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-red-500">•</span>
                <span>ניסיון {i + 2}: {describeRelaxation(step)} — נכשל</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">סיבות אפשריות לכישלון:</p>
        <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
          <li className="flex gap-2"><span>•</span><span>אין מספיק חיילים כשירים לטווח התאריכים</span></li>
          <li className="flex gap-2"><span>•</span><span>יותר מדי אילוצים אישיים מאושרים בתקופה זו</span></li>
          <li className="flex gap-2"><span>•</span><span>מגבלת הצפיפות נמוכה מדי ביחס לכמות המשמרות</span></li>
          {reasons.map((r, i) => (
            <li key={i} className="flex gap-2"><span>•</span><span>{r}</span></li>
          ))}
        </ul>
      </div>

      <div>
        <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">המלצות:</p>
        <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
          <li className="flex gap-2"><span>→</span><span>הרחב את טווח התאריכים לפיזור טוב יותר</span></li>
          <li className="flex gap-2"><span>→</span><span>הפחת את מספר המשמרות הנדרשות לתקופה</span></li>
          <li className="flex gap-2"><span>→</span><span>בדוק אילוצים אישיים שאושרו לאותה תקופה</span></li>
        </ul>
      </div>
    </div>
  );
}
