import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, Textarea } from "@/components/ui/inputs";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  useGetRouteSuggestionsSuspense,
  useListRoutes,
  useReassignStop,
  type SuggestionOut,
} from "@/lib/api";
import { useFlow } from "@/lib/flow";
import { invalidateAll } from "@/lib/live";
import type { StopStatus } from "@/lib/status";
import { errorMessage } from "@/lib/utils";

const short = (routeId: string) => `R-${routeId.split("-").pop()}`;

/**
 * Step 3: the server-ranked late stops worth moving. Apply writes the reassignment
 * and its audit row in one Lakebase transaction, with reason sla_risk prefilled.
 */
export function SuggestedReassigns({ routeId, onMoved }: { routeId: string; onMoved: (stopId: string) => void }) {
  const { restart } = useFlow();
  const { data } = useGetRouteSuggestionsSuspense(routeId);
  const { at_risk, suggestions } = data.data;

  if (!at_risk) {
    return (
      <p className="p-3 text-sm text-muted-foreground">
        {short(routeId)} is not at risk, so there is nothing to move.{" "}
        <button type="button" className="text-accent underline" onClick={restart}>Pick the red route instead</button>
      </p>
    );
  }
  if (suggestions.length === 0) {
    return (
      <p className="p-3 text-sm text-muted-foreground">
        No same-hub route has spare capacity and lower risk.{" "}
        <button type="button" className="text-accent underline" onClick={restart}>Pick another route</button>
      </p>
    );
  }
  return (
    <ul className="space-y-2 p-3" aria-label="Suggested reassigns">
      {suggestions.map((s) => <Suggestion key={s.stop_id} s={s} onMoved={onMoved} />)}
    </ul>
  );
}

function Suggestion({ s, onMoved }: { s: SuggestionOut; onMoved: (stopId: string) => void }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"idle" | "confirm" | "other">("idle");
  const [target, setTarget] = useState(s.to_route_id);
  const [note, setNote] = useState(s.reason);
  const move = useReassignStop({
    mutation: {
      onSuccess: () => { onMoved(s.stop_id); void invalidateAll(qc); },
      onError: (e) => toast.error(errorMessage(e)),
    },
  });
  const confirm = (to: string) =>
    move.mutate({ stopId: s.stop_id, data: { to_route_id: to, reason_code: "sla_risk", note: note || null } });

  return (
    <li className="rounded-md border border-border bg-white p-2.5 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">#{s.sequence} {s.customer_name}</span>
        <StatusBadge status={s.stop_status as StopStatus} />
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {(s.late_minutes ?? 0) > 0 ? `${s.late_minutes} min late · ` : ""}move to <b className="text-foreground">{short(s.to_route_id)}</b>:{" "}
        {s.distance_km.toFixed(1)} km away, risk {Math.round(s.to_risk_score * 100)}% vs {Math.round(s.from_risk_score * 100)}%
      </p>
      {mode === "idle" && (
        <div className="mt-2 flex items-center gap-3">
          <Button size="sm" onClick={() => setMode("confirm")}>Apply</Button>
          <button type="button" className="text-xs text-accent underline" onClick={() => setMode("other")}>Pick another route</button>
        </div>
      )}
      {mode !== "idle" && (
        <form
          className="mt-2 space-y-2"
          onSubmit={(e) => { e.preventDefault(); confirm(mode === "other" ? target : s.to_route_id); }}
        >
          {mode === "other" && <OtherRoute from={s.from_route_id} hubStop={s} value={target} onChange={setTarget} />}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Reason</span>
            <code className="rounded bg-muted px-1.5 py-0.5">sla_risk</code>
          </div>
          <Textarea aria-label="Note" rows={2} className="min-h-0 text-xs" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={move.isPending}>
              {move.isPending ? "Moving…" : `Confirm move to ${short(mode === "other" ? target : s.to_route_id)}`}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setMode("idle")}>Cancel</Button>
          </div>
        </form>
      )}
    </li>
  );
}

function OtherRoute({ from, hubStop, value, onChange }: { from: string; hubStop: SuggestionOut; value: string; onChange: (v: string) => void }) {
  const routes = useListRoutes().data?.data ?? [];
  const depot = routes.find((r) => r.route_id === from)?.depot_id;
  const options = routes.filter((r) => r.route_id !== from && r.depot_id === depot);
  return (
    <Select aria-label={`Target route for stop ${hubStop.sequence}`} className="h-8 py-0 text-xs" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((r) => (
        <option key={r.route_id} value={r.route_id}>
          {short(r.route_id)} · risk {Math.round(r.risk_score * 100)}% · {r.effective_stops}/{r.capacity_stops ?? "?"} stops
        </option>
      ))}
    </Select>
  );
}
