import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { API_BASE } from "@/lib/queryClient";
import type { CaseMetadata, Plane } from "@/types";
import WebGLViewport from "@/components/WebGLViewport";
import Sidebar from "@/components/Sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { useVolume } from "@/hooks/useVolume";

interface ViewerProps {
  caseId: string;
  onBack: () => void;
}

export default function Viewer({ caseId, onBack }: ViewerProps) {
  const { data: metadata, isLoading, isError } = useQuery<CaseMetadata>({
    queryKey: ["/api/cases", caseId, "metadata"],
    queryFn: () => fetch(`${API_BASE}/api/cases/${caseId}/metadata`).then(r => r.json()),
  });

  // Load full volume binary once
  const volume = useVolume(caseId, metadata ?? null);

  // ─── Viewer state ──────────────────────────────────────────────
  const [indices, setIndices] = useState<Record<Plane, number>>({
    axial: 0, sagittal: 0, coronal: 0,
  });
  const [windowCenter, setWindowCenter] = useState<number | null>(null);
  const [windowWidth,  setWindowWidth]  = useState<number | null>(null);
  const [showDose, setShowDose]         = useState(false);
  const [showStructures, setShowStructures] = useState(true);
  const [enabledRois, setEnabledRois]   = useState<Set<string>>(new Set(["1","2","3","4","5","6","7","8","9","10"]));
  const [activePane, setActivePane]     = useState<Plane>("axial");
  const [centeredOnLoad, setCenteredOnLoad] = useState(false);

  const wc = windowCenter ?? (metadata?.window_center ?? 40);
  const ww = windowWidth  ?? (metadata?.window_width  ?? 400);

  // Init indices to center of volume when metadata first loads
  if (metadata && !centeredOnLoad) {
    const [nz, ny, nx] = metadata.shape;
    setIndices({
      axial:    Math.floor(nz / 2),
      sagittal: Math.floor(nx / 2),
      coronal:  Math.floor(ny / 2),
    });
    setCenteredOnLoad(true);
  }

  const handleIndexChange = useCallback((plane: Plane, idx: number) => {
    setIndices(prev => ({ ...prev, [plane]: idx }));
  }, []);

  const handleToggleRoi = useCallback((roiNum: string) => {
    setEnabledRois(prev => {
      const next = new Set(prev);
      if (next.has(roiNum)) next.delete(roiNum); else next.add(roiNum);
      return next;
    });
  }, []);

  if (isLoading) {
    return (
      <div className="h-screen flex">
        <div className="w-[220px] bg-card border-r border-border p-4 space-y-3">
          {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-6 w-full" />)}
        </div>
        <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-px bg-border p-px">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="w-full h-full rounded-none bg-card" />)}
        </div>
      </div>
    );
  }

  if (isError || !metadata) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-center space-y-3">
          <p className="text-destructive text-sm">Failed to load case data</p>
          <button className="text-sm text-primary hover:underline" onClick={onBack}>← Back to cases</button>
        </div>
      </div>
    );
  }

  const viewports: { plane: Plane }[] = [
    { plane: "axial" },
    { plane: "sagittal" },
    { plane: "coronal" },
  ];

  return (
    <div className="h-screen flex overflow-hidden bg-background">
      {/* Sidebar */}
      <div className="w-[220px] flex-shrink-0 border-r border-border">
        <Sidebar
          metadata={metadata}
          windowCenter={wc}
          windowWidth={ww}
          onWCChange={setWindowCenter}
          onWWChange={setWindowWidth}
          showDose={showDose}
          onShowDoseChange={setShowDose}
          showStructures={showStructures}
          onShowStructuresChange={setShowStructures}
          enabledRois={enabledRois}
          onToggleRoi={handleToggleRoi}
          axialIndex={indices.axial}
          sagittalIndex={indices.sagittal}
          coronalIndex={indices.coronal}
          onIndexChange={handleIndexChange}
        />
      </div>

      {/* Viewport area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <div className="h-9 flex items-center px-4 gap-3 border-b border-border bg-card flex-shrink-0">
          <button
            className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            onClick={onBack}
            data-testid="btn-back"
          >
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none">
              <path d="M10.5 3L5.5 8l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            Cases
          </button>
          <span className="text-muted-foreground/30">|</span>
          <span className="text-xs font-mono text-muted-foreground truncate max-w-[200px]">{caseId}</span>
          <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
            {!volume.loaded && volume.progress > 0 && (
              <span className="text-primary animate-pulse mono">
                Loading {Math.round(volume.progress * 100)}%…
              </span>
            )}
            <span className="mono">W:{Math.round(ww)}</span>
            <span className="mono">L:{Math.round(wc)}</span>
          </div>
        </div>

        {/* 2×2 viewport grid */}
        <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-px bg-border overflow-hidden">
          {viewports.map(({ plane }) => (
            <WebGLViewport
              key={plane}
              caseId={caseId}
              metadata={metadata}
              volume={volume}
              plane={plane}
              index={indices[plane]}
              onIndexChange={handleIndexChange}
              showDose={showDose}
              showStructures={showStructures}
              enabledRois={enabledRois}
              windowCenter={wc}
              windowWidth={ww}
              isActive={activePane === plane}
              onActivate={() => setActivePane(plane)}
            />
          ))}

          {/* 4th pane: Plan info */}
          <div className="bg-card flex flex-col p-4 overflow-y-auto gap-3">
            <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground/60">Plan Info</p>

            <div className="space-y-2">
              <InfoRow label="Dimensions" value={`${metadata.shape[2]}×${metadata.shape[1]}×${metadata.shape[0]}`} />
              <InfoRow label="Voxel" value={`${metadata.spacing[0]}×${metadata.spacing[1]}×${metadata.thickness.toFixed(1)} mm`} />
              <InfoRow label="ROIs" value={String(Object.keys(metadata.rois).length)} />
              {metadata.has_dose && (
                <>
                  <InfoRow label="Dose max" value={`${metadata.dose_max.toFixed(2)} Gy`} />
                  <InfoRow label="Dose min" value={`${metadata.dose_min.toFixed(2)} Gy`} />
                </>
              )}
            </div>

            <div className="mt-1">
              <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground/60 mb-2">Structures</p>
              <div className="space-y-1.5">
                {Object.entries(metadata.rois).map(([num, roi]) => {
                  const [r, g, b] = roi.color;
                  return (
                    <div key={num} className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-sm flex-shrink-0" style={{ backgroundColor: `rgb(${r},${g},${b})` }} />
                      <span className="text-xs text-foreground truncate">{roi.name}</span>
                      <span className="text-xs text-muted-foreground ml-auto mono">{roi.slice_count}sl</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {metadata.has_dose && (
              <div className="mt-1">
                <p className="text-xs font-semibold tracking-widest uppercase text-muted-foreground/60 mb-2">Dose Colormap</p>
                <div className="dose-colorbar mb-1" />
                <div className="flex justify-between text-xs text-muted-foreground mono">
                  <span>0 Gy</span>
                  <span>{(metadata.dose_max / 2).toFixed(1)}</span>
                  <span>{metadata.dose_max.toFixed(1)} Gy</span>
                </div>
              </div>
            )}

            <div className="mt-auto pt-3 border-t border-border">
              <p className="text-xs text-muted-foreground leading-relaxed">
                Scroll wheel or drag to browse slices. W/L adjusts in real-time.
              </p>
              <p className="text-xs text-muted-foreground/50 mt-1">
                GPU-rendered · WebGL
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-baseline gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs font-medium mono text-foreground">{value}</span>
    </div>
  );
}
