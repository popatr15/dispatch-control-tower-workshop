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
const auditRoute = createRoute({ getParentRoute: () => rootRoute, path: "/audit", component: AuditPage });

export const router = createRouter({
  routeTree: rootRoute.addChildren([indexRoute, auditRoute]),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
