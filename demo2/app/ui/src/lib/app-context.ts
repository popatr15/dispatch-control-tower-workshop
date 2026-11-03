import { createContext, useContext } from "react";

export interface MapFilters {
  day?: string;
  depot_id?: string; // the selected hub
  carrier_id?: string;
  region?: string;
}

/** Advanced map layers, all off by default (the "Layers" control). */
export interface LayerToggles {
  allRoutes: boolean;
  clusters: boolean;
  catchments: boolean;
  heat: boolean;
}

export interface AppState {
  filters: MapFilters;
  setFilters: (f: MapFilters) => void;
  layers: LayerToggles;
  toggleLayer: (k: keyof LayerToggles) => void;
  hubId?: string;
  routeId?: string;
  stopId?: string;
  /** Open a hub (or the hub picker when undefined); clears route and stop. */
  selectHub: (id?: string) => void;
  selectRoute: (id?: string) => void;
  selectStop: (stopId?: string, routeId?: string, hubId?: string) => void;
  roleOverride?: string;
  setRoleOverride: (role?: string) => void;
}

export const AppStateContext = createContext<AppState | null>(null);

export function useAppState(): AppState {
  const v = useContext(AppStateContext);
  if (!v) throw new Error("useAppState outside provider");
  return v;
}

/** Query params shared by the map/route endpoints, without empty values. */
export function cleanParams<T extends object>(p: T): T {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== "")) as T;
}
