import { Link, Outlet } from "@tanstack/react-router";
import { useCallback } from "react";
import { Toaster, toast } from "sonner";
import { Boundary } from "@/components/boundary";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/inputs";
import { useGetMeSuspense } from "@/lib/api";
import { useAppState } from "@/lib/app-context";
import { useLiveUpdates, type LiveEvent } from "@/lib/live";
import { cn } from "@/lib/utils";

function Identity() {
  const { data } = useGetMeSuspense();
  const me = data.data;
  const { roleOverride, setRoleOverride } = useAppState();
  return (
    <div className="flex items-center gap-2 text-xs">
      {me.mock && <Badge variant="at_risk">offline mock data</Badge>}
      <span className="text-muted-foreground">{me.user}</span>
      {me.can_switch_role ? (
        <Select
          aria-label="Role (workshop switch)"
          className="h-7 w-32 py-0 text-xs"
          value={roleOverride ?? me.role}
          onChange={(e) => setRoleOverride(e.target.value)}
        >
          <option value="dispatcher">Dispatcher</option>
          <option value="manager">Manager</option>
        </Select>
      ) : (
        <Badge variant="outline" title={`role from ${me.role_source}`}>{me.role}</Badge>
      )}
    </div>
  );
}

function LiveIndicator() {
  const onEvent = useCallback((e: LiveEvent) => {
    if (e.actor && e.type !== "comment.added") {
      toast.message(`${e.actor}: ${e.type.replace(".", " ")}`, { description: e.entity_id });
    }
  }, []);
  const mode = useLiveUpdates(onEvent);
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground" title="Live route-state updates">
      <span className={cn("h-2 w-2 rounded-full", mode === "live" ? "bg-on-time" : mode === "polling" ? "bg-at-risk" : "bg-delivered")} />
      {mode === "live" ? "Live" : mode === "polling" ? "Polling" : "Connecting"}
    </span>
  );
}

const navLink = "rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground";

export function RootLayout() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-white px-4">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-6 w-6" />
          <span className="font-semibold">Dispatch Control Tower</span>
        </div>
        <nav className="flex gap-1">
          <Link to="/" className={navLink} activeProps={{ className: "bg-muted text-foreground" }}>Operations</Link>
          <Link to="/approvals" className={navLink} activeProps={{ className: "bg-muted text-foreground" }}>Approvals</Link>
          <Link to="/audit" className={navLink} activeProps={{ className: "bg-muted text-foreground" }}>Audit trail</Link>
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <LiveIndicator />
          <Boundary fallback={<span className="text-xs text-muted-foreground">…</span>}>
            <Identity />
          </Boundary>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
      <Toaster position="bottom-right" richColors />
    </div>
  );
}
