import { usePublicSettings } from "../hooks/usePublicSettings";

interface Props {
  linked: boolean;
}

export default function TelegramBadge({ linked }: Props) {
  const settings = usePublicSettings();
  if (settings?.["telegram.enabled"] !== true) return null;

  return (
    <span
      className="inline-flex items-center gap-0.5"
      title={linked ? "Telegram מקושר" : "Telegram לא מקושר"}
    >
      {/* Telegram paper-plane logo */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        className="w-3.5 h-3.5 flex-shrink-0"
        fill={linked ? "#229ED9" : "#9CA3AF"}
        aria-hidden="true"
      >
        <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L8.32 13.617l-2.96-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.828.942z" />
      </svg>
      <span
        className={`w-3 h-3 rounded-sm border flex items-center justify-center flex-shrink-0 ${linked ? "bg-[#229ED9] border-[#229ED9]" : "border-gray-400 bg-white"}`}
        aria-hidden="true"
      >
        {linked && (
          <svg viewBox="0 0 10 8" className="w-2 h-2" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="1,4 3.5,6.5 9,1" />
          </svg>
        )}
      </span>
    </span>
  );
}
