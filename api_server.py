"""
RT Viewer API Server
FastAPI backend for serving CT, RTStruct, and RTDose data
from DICOM files to the web viewer frontend.

Endpoints:
  GET  /api/cases                           -> list all ingested cases
  GET  /api/cases/{id}/metadata             -> CT geometry + ROI names
  GET  /api/cases/{id}/volume               -> full CT volume as gzip int16 binary
  GET  /api/cases/{id}/dose/volume          -> full dose volume as gzip float32 binary
  GET  /api/cases/{id}/structures           -> all contour polylines (JSON)
  GET  /api/cases/{id}/structures/{plane}/{index} -> contours for one slice
  GET  /api/cases/{id}/dose/stats           -> dose min/max
  GET  /api/events                          -> SSE stream for live patient list updates
  POST /api/ingest                          -> trigger re-ingest of dicom_data directory
"""

import os, json, math, io, time, gzip, asyncio, threading
from pathlib import Path
from typing import Optional
import numpy as np
from PIL import Image as PILImage
import pydicom
from pydicom.dataset import Dataset
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from contextlib import asynccontextmanager
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    print("[watcher] watchdog not installed — run: pip install watchdog")
    print("[watcher] File watching disabled; use POST /api/ingest to refresh manually.")

# ─── Configuration ─────────────────────────────────────────────────────────────
DICOM_ROOT = Path(__file__).parent / "dicom_data"
CACHE_DIR  = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# In-memory case registry: {case_id: CaseData}
case_registry: dict = {}

# ─── File watcher / SSE state ──────────────────────────────────────────────────
# Active SSE subscribers — each is an asyncio.Queue that receives event dicts
_sse_subscribers: list[asyncio.Queue] = []
_sse_lock = threading.Lock()

# Debounce: only re-ingest after files have been stable for this many seconds
WATCHER_DEBOUNCE_SECS = 3.0

def _broadcast(event: dict):
    """Push an event to all SSE subscribers (thread-safe)."""
    data = json.dumps(event)
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


if WATCHDOG_AVAILABLE:
  class _DicomWatcherBase(FileSystemEventHandler):
    pass
else:
  class _DicomWatcherBase:  # type: ignore
    pass


