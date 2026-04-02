"""
RayStation RT Viewer Export Script  (numpy / direct API version)
================================================================
Run from within RayStation via Script tab → Run Script (CPython).

This script does NOT use DICOM export. It reads data directly from
RayStation's in-memory API as numpy arrays and writes them to the
cache folder in the binary formats the viewer backend already reads:

  <CACHE_ROOT>/<PatientID>/<CaseName>/<PlanName>/
      ct_volume.npz         -- int16 HU, shape (NZ,NY,NX)
      ct_geometry.json      -- origin, spacing, orientation
      dose_volume.npz       -- float32 cGy, shape (NZ,NY,NX), on dose grid
      dose_geometry.json    -- dose grid origin, spacing
      structures.json       -- ROI contours in patient coords (mm)
      manifest.json         -- metadata for the patient list

The backend reads these files at startup / on ingest and serves them
to the viewer frontend — no DICOM parsing involved.

Requires: numpy (standard in RayStation CPython 3.x)
"""

import os
import sys
import json
import datetime
import numpy as np

# ── RayStation API connection ─────────────────────────────────────────────────
try:
    from raystation import v2025 as rs_api
    patient_db = rs_api.get_current_patient_db()
except Exception:
    try:
        import connect
        patient_db = connect.get_current_patient_db()
    except Exception as e:
        print(f"[ERROR] Could not connect to RayStation API: {e}")
        sys.exit(1)

# ── WPF UI imports ────────────────────────────────────────────────────────────
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
from System.Windows.Forms import (
    Form, Label, TextBox, Button, ComboBox, CheckedListBox,
    DialogResult, FormBorderStyle, MessageBox, MessageBoxButtons,
    MessageBoxIcon, FormStartPosition, SelectionMode
)
from System.Drawing import Size, Point, Font, FontStyle, Color

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
CACHE_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "dicom_data"
)
# ─────────────────────────────────────────────────────────────────────────────


# ─── UI helpers ───────────────────────────────────────────────────────────────

def lbl(text, x, y, w=160, h=20, bold=False):
    l = Label()
    l.Text = text
    l.Location = Point(x, y)
    l.Size = Size(w, h)
    if bold:
        l.Font = Font("Segoe UI", 9, FontStyle.Bold)
    return l

def combo(x, y, w=340):
    c = ComboBox()
    c.Location = Point(x, y)
    c.Size = Size(w, 24)
    c.DropDownStyle = c.DropDownStyle.DropDownList
    return c

def safe_name(s):
    return "".join(c for c in str(s) if c.isalnum() or c in "._- ").strip().replace(" ", "_")


# ─── Step 1: MRN lookup ──────────────────────────────────────────────────────

def query_patient():
    form = Form()
    form.Text = "RT Viewer Export — Patient Search"
    form.Size = Size(460, 210)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterScreen
    form.MaximizeBox = False

    form.Controls.Add(lbl("Patient MRN (ID):", 16, 18, 160, 20, bold=True))
    txt = TextBox()
    txt.Location = Point(16, 42)
    txt.Size = Size(240, 24)
    try:
        import connect
        current = connect.get_current("Patient")
        txt.Text = current.PatientID
    except Exception:
        pass
    form.Controls.Add(txt)

    hint = Label()
    hint.Text = "Leave blank to list all (slow on large databases)"
    hint.Location = Point(16, 70)
    hint.Size = Size(420, 18)
    hint.ForeColor = Color.Gray
    form.Controls.Add(hint)

    btn_ok = Button(); btn_ok.Text = "Search"; btn_ok.Location = Point(16, 100)
    btn_ok.Size = Size(90, 30); btn_ok.DialogResult = DialogResult.OK
    form.AcceptButton = btn_ok; form.Controls.Add(btn_ok)

    btn_cancel = Button(); btn_cancel.Text = "Cancel"; btn_cancel.Location = Point(116, 100)
    btn_cancel.Size = Size(90, 30); btn_cancel.DialogResult = DialogResult.Cancel
    form.CancelButton = btn_cancel; form.Controls.Add(btn_cancel)

    if form.ShowDialog() != DialogResult.OK:
        return None

    mrn = txt.Text.strip()
    filt = {"PatientId": mrn} if mrn else {}
    try:
        infos = patient_db.QueryPatientInfo(Filter=filt)
    except Exception as e:
        MessageBox.Show(f"Query failed:\n{e}", "Error",
                        MessageBoxButtons.OK, MessageBoxIcon.Error)
        return None

    if not infos:
        MessageBox.Show(f"No patients found for '{mrn}'", "Not Found",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning)
        return None
    return infos


