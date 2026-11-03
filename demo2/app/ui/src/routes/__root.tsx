import { Link, Outlet } from "@tanstack/react-router";
import { useCallback } from "react";
import { Toaster } from "sonner";
import { Boundary } from "@/components/boundary";
import { Badge } from "@/components/ui/badge";
import { useGetMeSuspense } from "@/lib/api";
import { useLiveUpdates } from "@/lib/live";
import { cn } from "@/lib/utils";

function Identity() {
  const me = useGetMeSuspense().data.data;
  return (
    <div className="flex items-center gap-2 text-xs">
      {me.mock && <Badge variant="at_risk">offline mock data</Badge>}
      <span className="text-muted-foreground">{me.user}</span>
    </div>
  );
}

// Live updates only refresh the data; there are no pop-up notices.
function LiveIndicator() {
  const mode = useLiveUpdates(useCallback(() => undefined, []));
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground" title="Live updates from other users">
      <span className={cn("h-2 w-2 rounded-full", mode === "live" ? "bg-on-time" : mode === "polling" ? "bg-at-risk" : "bg-delivered")} />
      {mode === "live" ? "Live" : mode === "polling" ? "Polling" : "Connecting"}
    </span>
  );
}

export function RootLayout() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-white px-4">
        <Link to="/" search={{ step: "see" }} className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-6 w-6" />
          <span className="font-semibold">Dispatch Control Tower</span>
        </Link>
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