class _DicomWatcher(_DicomWatcherBase):
    """
    Watchdog handler for the dicom_data directory.
    Debounces rapid file-write bursts (e.g. many .dcm files landing at once)
    then triggers a full re-ingest and broadcasts the updated patient list.
    """
    def __init__(self):
        super().__init__()
        self._timer: Optional[threading.Timer] = None
        self._lock  = threading.Lock()

    def _is_relevant(self, path: str) -> bool:
        p = path.lower()
        return p.endswith(".npz") or p.endswith(".json") or p.endswith(".dcm")

    def on_created(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._schedule()

    def on_modified(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._schedule()

    def on_moved(self, event):
        if not event.is_directory and self._is_relevant(event.dest_path):
            self._schedule()

    def _schedule(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(WATCHER_DEBOUNCE_SECS, self._run_ingest)
            self._timer.daemon = True
            self._timer.start()

    def _run_ingest(self):
        print("[watcher] Change detected — re-ingesting...")
        try:
            case_registry.clear()
            ingest_all()
            _broadcast({
                "event":    "patients_updated",
                "patients": len(patient_index),
                "cases":    len(case_registry),
            })
            print(f"[watcher] Done. {len(patient_index)} patients, {len(case_registry)} cases.")
        except Exception as e:
            print(f"[watcher] Ingest error: {e}")

# ─── DICOM parsing helpers ─────────────────────────────────────────────────────

def load_ct_volume(ct_files: list[Path]) -> dict:
    """Load and sort CT slices into a 3D numpy array."""
    slices = []
    for f in ct_files:
        try:
            ds = pydicom.dcmread(str(f), force=True)
            if not hasattr(ds, 'ImagePositionPatient'):
                continue
            slices.append(ds)
        except Exception:
            continue
    if not slices:
        return {}

    slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))

    ref = slices[0]
    rows    = int(ref.Rows)
    cols    = int(ref.Columns)
    nz      = len(slices)
    spacing = [float(x) for x in ref.PixelSpacing]  # [row_spacing, col_spacing]
    thick   = float(ref.SliceThickness) if hasattr(ref, 'SliceThickness') else abs(
        float(slices[1].ImagePositionPatient[2]) - float(slices[0].ImagePositionPatient[2])
    ) if len(slices) > 1 else 1.0
    origin  = [float(x) for x in ref.ImagePositionPatient]
    orient  = [float(x) for x in ref.ImageOrientationPatient] if hasattr(ref, 'ImageOrientationPatient') else [1,0,0,0,1,0]

    volume = np.zeros((nz, rows, cols), dtype=np.float32)
    z_positions = []
    instance_uids = []
    for i, s in enumerate(slices):
        arr = s.pixel_array.astype(np.float32)
        slope     = float(getattr(s, 'RescaleSlope', 1))
        intercept = float(getattr(s, 'RescaleIntercept', 0))
        volume[i] = arr * slope + intercept
        z_positions.append(float(s.ImagePositionPatient[2]))
        instance_uids.append(str(s.SOPInstanceUID))

    return {
        "volume": volume,          # (NZ, NY, NX) float32 HU
        "shape": [nz, rows, cols],
        "spacing": spacing,        # [row_mm, col_mm]
        "thickness": thick,        # mm
        "origin": origin,          # [x, y, z] mm of slice[0] corner
        "orient": orient,
        "z_positions": z_positions,
        "instance_uids": instance_uids,
        "window_center": float(getattr(ref, 'WindowCenter', 40)),
        "window_width":  float(getattr(ref, 'WindowWidth', 400)),
    }


def load_rtstruct(rs_file: Path, ct_data: dict) -> dict:
    """Parse RTStruct: return {roi_name: {color, contours_by_z_index}}"""
    ds = pydicom.dcmread(str(rs_file), force=True)

    # Build ROI number -> name/color map
    roi_info = {}
    if hasattr(ds, 'StructureSetROISequence'):
        for roi in ds.StructureSetROISequence:
            roi_info[int(roi.ROINumber)] = {
                "name": str(roi.ROIName),
                "color": [255, 255, 255]
            }
    if hasattr(ds, 'ROIContourSequence'):
        for rc in ds.ROIContourSequence:
            n = int(rc.ReferencedROINumber)
            if n in roi_info and hasattr(rc, 'ROIDisplayColor'):
                roi_info[n]["color"] = [int(x) for x in rc.ROIDisplayColor]

    rois = {}
    if not hasattr(ds, 'ROIContourSequence'):
        return rois

    z_positions = ct_data.get("z_positions", [])
    origin      = ct_data.get("origin", [0, 0, 0])
    spacing     = ct_data.get("spacing", [1, 1])  # [row_mm, col_mm]
    thick       = ct_data.get("thickness", 1.0)
    nz = len(z_positions)
    ny = ct_data["shape"][1]
    nx = ct_data["shape"][2]

    def z_to_index(z_mm: float) -> Optional[int]:
        """Map a z coordinate to the nearest CT slice index."""
        if not z_positions:
            return None
        diffs = [abs(z_mm - zp) for zp in z_positions]
        idx = int(np.argmin(diffs))
        if diffs[idx] > thick * 1.5:
            return None
        return idx

    def mm_to_pixel(x_mm: float, y_mm: float):
        """Convert patient coords (mm) to pixel coords."""
        px = (x_mm - origin[0]) / spacing[1]  # col_spacing
        py = (y_mm - origin[1]) / spacing[0]  # row_spacing
        return px, py

    for rc in ds.ROIContourSequence:
        n = int(rc.ReferencedROINumber)
        info = roi_info.get(n, {"name": f"ROI {n}", "color": [255,255,255]})
        contours_by_z: dict[int, list] = {}

        if not hasattr(rc, 'ContourSequence'):
            continue

        for contour in rc.ContourSequence:
            if not hasattr(contour, 'ContourData'):
                continue
            pts = list(contour.ContourData)
            if len(pts) < 9:
                continue
            # pts = [x1,y1,z1, x2,y2,z2, ...]
            z_mm = float(pts[2])
            z_idx = z_to_index(z_mm)
            if z_idx is None:
                continue
            # Convert to pixel coordinates
            pixel_pts = []
            for j in range(0, len(pts), 3):
                px, py = mm_to_pixel(float(pts[j]), float(pts[j+1]))
                pixel_pts.append([round(px, 2), round(py, 2)])
            if pixel_pts:
                if z_idx not in contours_by_z:
                    contours_by_z[z_idx] = []
                contours_by_z[z_idx].append(pixel_pts)

        rois[str(n)] = {
            "roi_number": n,
            "name":  info["name"],
            "color": info["color"],
            "contours_by_z": {str(k): v for k, v in contours_by_z.items()}
        }

    return rois


def load_rtdose(rd_file: Path, ct_data: dict) -> dict:
    """Load RTDose and resample to CT grid."""
    ds = pydicom.dcmread(str(rd_file), force=True)
    scaling  = float(ds.DoseGridScaling)
    raw      = ds.pixel_array  # shape (NZ_dose, NY_dose, NX_dose) uint32
    dose_3d  = raw.astype(np.float32) * scaling  # in Gy (or cGy depending on file)

    dnz, dny, dnx = dose_3d.shape
    d_spacing_row = float(ds.PixelSpacing[0])
    d_spacing_col = float(ds.PixelSpacing[1])
    d_origin      = [float(x) for x in ds.ImagePositionPatient]
    grid_offsets  = [float(x) for x in ds.GridFrameOffsetVector]
    d_z_positions = [d_origin[2] + off for off in grid_offsets]

    ct_shape    = ct_data["shape"]   # [nz, ny, nx]
    ct_spacing  = ct_data["spacing"] # [row_mm, col_mm]
    ct_thick    = ct_data["thickness"]
    ct_origin   = ct_data["origin"]
    ct_z_pos    = ct_data["z_positions"]

    nz_ct = ct_shape[0]
    ny_ct = ct_shape[1]
    nx_ct = ct_shape[2]

    # Build resampled dose on CT grid using nearest-neighbor (fast, sufficient for display)
    dose_on_ct = np.zeros((nz_ct, ny_ct, nx_ct), dtype=np.float32)

    for iz_ct, z_ct in enumerate(ct_z_pos):
        # find nearest dose z
        diffs_z = [abs(z_ct - zd) for zd in d_z_positions]
        iz_d = int(np.argmin(diffs_z))
        if diffs_z[iz_d] > max(abs(grid_offsets[1] - grid_offsets[0]) if len(grid_offsets) > 1 else 5, 5) * 1.5:
            continue

        dose_slice = dose_3d[iz_d]  # (DNY, DNX)

        for iy_ct in range(ny_ct):
            y_mm_ct = ct_origin[1] + iy_ct * ct_spacing[0]
            iy_d = (y_mm_ct - d_origin[1]) / d_spacing_row
            iy_d = int(round(iy_d))
            if not (0 <= iy_d < dny):
                continue
            for ix_ct in range(nx_ct):
                x_mm_ct = ct_origin[0] + ix_ct * ct_spacing[1]
                ix_d = (x_mm_ct - d_origin[0]) / d_spacing_col
                ix_d = int(round(ix_d))
                if 0 <= ix_d < dnx:
                    dose_on_ct[iz_ct, iy_ct, ix_ct] = dose_slice[iy_d, ix_d]

    return {
        "dose": dose_on_ct,
        "max": float(dose_on_ct.max()),
        "min": float(dose_on_ct.min()),
        "mean": float(dose_on_ct[dose_on_ct > 0].mean()) if (dose_on_ct > 0).any() else 0.0,
    }


# ─── Manifest / patient index ─────────────────────────────────────────────────
# patient_index maps patient_id → {name, cases: [{case_name, plan_name, beamset_labels,
#   exported_at, case_id}]}
patient_index: dict = {}

def load_manifest(case_dir: Path) -> Optional[dict]:
    """Read manifest.json from an export directory, if present."""
    mf = case_dir / "manifest.json"
    if mf.exists():
        try:
            with open(mf) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def rebuild_patient_index():
    """Walk DICOM_ROOT and rebuild patient_index from manifests."""
    patient_index.clear()
    if not DICOM_ROOT.exists():
        return

    # Walk up to 3 levels deep looking for manifest.json files
    for root, dirs, files in os.walk(str(DICOM_ROOT)):
        if "manifest.json" in files:
            try:
                with open(os.path.join(root, "manifest.json")) as f:
                    mf = json.load(f)
                pid   = mf.get("patient_id",   Path(root).name)
                pname = mf.get("patient_name", "Unknown")
                case_entry = {
                    "case_id":       mf.get("viewer_case_id", os.path.relpath(root, str(DICOM_ROOT)).replace(os.sep, "/")),
                    "case_name":     mf.get("case_name", ""),
                    "plan_name":     mf.get("plan_name", ""),
                    "exam_name":     mf.get("exam_name", ""),
                    "beamset_labels": mf.get("beamset_labels", []),
                    "dose_type":     mf.get("dose_type", "physical"),
                    "exported_at":   mf.get("exported_at", ""),
                }
                if pid not in patient_index:
                    patient_index[pid] = {"patient_id": pid, "patient_name": pname, "cases": []}
                patient_index[pid]["cases"].append(case_entry)
            except Exception as e:
                print(f"[manifest] Error reading {root}: {e}")


# ─── Case ingestion ────────────────────────────────────────────────────────────

# ─── Native .npz ingest (from raystation_export.py numpy path) ───────────────

def ingest_case_native(case_dir: Path, case_id: str) -> str:
    """
    Load a case exported by raystation_export.py (numpy direct API path).
    Expects: ct_volume.npz, ct_geometry.json, structures.json,
             dose_<label>.npz, dose_<label>_geometry.json
    """
    # ── CT ────────────────────────────────────────────────────────────────────
    ct_npz = case_dir / "ct_volume.npz"
    ct_geo_f = case_dir / "ct_geometry.json"
    if not ct_npz.exists():
        raise ValueError(f"ct_volume.npz not found in {case_dir}")

    t0 = time.time()
    with np.load(str(ct_npz)) as d:
        volume = d["volume"].astype(np.float32)   # (NZ, NY, NX) int16 → float32

    with open(ct_geo_f) as f:
        geo = json.load(f)

    nz, ny, nx = volume.shape
    ct_data = {
        "volume":         volume,
        "shape":          [nz, ny, nx],
        "spacing":        geo["spacing"],           # [row_mm, col_mm]
        "thickness":      geo["thickness"],
        "origin":         geo["origin"],            # [x,y,z] mm
        "orient":         geo.get("col_direction", [1,0,0]) + geo.get("row_direction", [0,1,0]),
        "z_positions":    geo.get("z_positions", [geo["origin"][2] + i*geo["thickness"] for i in range(nz)]),
        "window_center":  geo.get("window_center", 40.0),
        "window_width":   geo.get("window_width",  400.0),
        "instance_uids":  [],
    }
    print(f"[ingest native] {case_id}: CT {volume.shape} in {time.time()-t0:.1f}s")

    # ── Structures ────────────────────────────────────────────────────────────
    struct_f = case_dir / "structures.json"
    rois = {}
    if struct_f.exists():
        t0 = time.time()
        with open(struct_f) as f:
            raw_rois = json.load(f)  # {roi_name: {name, color, contours: [[[x,y,z],...],...]}
        rois = _convert_native_structures(raw_rois, ct_data)
        print(f"  Structures: {len(rois)} ROIs in {time.time()-t0:.1f}s")

    # ── Dose (first matching .npz file) ───────────────────────────────────────
    dose_data = {}
    dose_npz_files = sorted(case_dir.glob("dose_*.npz"))
    if dose_npz_files:
        t0 = time.time()
        dose_file = dose_npz_files[0]
        label = dose_file.stem[5:]  # strip "dose_"
        geo_file = case_dir / f"dose_{label}_geometry.json"

        with np.load(str(dose_file)) as d:
            dose_raw = d["dose"].astype(np.float32)  # Gy, on dose grid

        dose_geo = {}
        if geo_file.exists():
            with open(geo_file) as f:
                dose_geo = json.load(f)

        # Resample dose onto CT grid
        dose_on_ct = _resample_dose_to_ct(dose_raw, dose_geo, ct_data)
        dose_data = {
            "dose": dose_on_ct,
            "max":  float(dose_on_ct.max()),
            "min":  float(dose_on_ct[dose_on_ct > 0].min()) if (dose_on_ct > 0).any() else 0.0,
            "mean": float(dose_on_ct[dose_on_ct > 0].mean()) if (dose_on_ct > 0).any() else 0.0,
        }
        print(f"  Dose: {dose_raw.shape}→{dose_on_ct.shape} max={dose_data['max']:.2f} Gy "
              f"in {time.time()-t0:.1f}s")

    case_registry[case_id] = {
        "id":   case_id,
        "ct":   ct_data,
        "rois": rois,
        "dose": dose_data,
    }
    return case_id


def _convert_native_structures(raw_rois: dict, ct_data: dict) -> dict:
    """
    Convert native structures.json (patient-coord mm polygons) to the
    same pixel-coord format the viewer frontend expects.
    {roi_num_str: {name, color, contours_by_z: {z_idx_str: [[px, py], ...]}}}
    """
    origin    = ct_data["origin"]    # [x, y, z0] mm
    spacing   = ct_data["spacing"]   # [row_mm, col_mm]
    z_positions = ct_data["z_positions"]
    thickness   = ct_data["thickness"]

    def z_to_index(z_mm: float) -> Optional[int]:
        if not z_positions:
            return None
        diffs = [abs(z_mm - zp) for zp in z_positions]
        idx = int(np.argmin(diffs))
        return idx if diffs[idx] <= thickness * 1.5 else None

    def mm_to_pixel(x_mm, y_mm):
        px = (x_mm - origin[0]) / spacing[1]   # col
        py = (y_mm - origin[1]) / spacing[0]   # row
        return px, py

    result = {}
    for roi_idx, (roi_name, roi) in enumerate(raw_rois.items()):
        roi_num = str(roi_idx + 1)
        contours_by_z: dict = {}
        for polygon in roi.get("contours", []):
            if not polygon:
                continue
            # All points in a polygon have the same z (planar contour)
            z_mm = float(polygon[0][2])
            z_idx = z_to_index(z_mm)
            if z_idx is None:
                continue
            pixel_pts = []
            for pt in polygon:
                px, py = mm_to_pixel(float(pt[0]), float(pt[1]))
                pixel_pts.append([round(px, 2), round(py, 2)])
            if pixel_pts:
                key = str(z_idx)
                if key not in contours_by_z:
                    contours_by_z[key] = []
                contours_by_z[key].append(pixel_pts)

        result[roi_num] = {
            "roi_number": roi_idx + 1,
            "name":  roi["name"],
            "color": roi["color"],
            "contours_by_z": contours_by_z,
        }
    return result


def _resample_dose_to_ct(dose_3d: np.ndarray, dose_geo: dict, ct_data: dict) -> np.ndarray:
    """
    Nearest-neighbour resample dose grid onto CT grid.
    dose_3d: (NZ_d, NY_d, NX_d) float32 Gy
    Returns: (NZ_ct, NY_ct, NX_ct) float32 Gy
    """
    nz_ct, ny_ct, nx_ct = ct_data["shape"]
    ct_origin  = ct_data["origin"]
    ct_spacing = ct_data["spacing"]   # [row_mm, col_mm]
    ct_thick   = ct_data["thickness"]
    ct_z_pos   = ct_data["z_positions"]

    if not dose_geo:
        return np.zeros((nz_ct, ny_ct, nx_ct), dtype=np.float32)

    d_origin  = dose_geo["origin"]    # [x, y, z] mm
    d_spacing = dose_geo["spacing"]   # [row_mm, col_mm]
    d_thick   = dose_geo["thickness"]  # mm
    nz_d, ny_d, nx_d = dose_3d.shape

    # Build z-position arrays for dose grid
    d_z_pos = [d_origin[2] + k * d_thick for k in range(nz_d)]

    out = np.zeros((nz_ct, ny_ct, nx_ct), dtype=np.float32)

    for iz_ct, z_ct in enumerate(ct_z_pos):
        # Nearest dose Z
        dz = [abs(z_ct - zd) for zd in d_z_pos]
        iz_d = int(np.argmin(dz))
        if dz[iz_d] > d_thick * 1.5:
            continue
        dose_slice = dose_3d[iz_d]

        for iy_ct in range(ny_ct):
            y_mm = ct_origin[1] + iy_ct * ct_spacing[0]
            iy_d = int(round((y_mm - d_origin[1]) / d_spacing[0]))
            if not (0 <= iy_d < ny_d):
                continue
            for ix_ct in range(nx_ct):
                x_mm = ct_origin[0] + ix_ct * ct_spacing[1]
                ix_d = int(round((x_mm - d_origin[0]) / d_spacing[1]))
                if 0 <= ix_d < nx_d:
                    out[iz_ct, iy_ct, ix_ct] = dose_slice[iy_d, ix_d]
    return out


# ─── DICOM-based ingest (fallback) ────────────────────────────────────────────

def ingest_case(case_dir: Path, case_id_override: str = None) -> str:
    """
    Ingest a case directory.
    Prefers native .npz format (raystation_export.py numpy path).
    Falls back to DICOM if no ct_volume.npz is present.
    """
    case_id = case_id_override if case_id_override else case_dir.name

    # ── Prefer native format ──────────────────────────────────────────────────
    if (case_dir / "ct_volume.npz").exists():
        return ingest_case_native(case_dir, case_id)

    # ── DICOM fallback ────────────────────────────────────────────────────────
    ct_files = []
    rs_files = []
    rd_files = []

    for f in sorted(case_dir.glob("*.dcm")):
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
            modality = str(getattr(ds, "Modality", "")).upper()
            if modality == "CT":
                ct_files.append(f)
            elif modality == "RTSTRUCT":
                rs_files.append(f)
            elif modality == "RTDOSE":
                rd_files.append(f)
        except Exception:
            continue

    if not ct_files:
        raise ValueError(f"No CT files found in {case_dir} (checked {len(list(case_dir.glob('*.dcm')))} .dcm files)")

    print(f"[ingest DICOM] {case_id}: {len(ct_files)} CT slices, "
          f"{len(rs_files)} RTSTRUCT, {len(rd_files)} RTDOSE")

    t0 = time.time()
    ct_data = load_ct_volume(ct_files)
    print(f"  CT loaded in {time.time()-t0:.1f}s  shape={ct_data['shape']}")

    rois = {}
    if rs_files:
        t0 = time.time()
        rois = load_rtstruct(rs_files[0], ct_data)
        print(f"  RTStruct loaded in {time.time()-t0:.1f}s  ROIs={list(rois.keys())}")

    dose_data = {}
    if rd_files:
        t0 = time.time()
        dose_data = load_rtdose(rd_files[0], ct_data)
        print(f"  RTDose loaded in {time.time()-t0:.1f}s  max={dose_data['max']:.2f}")

    case_registry[case_id] = {
        "id":       case_id,
        "ct":       ct_data,
        "rois":     rois,
        "dose":     dose_data,
        "ct_files": [str(f) for f in ct_files],
    }
    return case_id


def ingest_all():
    """Recursively scan DICOM_ROOT for case directories and ingest them.
    A 'case directory' is any directory containing at least one .dcm file.
    Supports flat layout (dicom_data/PatientID/*.dcm) and nested layout
    (dicom_data/PatientID/CaseName/PlanName/*.dcm) produced by raystation_export.py.
    """
    if not DICOM_ROOT.exists():
        return

    def find_leaf_dirs(root: Path):
        """Find directories that contain ingestable data:
        - Native: contains ct_volume.npz
        - DICOM:  contains at least one .dcm file
        Does not descend into a directory that is itself a leaf.
        """
        leaves = []
        if (root / "ct_volume.npz").exists() or any(root.glob("*.dcm")):
            leaves.append(root)
        else:
            for child in sorted(root.iterdir()):
                if child.is_dir():
                    leaves.extend(find_leaf_dirs(child))
        return leaves

    leaf_dirs = find_leaf_dirs(DICOM_ROOT)
    for d in leaf_dirs:
        try:
            # Use relative path as case_id so nested paths work
            rel = d.relative_to(DICOM_ROOT)
            case_id = str(rel).replace(os.sep, "/")
            ingest_case(d, case_id_override=case_id)
        except Exception as e:
            print(f"[ingest] Error on {d}: {e}")

    rebuild_patient_index()
    print(f"[ingest] Patient index: {list(patient_index.keys())}")


# ─── Rendering helpers ─────────────────────────────────────────────────────────

DOSE_CMAP = [
    (0.0,  (0,   0,   0,   0)),
    (0.2,  (0,   0, 255, 120)),
    (0.4,  (0, 255,   0, 160)),
    (0.6,  (255, 255, 0, 180)),
    (0.8,  (255, 128, 0, 200)),
    (1.0,  (255,   0, 0, 220)),
]

def apply_dose_colormap(norm: float) -> tuple:
    """Map normalized dose [0,1] to RGBA."""
    norm = float(np.clip(norm, 0, 1))
    if norm < 0.05:
        return (0, 0, 0, 0)
    for i in range(len(DOSE_CMAP) - 1):
        t0, c0 = DOSE_CMAP[i]
        t1, c1 = DOSE_CMAP[i+1]
        if t0 <= norm <= t1:
            f = (norm - t0) / (t1 - t0)
            r = int(c0[0] + f*(c1[0]-c0[0]))
            g = int(c0[1] + f*(c1[1]-c0[1]))
            b = int(c0[2] + f*(c1[2]-c0[2]))
            a = int(c0[3] + f*(c1[3]-c0[3]))
            return (r, g, b, a)
    return DOSE_CMAP[-1][1]


def ct_slice_to_png(ct_slice: np.ndarray, wc: float, ww: float,
                    dose_slice: Optional[np.ndarray] = None,
                    dose_max: float = 1.0) -> bytes:
    """Convert a 2D CT array to PNG bytes with optional dose overlay."""
    lo = wc - ww / 2
    hi = wc + ww / 2
    norm = np.clip((ct_slice - lo) / (hi - lo), 0, 1)
    gray = (norm * 255).astype(np.uint8)

    # Base: RGB from grayscale
    rgb = np.stack([gray, gray, gray], axis=-1)
    rgba = np.dstack([rgb, np.full_like(gray, 255)])  # (H, W, 4)

    if dose_slice is not None and dose_max > 0:
        dose_norm = dose_slice / dose_max
        for y in range(dose_slice.shape[0]):
            for x in range(dose_slice.shape[1]):
                d = dose_norm[y, x]
                if d < 0.05:
                    continue
                dr, dg, db, da = apply_dose_colormap(d)
                alpha = da / 255.0 * 0.65
                rgba[y, x, 0] = int(rgba[y, x, 0] * (1 - alpha) + dr * alpha)
                rgba[y, x, 1] = int(rgba[y, x, 1] * (1 - alpha) + dg * alpha)
                rgba[y, x, 2] = int(rgba[y, x, 2] * (1 - alpha) + db * alpha)

    img = PILImage.fromarray(rgba.astype(np.uint8), mode='RGBA')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=False)
    return buf.getvalue()


