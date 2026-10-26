import { useQueryClient } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/inputs";
import { useAskGenie, useListGenieHistory, useSendGenieFeedback, type GenieAnswerOut } from "@/lib/api";
import { errorMessage } from "@/lib/utils";

const SAMPLES = [
  "Which depots missed SLA most last week, and what do the late stops have in common?",
  "Show late deliveries in the Northeast by carrier.",
];

export function GeniePanel() {
  const qc = useQueryClient();
  const [conversationId, setConversationId] = useState<string>();
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<GenieAnswerOut[]>([]);
  const [rated, setRated] = useState<Record<string, string>>({});
  const history = useListGenieHistory({}, { query: { enabled: answers.length === 0 } });
  const ask = useAskGenie({
    mutation: {
      onSuccess: (r) => {
        setConversationId(r.data.conversation_id);
        setAnswers((a) => [...a, r.data]);
        setQuestion("");
        qc.invalidateQueries({ queryKey: ["/api/genie/history"] });
      },
      onError: (e) => toast.error(errorMessage(e)),
    },
  });
  const feedback = useSendGenieFeedback({ mutation: { onError: (e) => toast.error(errorMessage(e)) } });

  const send = (q: string) => ask.mutate({ data: { question: q, conversation_id: conversationId ?? null } });
  const past = (history.data?.data ?? []).slice(-6);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Ask why. Answers come from Genie over the gold tables; the SQL is shown.</p>
        {conversationId && <Button size="sm" variant="ghost" onClick={() => { setConversationId(undefined); setAnswers([]); }}>New chat</Button>}
      </div>
      {answers.length === 0 && (
        <div className="space-y-1.5">
          {SAMPLES.map((q) => (
            <button key={q} type="button" className="w-full rounded-md border border-border px-2 py-1.5 text-left text-xs hover:bg-muted" onClick={() => send(q)} disabled={ask.isPending}>{q}</button>
          ))}
          {past.length > 0 && (
            <div className="pt-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Your recent questions</h4>
              <ul className="mt-1 space-y-1 text-xs">
                {past.map((m) => (
                  <li key={m.message_id}>
                    <button type="button" className="text-left text-accent underline" onClick={() => setConversationId(m.conversation_id)}>{m.question}</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      <ol className="space-y-3">
        {answers.map((a) => (
          <li key={a.message_id} className="space-y-1.5 rounded-md border border-border p-2 text-xs">
            <p className="font-medium">{a.question}</p>
            {a.text && <p className="whitespace-pre-wrap">{a.text}</p>}
            {a.sql && (
              <details>
                <summary className="cursor-pointer text-muted-foreground">Generated SQL</summary>
                <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-[11px]">{a.sql}</pre>
              </details>
            )}
            {a.columns && a.columns.length > 0 && (
              <div className="max-h-56 overflow-auto rounded border border-border">
                <table className="w-full text-[11px]">
                  <thead className="bg-muted"><tr>{a.columns.map((c) => <th key={c} className="px-1.5 py-1 text-left font-medium">{c}</th>)}</tr></thead>
                  <tbody>{(a.rows ?? []).map((row, i) => <tr key={i} className="border-t border-border">{(row as unknown[]).map((v, j) => <td key={j} className="px-1.5 py-0.5">{v == null ? "" : String(v)}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
            <div className="flex items-center gap-1">
              {(["positive", "negative"] as const).map((rating) => (
                <Button key={rating} size="icon" variant={rated[a.message_id] === rating ? "default" : "ghost"} aria-label={rating === "positive" ? "Helpful" : "Not helpful"}
                  disabled={!!rated[a.message_id] || feedback.isPending}
                  onClick={() => feedback.mutate({ data: { conversation_id: a.conversation_id, message_id: a.message_id, rating } }, { onSuccess: () => setRated((r) => ({ ...r, [a.message_id]: rating })) })}>
                  {rating === "positive" ? <ThumbsUp className="h-3.5 w-3.5" /> : <ThumbsDown className="h-3.5 w-3.5" />}
                </Button>
              ))}
              {(a.suggested_questions ?? []).slice(0, 2).map((q) => (
                <button key={q} type="button" className="ml-1 truncate rounded-full border border-border px-2 py-0.5 hover:bg-muted" onClick={() => send(q)}>{q}</button>
              ))}
            </div>
          </li>
        ))}
      </ol>
      <form className="mt-auto flex gap-2" onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 3) send(question); }}>
        <Textarea aria-label="Ask Genie" rows={2} placeholder={conversationId ? "Ask a follow-up…" : "Ask a question about deliveries…"} value={question} onChange={(e) => setQuestion(e.target.value)} />
        <Button type="submit" disabled={ask.isPending || question.trim().length < 3}>{ask.isPending ? "Thinking…" : "Ask"}</Button>
      </form>
    </div>
  );
}
