import { useQuery } from "@tanstack/react-query";
import { API_BASE } from "@/lib/queryClient";
import type { CaseSummary } from "@/types";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

interface CaseListProps {
  onSelectCase: (id: string) => void;
}

export default function CaseList({ onSelectCase }: CaseListProps) {
  const { data: cases, isLoading, isError } = useQuery<CaseSummary[]>({
    queryKey: ["/api/cases"],
    queryFn: () => fetch(`${API_BASE}/api/cases`).then(r => r.json()),
  });

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center gap-3">
        <svg viewBox="0 0 32 32" width="28" height="28" fill="none" aria-label="RT Viewer logo">
          <circle cx="16" cy="16" r="12" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
          <circle cx="16" cy="16" r="4.5" fill="hsl(188 35% 47%)"/>
          <line x1="16" y1="4" x2="16" y2="10" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="16" y1="22" x2="16" y2="28" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="4" y1="16" x2="10" y2="16" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
          <line x1="22" y1="16" x2="28" y2="16" stroke="hsl(188 35% 47%)" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        <div>
          <h1 className="text-base font-semibold text-foreground tracking-tight">RT Viewer</h1>
          <p className="text-xs text-muted-foreground">Radiation Therapy DICOM Viewer</p>
        </div>
      </header>

      <main className="flex-1 max-w-3xl mx-auto w-full px-6 py-8">
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-foreground mb-1">Patient Cases</h2>
          <p className="text-xs text-muted-foreground">
            Select a case to open the MPR viewer with CT, structures, and dose overlay.
          </p>
        </div>

        {isLoading && (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-24 w-full rounded-lg" />
            ))}
          </div>
        )}

        {isError && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            Failed to connect to API server. Make sure the backend is running on port 8000.
          </div>
        )}

        {cases && cases.length === 0 && (
          <div className="rounded-lg border border-border bg-card p-8 text-center">
            <p className="text-sm text-muted-foreground">No DICOM cases found.</p>
            <p className="text-xs text-muted-foreground mt-1">Place case folders in the <code className="mono text-xs">dicom_data/</code> directory.</p>
          </div>
        )}

        {cases && cases.length > 0 && (
          <div className="space-y-2">
            {cases.map(c => (
              <button
                key={c.id}
                className="w-full text-left rounded-lg border border-border bg-card hover:border-primary/40 hover:bg-secondary/60 transition-colors p-4 group"
                onClick={() => onSelectCase(c.id)}
                data-testid={`case-card-${c.id}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors mono">
                      {c.id}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5 mono">
                      {c.shape[2]}×{c.shape[1]}×{c.shape[0]} · {c.spacing[0]}×{c.thickness.toFixed(1)} mm
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5 justify-end">
                    <Badge variant="secondary" className="text-xs mono">CT</Badge>
                    {c.roi_count > 0 && (
                      <Badge variant="outline" className="text-xs border-primary/30 text-primary">
                        {c.roi_count} ROI{c.roi_count !== 1 ? "s" : ""}
                      </Badge>
                    )}
                    {c.has_dose && (
                      <Badge variant="outline" className="text-xs border-orange-400/30 text-orange-400">
                        DOSE
                      </Badge>
                    )}
                  </div>
                </div>

                {/* Mini spec bar */}
                <div className="mt-3 flex gap-4">
                  <SpecItem label="Slices"  value={String(c.shape[0])} />
                  <SpecItem label="Rows"    value={String(c.shape[1])} />
                  <SpecItem label="Cols"    value={String(c.shape[2])} />
                  <SpecItem label="Spacing" value={`${c.spacing[0]}mm`} />
                </div>
              </button>
            ))}
          </div>
        )}
      </main>

      <footer className="px-6 py-4 border-t border-border text-xs text-muted-foreground text-center">
        RT Viewer · DICOM CT / RTStruct / RTDose · Research use only
      </footer>
    </div>
  );
}

function SpecItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground/60">{label}</p>
      <p className="text-xs font-medium mono text-muted-foreground">{value}</p>
    </div>
  );
}