def get_plane_slice(volume: np.ndarray, plane: str, index: int) -> np.ndarray:
    """Extract a 2D slice from a 3D volume."""
    nz, ny, nx = volume.shape
    if plane == "axial":
        idx = max(0, min(index, nz - 1))
        return volume[idx]           # (NY, NX)
    elif plane == "sagittal":
        idx = max(0, min(index, nx - 1))
        return volume[:, :, idx]     # (NZ, NY)
    elif plane == "coronal":
        idx = max(0, min(index, ny - 1))
        return volume[:, idx, :]     # (NZ, NX)
    else:
        raise ValueError(f"Unknown plane: {plane}")


# ─── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] Ingesting DICOM data...")
    ingest_all()
    print(f"[startup] Ready. Cases: {list(case_registry.keys())}")

    # Start the filesystem watcher (if watchdog is installed)
    observer = None
    DICOM_ROOT.mkdir(exist_ok=True)
    if WATCHDOG_AVAILABLE:
        observer = Observer()
        observer.schedule(_DicomWatcher(), str(DICOM_ROOT), recursive=True)
        observer.start()
        print(f"[watcher] Watching {DICOM_ROOT} for changes...")
    else:
        print(f"[watcher] Disabled (watchdog not installed). POST /api/ingest to refresh.")

    yield

    if observer is not None:
        observer.stop()
        observer.join()
        print("[watcher] Stopped.")