# ─── Step 2: Patient picker ──────────────────────────────────────────────────

def pick_patient(infos):
    if len(infos) == 1:
        return infos[0]

    form = Form()
    form.Text = "Select Patient"
    form.Size = Size(500, 340)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterScreen

    form.Controls.Add(lbl(f"{len(infos)} patients found — select one:", 16, 12, 460, 20, bold=True))

    lb = CheckedListBox()
    lb.Location = Point(16, 36); lb.Size = Size(460, 220)
    lb.SelectionMode = SelectionMode.One
    for pi in infos:
        lb.Items.Add(f"{pi.get('PatientID', '')}  —  {pi.get('Name', pi.get('LastName', 'Unknown'))}")
    lb.SetSelected(0, True)
    form.Controls.Add(lb)

    btn = Button(); btn.Text = "Select"; btn.Location = Point(16, 268)
    btn.Size = Size(90, 30); btn.DialogResult = DialogResult.OK
    form.AcceptButton = btn; form.Controls.Add(btn)

    if form.ShowDialog() != DialogResult.OK or lb.SelectedIndex < 0:
        return None
    return infos[lb.SelectedIndex]


# ─── Step 3: Case / Plan / BeamSet selector ──────────────────────────────────

def pick_plan(patient_info):
    try:
        patient = patient_db.LoadPatient(PatientInfo=patient_info)
    except Exception as e:
        MessageBox.Show(f"Could not load patient:\n{e}", "Error",
                        MessageBoxButtons.OK, MessageBoxIcon.Error)
        return None

    cases = list(patient.Cases)
    if not cases:
        MessageBox.Show("No Cases found for this patient.", "No Data",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning)
        return None

    # Build tree
    tree = {}
    for case in cases:
        plans = {}
        for plan in list(case.TreatmentPlans):
            plans[plan.Name] = [bs.DicomPlanLabel for bs in list(plan.BeamSets)]
        tree[case.Name] = plans

    form = Form()
    form.Text = "RT Viewer Export — Select Plan"
    form.Size = Size(560, 460)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterScreen
    form.MaximizeBox = False

    pid   = patient_info.get("PatientID", "")
    pname = patient_info.get("Name", patient_info.get("LastName", ""))
    form.Controls.Add(lbl(f"Patient: {pid}  —  {pname}", 16, 10, 520, 20, bold=True))

    form.Controls.Add(lbl("Case:", 16, 40))
    cb_case = combo(100, 38)
    for c in tree: cb_case.Items.Add(c)
    cb_case.SelectedIndex = 0
    form.Controls.Add(cb_case)

    form.Controls.Add(lbl("Plan:", 16, 76))
    cb_plan = combo(100, 74)
    form.Controls.Add(cb_plan)

    form.Controls.Add(lbl("BeamSets:", 16, 114, 80, 20, bold=True))
    form.Controls.Add(lbl("(check all to export)", 100, 116, 260, 18))

    clb = CheckedListBox()
    clb.Location = Point(16, 138); clb.Size = Size(516, 180); clb.CheckOnClick = True
    form.Controls.Add(clb)

    def on_case(s, e):
        cb_plan.Items.Clear()
        for p in tree.get(str(cb_case.SelectedItem), {}): cb_plan.Items.Add(p)
        if cb_plan.Items.Count > 0: cb_plan.SelectedIndex = 0

    def on_plan(s, e):
        clb.Items.Clear()
        c = str(cb_case.SelectedItem) if cb_case.SelectedItem else ""
        p = str(cb_plan.SelectedItem) if cb_plan.SelectedItem else ""
        for bs in tree.get(c, {}).get(p, []):
            clb.Items.Add(bs, True)

    cb_case.SelectedIndexChanged += on_case
    cb_plan.SelectedIndexChanged += on_plan
    on_case(None, None)

    form.Controls.Add(lbl("Dose type:", 16, 332))
    cb_dose = combo(120, 330, 220)
    cb_dose.Items.Add("Physical beam set dose")
    cb_dose.Items.Add("Effective beam set dose")
    cb_dose.SelectedIndex = 0
    form.Controls.Add(cb_dose)

    btn_ok = Button(); btn_ok.Text = "Export to Viewer"
    btn_ok.Location = Point(16, 380); btn_ok.Size = Size(150, 32)
    btn_ok.DialogResult = DialogResult.OK
    form.AcceptButton = btn_ok; form.Controls.Add(btn_ok)

    btn_cancel = Button(); btn_cancel.Text = "Cancel"
    btn_cancel.Location = Point(176, 380); btn_cancel.Size = Size(90, 32)
    btn_cancel.DialogResult = DialogResult.Cancel
    form.CancelButton = btn_cancel; form.Controls.Add(btn_cancel)

    if form.ShowDialog() != DialogResult.OK:
        return None

    selected_bs = [str(clb.Items[i]) for i in range(clb.Items.Count) if clb.GetItemChecked(i)]

    return {
        "patient":        patient,
        "patient_info":   patient_info,
        "case_name":      str(cb_case.SelectedItem),
        "plan_name":      str(cb_plan.SelectedItem),
        "beamset_labels": selected_bs,
        "use_effective":  "Effective" in str(cb_dose.SelectedItem),
    }


