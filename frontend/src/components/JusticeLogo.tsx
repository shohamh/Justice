import { APP_ENV } from "../version";

interface Props {
  size?: "sm" | "md" | "lg";
}

const SIZE_MAP = {
  sm: { svgSize: 28, textClass: "text-xl",  badgeClass: "text-[8px] px-0.5 py-px" },
  md: { svgSize: 36, textClass: "text-2xl", badgeClass: "text-[9px] px-0.5 py-px" },
  lg: { svgSize: 52, textClass: "text-4xl", badgeClass: "text-[10px] px-1 py-px" },
};

const BADGE_COLORS: Record<string, string> = {
  alpha:   "bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-700",
  beta:    "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-700",
  stable:  "bg-green-100 text-green-700 border-green-300 dark:bg-green-950 dark:text-green-300 dark:border-green-700",
  staging: "bg-yellow-100 text-yellow-700 border-yellow-300 dark:bg-yellow-950 dark:text-yellow-300 dark:border-yellow-700",
  dev:     "bg-gray-100 text-gray-600 border-gray-300 dark:bg-gray-700 dark:text-gray-400 dark:border-gray-500",
  prod:    "bg-indigo-100 text-indigo-700 border-indigo-300 dark:bg-indigo-950 dark:text-indigo-300 dark:border-indigo-700",
};

export default function JusticeLogo({ size = "md" }: Props) {
  const { svgSize, textClass, badgeClass } = SIZE_MAP[size];

  return (
    <div className="flex items-start gap-1.5 sm:gap-3" data-testid="justice-logo">
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
      <div className="flex flex-col items-start">
        <span
          className={`font-cinzel font-semibold tracking-widest text-indigo-700 dark:text-indigo-300 ${textClass}`}
          data-testid="justice-logo-text"
        >
          Justice
        </span>
        {APP_ENV && (
          <span
            className={`font-sans font-semibold uppercase tracking-wide border rounded ${badgeClass} ${BADGE_COLORS[APP_ENV.variant]}`}
            data-testid="env-badge"
          >
            {APP_ENV.label}
          </span>
        )}
      </div>
    </div>
  );
}