app = FastAPI(title="RT Viewer API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/patients")
def list_patients():
    """Return patient index built from manifest.json files."""
    return list(patient_index.values())


@app.get("/api/cases")
def list_cases():
    result = []
    for cid, c in case_registry.items():
        ct = c["ct"]
        result.append({
            "id": cid,
            "shape": ct.get("shape", []),
            "spacing": ct.get("spacing", []),
            "thickness": ct.get("thickness", 1.0),
            "roi_count": len(c["rois"]),
            "has_dose": bool(c["dose"]),
        })
    return result


@app.get("/api/cases/{case_id:path}/metadata")
def case_metadata(case_id: str):
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    c = case_registry[case_id]
    ct = c["ct"]
    rois_summary = {
        k: {"name": v["name"], "color": v["color"],
            "slice_count": len(v["contours_by_z"])}
        for k, v in c["rois"].items()
    }
    return {
        "id": case_id,
        "shape": ct["shape"],
        "spacing": ct["spacing"],
        "thickness": ct["thickness"],
        "origin": ct["origin"],
        "window_center": ct["window_center"],
        "window_width":  ct["window_width"],
        "rois": rois_summary,
        "has_dose": bool(c["dose"]),
        "dose_max": c["dose"].get("max", 0) if c["dose"] else 0,
        "dose_min": c["dose"].get("min", 0) if c["dose"] else 0,
    }


