import { Badge } from "@/components/ui/badge";
import { STATUS_GLYPH, STATUS_LABEL, type StopStatus } from "@/lib/status";

export function StatusBadge({ status }: { status: StopStatus }) {
  return (
    <Badge variant={status}>
      <span aria-hidden>{STATUS_GLYPH[status]}</span>
      {STATUS_LABEL[status]}
    </Badge>
  );
}
