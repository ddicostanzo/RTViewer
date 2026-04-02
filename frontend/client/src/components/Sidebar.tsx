import { useState } from "react";
import type { CaseMetadata } from "@/types";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

interface SidebarProps {
  metadata: CaseMetadata;
  windowCenter: number;
  windowWidth: number;
  onWCChange: (wc: number) => void;
  onWWChange: (ww: number) => void;
  showDose: boolean;
  onShowDoseChange: (v: boolean) => void;
  showStructures: boolean;
  onShowStructuresChange: (v: boolean) => void;
  enabledRois: Set<string>;
  onToggleRoi: (roiNum: string) => void;
  axialIndex: number;
  sagittalIndex: number;
  coronalIndex: number;
  onIndexChange: (plane: "axial" | "sagittal" | "coronal", val: number) => void;
}

function RoiRow({ roiNum, roi, enabled, onToggle }: {
  roiNum: string;
  roi: { name: string; color: [number, number, number]; slice_count: number };
  enabled: boolean;
  onToggle: () => void;
}) {
  const [r, g, b] = roi.color;
  return (
    <div
      className={`flex items-center gap-2.5 px-2 py-1.5 rounded cursor-pointer transition-colors ${enabled ? "bg-secondary/60" : "opacity-40"}`}
      onClick={onToggle}
      data-testid={`roi-row-${roiNum}`}
    >
      <div
        className="roi-dot"
        style={{
          backgroundColor: enabled ? `rgb(${r},${g},${b})` : "transparent",
          border: `2px solid rgb(${r},${g},${b})`,
        }}
      />
      <span className="text-sm flex-1 truncate" style={{ color: enabled ? `rgb(${r},${g},${b})` : undefined }}>
        {roi.name}
      </span>
      <span className="text-xs text-muted-foreground mono">{roi.slice_count}s</span>
    </div>
  );
}

export default function Sidebar({
  metadata,
  windowCenter, windowWidth, onWCChange, onWWChange,
  showDose, onShowDoseChange,
  showStructures, onShowStructuresChange,
  enabledRois, onToggleRoi,
  axialIndex, sagittalIndex, coronalIndex, onIndexChange,
}: SidebarProps) {
  const [nz, ny, nx] = metadata.shape;

  return (
    <div className="h-full flex flex-col overflow-y-auto bg-card text-card-foreground">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          {/* Logo mark */}
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-label="RT Viewer">
            <circle cx="12" cy="12" r="9" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
            <circle cx="12" cy="12" r="3.5" fill="hsl(188 35% 47%)"/>
            <line x1="12" y1="3" x2="12" y2="7" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
            <line x1="12" y1="17" x2="12" y2="21" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
            <line x1="3" y1="12" x2="7" y2="12" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
            <line x1="17" y1="12" x2="21" y2="12" stroke="hsl(188 35% 47%)" strokeWidth="1.5"/>
          </svg>
          <span className="text-sm font-semibold tracking-tight text-foreground">RT Viewer</span>
        </div>
        <div className="mt-1">
          <p className="text-xs text-muted-foreground mono truncate">{metadata.id}</p>
          <p className="text-xs text-muted-foreground mono">
            {nx}×{ny}×{nz} · {metadata.spacing[0]}mm
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* Slice Navigation */}
        <div className="sidebar-section border-b border-border">
          <p className="sidebar-section-title">Navigation</p>

          <div className="space-y-3">
            {/* Axial */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-medium" style={{ color: "hsl(188 60% 55%)" }}>Axial</span>
                <span className="mono text-xs text-muted-foreground">{axialIndex + 1}/{nz}</span>
              </div>
              <Slider
                min={0} max={nz - 1} step={1}
                value={[axialIndex]}
                onValueChange={([v]) => onIndexChange("axial", v)}
                className="h-1.5"
                data-testid="slider-axial"
              />
            </div>

            {/* Sagittal */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-medium" style={{ color: "hsl(142 50% 50%)" }}>Sagittal</span>
                <span className="mono text-xs text-muted-foreground">{sagittalIndex + 1}/{nx}</span>
              </div>
              <Slider
                min={0} max={nx - 1} step={1}
                value={[sagittalIndex]}
                onValueChange={([v]) => onIndexChange("sagittal", v)}
                className="h-1.5"
                data-testid="slider-sagittal"
              />
            </div>

            {/* Coronal */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-medium" style={{ color: "hsl(38 90% 60%)" }}>Coronal</span>
                <span className="mono text-xs text-muted-foreground">{coronalIndex + 1}/{ny}</span>
              </div>
              <Slider
                min={0} max={ny - 1} step={1}
                value={[coronalIndex]}
                onValueChange={([v]) => onIndexChange("coronal", v)}
                className="h-1.5"
                data-testid="slider-coronal"
              />
            </div>
          </div>
        </div>

        {/* Window / Level */}
        <div className="sidebar-section border-b border-border">
          <p className="sidebar-section-title">Window / Level</p>

          <div className="space-y-3">
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-muted-foreground">Center (WL)</span>
                <span className="mono text-xs text-foreground">{Math.round(windowCenter)} HU</span>
              </div>
              <Slider
                min={-1000} max={3000} step={5}
                value={[windowCenter]}
                onValueChange={([v]) => onWCChange(v)}
                data-testid="slider-window-center"
              />
            </div>
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs text-muted-foreground">Width (WW)</span>
                <span className="mono text-xs text-foreground">{Math.round(windowWidth)} HU</span>
              </div>
              <Slider
                min={1} max={4000} step={10}
                value={[windowWidth]}
                onValueChange={([v]) => onWWChange(v)}
                data-testid="slider-window-width"
              />
            </div>

            {/* WL presets */}
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {[
                { label: "Brain",    wc: 40,   ww: 80 },
                { label: "Bone",     wc: 400,  ww: 1800 },
                { label: "Lung",     wc: -600, ww: 1500 },
                { label: "Soft Tis", wc: 40,   ww: 400 },
              ].map(p => (
                <button
                  key={p.label}
                  className="text-xs px-2 py-0.5 rounded bg-secondary text-secondary-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
                  onClick={() => { onWCChange(p.wc); onWWChange(p.ww); }}
                  data-testid={`preset-${p.label.toLowerCase().replace(/\s/g, "-")}`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Structures */}
        <div className="sidebar-section border-b border-border">
          <div className="flex items-center justify-between mb-2">
            <p className="sidebar-section-title mb-0">Structures</p>
            <Switch
              checked={showStructures}
              onCheckedChange={onShowStructuresChange}
              data-testid="toggle-structures"
            />
          </div>

          {showStructures && (
            <div className="space-y-0.5 mt-1">
              {Object.entries(metadata.rois).map(([num, roi]) => (
                <RoiRow
                  key={num}
                  roiNum={num}
                  roi={roi}
                  enabled={enabledRois.has(num)}
                  onToggle={() => onToggleRoi(num)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Dose */}
        {metadata.has_dose && (
          <div className="sidebar-section">
            <div className="flex items-center justify-between mb-2">
              <p className="sidebar-section-title mb-0">Dose Wash</p>
              <Switch
                checked={showDose}
                onCheckedChange={onShowDoseChange}
                data-testid="toggle-dose"
              />
            </div>

            {showDose && (
              <div>
                <div className="dose-colorbar mb-1" />
                <div className="flex justify-between text-xs text-muted-foreground mono">
                  <span>0</span>
                  <span>{metadata.dose_max.toFixed(1)} Gy</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border">
        <p className="text-xs text-muted-foreground">
          Scroll or drag to browse slices
        </p>
      </div>
    </div>
  );
}
