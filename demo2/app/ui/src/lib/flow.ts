import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback } from "react";

export const STEPS = ["see", "why", "act", "prove"] as const;
export type Step = (typeof STEPS)[number];

export const STEP_LABEL: Record<Step, { title: string; hint: string }> = {
  see: { title: "See", hint: "Which hub is in trouble?" },
  why: { title: "Why", hint: "What is behind the late stops?" },
  act: { title: "Act", hint: "Which late stops move, and where?" },
  prove: { title: "Prove", hint: "What changed, and who decided?" },
};

/** The whole flow state lives in the URL, so every step is deep-linkable. */
export interface FlowSearch {
  step: Step;
  hub?: string;
  route?: string;
}

export function validateFlowSearch(raw: Record<string, unknown>): FlowSearch {
  const step = STEPS.find((s) => s === raw.step) ?? "see";
  const str = (v: unknown) => (typeof v === "string" && v ? v : undefined);
  return { step, hub: str(raw.hub), route: str(raw.route) };
}

export function useFlow() {
  const search = useSearch({ strict: false }) as Partial<FlowSearch>;
  const navigate = useNavigate();
  const step: Step = search.step ?? "see";
  const hubId = search.hub;
  const routeId = search.route;

  const update = useCallback(
    (patch: Partial<FlowSearch>) => {
      void navigate({ to: "/", search: (prev) => ({ ...validateFlowSearch(prev), ...patch }) });
    },
    [navigate],
  );

  return {
    step,
    hubId,
    routeId,
    go: (s: Step) => update({ step: s }),
    next: () => update({ step: STEPS[Math.min(STEPS.indexOf(step) + 1, STEPS.length - 1)] }),
    back: () => update({ step: STEPS[Math.max(STEPS.indexOf(step) - 1, 0)] }),
    selectHub: (id: string) => update({ step: "see", hub: id, route: undefined }),
    /** Choosing a route is the decision to look closer: it advances to Why. */
    selectRoute: (id: string, hub: string) => update({ step: "why", hub, route: id }),
    /** Change the route without leaving the current step (Act: "Pick another route"). */
    restart: () => update({ step: "see", route: undefined }),
  };
}
