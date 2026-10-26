import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Comments } from "@/components/Comments";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/inputs";
import { StatusBadge } from "@/components/ui/status-badge";
import { useGetRouteSuspense, useRequestApproval, useSetRouteState, type RouteStateInState } from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { invalidateAll } from "@/lib/live";
import type { StopStatus } from "@/lib/status";
import { errorMessage, fmtDateTime, fmtTime } from "@/lib/utils";

const STATES: RouteStateInState[] = ["planned", "in_progress", "delayed", "completed"];

export function RoutePanel() {
  const { routeId } = useAppState();
  if (!routeId) return <p className="text-sm text-muted-foreground">Select a route in the list or on the map.</p>;
  return <RouteDetail routeId={routeId} />;
}

function RouteDetail({ routeId }: { routeId: string }) {
  const qc = useQueryClient();
  const { filters, selectStop } = useAppState();
  const { data } = useGetRouteSuspense(routeId, cleanParams({ day: filters.day }));
  const { route, stops, comments, approvals } = data.data;
  const [amount, setAmount] = useState("250");
  const [why, setWhy] = useState("");
  const onError = (e: unknown) => toast.error(errorMessage(e));
  const setState = useSetRouteState({ mutation: { onSuccess: () => { toast.success("Route state updated"); invalidateAll(qc); }, onError } });
  const request = useRequestApproval({ mutation: { onSuccess: () => { toast.success("Expedite request sent to managers"); setWhy(""); invalidateAll(qc); }, onError } });

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-mono text-sm font-semibold">{route.route_id}</h3>
          <span className="text-sm font-semibold">risk {Math.round(route.risk_score * 100)}%</span>
        </div>
        <p className="text-xs text-muted-foreground">{route.risk_reason ?? "No risk reason"}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Driver {route.driver_name ?? "—"} · vehicle {route.vehicle_id ?? "—"} · starts {fmtTime(route.planned_start_ts)}
        </p>
      </div>

      <section className="space-y-1.5">
        <Label htmlFor="route-state">Live route state</Label>
        <div className="flex items-center gap-2">
          <Select id="route-state" value={route.status} disabled={setState.isPending}
            onChange={(e) => setState.mutate({ routeId, data: { state: e.target.value as RouteStateInState } })}>
            {STATES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </Select>
        </div>
        {route.state_updated_by && (
          <p className="text-xs text-muted-foreground">Last set by {route.state_updated_by} · {fmtDateTime(route.state_updated_at)}</p>
        )}
      </section>

      <section className="space-y-1.5 rounded-md border border-border p-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Request expedite fee</h4>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); request.mutate({ data: { route_id: routeId, amount_usd: Number(amount), justification: why } }); }}>
          <div className="flex gap-2">
            <Input aria-label="Amount (USD)" type="number" min={1} step="0.01" className="w-28" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <Textarea aria-label="Justification" rows={1} className="min-h-9" placeholder="Justification (min 5 chars)" value={why} onChange={(e) => setWhy(e.target.value)} />
          </div>
          <Button size="sm" type="submit" disabled={request.isPending || why.trim().length < 5 || !(Number(amount) > 0)}>Submit request</Button>
        </form>
        {approvals.length > 0 && (
          <ul className="space-y-1 pt-1 text-xs">
            {approvals.map((a) => (
              <li key={a.id} className="flex items-center justify-between">
                <span>${a.amount_usd.toFixed(2)} by {a.requested_by}</span>
                <Badge variant={a.status === "approved" ? "on_time" : a.status === "rejected" ? "late" : "at_risk"}>{a.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-1">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Stops ({stops.length})</h4>
        <ul className="max-h-64 overflow-y-auto rounded-md border border-border">
          {stops.map((s) => (
            <li key={s.stop_id}>
              <button type="button" className="flex w-full items-center justify-between gap-2 border-b border-border px-2 py-1 text-left text-xs last:border-0 hover:bg-muted" onClick={() => selectStop(s.stop_id, s.route_id)}>
                <span className="truncate">#{s.sequence} {s.customer_name}{s.reassigned && <span className="ml-1 text-violet-800">(moved in)</span>}</span>
                <StatusBadge status={s.status as StopStatus} />
              </button>
            </li>
          ))}
        </ul>
      </section>

      <Comments entityType="route" entityId={routeId} comments={comments} />
    </div>
  );
}
