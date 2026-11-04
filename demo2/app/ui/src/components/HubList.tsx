import { useListHubsSuspense, useListRoutesSuspense, type HubOut } from "@/lib/api";
import { useFlow } from "@/lib/flow";
import { HEALTH_HEX, HEALTH_LABEL, type Health } from "@/lib/status";
import { cn, pct } from "@/lib/utils";

/** Step 1: every hub with a traffic-light status; picking a hub lists its routes. */
export function HubList() {
  const { hubId, routeId, selectHub, selectRoute } = useFlow();
  const hubs = useListHubsSuspense().data.data;
  return (
    <ul className="space-y-2 p-3">
      {hubs.map((h) => (
        <li key={h.depot_id}>
          <HubCard hub={h} selected={h.depot_id === hubId} onOpen={() => selectHub(h.depot_id)} />
          {h.depot_id === hubId && (
            <HubRoutes hubId={h.depot_id} selected={routeId} onPick={(id) => selectRoute(id, h.depot_id)} />
          )}
        </li>
      ))}
    </ul>
  );
}

export function HealthDot({ health }: { health: Health }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: health === "amber" ? "#8a5a00" : HEALTH_HEX[health] }}>
      <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: HEALTH_HEX[health] }} />
      {HEALTH_LABEL[health]}
    </span>
  );
}

function HubCard({ hub, selected, onOpen }: { hub: HubOut; selected: boolean; onOpen: () => void }) {
  const health = (hub.health ?? "green") as Health;
  const below = hub.on_time_pct != null && hub.on_time_pct < hub.sla_target_pct;
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={selected}
      aria-label={`${hub.name}: ${HEALTH_LABEL[health]}`}
      className={cn(
        "w-full rounded-lg border bg-white p-3 text-left transition-colors hover:bg-muted/50",
        selected ? "border-accent ring-1 ring-accent" : "border-border",
        health === "red" && !selected && "border-l-4 border-l-late",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{hub.name}</div>
          <div className="text-xs text-muted-foreground">{hub.city}, {hub.state}</div>
        </div>
        <HealthDot health={health} />
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        <span className={cn("font-medium", below ? "text-late" : "text-foreground")}>
          {hub.on_time_pct == null ? "—" : pct(hub.on_time_pct)} on time
        </span>{" "}
        (target {pct(hub.sla_target_pct)}) · {hub.late_stops} late · {hub.at_risk_stops} at risk
      </p>
    </button>
  );
}

function HubRoutes({ hubId, selected, onPick }: { hubId: string; selected?: string; onPick: (id: string) => void }) {
  const routes = useListRoutesSuspense({ depot_id: hubId }).data.data;
  return (
    <ul className="mt-1 space-y-1 border-l-2 border-border pl-3" aria-label="Routes in this hub">
      <li className="pt-1 text-xs font-medium text-muted-foreground">Pick a route to look into</li>
      {routes.map((r) => {
        const bad = r.late_stops + r.at_risk_stops;
        return (
          <li key={r.route_id}>
            <button
              type="button"
              onClick={() => onPick(r.route_id)}
              className={cn(
                "flex w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-xs hover:bg-muted/60",
                r.route_id === selected ? "border-accent bg-accent/5" : "border-border bg-white",
              )}
            >
              <span className="font-medium">{r.route_id.split("-").pop() ? `R-${r.route_id.split("-").pop()}` : r.route_id}</span>
              <span className={cn("tabular-nums", r.late_stops ? "font-medium text-late" : "text-muted-foreground")}>
                {bad === 0 ? "all on track" : `${r.late_stops} late · ${r.at_risk_stops} at risk`}
              </span>
              <span className="tabular-nums text-muted-foreground">risk {Math.round(r.risk_score * 100)}%</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
