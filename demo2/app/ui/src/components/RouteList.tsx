import { AlertTriangle, CircleDollarSign } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useListRoutesSuspense } from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { riskLabel } from "@/lib/status";
import { cn } from "@/lib/utils";

const STATE_VARIANT = { delayed: "late", in_progress: "on_time", planned: "muted", completed: "delivered" } as const;

export function RouteList() {
  const { filters, routeId, selectRoute } = useAppState();
  const { data } = useListRoutesSuspense(cleanParams(filters));
  const routes = data.data;
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">At-risk routes</h2>
        <p className="text-xs text-muted-foreground">{routes.length} routes · sorted by risk</p>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {routes.map((r) => {
          const level = riskLabel(r.risk_score);
          return (
            <li key={r.route_id}>
              <button
                type="button"
                onClick={() => selectRoute(r.route_id === routeId ? undefined : r.route_id)}
                className={cn(
                  "w-full border-b border-border px-3 py-2 text-left hover:bg-muted",
                  r.route_id === routeId && "bg-accent/10 ring-1 ring-inset ring-accent",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-medium">{r.route_id}</span>
                  <span className={cn("text-xs font-semibold", level === "high" ? "text-late" : level === "medium" ? "text-[#8a5a00]" : "text-muted-foreground")}>
                    {level === "high" && <AlertTriangle className="mr-0.5 inline h-3 w-3" aria-label="high risk" />}
                    {Math.round(r.risk_score * 100)}%
                  </span>
                </div>
                <div className="mt-0.5 truncate text-xs text-muted-foreground">{r.risk_reason ?? "No risk flagged"}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  <Badge variant={STATE_VARIANT[r.status]}>{r.status.replace("_", " ")}</Badge>
                  <span className="text-xs text-muted-foreground">{r.late_stops} late · {r.at_risk_stops} at risk · {r.effective_stops} stops</span>
                  {!!r.open_exceptions && <Badge variant="at_risk">{r.open_exceptions} exc</Badge>}
                  {!!r.pending_approvals && <Badge variant="outline"><CircleDollarSign className="h-3 w-3" />{r.pending_approvals}</Badge>}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
