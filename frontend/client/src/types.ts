export interface CaseSummary {
  id: string;
  shape: [number, number, number];  // [nz, ny, nx]
  spacing: [number, number];
  thickness: number;
  roi_count: number;
  has_dose: boolean;
}

export interface ROISummary {
  name: string;
  color: [number, number, number];
  slice_count: number;
}

export interface CaseMetadata {
  id: string;
  shape: [number, number, number];
  spacing: [number, number];
  thickness: number;
  origin: [number, number, number];
  window_center: number;
  window_width: number;
  rois: Record<string, ROISummary>;
  has_dose: boolean;
  dose_max: number;
  dose_min: number;
}

export interface ContourData {
  name: string;
  color: [number, number, number];
  contours: number[][][];
}

export type StructureSliceResponse = Record<string, ContourData>;

export type Plane = "axial" | "sagittal" | "coronal";

// ── Patient index (from manifest.json files) ────────────────────────────────

export interface PatientCaseEntry {
  case_id: string;        // viewer case ID (relative path in dicom_data)
  case_name: string;      // RayStation case name
  plan_name: string;      // RayStation plan name
  exam_name: string;
  beamset_labels: string[];
  dose_type: string;
  exported_at: string;    // ISO timestamp
}

export interface PatientRecord {
  patient_id: string;
  patient_name: string;
  cases: PatientCaseEntry[];
}
