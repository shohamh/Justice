import { PropsWithChildren, useId, useState } from "react";
import { useTranslation } from "react-i18next";

interface CommandDashboardSectionProps extends PropsWithChildren {
  title?: string;
  scopeLabel?: string;
  "data-testid"?: string;
}

export default function CommandDashboardSection({
  children,
  title,
  scopeLabel,
  "data-testid": testId,
}: CommandDashboardSectionProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const [collapsed, setCollapsed] = useState(false);
  const resolvedTitle =
    title ??
    t("command_dashboard.management_section_title", {
      defaultValue: "דאשבורד מפקד",
    });

  return (
    <section
      dir="rtl"
      aria-labelledby={headingId}
      data-testid={testId}
      className="rounded-lg border-2 border-indigo-400 bg-indigo-50/50 p-4 shadow dark:border-indigo-500 dark:bg-indigo-950/30"
    >
      <button
        type="button"
        className="mb-3 flex w-full items-start justify-between space-y-1 text-right"
        onClick={() => setCollapsed((prev) => !prev)}
        aria-expanded={!collapsed}
      >
        <div>
          <h2 id={headingId} className="text-lg font-semibold text-indigo-950 dark:text-indigo-100">
            {resolvedTitle}
          </h2>
          {scopeLabel && (
            <p className="text-sm text-indigo-700 dark:text-indigo-200">
              {scopeLabel}
            </p>
          )}
        </div>
        <span
          className={`text-indigo-700 transition-transform dark:text-indigo-200 ${collapsed ? "-rotate-90" : ""}`}
          aria-hidden="true"
        >
          ▼
        </span>
      </button>
      {!collapsed && children}
    </section>
  );
}
