/**
 * useVolume — fetches the CT and dose volumes once and caches them in memory.
 * Returns typed arrays that the WebGL viewport can upload directly as textures.
 */
import { useState, useEffect, useRef } from "react";
import { API_BASE } from "@/lib/queryClient";
import type { CaseMetadata } from "@/types";

export interface VolumeData {
  ct: Int16Array;       // [NZ * NY * NX] row-major (C-order)
  dose: Float32Array | null;
  shape: [number, number, number]; // [NZ, NY, NX]
  loaded: boolean;
  error: string | null;
  progress: number;     // 0–1
}

export function useVolume(caseId: string, metadata: CaseMetadata | null): VolumeData {
  const [state, setState] = useState<VolumeData>({
    ct: new Int16Array(0),
    dose: null,
    shape: [0, 0, 0],
    loaded: false,
    error: null,
    progress: 0,
  });

  const prevCaseId = useRef<string | null>(null);

  useEffect(() => {
    if (!metadata || !caseId) return;
    if (prevCaseId.current === caseId) return;
    prevCaseId.current = caseId;

    setState({ ct: new Int16Array(0), dose: null, shape: [0,0,0], loaded: false, error: null, progress: 0 });

    const [nz, ny, nx] = metadata.shape;
    const expectedCTBytes = nz * ny * nx * 2; // int16

    async function fetchVolumes() {
      try {
        // ── Fetch CT volume ─────────────────────────────────────────────
        // The server sends Content-Encoding: gzip, so fetch() decompresses
        // automatically. We just receive the raw int16 bytes.
        setState(s => ({ ...s, progress: 0.05 }));
        const ctRes = await fetch(`${API_BASE}/api/cases/${caseId}/volume`);
        if (!ctRes.ok) throw new Error(`CT volume fetch failed: ${ctRes.status}`);

        const ctBuf = await ctRes.arrayBuffer();
        const ctArr = new Int16Array(ctBuf);
        setState(s => ({ ...s, progress: 0.6 }));

        // ── Fetch dose volume (optional) ────────────────────────────────
        let doseArr: Float32Array | null = null;
        if (metadata.has_dose) {
          const doseRes = await fetch(`${API_BASE}/api/cases/${caseId}/dose/volume`);
          if (doseRes.ok) {
            const doseBuf = await doseRes.arrayBuffer();
            doseArr = new Float32Array(doseBuf);
          }
        }
        setState(s => ({ ...s, progress: 0.9 }));

        setState({
          ct: ctArr,
          dose: doseArr,
          shape: [nz, ny, nx],
          loaded: true,
          error: null,
          progress: 1,
        });
      } catch (err: any) {
        setState(s => ({ ...s, loaded: false, error: err.message, progress: 0 }));
      }
    }

    fetchVolumes();
  }, [caseId, metadata]);

  return state;
}
