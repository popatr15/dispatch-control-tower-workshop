import { createContext, useContext } from "react";

export interface MapFilters {
  day?: string;
  depot_id?: string;
  carrier_id?: string;
  region?: string;
}

export interface LayerToggles {
  clusters: boolean;
  routes: boolean;
  catchments: boolean;
  heat: boolean;
}

export interface AppState {
  filters: MapFilters;
  setFilters: (f: MapFilters) => void;
  layers: LayerToggles;
  toggleLayer: (k: keyof LayerToggles) => void;
  routeId?: string;
  stopId?: string;
  selectRoute: (id?: string) => void;
  selectStop: (stopId?: string, routeId?: string) => void;
  panel: string;
  setPanel: (p: string) => void;
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
