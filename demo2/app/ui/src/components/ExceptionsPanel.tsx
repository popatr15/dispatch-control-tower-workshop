import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/inputs";
import { useListExceptionsSuspense, useUpdateException, type ListExceptionsParams } from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { invalidateAll } from "@/lib/live";
import { errorMessage, fmtDateTime } from "@/lib/utils";

export function ExceptionsPanel() {
  const qc = useQueryClient();
  const { selectStop } = useAppState();
  const [status, setStatus] = useState<string>("open");
  const { data } = useListExceptionsSuspense(cleanParams({ status: status || undefined } as ListExceptionsParams));
  const update = useUpdateException({
    mutation: { onSuccess: () => invalidateAll(qc), onError: (e) => toast.error(errorMessage(e)) },
  });
  return (
    <div className="space-y-2">
      <Select aria-label="Exception status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-36">
        <option value="open">Open</option>
        <option value="resolved">Resolved</option>
        <option value="">All</option>
      </Select>
      {data.data.length === 0 && <p className="text-sm text-muted-foreground">No exceptions.</p>}
      <ul className="space-y-2">
        {data.data.map((x) => (
          <li key={x.id} className="rounded-md border border-border p-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{x.exception_type.replace("_", " ")}</span>
              <Badge variant={x.status === "open" ? "at_risk" : "muted"}>{x.status}</Badge>
            </div>
            <p className="mt-1">{x.reason}</p>
            <p className="mt-1 text-muted-foreground">
              <button type="button" className="font-mono text-accent underline" onClick={() => selectStop(x.stop_id, x.route_id)}>{x.stop_id}</button>
              {" "}· {x.created_by} · {fmtDateTime(x.created_at)}
            </p>
            <Button size="sm" variant="outline" className="mt-1.5" disabled={update.isPending}
              onClick={() => update.mutate({ exceptionId: x.id, data: { status: x.status === "open" ? "resolved" : "open" } })}>
              {x.status === "open" ? "Mark resolved" : "Reopen"}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
