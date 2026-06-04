// frontend/src/components/SoldierLink.tsx
import { useSoldierModal } from "../contexts/SoldierModalContext";

interface Props {
  id: string;
  name: string;
  className?: string;
}

export default function SoldierLink({ id, name, className }: Props) {
  const { openSoldierModal } = useSoldierModal();
  return (
    <button
      type="button"
      className={`text-indigo-600 hover:underline ${className ?? ""}`}
      onClick={(e) => {
        e.stopPropagation();
        void openSoldierModal(id);
      }}
    >
      {name}
    </button>
  );
}