@app.get("/api/cases/{case_id:path}/slice/{plane}/{index}")
def get_slice(
    case_id: str,
    plane: str,
    index: int,
    wc: float = None,
    ww: float = None,
    dose: bool = False,
    dose_threshold: float = 0.05,
):
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    if plane not in ("axial", "sagittal", "coronal"):
        raise HTTPException(400, "plane must be axial, sagittal, or coronal")

    c   = case_registry[case_id]
    ct  = c["ct"]
    vol = ct["volume"]

    _wc = wc if wc is not None else ct["window_center"]
    _ww = ww if ww is not None else ct["window_width"]

    ct_slice = get_plane_slice(vol, plane, index)

    dose_slice = None
    dose_max   = 1.0
    if dose and c["dose"]:
        dose_vol  = c["dose"]["dose"]
        dose_slice = get_plane_slice(dose_vol, plane, index)
        dose_max   = c["dose"]["max"]

    png_bytes = ct_slice_to_png(ct_slice, _wc, _ww, dose_slice, dose_max)
    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")


@app.get("/api/cases/{case_id:path}/structures")
def get_structures(case_id: str):
    """Return all ROI contour data."""
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    return case_registry[case_id]["rois"]


@app.get("/api/cases/{case_id:path}/structures/{plane}/{index}")
def get_structures_for_slice(case_id: str, plane: str, index: int):
    """Return contour polylines for a specific slice+plane."""
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    if plane not in ("axial", "sagittal", "coronal"):
        raise HTTPException(400, "plane must be axial, sagittal, or coronal")

    rois = case_registry[case_id]["rois"]
    ct   = case_registry[case_id]["ct"]
    result = {}

    for roi_num, roi in rois.items():
        contours_for_slice = []

        if plane == "axial":
            key = str(index)
            if key in roi["contours_by_z"]:
                contours_for_slice = roi["contours_by_z"][key]
        elif plane == "sagittal":
            # For sagittal view, project contours where x ~ index
            nx = ct["shape"][2]
            for z_key, contour_list in roi["contours_by_z"].items():
                for contour in contour_list:
                    z_idx = int(z_key)
                    # Filter points near x=index (col), return as [z, y] pairs
                    pts_near = [pt for pt in contour if abs(pt[0] - index) < 2]
                    if pts_near:
                        contours_for_slice.append([[z_idx, pt[1]] for pt in pts_near])
        elif plane == "coronal":
            # For coronal view, project contours where y ~ index
            for z_key, contour_list in roi["contours_by_z"].items():
                for contour in contour_list:
                    z_idx = int(z_key)
                    pts_near = [pt for pt in contour if abs(pt[1] - index) < 2]
                    if pts_near:
                        contours_for_slice.append([[z_idx, pt[0]] for pt in pts_near])

        if contours_for_slice:
            result[roi_num] = {
                "name":     roi["name"],
                "color":    roi["color"],
                "contours": contours_for_slice,
            }

    return result


