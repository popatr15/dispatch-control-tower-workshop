import { Boundary } from "@/components/boundary";
import { ExceptionsPanel } from "@/components/ExceptionsPanel";
import { FilterBar } from "@/components/FilterBar";
import { GeniePanel } from "@/components/GeniePanel";
import { RouteList } from "@/components/RouteList";
import { RoutePanel } from "@/components/RoutePanel";
import { StopPanel } from "@/components/StopPanel";
import { Skeleton } from "@/components/ui/inputs";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAppState } from "@/lib/app-context";
import { DispatchMap } from "@/map/DispatchMap";

export function ControlTowerPage() {
  const { panel, setPanel } = useAppState();
  return (
    <div className="flex h-full flex-col">
      <Boundary fallback={<Skeleton className="m-2 h-9" />}>
        <FilterBar />
      </Boundary>
      <div className="grid min-h-0 flex-1 grid-cols-[300px_1fr_380px]">
        <aside className="min-h-0 border-r border-border bg-white">
          <Boundary fallback={<div className="space-y-2 p-3">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-14" />)}</div>}>
            <RouteList />
          </Boundary>
        </aside>
        <section className="min-h-0">
          <DispatchMap />
        </section>
        <aside className="flex min-h-0 flex-col border-l border-border bg-white">
          <Tabs value={panel} onValueChange={setPanel} className="flex min-h-0 flex-1 flex-col">
            <TabsList>
              <TabsTrigger value="route">Route</TabsTrigger>
              <TabsTrigger value="stop">Stop</TabsTrigger>
              <TabsTrigger value="exceptions">Exceptions</TabsTrigger>
              <TabsTrigger value="genie">Ask Genie</TabsTrigger>
            </TabsList>
            <TabsContent value="route"><Boundary><RoutePanel /></Boundary></TabsContent>
            <TabsContent value="stop"><Boundary><StopPanel /></Boundary></TabsContent>
            <TabsContent value="exceptions"><Boundary><ExceptionsPanel /></Boundary></TabsContent>
            <TabsContent value="genie"><Boundary><GeniePanel /></Boundary></TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}
