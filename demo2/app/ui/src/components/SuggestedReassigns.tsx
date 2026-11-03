import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/inputs";
import { StatusBadge } from "@/components/ui/status-badge";
import { useGetRouteSuggestionsSuspense, useReassignStop, type SuggestionOut } from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { invalidateAll } from "@/lib/live";
import type { StopStatus } from "@/lib/status";
import { errorMessage } from "@/lib/utils";

const DISMISSED_KEY = "dispatch-tower-dismissed";
const SHOW = 4;

const key = (s: SuggestionOut) => `${s.stop_id}>${s.to_route_id}`;

function loadDismissed(): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(DISMISSED_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

/**
 * Server-computed suggestions for the late/at-risk stops on this route. Apply
 * uses the normal reassign endpoint (audit row in the same transaction) with
 * reason sla_risk and the suggestion as the note; Dismiss is per browser session.
 */
export function SuggestedReassigns({ routeId }: { routeId: string }) {
  const { filters, selectStop } = useAppState();
  const { data } = useGetRouteSuggestionsSuspense(routeId, cleanParams({ day: filters.day }));
  const [dismissed, setDismissed] = useState(loadDismissed);
  const [showAll, setShowAll] = useState(false);
  const { at_risk, suggestions } = data.data;

  const dismiss = (s: SuggestionOut) => {
    const next = new Set(dismissed).add(key(s));
    sessionStorage.setItem(DISMISSED_KEY, JSON.stringify([...next]));
    setDismissed(next);
  };
  const restore = () => {
    sessionStorage.removeItem(DISMISSED_KEY);
    setDismissed(new Set());
  };

  const byStop = new Map<string, SuggestionOut[]>();
  for (const s of suggestions) {
    if (dismissed.has(key(s))) continue;
    byStop.set(s.stop_id, [...(byStop.get(s.stop_id) ?? []), s]);
  }
  const groups = [...byStop.values()];
  const hidden = suggestions.filter((s) => dismissed.has(key(s))).length;

  return (
    <section aria-labelledby="suggested-title" className="space-y-2 rounded-md border border-accent/40 bg-accent/5 p-2">
      <div className="flex items-baseline justify-between gap-2">
        <h4 id="suggested-title" className="text-sm font-semibold">Suggested reassigns</h4>
        {groups.length > 0 && <span className="text-xs text-muted-foreground">{groups.length} stop{groups.length > 1 ? "s" : ""}</span>}
      </div>
      {!at_risk && <p className="text-xs text-muted-foreground">This route is not at risk, so there is nothing to suggest.</p>}
      {at_risk && groups.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No same-hub route with lower risk and spare capacity is close enough. Use a stop's manual reassign instead.
        </p>
      )}
      <ul className="space-y-2">
        {(showAll ? groups : groups.slice(0, SHOW)).map((options) => (
          <li key={options[0].stop_id} className="rounded-md border border-border bg-white p-2">
            <div className="flex items-center justify-between gap-2 text-xs">
              <button type="button" className="truncate text-left font-medium hover:underline"
                onClick={() => selectStop(options[0].stop_id, routeId)}>
                #{options[0].sequence} {options[0].customer_name}
                {options[0].late_minutes > 0 && <span className="text-muted-foreground"> · {options[0].late_minutes} min late</span>}
              </button>
              <StatusBadge status={options[0].stop_status as StopStatus} />
            </div>
            <ul className="mt-1.5 space-y-1.5">
              {options.map((s) => <Option key={key(s)} s={s} onDismiss={() => dismiss(s)} />)}
            </ul>
          </li>
        ))}
      </ul>
      <div className="flex gap-3 text-xs">
        {groups.length > SHOW && (
          <button type="button" className="text-accent hover:underline" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${groups.length}`}
          </button>
        )}
        {hidden > 0 && <button type="button" className="text-accent hover:underline" onClick={restore}>Restore {hidden} dismissed</button>}
      </div>
    </section>
  );
}

function Option({ s, onDismiss }: { s: SuggestionOut; onDismiss: () => void }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState(s.reason);
  const apply = useReassignStop({
    mutation: {
      onSuccess: (r) => { toast.success(`Moved to ${r.data.to_route_id}`); invalidateAll(qc); },
      onError: (e) => toast.error(errorMessage(e)),
    },
  });
  return (
    <li className="text-xs">
      <p>{s.reason}</p>
      {confirming ? (
        <form className="mt-1 space-y-1" onSubmit={(e) => {
          e.preventDefault();
          apply.mutate({ stopId: s.stop_id, data: { to_route_id: s.to_route_id, reason_code: "sla_risk", note: note || null } });
        }}>
          <Textarea aria-label="Reassignment note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={apply.isPending}>{apply.isPending ? "Applying…" : `Confirm move to ${s.to_route_id}`}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <div className="mt-1 flex gap-2">
          <Button type="button" size="sm" onClick={() => setConfirming(true)}>Apply</Button>
          <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>
        </div>
      )}
    </li>
  );
}
