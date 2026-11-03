import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Boundary } from "@/components/boundary";
import { Input, Select } from "@/components/ui/inputs";
import { useListAuditSuspense, type ListAuditParams } from "@/lib/api";
import { cleanParams } from "@/lib/app-context";
import { fmtDateTime } from "@/lib/utils";

const ACTIONS = [
  "stop.reassign", "exception.create", "exception.update", "approval.request", "approval.approve",
  "approval.reject", "comment.create", "route_state.update", "genie.feedback",
];

export function AuditPage() {
  const [filters, setFilters] = useState<ListAuditParams>({});
  const set = (patch: Partial<ListAuditParams>) => setFilters((f) => cleanParams({ ...f, ...patch }));
  return (
    <div className="flex h-full flex-col p-4">
      <div className="mb-3">
        <Link to="/" search={{ step: "prove" }} className="text-xs text-accent underline">← Back to the flow</Link>
        <h1 className="text-lg font-semibold">Audit trail</h1>
        <p className="text-sm text-muted-foreground">Every write, recorded in the same Lakebase transaction as the change it describes.</p>
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        <Input aria-label="Actor" className="w-56" placeholder="Actor" value={filters.actor ?? ""} onChange={(e) => set({ actor: e.target.value || undefined })} />
        <Select aria-label="Action" className="w-48" value={filters.action ?? ""} onChange={(e) => set({ action: e.target.value || undefined })}>
          <option value="">All actions</option>
          {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
        </Select>
        <Select aria-label="Entity type" className="w-36" value={filters.entity_type ?? ""} onChange={(e) => set({ entity_type: e.target.value || undefined })}>
          <option value="">All entities</option>
          <option value="stop">Stop</option>
          <option value="route">Route</option>
          <option value="genie_message">Genie message</option>
        </Select>
        <Input aria-label="Entity id" className="w-56" placeholder="Stop or route id" value={filters.entity_id ?? ""} onChange={(e) => set({ entity_id: e.target.value || undefined })} />
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-md border border-border bg-white">
        <Boundary><AuditTable filters={filters} /></Boundary>
      </div>
    </div>
  );
}

function AuditTable({ filters }: { filters: ListAuditParams }) {
  const { data } = useListAuditSuspense({ ...filters, limit: 500 });
  if (data.data.length === 0) return <p className="p-3 text-sm text-muted-foreground">No audit entries match.</p>;
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 bg-muted text-left">
        <tr>{["Time", "Actor", "Action", "Entity", "Reason", "Details"].map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}</tr>
      </thead>
      <tbody>
        {data.data.map((a) => (
          <tr key={a.id} className="border-t border-border align-top">
            <td className="whitespace-nowrap px-2 py-1">{fmtDateTime(a.created_at)}</td>
            <td className="px-2 py-1">{a.actor}</td>
            <td className="px-2 py-1 font-mono">{a.action}</td>
            <td className="px-2 py-1 font-mono">{a.entity_type}:{a.entity_id}</td>
            <td className="px-2 py-1">{a.reason ?? ""}</td>
            <td className="px-2 py-1">
              <details>
                <summary className="cursor-pointer text-muted-foreground">payload</summary>
                <pre className="mt-1 max-w-md overflow-x-auto text-[11px]">{JSON.stringify(a.payload, null, 2)}</pre>
              </details>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
