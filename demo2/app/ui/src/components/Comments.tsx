import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/inputs";
import { useCreateComment, type CommentOut } from "@/lib/api";
import { invalidateAll } from "@/lib/live";
import { errorMessage, fmtDateTime } from "@/lib/utils";

export function Comments({ entityType, entityId, comments }: { entityType: "stop" | "route"; entityId: string; comments: CommentOut[] }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const create = useCreateComment({
    mutation: {
      onSuccess: () => { setBody(""); invalidateAll(qc); },
      onError: (e) => toast.error(errorMessage(e)),
    },
  });
  return (
    <section className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Comments</h4>
      {comments.length === 0 && <p className="text-xs text-muted-foreground">No comments yet.</p>}
      <ul className="space-y-1.5">
        {comments.map((c) => (
          <li key={c.id} className="rounded-md bg-muted px-2 py-1.5 text-xs">
            <div className="text-muted-foreground">{c.created_by} · {fmtDateTime(c.created_at)}</div>
            <div className="whitespace-pre-wrap">{c.body}</div>
          </li>
        ))}
      </ul>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (body.trim()) create.mutate({ data: { entity_type: entityType, entity_id: entityId, body } }); }}>
        <Textarea aria-label="New comment" className="min-h-9" rows={1} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Add a comment" />
        <Button size="sm" type="submit" disabled={create.isPending || !body.trim()}>Post</Button>
      </form>
    </section>
  );
}
