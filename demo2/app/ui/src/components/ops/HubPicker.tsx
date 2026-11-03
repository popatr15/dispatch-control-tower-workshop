import { ChevronRight } from "lucide-react";
import { Select } from "@/components/ui/inputs";
import { useGetFiltersSuspense, useListHubsSuspense, type HubOut } from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { cn, pct } from "@/lib/utils";

/** Default screen: one card per depot with the day's counts. */
export function HubPicker() {
  const { filters, setFilters, selectHub } = useAppState();
  const meta = useGetFiltersSuspense().data.data;
  const hubs = useListHubsSuspense(cleanParams({ day: filters.day })).data.data
    .filter((h) => !filters.region || h.region === filters.region);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold">Choose a hub</h2>
          <p className="text-xs text-muted-foreground">Hubs with at-risk routes are listed first.</p>
        </div>
        <Select aria-label="Date" className="h-8 w-40 py-0 text-xs" value={filters.day ?? meta.today}
          onChange={(e) => setFilters({ ...filters, day: e.target.value === meta.today ? undefined : e.target.value })}>
          {meta.dates.map((d) => <option key={d} value={d}>{d === meta.today ? `${d} (today)` : d}</option>)}
        </Select>
      </div>
      <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {hubs.map((h) => <li key={h.depot_id}><HubCard hub={h} onOpen={() => selectHub(h.depot_id)} /></li>)}
        {hubs.length === 0 && <li className="text-sm text-muted-foreground">No hubs match the region filter.</li>}
      </ul>
    </div>
  );
}

function HubCard({ hub, onOpen }: { hub: HubOut; onOpen: () => void }) {
  const below = hub.on_time_pct != null && hub.on_time_pct < hub.sla_target_pct;
  return (
    <button type="button" onClick={onOpen} aria-label={`Open ${hub.name}`}
      className="w-full rounded-lg border border-border bg-white p-3 text-left hover:border-accent hover:bg-accent/5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{hub.name}</div>
          <div className="text-xs text-muted-foreground">{hub.city}, {hub.state} · {hub.region}</div>
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>
      <dl className="mt-2 grid grid-cols-5 gap-1 text-center">
        <Stat label="Routes" value={hub.routes} />
        <Stat label="Stops" value={hub.stops} />
        <Stat label="At risk" value={hub.at_risk_stops} tone={hub.at_risk_stops ? "at_risk" : undefined} />
        <Stat label="Late" value={hub.late_stops} tone={hub.late_stops ? "late" : undefined} />
        <Stat label="On time" value={hub.on_time_pct == null ? "—" : pct(hub.on_time_pct)} tone={below ? "late" : undefined}
          title={`SLA target ${pct(hub.sla_target_pct)}`} />
      </dl>
      {hub.at_risk_routes > 0 && (
        <p className="mt-2 text-xs font-medium text-late">{hub.at_risk_routes} at-risk route{hub.at_risk_routes > 1 ? "s" : ""}</p>
      )}
    </button>
  );
}

function Stat({ label, value, tone, title }: { label: string; value: number | string; tone?: "late" | "at_risk"; title?: string }) {
  return (
    <div title={title} className="flex flex-col-reverse">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className={cn("text-sm font-semibold tabular-nums", tone === "late" && "text-late", tone === "at_risk" && "text-[#8a5a00]")}>{value}</dd>
    </div>
  );
}
