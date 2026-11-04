import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { RootLayout } from "@/routes/__root";
import { AuditPage } from "@/routes/audit";
import { validateFlowSearch } from "@/lib/flow";
import { ControlTowerPage } from "@/routes/index";

const rootRoute = createRootRoute({ component: RootLayout });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/",
  component: ControlTowerPage,
  validateSearch: validateFlowSearch,
});
const auditRoute = createRoute({ getParentRoute: () => rootRoute, path: "/audit", component: AuditPage,
  // hub and route ride along so "Back to the flow" lands on the same Prove step.
  validateSearch: (raw: Record<string, unknown>) => {
    const { hub, route } = validateFlowSearch(raw);
    return { hub, route };
  },
});

export const router = createRouter({
  routeTree: rootRoute.addChildren([indexRoute, auditRoute]),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