# ─── Data extraction helpers ──────────────────────────────────────────────────

def extract_ct(exam):
    """
    Pull CT volume from RayStation API as a numpy int16 HU array.

    Returns:
        volume : np.ndarray  shape (NZ, NY, NX)  int16  HU
        geometry : dict  with origin/spacing/orientation in patient mm coords
    """
    series = list(exam.Series)
    if not series:
        raise ValueError(f"No Series found in examination '{exam.Name}'")

    stack = series[0].ImageStack

    # PixelData is (NZ, NY, NX) as a numpy array of stored values
    pixel_data = np.array(stack.PixelData)  # shape (NZ, NY, NX)

    # Geometry
    corner     = stack.Corner          # Point3[float] in mm
    col_dir    = stack.ColumnDirection # unit vector
    row_dir    = stack.RowDirection    # unit vector
    pixel_size = stack.PixelSize       # Point2[float] in mm  {x: col_mm, y: row_mm}

    # SlicePositions is an array of z-positions in mm (or None for single-slice)
    try:
        z_pos = list(stack.SlicePositions)  # list of float, mm
    except Exception:
        z_pos = [float(corner.z)]

    slice_thickness = abs(z_pos[1] - z_pos[0]) if len(z_pos) > 1 else 3.0

    # Convert stored values → HU
    # ConversionParameters is None for modern data (pixel already in HU)
    conv = getattr(stack, "ConversionParameters", None)
    if conv is not None:
        try:
            slopes     = np.array(conv.RescaleSlopes, dtype=np.float32)
            intercepts = np.array(conv.RescaleIntercepts, dtype=np.float32)
            nz = pixel_data.shape[0]
            hu = np.empty_like(pixel_data, dtype=np.float32)
            for z in range(nz):
                s = float(slopes[z]) if z < len(slopes) else 1.0
                i = float(intercepts[z]) if z < len(intercepts) else 0.0
                hu[z] = pixel_data[z].astype(np.float32) * s + i
            volume = np.clip(hu, -32768, 32767).astype(np.int16)
        except Exception:
            volume = pixel_data.astype(np.int16)
    else:
        volume = pixel_data.astype(np.int16)

    geometry = {
        "origin":          [float(corner.x), float(corner.y), float(z_pos[0])],
        "spacing":         [float(pixel_size.y), float(pixel_size.x)],   # [row_mm, col_mm]
        "thickness":       float(slice_thickness),
        "z_positions":     [float(z) for z in z_pos],
        "col_direction":   [float(col_dir.x), float(col_dir.y), float(col_dir.z)],
        "row_direction":   [float(row_dir.x), float(row_dir.y), float(row_dir.z)],
        "shape":           list(volume.shape),   # [NZ, NY, NX]
        "window_center":   40.0,
        "window_width":    400.0,
        "exam_name":       str(exam.Name),
    }
    return volume, geometry


