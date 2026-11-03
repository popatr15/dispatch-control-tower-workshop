import { ChevronLeft } from "lucide-react";
import type { ReactNode } from "react";

/** Sidebar header: a back link to the previous level plus the current title. */
export function PanelHeader({ back, onBack, title, children }: {
  back: string; onBack: () => void; title: ReactNode; children?: ReactNode;
}) {
  return (
    <div className="border-b border-border px-3 py-2">
      <button type="button" onClick={onBack} className="-ml-1 flex items-center text-xs text-accent hover:underline">
        <ChevronLeft className="h-3.5 w-3.5" />{back}
      </button>
      <div className="mt-0.5 flex items-center justify-between gap-2">
        <h2 className="truncate text-sm font-semibold">{title}</h2>
        {children}
      </div>
    </div>
  );
}
