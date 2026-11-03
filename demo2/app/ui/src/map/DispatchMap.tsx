import type { Layer, PickingInfo } from "@deck.gl/core";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import { useListRoutePaths, useListStops, type HubOut, type StopOut } from "@/lib/api";
import { HEALTH_RGB, STATUS_RADIUS, STATUS_RGB, type Health, type StopStatus } from "@/lib/status";
import { MapLegend } from "@/map/MapLegend";

// Open, key-less basemap (CARTO Positron vector style).
const STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

/** Hubs colored by health; once a route is picked, only that route's line and stops. */
export function DispatchMap({ hubs, hubId, routeId, onSelectHub }: {
  hubs: HubOut[];
  hubId?: string;
  routeId?: string;
  onSelectHub: (id: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);

  const pathsQ = useListRoutePaths({ depot_id: hubId }, { query: { enabled: !!routeId && !!hubId } });
  const path = useMemo(() => pathsQ.data?.data.find((p) => p.route_id === routeId), [pathsQ.data, routeId]);
  const stopsQ = useListStops({ route_id: routeId }, { query: { enabled: !!routeId } });
  const stops = useMemo(() => stopsQ.data?.data ?? [], [stopsQ.data]);

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
    mapRef.current = map;
    overlayRef.current = overlay;
    return () => {
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  // Camera: the route when picked, else the chosen hub, else the whole network.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (path && path.path.length > 1) {
      const bounds = new maplibregl.LngLatBounds();
      path.path.forEach(([lon, lat]) => bounds.extend([lon, lat]));
      map.fitBounds(bounds, { padding: 70, maxZoom: 11, duration: 600 });
    } else if (hubId) {
      const hub = hubs.find((h) => h.depot_id === hubId);
      if (hub) map.flyTo({ center: [hub.lon, hub.lat], zoom: 8.5, duration: 600 });
    }
  }, [path, hubId, hubs]);

  const layers = useMemo(() => {
    const out: Layer[] = [];
    if (path) {
      out.push(new PathLayer({
        id: "route",
        data: [path],
        getPath: (d) => d.path,
        getColor: [15, 23, 42, 200],
        getWidth: 3,
        widthUnits: "pixels",
      }));
      out.push(new ScatterplotLayer<StopOut>({
        id: "stops",
        data: stops,
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => STATUS_RADIUS[d.status as StopStatus],
        radiusUnits: "pixels",
        getFillColor: (d) => [...STATUS_RGB[d.status as StopStatus], d.status === "delivered" ? 150 : 235],
        stroked: true,
        // A dark ring on late and at-risk stops, so status does not rely on color alone.
        getLineColor: (d) => (d.status === "late" || d.status === "at_risk" ? [15, 23, 42] : [255, 255, 255]),
        getLineWidth: (d) => (d.status === "late" ? 2 : 1),
        lineWidthUnits: "pixels",
        pickable: true,
      }));
    }
    out.push(new ScatterplotLayer<HubOut>({
      id: "hubs",
      data: hubs,
      getPosition: (d) => [d.lon, d.lat],
      getRadius: (d) => (d.depot_id === hubId ? 13 : (d.health ?? "green") === "green" ? 8 : 11),
      radiusUnits: "pixels",
      getFillColor: (d) => HEALTH_RGB[(d.health ?? "green") as Health],
      stroked: true,
      getLineColor: (d) => (d.depot_id === hubId ? [15, 23, 42] : [255, 255, 255]),
      getLineWidth: 3,
      lineWidthUnits: "pixels",
      pickable: true,
      updateTriggers: { getRadius: hubId, getLineColor: hubId },
    }));
    out.push(new TextLayer<HubOut>({
      id: "hub-labels",
      data: hubs,
      getPosition: (d) => [d.lon, d.lat],
      getText: (d) => d.city,
      getSize: 12,
      getPixelOffset: [0, -20],
      getColor: [15, 23, 42],
      background: true,
      getBackgroundColor: [255, 255, 255, 220],
      backgroundPadding: [3, 1],
    }));
    return out;
  }, [path, stops, hubs, hubId]);

  useEffect(() => {
    overlayRef.current?.setProps({
      layers,
      getTooltip: (info: PickingInfo) => tooltip(info),
      onClick: (info: PickingInfo) => {
        if (info.object && info.layer?.id === "hubs") onSelectHub((info.object as HubOut).depot_id);
      },
    });
  }, [layers, onSelectHub]);

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" aria-label="Delivery map" />
      <MapLegend showStops={!!routeId} />
    </div>
  );
}

function tooltip(info: PickingInfo) {
  const o = info.object;
  if (!o || !info.layer) return null;
  if (info.layer.id === "stops") {
    const s = o as StopOut;
    return { text: `${s.customer_name}\n${s.status.replace("_", " ")}${s.late_minutes ? ` · ${s.late_minutes} min late` : ""}` };
  }
  if (info.layer.id === "hubs") {
    const h = o as HubOut;
    return { text: `${h.name}\n${h.late_stops} late · ${h.at_risk_routes} at-risk route${h.at_risk_routes === 1 ? "" : "s"}` };
  }
  return null;
}