def extract_dose(beam_set, use_effective=False):
    """
    Pull dose distribution as a numpy float32 array in Gy.

    Returns:
        dose_vol : np.ndarray  shape (NZ, NY, NX) float32 in Gy
        dose_geo : dict  with grid geometry
    """
    # Get dose distribution
    try:
        if use_effective:
            dist = beam_set.FractionDose   # effective if available
        else:
            dist = beam_set.FractionDose
    except Exception as e:
        raise ValueError(f"No dose distribution on beam set '{beam_set.DicomPlanLabel}': {e}")

    # DoseValues.DoseData is flat X-first float32 array in cGy
    try:
        raw = np.array(dist.DoseValues.DoseData, dtype=np.float32)
    except Exception as e:
        raise ValueError(f"Could not read DoseData: {e}")

    # Dose grid geometry
    grid = beam_set.GetDoseGrid()
    nx = int(grid.NrVoxels.x)
    ny = int(grid.NrVoxels.y)
    nz = int(grid.NrVoxels.z)

    # Reshape: flat array is stored X-first → shape (NZ, NY, NX)
    dose_3d = raw.reshape((nz, ny, nx))

    # Convert cGy → Gy
    dose_gy = dose_3d / 100.0

    # VoxelSize is in cm → convert to mm
    vx = float(grid.VoxelSize.x) * 10.0  # mm
    vy = float(grid.VoxelSize.y) * 10.0
    vz = float(grid.VoxelSize.z) * 10.0

    dose_geo = {
        "origin":   [float(grid.Corner.x), float(grid.Corner.y), float(grid.Corner.z)],  # mm
        "spacing":  [vy, vx],      # [row_mm, col_mm] — matching CT convention
        "thickness": vz,
        "shape":    [nz, ny, nx],
        "max_gy":   float(dose_gy.max()),
        "min_gy":   float(dose_gy[dose_gy > 0].min()) if (dose_gy > 0).any() else 0.0,
    }
    return dose_gy, dose_geo


def extract_structures(case, exam):
    """
    Pull ROI contour data from the structure set on the given examination.
    Returns a dict suitable for structures.json.
    """
    # Find structure set on this exam
    struct_set = None
    try:
        for ss in list(case.PatientModel.StructureSets):
            if ss.OnExamination.Name == exam.Name:
                struct_set = ss
                break
    except Exception:
        pass

    if struct_set is None:
        return {}

    rois_out = {}
    rois     = list(case.PatientModel.RegionsOfInterest)

    for roi in rois:
        try:
            geom = struct_set.RoiGeometries[roi.Name]
        except Exception:
            continue

        if not geom.HasContours():
            continue

        shape = geom.PrimaryShape
        if shape is None:
            continue

        # shape.Contours is array_list[list[Point3[float]]]
        try:
            contours_raw = shape.Contours
        except Exception:
            continue

        # Convert to plain Python lists
        contours_out = []
        for polygon in contours_raw:
            pts = [[float(p.x), float(p.y), float(p.z)] for p in polygon]
            if pts:
                contours_out.append(pts)

        if not contours_out:
            continue

        # ROI color
        try:
            color = roi.Color
            rgb = [int(color.R), int(color.G), int(color.B)]
        except Exception:
            rgb = [255, 255, 255]

        rois_out[roi.Name] = {
            "name":     str(roi.Name),
            "type":     str(getattr(roi, "OrganData", {}) and getattr(roi.OrganData, "OrganType", "Unknown") or "Unknown"),
            "color":    rgb,
            "contours": contours_out,   # list of polygons, each [[x,y,z], ...]
        }

    return rois_out


# ─── Main export ─────────────────────────────────────────────────────────────

