import { AlertTriangle } from "lucide-react";
import { PanelHeader } from "@/components/ops/Breadcrumb";
import { useListHubsSuspense, useListRoutesSuspense } from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { AT_RISK_SCORE } from "@/lib/status";
import { cn, pct } from "@/lib/utils";

/** One hub: its counts and its routes, at-risk first (the API sorts by risk). */
export function RouteList({ hubId }: { hubId: string }) {
  const { filters, selectHub, selectRoute } = useAppState();
  const hub = useListHubsSuspense(cleanParams({ day: filters.day })).data.data.find((h) => h.depot_id === hubId);
  const routes = useListRoutesSuspense(cleanParams({ day: filters.day, depot_id: hubId, carrier_id: filters.carrier_id })).data.data;
  const atRisk = routes.filter((r) => r.risk_score >= AT_RISK_SCORE).length;
  return (
    <div className="flex h-full flex-col">
      <PanelHeader back="All hubs" onBack={() => selectHub(undefined)} title={hub?.name ?? hubId} />
      {hub && (
        <p className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
          {hub.stops} stops · <span className={cn(hub.late_stops && "font-medium text-late")}>{hub.late_stops} late</span> ·{" "}
          {hub.at_risk_stops} at risk · {hub.on_time_pct == null ? "—" : pct(hub.on_time_pct)} on time (target {pct(hub.sla_target_pct)})
        </p>
      )}
      <div className="px-3 pt-2 text-xs font-medium text-muted-foreground">
        {routes.length} routes{atRisk ? ` · ${atRisk} at risk` : ""}{filters.carrier_id ? " · carrier filter on" : ""}
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {routes.map((r) => {
          const risky = r.risk_score >= AT_RISK_SCORE;
          return (
            <li key={r.route_id}>
              <button type="button" onClick={() => selectRoute(r.route_id)}
                className="mb-1 w-full rounded-md border border-border bg-white px-3 py-2 text-left hover:border-accent hover:bg-accent/5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-medium">{r.route_id}</span>
                  <span className={cn("flex items-center gap-1 text-xs font-semibold", risky ? "text-late" : "text-muted-foreground")}>
                    {risky && <AlertTriangle className="h-3 w-3" aria-hidden />}
                    {risky ? "At risk" : "Risk"} {pct(r.risk_score)}
                  </span>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {r.late_stops} late · {r.at_risk_stops} at risk · {r.effective_stops} stops
                  {r.capacity_stops != null && ` / ${r.capacity_stops} capacity`}
                </div>
                {risky && r.risk_reason && <div className="mt-0.5 truncate text-xs">{r.risk_reason}</div>}
              </button>
            </li>
          );
        })}
        {routes.length === 0 && <li className="p-2 text-sm text-muted-foreground">No routes for this hub on this day.</li>}
      </ul>
    </div>
  );
}
