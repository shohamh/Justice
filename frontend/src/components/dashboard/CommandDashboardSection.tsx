import { PropsWithChildren, useId } from "react";
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
  const resolvedTitle =
    title ??
    t("command_dashboard.management_section_title", {
      defaultValue: "ניהול היחידה",
    });

  return (
    <section
      dir="rtl"
      aria-labelledby={headingId}
      data-testid={testId}
      className="rounded-lg border-2 border-indigo-400 bg-indigo-50/50 p-4 shadow dark:border-indigo-500 dark:bg-indigo-950/30"
    >
      <div className="mb-3 space-y-1">
        <h2 id={headingId} className="text-lg font-semibold text-indigo-950 dark:text-indigo-100">
          {resolvedTitle}
        </h2>
        {scopeLabel && (
          <p className="text-sm text-indigo-700 dark:text-indigo-200">
            {scopeLabel}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}
