import { ArrowRight } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Badge } from "@/components/ui/badge";
import { useGetMeSuspense, useGetRouteImpactSuspense, useListAuditSuspense, type AuditOut, type ImpactOut } from "@/lib/api";
import { useFlow } from "@/lib/flow";
import { cn, fmtDateTime, pct } from "@/lib/utils";

const short = (routeId: string) => `R-${routeId.split("-").pop()}`;

/** Step 4: what the decision changed, and the record it left behind. */
export function ProveStep({ routeId }: { routeId: string }) {
  const impact = useGetRouteImpactSuspense(routeId).data.data;
  return (
    <div className="space-y-4 p-3">
      <ImpactStrip impact={impact} />
      <DecisionLog />
      <CloseTheLoop />
    </div>
  );
}

function Delta({ label, before, after, better, note }: { label: string; before: string; after: string; better: boolean; note?: string }) {
  return (
    <div className="rounded-md border border-border bg-white p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 flex items-baseline gap-2 tabular-nums">
        <span className="text-lg text-muted-foreground line-through decoration-1">{before}</span>
        <ArrowRight aria-hidden className="h-4 w-4 self-center text-muted-foreground" />
        <span className={cn("text-2xl font-semibold", better ? "text-[#00684c]" : "text-foreground")}>{after}</span>
      </dd>
      {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

function ImpactStrip({ impact }: { impact: ImpactOut }) {
  const { go } = useFlow();
  if (impact.moved_stops === 0) {
    return (
      <section aria-label="Impact" className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
        Nothing moved yet on {short(impact.route_id)}.{" "}
        <button type="button" className="text-accent underline" onClick={() => go("act")}>Apply a suggestion in Act</button> to see the impact here.
      </section>
    );
  }
  const hubBefore = impact.hub_on_time_before ?? 0;
  const hubAfter = impact.hub_on_time_after ?? 0;
  return (
    <section aria-label="Impact" className="space-y-2">
      <h3 className="text-sm font-semibold">
        Impact of {impact.moved_stops} move{impact.moved_stops > 1 ? "s" : ""} <span className="font-normal text-muted-foreground">(projected)</span>
      </h3>
      <dl className="grid gap-2">
        <Delta label={`${short(impact.route_id)} late stops`} before={String(impact.route_late_before)} after={String(impact.route_late_after)} better={impact.route_late_after < impact.route_late_before} />
        <Delta label={`${short(impact.route_id)} risk`} before={pct(impact.route_risk_before)} after={pct(impact.route_risk_after)} better={impact.route_risk_after < impact.route_risk_before}
          note={impact.route_risk_after < 0.5 && impact.route_risk_before >= 0.5 ? "No longer an at-risk route" : undefined} />
        <Delta label={`${impact.hub_name ?? "Hub"} on time`} before={pct(hubBefore)} after={pct(hubAfter)} better={hubAfter > hubBefore}
          note={impact.sla_target_pct != null ? `SLA target ${pct(impact.sla_target_pct)}${impact.meets_sla_after ? " · now met" : impact.meets_sla_after === false ? " · still below" : ""}` : undefined} />
      </dl>
      <p className="text-xs text-muted-foreground">
        Heuristic: a moved late stop counts as on time on a route with room for it. There is no routing solver.
      </p>
    </section>
  );
}

type Features = Record<string, unknown>;

function DecisionLog() {
  const me = useGetMeSuspense().data.data;
  const { hubId, routeId } = useFlow();
  const rows = useListAuditSuspense({ actor: me.user, action: "stop.reassign", limit: 5 }).data.data;
  return (
    <section aria-label="Decision log" className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">Your last {rows.length || 5} decisions</h3>
        <Link to="/audit" search={{ hub: hubId, route: routeId }} className="text-xs text-accent underline">Full audit trail</Link>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No decisions recorded for {me.user} yet.</p>
      ) : (
        <ul className="space-y-1.5">{rows.map((a) => <LogRow key={a.id} row={a} />)}</ul>
      )}
    </section>
  );
}

function LogRow({ row }: { row: AuditOut }) {
  const f = ((row.payload as { features?: Features }).features ?? {}) as Features;
  const p = row.payload as { from_route_id?: string; to_route_id?: string };
  const chips: [string, string][] = [];
  if (f.stop_status) chips.push(["status", String(f.stop_status)]);
  if (typeof f.late_minutes === "number" && f.late_minutes > 0) chips.push(["late", `${f.late_minutes} min`]);
  if (typeof f.route_risk_score === "number") chips.push(["route risk", pct(f.route_risk_score)]);
  if (typeof f.to_route_risk_score === "number") chips.push(["target risk", pct(f.to_route_risk_score)]);
  if (f.carrier_id) chips.push(["carrier", String(f.carrier_id)]);
  return (
    <li className="rounded-md border border-border bg-white p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">
          {row.entity_id.split("-").slice(-1)[0] && `Stop …${row.entity_id.slice(-5)}`} · {p.from_route_id ? short(p.from_route_id) : "?"} → {p.to_route_id ? short(p.to_route_id) : "?"}
        </span>
        <span className="text-muted-foreground">{fmtDateTime(row.created_at)}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {row.reason && <Badge variant="default">{row.reason}</Badge>}
        {chips.map(([k, v]) => <Badge key={k} variant="muted">{k}: {v}</Badge>)}
      </div>
    </li>
  );
}

function CloseTheLoop() {
  return (
    <section aria-label="Close the loop" className="rounded-md border border-accent/30 bg-accent/5 p-3 text-xs">
      <h3 className="text-sm font-semibold">These decisions become training data</h3>
      <p className="mt-1">
        The <code>sync_decisions</code> job copies each audit row, with the features above, from Lakebase into the Unity Catalog table{" "}
        <code>decision_labels</code>. Run it, then open the manager dashboard.
      </p>
      <pre className="mt-2 overflow-x-auto rounded bg-white p-2 text-[11px]">databricks bundle run sync_decisions -t dev --profile &lt;profile&gt;</pre>
      <p className="mt-1 text-muted-foreground">
        Manager dashboard: “Dispatch Control Tower - manager view” (decisions synced, SLA by depot, late causes).
      </p>
    </section>
  );
}
