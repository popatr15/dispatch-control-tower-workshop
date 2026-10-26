import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import * as maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  useGetHistoryHeat,
  useGetStopClusters,
  useListDepots,
  useListRoutePaths,
  useListStops,
  type DepotOut,
  type HeatCellOut,
  type RoutePathOut,
  type StopClusterOut,
  type StopOut,
} from "@/lib/api";
import { cleanParams, useAppState } from "@/lib/app-context";
import { STATUS_RADIUS, STATUS_RGB, type StopStatus } from "@/lib/status";
import { MapLegend } from "@/map/MapLegend";

// Open, key-less basemap (CARTO Positron vector style).
const STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const STOP_ZOOM = 9; // below this, stops are server-side clustered

function cellForZoom(zoom: number): number {
  // ~40px cells at the current zoom, bounded to sensible degrees
  const deg = 360 / Math.pow(2, zoom) / 6;
  return Math.min(2, Math.max(0.01, Number(deg.toFixed(3))));
}

export function DispatchMap() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const [zoom, setZoom] = useState(3.6);
  const { filters, layers, routeId, stopId, selectRoute, selectStop } = useAppState();
  const params = cleanParams(filters);

  const depotsQ = useListDepots();
  const depots = useMemo(() => depotsQ.data?.data ?? [], [depotsQ.data]);
  const showStops = zoom >= STOP_ZOOM || !!routeId;
  const stopsQ = useListStops(cleanParams({ ...params, route_id: zoom >= STOP_ZOOM ? undefined : routeId }), {
    query: { enabled: showStops },
  });
  const stops = useMemo(() => stopsQ.data?.data ?? [], [stopsQ.data]);
  const cellDeg = cellForZoom(Math.round(zoom));
  const clustersQ = useGetStopClusters(cleanParams({ ...params, cell_deg: cellDeg }), {
    query: { enabled: layers.clusters && zoom < STOP_ZOOM, placeholderData: (prev) => prev },
  });
  const clusters = useMemo(() => clustersQ.data?.data ?? [], [clustersQ.data]);
  const pathsQ = useListRoutePaths(cleanParams({ day: params.day, depot_id: params.depot_id, carrier_id: params.carrier_id }), {
    query: { enabled: layers.routes },
  });
  const paths = useMemo(() => pathsQ.data?.data ?? [], [pathsQ.data]);
  const heatQ = useGetHistoryHeat(cleanParams({ ...params, days: 30 }), {
    query: { enabled: layers.heat },
  });
  const heat = useMemo(() => heatQ.data?.data ?? [], [heatQ.data]);

  // Map + overlay are created once.
  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      center: [-96, 38.5],
      zoom: 3.6,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(overlay);
    map.on("zoomend", () => setZoom(map.getZoom()));
    mapRef.current = map;
    overlayRef.current = overlay;
    return () => {
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  // Fit to the selected route when it changes.
  useEffect(() => {
    const map = mapRef.current;
    const path = paths.find((p) => p.route_id === routeId);
    if (!map || !path || path.path.length < 2) return;
    const bounds = new maplibregl.LngLatBounds();
    path.path.forEach(([lon, lat]) => bounds.extend([lon, lat]));
    map.fitBounds(bounds, { padding: 60, maxZoom: 11, duration: 600 });
  }, [routeId, paths]);

  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (layers.heat && heat.length) {
      out.push(new HeatmapLayer<HeatCellOut>({
        id: "history-heat",
        data: heat,
        getPosition: (d) => [d.lon, d.lat],
        getWeight: (d) => d.deliveries * (1 - d.on_time_pct), // late deliveries
        radiusPixels: 45,
        colorRange: [[255, 237, 160], [254, 217, 118], [254, 178, 76], [253, 141, 60], [240, 59, 32], [189, 0, 38]],
      }));
    }
    if (layers.catchments) {
      out.push(new ScatterplotLayer<DepotOut>({
        id: "catchments",
        data: depots,
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => d.catchment_radius_km * 1000,
        radiusUnits: "meters",
        stroked: true,
        filled: true,
        getFillColor: [34, 114, 180, 18],
        getLineColor: [34, 114, 180, 140],
        lineWidthMinPixels: 1,
      }));
    }
    if (layers.routes) {
      out.push(new PathLayer<RoutePathOut>({
        id: "routes",
        data: paths,
        getPath: (d) => d.path,
        getColor: (d) => d.route_id === routeId ? [15, 23, 42, 230] : d.risk_score >= 0.6 ? [213, 94, 0, 150] : [90, 100, 120, 90],
        getWidth: (d) => (d.route_id === routeId ? 4 : 1.5 + d.risk_score * 2),
        widthUnits: "pixels",
        pickable: true,
        updateTriggers: { getColor: routeId, getWidth: routeId },
      }));
    }
    if (layers.clusters && !showStops) {
      out.push(new ScatterplotLayer<StopClusterOut>({
        id: "clusters",
        data: clusters,
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => 5 + Math.sqrt(d.count) * 1.6,
        radiusUnits: "pixels",
        getFillColor: (d) => [...STATUS_RGB[d.worst_status as StopStatus], 190],
        stroked: true,
        getLineColor: [255, 255, 255],
        lineWidthMinPixels: 1,
        pickable: true,
      }));
    }
    if (showStops) {
      const visible = stops.filter((s) => zoom >= STOP_ZOOM || s.route_id === routeId);
      out.push(new ScatterplotLayer<StopOut>({
        id: "stops",
        data: visible,
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => STATUS_RADIUS[d.status as StopStatus] + (d.stop_id === stopId ? 4 : 0),
        radiusUnits: "pixels",
        getFillColor: (d) => [...STATUS_RGB[d.status as StopStatus], d.status === "delivered" ? 150 : 235],
        stroked: true,
        // Shape cue in addition to color: dark ring on late/at-risk and on reassigned stops.
        getLineColor: (d) => d.stop_id === stopId ? [34, 114, 180] : d.reassigned ? [91, 33, 182] : d.status === "late" || d.status === "at_risk" ? [15, 23, 42] : [255, 255, 255],
        getLineWidth: (d) => (d.stop_id === stopId ? 3 : d.status === "late" ? 2 : 1),
        lineWidthUnits: "pixels",
        pickable: true,
        updateTriggers: { getRadius: stopId, getLineColor: stopId, getLineWidth: stopId },
      }));
    }
    out.push(new ScatterplotLayer<DepotOut>({
      id: "depots",
      data: depots,
      getPosition: (d) => [d.lon, d.lat],
      getRadius: 7,
      radiusUnits: "pixels",
      getFillColor: [15, 23, 42],
      stroked: true,
      getLineColor: [255, 255, 255],
      lineWidthMinPixels: 2,
      pickable: true,
    }));
    out.push(new TextLayer<DepotOut>({
      id: "depot-labels",
      data: depots,
      getPosition: (d) => [d.lon, d.lat],
      getText: (d) => d.name,
      getSize: 12,
      getPixelOffset: [0, -16],
      getColor: [15, 23, 42],
      background: true,
      getBackgroundColor: [255, 255, 255, 210],
      backgroundPadding: [3, 1],
    }));
    return out;
  }, [layers, heat, depots, paths, clusters, stops, showStops, zoom, routeId, stopId]);

  useEffect(() => {
    overlayRef.current?.setProps({
      layers: deckLayers,
      getTooltip: (info: PickingInfo) => tooltip(info),
      onClick: (info: PickingInfo) => {
        if (!info.object || !info.layer) return;
        if (info.layer.id === "stops") {
          const s = info.object as StopOut;
          selectStop(s.stop_id, s.route_id);
        } else if (info.layer.id === "routes") {
          selectRoute((info.object as RoutePathOut).route_id);
        } else if (info.layer.id === "clusters") {
          const c = info.object as StopClusterOut;
          mapRef.current?.flyTo({ center: [c.lon, c.lat], zoom: Math.max(zoom + 2, STOP_ZOOM) });
        }
      },
    });
  }, [deckLayers, selectRoute, selectStop, zoom]);

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="absolute inset-0" aria-label="Delivery map" />
      <MapLegend zoomedIn={showStops} />
    </div>
  );
}

function tooltip(info: PickingInfo) {
  const o = info.object;
  if (!o || !info.layer) return null;
  switch (info.layer.id) {
    case "stops": {
      const s = o as StopOut;
      return { text: `${s.customer_name}\n${s.status.replace("_", " ")}${s.late_minutes ? ` · ${s.late_minutes} min late` : ""}\nRoute ${s.route_id}${s.reassigned ? ` (from ${s.original_route_id})` : ""}` };
    }
    case "clusters": {
      const c = o as StopClusterOut;
      return { text: `${c.count} stops\n${c.late} late · ${c.at_risk} at risk · ${c.on_time} on time\nClick to zoom in` };
    }
    case "routes": {
      const r = o as RoutePathOut;
      return { text: `${r.route_id}\nrisk ${Math.round(r.risk_score * 100)}%` };
    }
    case "depots": {
      const d = o as DepotOut;
      return { text: `${d.name} (${d.region})\nSLA target ${Math.round(d.sla_target_pct * 100)}%` };
    }
    default:
      return null;
  }
}