@app.get("/api/cases/{case_id:path}/dose/stats")
def dose_stats(case_id: str):
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    d = case_registry[case_id]["dose"]
    if not d:
        raise HTTPException(404, "No dose data")
    return {"max": d["max"], "min": d["min"], "mean": d["mean"]}


@app.get("/api/cases/{case_id:path}/volume")
def get_ct_volume(case_id: str):
    """
    Stream the full CT volume as a gzip-compressed int16 binary blob.
    Layout: C-order [NZ, NY, NX], int16, little-endian.
    Use the metadata endpoint for shape/spacing/origin before reading.
    """
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    vol = case_registry[case_id]["ct"]["volume"]  # float32 HU
    # Clamp to int16 range and convert — keeps HU values exactly
    arr = np.clip(vol, -32768, 32767).astype('<i2')  # little-endian int16
    compressed = gzip.compress(arr.tobytes(), compresslevel=1)
    return Response(
        content=compressed,
        media_type="application/octet-stream",
        headers={
            "Content-Encoding": "gzip",
            "X-Volume-Shape": f"{vol.shape[0]},{vol.shape[1]},{vol.shape[2]}",
            "Access-Control-Expose-Headers": "X-Volume-Shape",
        },
    )


@app.get("/api/cases/{case_id:path}/dose/volume")
def get_dose_volume(case_id: str):
    """
    Stream the full dose volume (on CT grid) as gzip-compressed float32 binary.
    Layout: C-order [NZ, NY, NX], float32, little-endian.
    """
    if case_id not in case_registry:
        raise HTTPException(404, "Case not found")
    d = case_registry[case_id]["dose"]
    if not d:
        raise HTTPException(404, "No dose data")
    arr = d["dose"].astype('<f4')  # little-endian float32
    compressed = gzip.compress(arr.tobytes(), compresslevel=1)
    return Response(
        content=compressed,
        media_type="application/octet-stream",
        headers={
            "Content-Encoding": "gzip",
            "X-Volume-Shape": f"{arr.shape[0]},{arr.shape[1]},{arr.shape[2]}",
            "Access-Control-Expose-Headers": "X-Volume-Shape",
        },
    )


