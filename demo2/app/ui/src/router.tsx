import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { RootLayout } from "@/routes/__root";
import { ApprovalsPage } from "@/routes/approvals";
import { AuditPage } from "@/routes/audit";
import { ControlTowerPage } from "@/routes/index";

const rootRoute = createRootRoute({ component: RootLayout });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: ControlTowerPage });
const approvalsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/approvals", component: ApprovalsPage });
const auditRoute = createRoute({ getParentRoute: () => rootRoute, path: "/audit", component: AuditPage });

export const router = createRouter({
  routeTree: rootRoute.addChildren([indexRoute, approvalsRoute, auditRoute]),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
