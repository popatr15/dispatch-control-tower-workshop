import { QueryErrorResetBoundary } from "@tanstack/react-query";
import { Suspense, type ReactNode } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/inputs";
import { errorMessage } from "@/lib/utils";

/** Suspense + error boundary with retry, used around every data-backed panel. */
export function Boundary({ children, fallback }: { children: ReactNode; fallback?: ReactNode }) {
  return (
    <QueryErrorResetBoundary>
      {({ reset }) => (
        <ErrorBoundary
          onReset={reset}
          fallbackRender={({ error, resetErrorBoundary }) => (
            <div className="space-y-2 p-3 text-sm">
              <p className="text-destructive">Could not load: {errorMessage(error)}</p>
              <Button size="sm" variant="outline" onClick={resetErrorBoundary}>Try again</Button>
            </div>
          )}
        >
          <Suspense fallback={fallback ?? <Skeleton className="m-3 h-32" />}>{children}</Suspense>
        </ErrorBoundary>
      )}
    </QueryErrorResetBoundary>
  );
}
