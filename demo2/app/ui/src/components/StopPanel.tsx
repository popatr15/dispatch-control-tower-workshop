import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Comments } from "@/components/Comments";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label, Select, Textarea } from "@/components/ui/inputs";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  useCreateException,
  useGetFiltersSuspense,
  useGetStopSuspense,
  useListRoutesSuspense,
  useReassignStop,
  type ExceptionInExceptionType,
  type ReassignInReasonCode,
} from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { invalidateAll } from "@/lib/live";
import type { StopStatus } from "@/lib/status";
import { errorMessage, fmtDateTime, fmtTime } from "@/lib/utils";

export function StopPanel() {
  const { stopId } = useAppState();
  if (!stopId) return <p className="text-sm text-muted-foreground">Select a stop on the map (zoom in) or in a route's stop list.</p>;
  return <StopDetail key={stopId} stopId={stopId} />;
}

function StopDetail({ stopId }: { stopId: string }) {
  const qc = useQueryClient();
  const { filters, selectRoute } = useAppState();
  const { data } = useGetStopSuspense(stopId, cleanParams({ day: filters.day }));
  const { stop, reassignments, exceptions, comments, route_risk_score } = data.data;
  const meta = useGetFiltersSuspense().data.data;
  const routes = useListRoutesSuspense(cleanParams({ day: filters.day })).data.data;
  const candidates = routes.filter((r) => r.route_id !== stop.route_id)
    .sort((a, b) => Number(b.depot_id === stop.depot_id) - Number(a.depot_id === stop.depot_id) || a.risk_score - b.risk_score);

  const [toRoute, setToRoute] = useState("");
  const [reason, setReason] = useState<ReassignInReasonCode>("sla_risk");
  const [note, setNote] = useState("");
  const [excType, setExcType] = useState<ExceptionInExceptionType>("customer_unavailable");
  const [excReason, setExcReason] = useState("");
  const onError = (e: unknown) => toast.error(errorMessage(e));
  const reassign = useReassignStop({ mutation: { onSuccess: (r) => { toast.success(`Moved to ${r.data.to_route_id}`); setNote(""); setToRoute(""); invalidateAll(qc); }, onError } });
  const logException = useCreateException({ mutation: { onSuccess: () => { toast.success("Exception logged"); setExcReason(""); invalidateAll(qc); }, onError } });
  const delivered = stop.status === "delivered";

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">{stop.customer_name}</h3>
          <StatusBadge status={stop.status as StopStatus} />
        </div>
        <p className="text-xs text-muted-foreground">{stop.address}, {stop.city}, {stop.state}</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">Window (UTC)</dt><dd>{fmtTime(stop.promised_window_start)}–{fmtTime(stop.promised_window_end)}</dd>
          <dt className="text-muted-foreground">ETA</dt><dd>{fmtTime(stop.eta_ts)}{stop.late_minutes ? ` (+${stop.late_minutes} min)` : ""}</dd>
          <dt className="text-muted-foreground">Route</dt>
          <dd>
            <button type="button" className="font-mono text-accent underline" onClick={() => selectRoute(stop.route_id)}>{stop.route_id}</button>
            {stop.reassigned && <span className="ml-1 text-violet-800">from {stop.original_route_id}</span>}
          </dd>
          <dt className="text-muted-foreground">Route risk</dt><dd>{route_risk_score != null ? `${Math.round(route_risk_score * 100)}%` : "—"}</dd>
          {stop.late_reason_code && (<><dt className="text-muted-foreground">Late reason</dt><dd>{stop.late_reason_code}</dd></>)}
        </dl>
      </div>

      <section className="space-y-2 rounded-md border border-border p-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Reassign stop</h4>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); reassign.mutate({ stopId, data: { to_route_id: toRoute, reason_code: reason, note: note || null } }); }}>
          <div>
            <Label htmlFor="to-route">Move to route</Label>
            <Select id="to-route" value={toRoute} onChange={(e) => setToRoute(e.target.value)} disabled={delivered}>
              <option value="">Choose a route…</option>
              {candidates.map((r) => (
                <option key={r.route_id} value={r.route_id}>
                  {r.route_id} · {r.depot_id === stop.depot_id ? "same depot" : r.depot_id} · risk {Math.round(r.risk_score * 100)}%
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="reason-code">Reason</Label>
            <Select id="reason-code" value={reason} onChange={(e) => setReason(e.target.value as ReassignInReasonCode)}>
              {meta.reason_codes.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
            </Select>
          </div>
          <Textarea aria-label="Reassignment note" rows={2} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button type="submit" size="sm" disabled={!toRoute || reassign.isPending || delivered}>
            {reassign.isPending ? "Saving…" : "Reassign"}
          </Button>
          {delivered && <p className="text-xs text-muted-foreground">Delivered stops cannot be reassigned.</p>}
        </form>
        {reassignments.length > 0 && (
          <ul className="space-y-1 border-t border-border pt-2 text-xs">
            {reassignments.map((r) => (
              <li key={r.id}>{fmtDateTime(r.created_at)} · {r.from_route_id} → <span className="font-mono">{r.to_route_id}</span> · {r.reason_code} · {r.created_by}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2 rounded-md border border-border p-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Log exception</h4>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); logException.mutate({ data: { stop_id: stopId, exception_type: excType, reason: excReason } }); }}>
          <Select aria-label="Exception type" value={excType} onChange={(e) => setExcType(e.target.value as ExceptionInExceptionType)}>
            {meta.exception_types.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
          </Select>
          <Textarea aria-label="Exception reason" rows={2} placeholder="What happened? (min 3 chars)" value={excReason} onChange={(e) => setExcReason(e.target.value)} />
          <Button type="submit" size="sm" variant="outline" disabled={excReason.trim().length < 3 || logException.isPending}>Log exception</Button>
        </form>
        {exceptions.length > 0 && (
          <ul className="space-y-1 border-t border-border pt-2 text-xs">
            {exceptions.map((x) => (
              <li key={x.id} className="flex items-center justify-between gap-2">
                <span>{x.exception_type.replace("_", " ")}: {x.reason}</span>
                <Badge variant={x.status === "open" ? "at_risk" : "muted"}>{x.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Comments entityType="stop" entityId={stopId} comments={comments} />
    </div>
  );
}
