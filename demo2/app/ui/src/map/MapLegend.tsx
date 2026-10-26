import { STATUS_GLYPH, STATUS_HEX, STATUS_LABEL, type StopStatus } from "@/lib/status";

const ORDER: StopStatus[] = ["late", "at_risk", "on_time", "delivered"];

export function MapLegend({ zoomedIn }: { zoomedIn: boolean }) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-border bg-white/95 px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 font-medium">{zoomedIn ? "Stops" : "Stop clusters (worst status)"}</div>
      <ul className="space-y-0.5">
        {ORDER.map((s) => (
          <li key={s} className="flex items-center gap-2">
            <span
              className="inline-block rounded-full border-slate-900"
              style={{
                background: STATUS_HEX[s],
                width: s === "late" ? 12 : s === "at_risk" ? 11 : 8,
                height: s === "late" ? 12 : s === "at_risk" ? 11 : 8,
                borderWidth: s === "late" || s === "at_risk" ? 2 : 0,
              }}
            />
            <span aria-hidden>{STATUS_GLYPH[s]}</span> {STATUS_LABEL[s]}
          </li>
        ))}
        <li className="flex items-center gap-2"><span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-violet-800" /> Reassigned</li>
        <li className="flex items-center gap-2"><span className="inline-block h-2.5 w-2.5 rounded-full bg-slate-900" /> Depot</li>
      </ul>
    </div>
  );
}
