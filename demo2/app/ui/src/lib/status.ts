// Colorblind-safe status palette (Okabe-Ito) plus a size/outline cue per status.
export type StopStatus = "on_time" | "at_risk" | "late" | "delivered";

export const STATUS_HEX: Record<StopStatus, string> = {
  on_time: "#009e73",
  at_risk: "#e69f00",
  late: "#d55e00",
  delivered: "#8a8f98",
};

export const STATUS_RGB: Record<StopStatus, [number, number, number]> = {
  on_time: [0, 158, 115],
  at_risk: [230, 159, 0],
  late: [213, 94, 0],
  delivered: [138, 143, 152],
};

// Larger, outlined markers for the statuses that need attention.
export const STATUS_RADIUS: Record<StopStatus, number> = {
  delivered: 3, on_time: 4, at_risk: 6, late: 7,
};

export const STATUS_LABEL: Record<StopStatus, string> = {
  on_time: "On time", at_risk: "At risk", late: "Late", delivered: "Delivered",
};

export const STATUS_GLYPH: Record<StopStatus, string> = {
  on_time: "●", at_risk: "▲", late: "■", delivered: "○",
};

export function riskLabel(score: number): "high" | "medium" | "low" {
  if (score >= 0.6) return "high";
  if (score >= 0.3) return "medium";
  return "low";
}
