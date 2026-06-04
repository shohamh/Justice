import { useEffect, useRef } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "neutral",
  fontFamily: "inherit",
  flowchart: { curve: "basis", htmlLabels: true },
});

let counter = 0;

export default function MermaidDiagram({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const id = `mermaid-${++counter}`;
    ref.current.innerHTML = "";
    mermaid.render(id, chart).then(({ svg }) => {
      if (ref.current) ref.current.innerHTML = svg;
    }).catch(() => {
      if (ref.current) ref.current.innerHTML = `<p class="text-red-500 text-xs">שגיאה בטעינת הדיאגרמה</p>`;
    });
  }, [chart]);

  return <div ref={ref} className="flex justify-center my-4 overflow-x-auto" />;
}
