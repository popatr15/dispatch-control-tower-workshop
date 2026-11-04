import { Check } from "lucide-react";
import { STEPS, STEP_LABEL, useFlow, type Step } from "@/lib/flow";
import { cn } from "@/lib/utils";

/** See -> Why -> Act -> Prove. Steps after See need a route; a deep link supplies it. */
export function Stepper() {
  const { step, routeId, go } = useFlow();
  const at = STEPS.indexOf(step);
  return (
    <nav aria-label="Workflow steps" className="border-b border-border bg-white px-4 py-2">
      <ol className="flex items-center gap-2">
        {STEPS.map((s: Step, i) => {
          const locked = s !== "see" && !routeId;
          const done = i < at;
          return (
            <li key={s} className="flex items-center gap-2">
              {i > 0 && <span aria-hidden className={cn("h-px w-6", i <= at ? "bg-accent" : "bg-border")} />}
              <button
                type="button"
                disabled={locked}
                aria-current={s === step ? "step" : undefined}
                onClick={() => go(s)}
                title={locked ? "Pick a route in step 1 first" : STEP_LABEL[s].hint}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3 py-1 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  s === step ? "border-accent bg-accent text-white" : done ? "border-accent/40 text-accent hover:bg-accent/5" : "border-border text-muted-foreground hover:bg-muted",
                )}
              >
                <span className={cn("flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold", s === step ? "bg-white/20" : "bg-muted")}>
                  {done ? <Check className="h-3 w-3" /> : i + 1}
                </span>
                <span className="font-medium">{STEP_LABEL[s].title}</span>
              </button>
            </li>
          );
        })}
        <li className="ml-auto hidden text-sm text-muted-foreground md:block">{STEP_LABEL[step].hint}</li>
      </ol>
    </nav>
  );
}
