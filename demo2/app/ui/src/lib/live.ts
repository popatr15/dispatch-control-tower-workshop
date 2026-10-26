import { useQueryClient, type Query } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type LiveMode = "connecting" | "live" | "polling";

// Query-key prefixes (Orval keys start with the request path) refreshed per event type.
const AFFECTS: Record<string, string[]> = {
  "stop.reassigned": ["/api/routes", "/api/stops", "/api/map/clusters", "/api/audit"],
  "exception.changed": ["/api/exceptions", "/api/routes", "/api/stops", "/api/audit"],
  "approval.changed": ["/api/approvals", "/api/routes", "/api/audit"],
  "comment.added": ["/api/comments", "/api/routes", "/api/stops", "/api/audit"],
  "route_state.changed": ["/api/routes", "/api/route-state", "/api/audit"],
};
const ALL = [...new Set(Object.values(AFFECTS).flat())];
const POLL_MS = 10_000;

function matcher(prefixes: string[]) {
  return (q: Query) => {
    const head = q.queryKey[0];
    return typeof head === "string" && prefixes.some((p) => head.startsWith(p));
  };
}

export interface LiveEvent {
  type: string;
  actor?: string;
  entity_id?: string;
  state?: string;
}

/**
 * Subscribes to /api/events (SSE) and invalidates affected queries so other
 * users' changes appear within a second or two. If the stream keeps failing,
 * falls back to polling every 10s.
 */
export function useLiveUpdates(onEvent?: (e: LiveEvent) => void): LiveMode {
  const qc = useQueryClient();
  const [mode, setMode] = useState<LiveMode>("connecting");

  useEffect(() => {
    let failures = 0;
    let poll: ReturnType<typeof setInterval> | undefined;
    const source = new EventSource("/api/events");
    const startPolling = () => {
      if (poll) return;
      setMode("polling");
      poll = setInterval(() => qc.invalidateQueries({ predicate: matcher(ALL) }), POLL_MS);
    };
    source.onopen = () => {
      failures = 0;
      if (poll) clearInterval(poll);
      poll = undefined;
      setMode("live");
    };
    source.onerror = () => {
      failures += 1;
      if (failures >= 3) startPolling();
    };
    source.addEventListener("change", (msg) => {
      try {
        const event = JSON.parse((msg as MessageEvent).data) as LiveEvent;
        qc.invalidateQueries({ predicate: matcher(AFFECTS[event.type] ?? ALL) });
        onEvent?.(event);
      } catch {
        /* ignore malformed */
      }
    });
    return () => {
      source.close();
      if (poll) clearInterval(poll);
    };
  }, [qc, onEvent]);

  return mode;
}

export function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  return qc.invalidateQueries({ predicate: matcher(ALL) });
}