@app.post("/api/ingest")
def trigger_ingest():
    case_registry.clear()
    ingest_all()
    return {
        "cases":    list(case_registry.keys()),
        "patients": list(patient_index.keys()),
    }


@app.get("/api/events")
async def sse_events(request: Request):
    """
    Server-Sent Events stream.
    The frontend subscribes once and receives a 'patients_updated' event
    whenever the watcher detects new files and finishes re-ingesting.

    Event format:  data: {"event": "patients_updated", "patients": N, "cases": M}
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    with _sse_lock:
        _sse_subscribers.append(queue)

    async def generate():
        # Send an immediate heartbeat so the client knows the connection is live
        yield "data: {\"event\": \"connected\"}\n\n"
        try:
            while not await request.is_disconnected():
                try:
                    # Wait up to 25 s then send a keepalive comment
                    data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"   # SSE comment keeps connection open
        finally:
            with _sse_lock:
                try:
                    _sse_subscribers.remove(queue)
                except ValueError:
                    pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "cases": len(case_registry), "watching": str(DICOM_ROOT)}


if __name__ == "__main__":
    import uvicorn
    # Use 127.0.0.1 on Windows (0.0.0.0 can fail with ENOTSUP)
    host = "127.0.0.1" if __import__("sys").platform == "win32" else "0.0.0.0"
    uvicorn.run(app, host=host, port=8000)
