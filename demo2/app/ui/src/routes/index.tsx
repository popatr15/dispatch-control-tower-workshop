import { ArrowLeft, ArrowRight } from "lucide-react";
import { useState } from "react";
import { Boundary } from "@/components/boundary";
import { GeniePanel } from "@/components/GeniePanel";
import { HubList } from "@/components/HubList";
import { ProveStep } from "@/components/ProveStep";
import { Stepper } from "@/components/Stepper";
import { SuggestedReassigns } from "@/components/SuggestedReassigns";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/inputs";
import { useListHubs } from "@/lib/api";
import { STEP_LABEL, STEPS, useFlow } from "@/lib/flow";
import { DispatchMap } from "@/map/DispatchMap";

const short = (routeId: string) => `R-${routeId.split("-").pop()}`;

/** A linear See -> Why -> Act -> Prove stepper; the map stays on the left throughout. */
export function ControlTowerPage() {
  const { step, hubId, routeId, selectHub, next, back } = useFlow();
  const hubs = useListHubs().data?.data ?? [];
  const [moved, setMoved] = useState<string[]>([]);
  const needsRoute = step !== "see" && !routeId;
  const last = step === STEPS[STEPS.length - 1];

  return (
    <div className="flex h-full flex-col">
      <Stepper />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_440px] grid-rows-[minmax(0,1fr)]">
        <section className="min-h-0">
          <DispatchMap hubs={hubs} hubId={hubId} routeId={routeId} onSelectHub={selectHub} />
        </section>
        <aside className="flex min-h-0 flex-col border-l border-border bg-white" aria-label={`Step: ${STEP_LABEL[step].title}`}>
          <header className="border-b border-border px-3 py-2">
            <h2 className="text-base font-semibold">{STEP_LABEL[step].title}: {STEP_LABEL[step].hint}</h2>
            {routeId && <p className="text-xs text-muted-foreground">Route {short(routeId)}</p>}
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Boundary fallback={<div className="space-y-2 p-3">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-16" />)}</div>}>
              {needsRoute ? (
                <p className="p-3 text-sm text-muted-foreground">Pick a route in step 1 first.</p>
              ) : step === "see" ? (
                <HubList />
              ) : step === "why" ? (
                <GeniePanel />
              ) : step === "act" ? (
                <SuggestedReassigns routeId={routeId!} onMoved={(id) => setMoved((m) => [...m, id])} />
              ) : (
                <ProveStep routeId={routeId!} />
              )}
            </Boundary>
          </div>
          <footer className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
            <Button variant="outline" onClick={back} disabled={step === "see"}><ArrowLeft className="h-4 w-4" />Back</Button>
            {step === "act" && moved.length > 0 && <span className="text-xs text-[#00684c]">{moved.length} stop{moved.length > 1 ? "s" : ""} moved</span>}
            <Button onClick={next} disabled={last || (step === "see" && !routeId)} title={step === "see" && !routeId ? "Pick a route first" : undefined}>
              {step === "act" && moved.length > 0 ? "Prove it" : "Next"}<ArrowRight className="h-4 w-4" />
            </Button>
          </footer>
        </aside>
      </div>
    </div>
  );
}
