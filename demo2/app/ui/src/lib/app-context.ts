/** Query params for the map/route endpoints, without empty values. */
export function cleanParams<T extends object>(p: T): T {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== "")) as T;
}