def export_case(selection):
    patient      = selection["patient"]
    patient_info = selection["patient_info"]
    case_name    = selection["case_name"]
    plan_name    = selection["plan_name"]
    beamset_labels = selection["beamset_labels"]
    use_effective  = selection["use_effective"]

    patient_id   = patient_info.get("PatientID", "UNKNOWN")
    patient_name = patient_info.get("Name", patient_info.get("LastName", "Unknown"))

    case = next((c for c in patient.Cases if c.Name == case_name), None)
    if case is None:
        MessageBox.Show(f"Case '{case_name}' not found.", "Error",
                        MessageBoxButtons.OK, MessageBoxIcon.Error)
        return False

    plan = next((p for p in case.TreatmentPlans if p.Name == plan_name), None)
    if plan is None:
        MessageBox.Show(f"Plan '{plan_name}' not found.", "Error",
                        MessageBoxButtons.OK, MessageBoxIcon.Error)
        return False

    # Find the planning exam
    try:
        exam = plan.GetStructureSet().OnExamination
    except Exception:
        try:
            exam = list(case.Examinations)[0]
        except Exception as e:
            MessageBox.Show(f"Could not determine examination: {e}", "Error",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)
            return False

    # Build output directory
    export_dir = os.path.join(
        CACHE_ROOT,
        safe_name(patient_id),
        safe_name(case_name),
        safe_name(plan_name),
    )
    os.makedirs(export_dir, exist_ok=True)

    errors = []

    # ── CT ────────────────────────────────────────────────────────────────────
    print(f"[export] Extracting CT from '{exam.Name}'...")
    try:
        ct_vol, ct_geo = extract_ct(exam)
        np.savez_compressed(os.path.join(export_dir, "ct_volume.npz"), volume=ct_vol)
        with open(os.path.join(export_dir, "ct_geometry.json"), "w") as f:
            json.dump(ct_geo, f, indent=2)
        print(f"  CT: {ct_vol.shape}  HU [{ct_vol.min()}, {ct_vol.max()}]")
    except Exception as e:
        errors.append(f"CT: {e}")
        print(f"  [WARN] CT failed: {e}")

    # ── Structures ────────────────────────────────────────────────────────────
    print("[export] Extracting structures...")
    try:
        rois = extract_structures(case, exam)
        with open(os.path.join(export_dir, "structures.json"), "w") as f:
            json.dump(rois, f)
        print(f"  Structures: {len(rois)} ROIs")
    except Exception as e:
        errors.append(f"Structures: {e}")
        print(f"  [WARN] Structures failed: {e}")

    # ── Dose (for each selected beam set) ─────────────────────────────────────
    dose_exported = []
    for bs in list(plan.BeamSets):
        if beamset_labels and bs.DicomPlanLabel not in beamset_labels:
            continue
        print(f"[export] Extracting dose for beam set '{bs.DicomPlanLabel}'...")
        try:
            dose_vol, dose_geo = extract_dose(bs, use_effective)
            bs_label = safe_name(bs.DicomPlanLabel)
            np.savez_compressed(os.path.join(export_dir, f"dose_{bs_label}.npz"), dose=dose_vol)
            with open(os.path.join(export_dir, f"dose_{bs_label}_geometry.json"), "w") as f:
                json.dump(dose_geo, f, indent=2)
            dose_exported.append(bs.DicomPlanLabel)
            print(f"  Dose: {dose_vol.shape}  max={dose_geo['max_gy']:.2f} Gy")
        except Exception as e:
            errors.append(f"Dose [{bs.DicomPlanLabel}]: {e}")
            print(f"  [WARN] Dose failed: {e}")

    # ── Manifest ──────────────────────────────────────────────────────────────
    manifest = {
        "exported_at":      datetime.datetime.utcnow().isoformat() + "Z",
        "export_method":    "numpy_direct",
        "patient_id":       patient_id,
        "patient_name":     patient_name,
        "case_name":        case_name,
        "plan_name":        plan_name,
        "exam_name":        str(exam.Name),
        "beamset_labels":   dose_exported,
        "dose_type":        "effective" if use_effective else "physical",
        "viewer_case_id":   f"{safe_name(patient_id)}/{safe_name(case_name)}/{safe_name(plan_name)}",
    }
    with open(os.path.join(export_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────────
    warn_text = ("\n\nWarnings:\n" + "\n".join(errors)) if errors else ""
    MessageBox.Show(
        f"Export complete!\n\n"
        f"Patient:  {patient_id} — {patient_name}\n"
        f"Case:     {case_name}\n"
        f"Plan:     {plan_name}\n"
        f"Exam:     {exam.Name}\n"
        f"Dose BSs: {', '.join(dose_exported) or '(none)'}\n\n"
        f"Files: {export_dir}"
        + warn_text,
        "RT Viewer Export",
        MessageBoxButtons.OK,
        MessageBoxIcon.Information if not errors else MessageBoxIcon.Warning
    )
    return True


# ─── Backend api_server.py: native .npz ingest ───────────────────────────────
# The backend detects ct_volume.npz and reads it directly — no DICOM parsing.
# See: api_server.py  ingest_case_native()


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    infos = query_patient()
    if infos is None:
        return

    patient_info = pick_patient(infos)
    if patient_info is None:
        return

    selection = pick_plan(patient_info)
    if selection is None:
        return

    export_case(selection)


if __name__ == "__main__":
    main()
