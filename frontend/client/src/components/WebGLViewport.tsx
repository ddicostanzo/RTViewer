/**
 * WebGLViewport — GPU-rendered CT/dose viewer.
 *
 * Architecture:
 *  - CT volume is packed into a 2D atlas texture (atlasCols * NX wide, atlasRows * NY tall).
 *    Each "tile" is one axial slice (NX × NY). Tiles fill left-to-right, then top-to-bottom.
 *  - Texture encoding: RGBA8, R=high byte, G=low byte of uint16.
 *    CT:   uint16 = HU + 32768  →  shader decodes back to HU
 *    Dose: uint16 = dose_gy / doseMax * 65535  →  shader decodes to [0,1] normalized
 *  - Fragment shader does all slicing, W/L, and dose colormap per pixel on the GPU.
 *  - W/L changes are uniform updates — zero CPU work, zero network, instant response.
 *  - Structures rendered on a 2D Canvas overlay (separate element, always on top).
 *
 * Orientation (radiological convention):
 *  - Axial:    cols = L→R patient, rows = A→P patient. No flip needed.
 *  - Sagittal: cols = A→P, rows = S→I. flipY to put superior at top.
 *  - Coronal:  cols = R→L, rows = S→I. flipY to put superior at top.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { API_BASE } from "@/lib/queryClient";
import type { CaseMetadata, StructureSliceResponse, Plane } from "@/types";
import type { VolumeData } from "@/hooks/useVolume";

// ─── GLSL ──────────────────────────────────────────────────────────────────────

const VERT = `
attribute vec2 aPos;
varying   vec2 vUV;
void main() {
  vUV = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

const FRAG = `
precision highp float;
varying vec2 vUV;

uniform sampler2D uCT;
uniform sampler2D uDose;
uniform int  uHasDose;
uniform int  uShowDose;

// Atlas geometry (all as floats for GLSL ES 1.0 compatibility)
uniform float uAtlasCols;
uniform float uAtlasRows;
uniform float uNX;   // axial tile width
uniform float uNY;   // axial tile height
uniform float uNZ;   // total slices

// Volume shape (needed for reformats)
uniform float uVolNZ;
uniform float uVolNY;
uniform float uVolNX;

// What to display
uniform float uSlice;   // which slice/column/row
uniform int   uPlane;   // 0=axial 1=sagittal 2=coronal

// Orientation
uniform int uFlipX;
uniform int uFlipY;

// Window / Level (HU)
uniform float uWC;
uniform float uWW;

// Dose normalisation
uniform float uDoseMax;

// ── Helpers ───────────────────────────────────────────────────────────────────

// Decode RGBA8 packed uint16 (R=hi byte, G=lo byte)
float u16(vec4 s) {
  return floor(s.r * 255.0 + 0.5) * 256.0 + floor(s.g * 255.0 + 0.5);
}

// Get atlas UV for a given axial slice index + pixel position within tile
vec2 atlasUV(float zi, float px, float py) {
  float tc = mod(zi, uAtlasCols);
  float tr = floor(zi / uAtlasCols);
  float u  = (tc * uNX + px + 0.5) / (uAtlasCols * uNX);
  float v  = (tr * uNY + py + 0.5) / (uAtlasRows * uNY);
  return vec2(u, 1.0 - v);  // flip V: texture origin is bottom-left in GL
}

// Sample HU from CT atlas at (zi, px, py)
float ctHU(float zi, float px, float py) {
  return u16(texture2D(uCT, atlasUV(zi, px, py))) - 32768.0;
}

// Sample normalised dose [0,1] from dose atlas at (zi, px, py)
float doseN(float zi, float px, float py) {
  return u16(texture2D(uDose, atlasUV(zi, px, py))) / 65535.0;
}

// ── Colormap ──────────────────────────────────────────────────────────────────

vec3 doseColor(float t) {
  t = clamp(t, 0.0, 1.0);
  if (t < 0.25)  return mix(vec3(0.0, 0.0, 1.0),   vec3(0.0, 1.0, 0.5),   t * 4.0);
  if (t < 0.5)   return mix(vec3(0.0, 1.0, 0.5),   vec3(1.0, 1.0, 0.0),  (t-0.25)*4.0);
  if (t < 0.75)  return mix(vec3(1.0, 1.0, 0.0),   vec3(1.0, 0.5, 0.0),  (t-0.5)*4.0);
               return mix(vec3(1.0, 0.5, 0.0),   vec3(1.0, 0.0, 0.0),  (t-0.75)*4.0);
}

// ── Main ──────────────────────────────────────────────────────────────────────

void main() {
  float fx = uFlipX == 1 ? 1.0 - vUV.x : vUV.x;
  float fy = uFlipY == 1 ? 1.0 - vUV.y : vUV.y;

  float hu;
  float doseVal = 0.0;

  if (uPlane == 0) {
    // ── Axial: direct tile lookup ──────────────────────────────────────────
    float px = fx * uNX;
    float py = fy * uNY;
    hu = ctHU(uSlice, px, py);
    if (uHasDose == 1 && uShowDose == 1)
      doseVal = doseN(uSlice, px, py);

  } else if (uPlane == 1) {
    // ── Sagittal: show (Z, Y) at fixed X = uSlice ─────────────────────────
    // fx → Z axis (0 = z=0 ... 1 = z=NZ-1)
    // fy → Y axis (0 = y=0 ... 1 = y=NY-1, i.e. superior→inferior)
    float zi = floor(fx * uVolNZ);
    float py = floor(fy * uVolNY);
    zi = clamp(zi, 0.0, uVolNZ - 1.0);
    py = clamp(py, 0.0, uVolNY - 1.0);
    hu = ctHU(zi, uSlice, py);
    if (uHasDose == 1 && uShowDose == 1)
      doseVal = doseN(zi, uSlice, py);

  } else {
    // ── Coronal: show (Z, X) at fixed Y = uSlice ──────────────────────────
    // fx → Z axis
    // fy → X axis (cols, left→right of axial)
    float zi = floor(fx * uVolNZ);
    float px = floor(fy * uVolNX);
    zi = clamp(zi, 0.0, uVolNZ - 1.0);
    px = clamp(px, 0.0, uVolNX - 1.0);
    hu = ctHU(zi, px, uSlice);
    if (uHasDose == 1 && uShowDose == 1)
      doseVal = doseN(zi, px, uSlice);
  }

  // Window / level
  float lo  = uWC - uWW * 0.5;
  float hi  = uWC + uWW * 0.5;
  float lum = clamp((hu - lo) / (hi - lo), 0.0, 1.0);
  vec3 col  = vec3(lum);

  // Dose overlay
  if (uHasDose == 1 && uShowDose == 1 && uDoseMax > 0.0) {
    float norm = doseVal;  // already [0,1] scaled to doseMax at upload
    // Re-scale: upload used doseMax as ceiling, so doseVal=1 → doseMax Gy
    if (norm > 0.04) {
      float alpha = norm * 0.65;
      col = mix(col, doseColor(norm), alpha);
    }
  }

  gl_FragColor = vec4(col, 1.0);
}`;

// ─── WebGL helpers ──────────────────────────────────────────────────────────────

function buildProgram(gl: WebGLRenderingContext): WebGLProgram {
  function compile(type: number, src: string) {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
      throw new Error(gl.getShaderInfoLog(s) ?? "shader error");
    return s;
  }
  const prog = gl.createProgram()!;
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS))
    throw new Error(gl.getProgramInfoLog(prog) ?? "link error");
  return prog;
}

/**
 * Upload a volume into a 2D atlas RGBA8 texture.
 * Encoding: R=hi byte, G=lo byte of uint16.
 * CT:   uint16 = clamp(HU + 32768, 0, 65535)
 * Dose: uint16 = clamp(dose / doseMax * 65535, 0, 65535)
 */
