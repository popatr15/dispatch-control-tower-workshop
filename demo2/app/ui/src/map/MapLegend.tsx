import { HEALTH_HEX, HEALTH_LABEL, STATUS_GLYPH, STATUS_HEX, STATUS_LABEL, type Health, type StopStatus } from "@/lib/status";

const STOPS: StopStatus[] = ["late", "at_risk", "on_time"];
const HEALTH: Health[] = ["red", "amber", "green"];

export function MapLegend({ showStops }: { showStops: boolean }) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-border bg-white/95 px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 font-medium">Hubs</div>
      <ul className="space-y-0.5">
        {HEALTH.map((h) => (
          <li key={h} className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: HEALTH_HEX[h] }} /> {HEALTH_LABEL[h]}
          </li>
        ))}
      </ul>
      {showStops && (
        <>
          <div className="mb-1 mt-2 font-medium">Stops on the route</div>
          <ul className="space-y-0.5">
            {STOPS.map((s) => (
              <li key={s} className="flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS_HEX[s] }} />
                <span aria-hidden>{STATUS_GLYPH[s]}</span> {STATUS_LABEL[s]}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
