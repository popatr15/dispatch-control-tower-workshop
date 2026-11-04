import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Gold and Lakebase timestamps are UTC (docs/DATA_CONTRACT.md); show them as UTC.
export function fmtTime(value?: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", timeZone: "UTC", hour12: false,
  });
}

export function fmtDateTime(value?: string | null): string {
  if (!value) return "—";
  return `${new Date(value).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
    hour12: false,
  })} UTC`;
}

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function errorMessage(err: unknown): string {
  const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = anyErr?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join("; ");
  return anyErr?.message ?? "Request failed";
}
