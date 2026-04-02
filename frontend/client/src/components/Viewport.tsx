import { useEffect, useRef, useCallback, useState } from "react";
import { API_BASE } from "@/lib/queryClient";
import type { CaseMetadata, StructureSliceResponse, Plane } from "@/types";

interface ViewportProps {
  caseId: string;
  metadata: CaseMetadata;
  plane: Plane;
  index: number;
  onIndexChange: (plane: Plane, index: number) => void;
  showDose: boolean;
  showStructures: boolean;
  enabledRois: Set<string>;
  windowCenter: number;
  windowWidth: number;
  isActive: boolean;
  onActivate: () => void;
}

const PLANE_COLORS: Record<Plane, string> = {
  axial:    "#4cc9d6",
  sagittal: "#5cb87a",
  coronal:  "#f0a040",
};

const PLANE_LABELS: Record<Plane, string> = {
  axial:    "AX",
  sagittal: "SAG",
  coronal:  "COR",
};

function getMaxIndex(meta: CaseMetadata, plane: Plane): number {
  const [nz, ny, nx] = meta.shape;
  if (plane === "axial")    return nz - 1;
  if (plane === "sagittal") return nx - 1;
  if (plane === "coronal")  return ny - 1;
  return nz - 1;
}

export default function Viewport({
  caseId, metadata, plane, index, onIndexChange,
  showDose, showStructures, enabledRois,
  windowCenter, windowWidth,
  isActive, onActivate,
}: ViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const isDragging = useRef(false);
  const lastY = useRef(0);
  const [loading, setLoading] = useState(false);
  const [structData, setStructData] = useState<StructureSliceResponse>({});
  const maxIndex = getMaxIndex(metadata, plane);

  // ─── Load CT slice image ───────────────────────────────────────
  useEffect(() => {
    if (!canvasRef.current) return;
    const url = `${API_BASE}/api/cases/${caseId}/slice/${plane}/${index}?wc=${windowCenter}&ww=${windowWidth}&dose=${showDose}`;

    setLoading(true);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgRef.current = img;
      drawImage();
      setLoading(false);
    };
    img.onerror = () => setLoading(false);
    img.src = url;
  }, [caseId, plane, index, windowCenter, windowWidth, showDose]);

  // ─── Load structure contours ────────────────────────────────────
  useEffect(() => {
    if (!showStructures) {
      setStructData({});
      return;
    }
    fetch(`${API_BASE}/api/cases/${caseId}/structures/${plane}/${index}`)
      .then(r => r.json())
      .then(setStructData)
      .catch(() => setStructData({}));
  }, [caseId, plane, index, showStructures]);

  // ─── Redraw overlay when structures or image changes ───────────
  useEffect(() => {
    drawImage();
    drawOverlay();
  }, [structData, enabledRois]);

  function drawImage() {
    const canvas = canvasRef.current;
    if (!canvas || !imgRef.current) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = imgRef.current;
    canvas.width  = img.naturalWidth  || 256;
    canvas.height = img.naturalHeight || 256;
    ctx.drawImage(img, 0, 0);
    // Also sync overlay canvas size
    if (overlayRef.current) {
      overlayRef.current.width  = canvas.width;
      overlayRef.current.height = canvas.height;
    }
    drawOverlay();
  }

  function drawOverlay() {
    const overlay = overlayRef.current;
    const baseCanvas = canvasRef.current;
    if (!overlay || !baseCanvas) return;
    const ctx = overlay.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    if (!showStructures) return;

    const W = overlay.width;
    const H = overlay.height;

    for (const [roiNum, roi] of Object.entries(structData)) {
      if (!enabledRois.has(roiNum)) continue;
      const [r, g, b] = roi.color;
      ctx.strokeStyle = `rgb(${r},${g},${b})`;
      ctx.lineWidth   = 1.5;
      ctx.shadowColor = `rgba(${r},${g},${b},0.6)`;
      ctx.shadowBlur  = 2;

      for (const polyline of roi.contours) {
        if (polyline.length < 2) continue;
        ctx.beginPath();
        // Scale polyline coords to canvas size
        // For axial: [px_col, px_row] scaled from [nx, ny]
        // For sagittal/coronal: [z_idx, pixel] scaled to [nz/nx/ny, H]
        const [nz, ny, nx] = metadata.shape;
        let scaleX = 1, scaleY = 1, offsetX = 0, offsetY = 0;
        if (plane === "axial") {
          scaleX = W / nx;
          scaleY = H / ny;
        } else if (plane === "sagittal") {
          scaleX = W / nz;
          scaleY = H / ny;
        } else {
          scaleX = W / nz;
          scaleY = H / nx;
        }

        const firstPt = polyline[0];
        ctx.moveTo(firstPt[0] * scaleX, firstPt[1] * scaleY);
        for (let j = 1; j < polyline.length; j++) {
          ctx.lineTo(polyline[j][0] * scaleX, polyline[j][1] * scaleY);
        }
        ctx.closePath();
        ctx.stroke();
      }
      ctx.shadowBlur = 0;
    }

    // Crosshair lines
    ctx.strokeStyle = "rgba(255,255,255,0.25)";
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(W / 2, 0);
    ctx.lineTo(W / 2, H);
    ctx.moveTo(0, H / 2);
    ctx.lineTo(W, H / 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // ─── Scroll to change slice ────────────────────────────────────
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1 : -1;
    const newIndex = Math.max(0, Math.min(maxIndex, index + delta));
    if (newIndex !== index) onIndexChange(plane, newIndex);
  }, [plane, index, maxIndex, onIndexChange]);

  // ─── Drag to scroll ────────────────────────────────────────────
  const handleMouseDown = (e: React.MouseEvent) => {
    onActivate();
    isDragging.current = true;
    lastY.current = e.clientY;
  };
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dy = e.clientY - lastY.current;
    lastY.current = e.clientY;
    if (Math.abs(dy) > 4) {
      const delta = dy > 0 ? 1 : -1;
      const newIndex = Math.max(0, Math.min(maxIndex, index + delta));
      onIndexChange(plane, newIndex);
    }
  }, [plane, index, maxIndex, onIndexChange]);
  const handleMouseUp = () => { isDragging.current = false; };

  const planeColor = PLANE_COLORS[plane];

  return (
    <div
      ref={containerRef}
      className={`viewport-canvas w-full h-full relative bg-black ${isActive ? "viewport-active" : ""}`}
      style={{ border: isActive ? `1px solid ${planeColor}44` : "1px solid transparent" }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
    >
      {/* CT image canvas */}
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: "100%", imageRendering: "pixelated" }}
      />

      {/* Overlay canvas for contours + crosshair */}
      <canvas
        ref={overlayRef}
        className="overlay-canvas"
        style={{ imageRendering: "pixelated" }}
      />

      {/* Plane label */}
      <div className={`viewport-label ${plane}`}>
        {PLANE_LABELS[plane]}
      </div>

      {/* Slice index */}
      <div className="slice-label mono">
        {index + 1} / {maxIndex + 1}
      </div>

      {/* Loading indicator */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin opacity-60" />
        </div>
      )}
    </div>
  );
}