function uploadAtlas(
  gl: WebGLRenderingContext,
  data: Int16Array | Float32Array,
  nz: number, ny: number, nx: number,
  doseMax: number,     // only used when isFloat=true
  isFloat: boolean,
): { tex: WebGLTexture; atlasCols: number; atlasRows: number } {
  const atlasCols = Math.ceil(Math.sqrt(nz));
  const atlasRows = Math.ceil(nz / atlasCols);
  const atlasW = atlasCols * nx;
  const atlasH = atlasRows * ny;
  const rgba = new Uint8Array(atlasW * atlasH * 4);

  for (let z = 0; z < nz; z++) {
    const tc = z % atlasCols;
    const tr = Math.floor(z / atlasCols);
    for (let y = 0; y < ny; y++) {
      for (let x = 0; x < nx; x++) {
        const srcIdx = z * ny * nx + y * nx + x;
        let u16: number;
        if (isFloat) {
          const raw = (data as Float32Array)[srcIdx];
          u16 = Math.round(Math.max(0, Math.min(1, raw / doseMax)) * 65535);
        } else {
          u16 = Math.max(0, Math.min(65535, (data as Int16Array)[srcIdx] + 32768));
        }
        const dstIdx = ((tr * ny + y) * atlasW + (tc * nx + x)) * 4;
        rgba[dstIdx]     = (u16 >> 8) & 0xFF;  // R = hi
        rgba[dstIdx + 1] = u16 & 0xFF;          // G = lo
        rgba[dstIdx + 2] = 0;
        rgba[dstIdx + 3] = 255;
      }
    }
  }

  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, atlasW, atlasH, 0, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return { tex, atlasCols, atlasRows };
}

