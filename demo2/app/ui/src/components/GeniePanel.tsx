import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAskGenie, useSendGenieFeedback, type GenieAnswerOut } from "@/lib/api";
import { cn, errorMessage } from "@/lib/utils";

// The two canonical questions from the PRD; both are answered by the seeded gold tables.
const QUESTIONS = [
  { label: "Which depots missed SLA most last week?", ask: "Which depots missed SLA most last week, and what do the late stops have in common?" },
  { label: "Late deliveries in the Northeast, by carrier", ask: "Show late deliveries in the Northeast by carrier." },
];

/** Step 2: ask Genie why. Two canned questions, the answer, and the SQL behind it. */
export function GeniePanel() {
  const [answers, setAnswers] = useState<Record<string, GenieAnswerOut>>({});
  const [active, setActive] = useState<string>();
  const [rated, setRated] = useState<Record<string, string>>({});
  const ask = useAskGenie({
    mutation: { onError: (e) => toast.error(errorMessage(e)) },
  });
  const feedback = useSendGenieFeedback({ mutation: { onError: (e) => toast.error(errorMessage(e)) } });

  const send = (q: (typeof QUESTIONS)[number]) => {
    setActive(q.ask);
    if (answers[q.ask]) return;
    ask.mutate(
      { data: { question: q.ask, conversation_id: null } },
      { onSuccess: (r) => setAnswers((a) => ({ ...a, [q.ask]: r.data })) },
    );
  };
  const answer = active ? answers[active] : undefined;

  return (
    <div className="space-y-3 p-3">
      <p className="text-sm text-muted-foreground">Genie reads the gold tables. Ask it what the late stops have in common.</p>
      <div className="space-y-2">
        {QUESTIONS.map((q) => (
          <button
            key={q.ask}
            type="button"
            disabled={ask.isPending}
            onClick={() => send(q)}
            className={cn(
              "w-full rounded-md border px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-60",
              active === q.ask ? "border-accent bg-accent/5" : "border-border bg-white",
            )}
          >
            {q.label}
          </button>
        ))}
      </div>
      {ask.isPending && <p role="status" className="text-sm text-muted-foreground">Genie is thinking…</p>}
      {answer && active && !ask.isPending && (
        <section aria-label="Genie answer" className="space-y-2 rounded-md border border-border bg-white p-3 text-sm">
          {answer.text && <p className="whitespace-pre-wrap">{answer.text}</p>}
          {answer.columns && answer.columns.length > 0 && (
            <div className="max-h-56 overflow-auto rounded border border-border">
              <table className="w-full text-xs">
                <thead className="bg-muted"><tr>{answer.columns.map((c) => <th key={c} className="px-2 py-1 text-left font-medium">{c}</th>)}</tr></thead>
                <tbody>
                  {(answer.rows ?? []).map((row, i) => (
                    <tr key={i} className="border-t border-border">
                      {(row as unknown[]).map((v, j) => <td key={j} className="px-2 py-1 tabular-nums">{v == null ? "" : String(v)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {answer.sql && (
            <details>
              <summary className="cursor-pointer text-xs text-muted-foreground">Show the SQL Genie wrote</summary>
              <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-[11px]">{answer.sql}</pre>
            </details>
          )}
          <div className="flex items-center gap-1">
            {(["positive", "negative"] as const).map((rating) => (
              <Button
                key={rating}
                size="icon"
                variant={rated[answer.message_id] === rating ? "default" : "ghost"}
                aria-label={rating === "positive" ? "Helpful" : "Not helpful"}
                disabled={!!rated[answer.message_id] || feedback.isPending}
                onClick={() => feedback.mutate(
                  { data: { conversation_id: answer.conversation_id, message_id: answer.message_id, rating } },
                  { onSuccess: () => setRated((r) => ({ ...r, [answer.message_id]: rating })) },
                )}
              >
                {rating === "positive" ? <ThumbsUp className="h-3.5 w-3.5" /> : <ThumbsDown className="h-3.5 w-3.5" />}
              </Button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
