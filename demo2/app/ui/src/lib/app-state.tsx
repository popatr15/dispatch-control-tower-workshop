import axios from "axios";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { AppStateContext, type LayerToggles, type MapFilters } from "@/lib/app-context";

const ROLE_KEY = "dispatch-tower-role";

// Workshop role switch: only honored by the backend when DISPATCH_ALLOW_ROLE_SWITCH=true.
function applyRoleHeader(role?: string) {
  if (role) axios.defaults.headers.common["X-Dispatch-Role"] = role;
  else delete axios.defaults.headers.common["X-Dispatch-Role"];
}
applyRoleHeader(localStorage.getItem(ROLE_KEY) ?? undefined);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<MapFilters>({});
  const [layers, setLayers] = useState<LayerToggles>({
    allRoutes: false, clusters: false, catchments: false, heat: false,
  });
  const [routeId, setRouteId] = useState<string>();
  const [stopId, setStopId] = useState<string>();
  const [roleOverride, setRoleState] = useState<string | undefined>(
    localStorage.getItem(ROLE_KEY) ?? undefined,
  );

  const selectHub = useCallback((id?: string) => {
    setFilters((f) => ({ ...f, depot_id: id }));
    setRouteId(undefined);
    setStopId(undefined);
  }, []);
  const selectRoute = useCallback((id?: string) => {
    setRouteId(id);
    setStopId(undefined);
  }, []);
  const selectStop = useCallback((id?: string, route?: string, hub?: string) => {
    setStopId(id);
    if (route) setRouteId(route);
    if (hub) setFilters((f) => ({ ...f, depot_id: hub }));
  }, []);
  const toggleLayer = useCallback(
    (k: keyof LayerToggles) => setLayers((l) => ({ ...l, [k]: !l[k] })),
    [],
  );
  const setRoleOverride = useCallback((role?: string) => {
    if (role) localStorage.setItem(ROLE_KEY, role);
    else localStorage.removeItem(ROLE_KEY);
    applyRoleHeader(role);
    setRoleState(role);
  }, []);

  const value = useMemo(
    () => ({
      filters, setFilters, layers, toggleLayer, hubId: filters.depot_id, routeId, stopId,
      selectHub, selectRoute, selectStop, roleOverride, setRoleOverride,
    }),
    [filters, layers, toggleLayer, routeId, stopId, selectHub, selectRoute, selectStop,
      roleOverride, setRoleOverride],
  );
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}