// ─── Plane config ────────────────────────────────────────────────────────────

const PLANE_ORIENT: Record<Plane, { flipX: boolean; flipY: boolean }> = {
  axial:    { flipX: false, flipY: false },
  sagittal: { flipX: false, flipY: true  },
  coronal:  { flipX: false, flipY: true  },
};
const PLANE_IDX: Record<Plane, number> = { axial: 0, sagittal: 1, coronal: 2 };
const PLANE_COLORS: Record<Plane, string> = {
  axial: "#4cc9d6", sagittal: "#5cb87a", coronal: "#f0a040",
};
const PLANE_LABELS: Record<Plane, string> = {
  axial: "AX", sagittal: "SAG", coronal: "COR",
};

// ─── Component ────────────────────────────────────────────────────────────────

interface Props {
  metadata: CaseMetadata;
  volume: VolumeData;
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
  caseId: string;
}

export default function WebGLViewport({
  metadata, volume, plane, index, onIndexChange,
  showDose, showStructures, enabledRois,
  windowCenter, windowWidth,
  isActive, onActivate, caseId,
}: Props) {
  const glCanvasRef  = useRef<HTMLCanvasElement>(null);
  const overlayRef   = useRef<HTMLCanvasElement>(null);
  const glStateRef   = useRef<{
    gl: WebGLRenderingContext;
    prog: WebGLProgram;
    ctTex: WebGLTexture | null;
    doseTex: WebGLTexture | null;
    atlasCols: number;
    atlasRows: number;
    uploadedCase: string;
  } | null>(null);

  const isDragging = useRef(false);
  const lastY = useRef(0);
  const [structData, setStructData] = useState<StructureSliceResponse>({});

  const [nz, ny, nx] = metadata.shape;
  const maxIndex = plane === "axial" ? nz - 1 : plane === "sagittal" ? nx - 1 : ny - 1;

  // ── Init WebGL once ─────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = glCanvasRef.current;
    if (!canvas || glStateRef.current) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false });
    if (!gl) return;

    try {
      const prog = buildProgram(gl);
      gl.useProgram(prog);

      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
      const aPos = gl.getAttribLocation(prog, "aPos");
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

      glStateRef.current = { gl, prog, ctTex: null, doseTex: null, atlasCols: 1, atlasRows: 1, uploadedCase: "" };
    } catch (e) {
      console.error("WebGL init:", e);
    }
  }, []);

  // ── Upload textures when volume loads (once per case) ───────────────────────
  useEffect(() => {
    const state = glStateRef.current;
    if (!state || !volume.loaded || volume.shape[0] === 0) return;
    if (state.uploadedCase === caseId) return;

    const { gl } = state;
    const [vNZ, vNY, vNX] = volume.shape;

    if (state.ctTex) gl.deleteTexture(state.ctTex);
    const { tex: ctTex, atlasCols, atlasRows } = uploadAtlas(
      gl, volume.ct, vNZ, vNY, vNX, 1, false
    );
    state.ctTex = ctTex;
    state.atlasCols = atlasCols;
    state.atlasRows = atlasRows;

    if (state.doseTex) gl.deleteTexture(state.doseTex);
    state.doseTex = null;
    if (volume.dose && metadata.dose_max > 0) {
      const { tex: doseTex } = uploadAtlas(
        gl, volume.dose, vNZ, vNY, vNX, metadata.dose_max, true
      );
      state.doseTex = doseTex;
    }

    state.uploadedCase = caseId;
    renderGL();
  }, [volume.loaded, caseId]);

  // ── Render whenever display params change ───────────────────────────────────
  const renderGL = useCallback(() => {
    const state = glStateRef.current;
    const canvas = glCanvasRef.current;
    if (!state || !canvas || !state.ctTex) return;

    const { gl, prog, atlasCols, atlasRows } = state;
    const [vNZ, vNY, vNX] = volume.shape;

    // Match canvas to container
    const parent = canvas.parentElement;
    if (parent) {
      canvas.width  = parent.clientWidth  || 256;
      canvas.height = parent.clientHeight || 256;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.useProgram(prog);

    const u1f = (n: string, v: number)  => gl.uniform1f(gl.getUniformLocation(prog, n), v);
    const u1i = (n: string, v: number)  => gl.uniform1i(gl.getUniformLocation(prog, n), v);
    const u1s = (n: string, v: number)  => gl.uniform1i(gl.getUniformLocation(prog, n), v);

    u1f("uAtlasCols", atlasCols);
    u1f("uAtlasRows", atlasRows);
    u1f("uNX", vNX);
    u1f("uNY", vNY);
    u1f("uNZ", vNZ);
    u1f("uVolNZ", vNZ);
    u1f("uVolNY", vNY);
    u1f("uVolNX", vNX);
    u1f("uSlice",  index);
    u1i("uPlane",  PLANE_IDX[plane]);
    u1i("uFlipX",  PLANE_ORIENT[plane].flipX ? 1 : 0);
    u1i("uFlipY",  PLANE_ORIENT[plane].flipY ? 1 : 0);
    u1f("uWC", windowCenter);
    u1f("uWW", windowWidth);
    u1i("uShowDose", showDose ? 1 : 0);
    u1i("uHasDose",  state.doseTex ? 1 : 0);
    u1f("uDoseMax",  metadata.dose_max > 0 ? metadata.dose_max : 1.0);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, state.ctTex);
    u1s("uCT", 0);

    if (state.doseTex) {
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, state.doseTex);
      u1s("uDose", 1);
    }

    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    if (overlayRef.current) {
      overlayRef.current.width  = canvas.width;
      overlayRef.current.height = canvas.height;
    }
  }, [plane, index, windowCenter, windowWidth, showDose, volume, metadata]);

  useEffect(() => { renderGL(); }, [renderGL]);

  // ── Structure overlay ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!showStructures) { setStructData({}); return; }
    fetch(`${API_BASE}/api/cases/${caseId}/structures/${plane}/${index}`)
      .then(r => r.json()).then(setStructData).catch(() => setStructData({}));
  }, [caseId, plane, index, showStructures]);

  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    const ctx = overlay.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    const W = overlay.width;
    const H = overlay.height;

    if (showStructures) {
      for (const [roiNum, roi] of Object.entries(structData)) {
        if (!enabledRois.has(roiNum)) continue;
        const [r, g, b] = roi.color;
        ctx.strokeStyle = `rgb(${r},${g},${b})`;
        ctx.lineWidth = 1.5;
        ctx.shadowColor = `rgba(${r},${g},${b},0.5)`;
        ctx.shadowBlur = 2;

        for (const poly of roi.contours) {
          if (poly.length < 2) continue;
          let sX: number, sY: number;
          if (plane === "axial")    { sX = W / nx; sY = H / ny; }
          else if (plane === "sagittal") { sX = W / nz; sY = H / ny; }
          else                      { sX = W / nz; sY = H / nx; }

          // Sagittal and coronal contours may need Y-flip to match the viewport
          const needFlip = plane !== "axial";

          ctx.beginPath();
          const p0 = poly[0];
          const y0 = needFlip ? (1 - (p0[1] + 0.5) / (plane === "sagittal" ? ny : nx)) * H : p0[1] * sY;
          ctx.moveTo(p0[0] * sX, y0);
          for (let j = 1; j < poly.length; j++) {
            const p = poly[j];
            const yj = needFlip ? (1 - (p[1] + 0.5) / (plane === "sagittal" ? ny : nx)) * H : p[1] * sY;
            ctx.lineTo(p[0] * sX, yj);
          }
          ctx.closePath();
          ctx.stroke();
        }
        ctx.shadowBlur = 0;
      }
    }

    // Crosshair
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.lineWidth = 0.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(W/2, 0); ctx.lineTo(W/2, H);
    ctx.moveTo(0, H/2); ctx.lineTo(W, H/2);
    ctx.stroke();
    ctx.setLineDash([]);
  }, [structData, showStructures, enabledRois, plane, nx, ny, nz]);

  // ── Input handling ──────────────────────────────────────────────────────────
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    onIndexChange(plane, Math.max(0, Math.min(maxIndex, index + (e.deltaY > 0 ? 1 : -1))));
  }, [plane, index, maxIndex, onIndexChange]);

  const handleMouseDown = (e: React.MouseEvent) => {
    onActivate(); isDragging.current = true; lastY.current = e.clientY;
  };
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dy = e.clientY - lastY.current;
    lastY.current = e.clientY;
    if (Math.abs(dy) > 3)
      onIndexChange(plane, Math.max(0, Math.min(maxIndex, index + (dy > 0 ? 1 : -1))));
  }, [plane, index, maxIndex, onIndexChange]);

  const color = PLANE_COLORS[plane];

  return (
    <div
      className="relative w-full h-full bg-black overflow-hidden cursor-crosshair"
      style={{ border: isActive ? `1px solid ${color}55` : "1px solid transparent" }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={() => { isDragging.current = false; }}
      onMouseLeave={() => { isDragging.current = false; }}
      onWheel={handleWheel}
    >
      <canvas ref={glCanvasRef}  className="absolute inset-0 w-full h-full" />
      <canvas ref={overlayRef}   className="absolute inset-0 w-full h-full pointer-events-none" />

      <div className={`viewport-label ${plane}`}>{PLANE_LABELS[plane]}</div>
      <div className="slice-label mono">{index + 1} / {maxIndex + 1}</div>

      {!volume.loaded && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-3">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          {volume.progress > 0 && (
            <div className="w-32 h-1 bg-border rounded-full overflow-hidden">
              <div className="h-full bg-primary transition-all" style={{ width: `${volume.progress * 100}%` }} />
            </div>
          )}
          {volume.error && <p className="text-xs text-destructive px-2 text-center">{volume.error}</p>}
        </div>
      )}
    </div>
  );
}
