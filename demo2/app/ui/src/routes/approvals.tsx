import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Boundary } from "@/components/boundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/inputs";
import { useDecideApproval, useGetMeSuspense, useListApprovalsSuspense, type ApprovalOut, type ListApprovalsParams } from "@/lib/api";
import { cleanParams } from "@/lib/app-context";
import { invalidateAll } from "@/lib/live";
import { errorMessage, fmtDateTime } from "@/lib/utils";

export function ApprovalsPage() {
  const [status, setStatus] = useState("pending");
  return (
    <div className="mx-auto h-full max-w-4xl overflow-y-auto p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Expedite approval queue</h1>
          <p className="text-sm text-muted-foreground">Dispatchers request expedite fees from a route; managers approve or reject with a comment.</p>
        </div>
        <Select aria-label="Approval status" className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </Select>
      </div>
      <Boundary><ApprovalList status={status} /></Boundary>
    </div>
  );
}

function ApprovalList({ status }: { status: string }) {
  const { data } = useListApprovalsSuspense(cleanParams({ status: status || undefined } as ListApprovalsParams));
  const me = useGetMeSuspense().data.data;
  if (data.data.length === 0) return <p className="text-sm text-muted-foreground">Nothing here.</p>;
  return (
    <div className="space-y-3">
      {me.role !== "manager" && <p className="rounded-md bg-muted px-3 py-2 text-xs">You are signed in as a dispatcher: you can see requests, but only managers can decide them.</p>}
      {data.data.map((a) => <ApprovalCard key={a.id} approval={a} canDecide={me.role === "manager"} />)}
    </div>
  );
}

function ApprovalCard({ approval: a, canDecide }: { approval: ApprovalOut; canDecide: boolean }) {
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const decide = useDecideApproval({
    mutation: {
      onSuccess: (r) => { toast.success(`Request ${r.data.status}`); invalidateAll(qc); },
      onError: (e) => toast.error(errorMessage(e)),
    },
  });
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>${a.amount_usd.toFixed(2)} · <span className="font-mono">{a.route_id}</span>{a.stop_id && <span className="font-mono text-muted-foreground"> / {a.stop_id}</span>}</CardTitle>
          <Badge variant={a.status === "approved" ? "on_time" : a.status === "rejected" ? "late" : "at_risk"}>{a.status}</Badge>
        </div>
        <p className="text-xs text-muted-foreground">Requested by {a.requested_by} · {fmtDateTime(a.created_at)}</p>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>{a.justification}</p>
        {a.decided_by && <p className="text-xs text-muted-foreground">{a.status} by {a.decided_by} · {fmtDateTime(a.decided_at)}: “{a.decision_comment}”</p>}
        {a.status === "pending" && canDecide && (
          <div className="flex gap-2">
            <Input aria-label="Decision comment" placeholder="Comment (required)" value={comment} onChange={(e) => setComment(e.target.value)} />
            <Button variant="success" disabled={!comment.trim() || decide.isPending} onClick={() => decide.mutate({ approvalId: a.id, data: { decision: "approve", comment } })}>Approve</Button>
            <Button variant="destructive" disabled={!comment.trim() || decide.isPending} onClick={() => decide.mutate({ approvalId: a.id, data: { decision: "reject", comment } })}>Reject</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
