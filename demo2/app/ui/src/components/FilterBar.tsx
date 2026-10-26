import { useGetFiltersSuspense } from "@/lib/api";
import { useAppState, type LayerToggles } from "@/lib/app-context";
import { Select } from "@/components/ui/inputs";

const LAYERS: { key: keyof LayerToggles; label: string }[] = [
  { key: "clusters", label: "Stops / clusters" },
  { key: "routes", label: "Route lines" },
  { key: "catchments", label: "Depot catchments" },
  { key: "heat", label: "30-day late heat" },
];

export function FilterBar() {
  const { data } = useGetFiltersSuspense();
  const f = data.data;
  const { filters, setFilters, layers, toggleLayer, selectRoute } = useAppState();
  const set = (patch: Partial<typeof filters>) => {
    setFilters({ ...filters, ...patch });
    selectRoute(undefined);
  };
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-white px-3 py-2">
      <Select aria-label="Date" className="w-36" value={filters.day ?? f.today} onChange={(e) => set({ day: e.target.value === f.today ? undefined : e.target.value })}>
        {f.dates.map((d) => <option key={d} value={d}>{d === f.today ? `${d} (today)` : d}</option>)}
      </Select>
      <Select aria-label="Region" className="w-36" value={filters.region ?? ""} onChange={(e) => set({ region: e.target.value || undefined })}>
        <option value="">All regions</option>
        {f.regions.map((r) => <option key={r} value={r}>{r}</option>)}
      </Select>
      <Select aria-label="Depot" className="w-44" value={filters.depot_id ?? ""} onChange={(e) => set({ depot_id: e.target.value || undefined })}>
        <option value="">All depots</option>
        {f.depots.filter((d) => !filters.region || d.region === filters.region).map((d) => <option key={d.depot_id} value={d.depot_id}>{d.name}</option>)}
      </Select>
      <Select aria-label="Carrier" className="w-44" value={filters.carrier_id ?? ""} onChange={(e) => set({ carrier_id: e.target.value || undefined })}>
        <option value="">All carriers</option>
        {f.carriers.map((c) => <option key={c.carrier_id} value={c.carrier_id}>{c.name}</option>)}
      </Select>
      <div className="ml-auto flex flex-wrap items-center gap-3 text-xs">
        {LAYERS.map((l) => (
          <label key={l.key} className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={layers[l.key]} onChange={() => toggleLayer(l.key)} />
            {l.label}
          </label>
        ))}
      </div>
    </div>
  );
}
