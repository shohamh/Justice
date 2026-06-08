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
