# RT Viewer

**A lightweight radiation therapy DICOM viewer for research and clinical review.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Node 18+](https://img.shields.io/badge/node-18%2B-green.svg)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Platform: Windows | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)](#)

> [!WARNING]
> **Research and review use only.** RT Viewer is **not FDA-cleared** and is **not intended for clinical treatment decisions**. It must not be used as the primary basis for any treatment planning, dose verification, or clinical workflow where patient safety depends on the output. See [Disclaimer](#disclaimer) for full details.

---

## Screenshots

> Screenshots are located in [`/docs/screenshots/`](docs/screenshots/).

---

## Features

- **WebGL GPU-rendered MPR viewer** — axial, sagittal, and coronal reconstructions rendered in real time via WebGL; no server-side image generation
- **Dose wash overlay** — semi-transparent colorwash rendered over CT, with configurable colormap and opacity
- **Structure contour overlays** — RTStruct contours drawn per-slice over the MPR viewport, color-coded per structure
- **RayStation numpy API integration** — exports CT, RTStruct, and RTDose directly from RayStation as numpy arrays via the CPython scripting API; no intermediate DICOM export required
- **Live file watcher** — watchdog-based backend monitors `dicom_data/` and pushes updates to the frontend over Server-Sent Events (SSE)
- **Patient list with MRN search** — sidebar lists all loaded patients, filterable by MRN
- **System tray launcher** — Windows `.exe` built with PyInstaller launches both services from the system tray with a single click
- **Phantom test data included** — `HN_PHANTOM_001` (H&N carcinoma, 8 structures, VMAT 66 Gy, 90 axial slices) ships with the repository for immediate testing

---

## Architecture Overview

RT Viewer uses a two-service architecture:

| Service | Technology | Default Port | Role |
|---|---|---|---|
| **Backend API** | Python / FastAPI | `8000` | Serves patient data, geometry, dose volumes; runs the file watcher |
| **Frontend** | React + TypeScript / WebGL | `5000` | Renders MPR viewports, dose overlays, structure contours |

### Data Flow

```
RayStation (CPython API)
        │
        │  raystation_export.py
        ▼
  dicom_data/
  ├── <patient_id>/
  │   ├── ct_volume.npz
  │   ├── ct_geometry.json
  │   ├── structures.json
  │   ├── dose_<planname>.npz
  │   └── manifest.json
        │
        │  FastAPI (port 8000)
        │  watchdog SSE push on file change
        ▼
  React + WebGL Frontend (port 5000)
```

Standard DICOM `.dcm` files placed in `dicom_data/` are also supported and parsed by the backend directly without any pre-export step.

---

## Quick Start

### Path 1 — Development Mode (two terminals)

**Terminal 1 — Backend**

```bash
# Clone the repository
git clone https://github.com/<your-org>/rt-viewer.git
cd rt-viewer

# Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Start the FastAPI backend
python api_server.py
```

**Terminal 2 — Frontend**

```bash
cd rt-viewer/frontend

npm install
npm run dev
# Vite dev server starts on http://localhost:5000
```

Open `http://localhost:5000` in a browser.

---

### Path 2 — Standalone EXE (Windows)

The `build_exe.bat` script uses PyInstaller to bundle the backend and the `pystray` system tray launcher into a single Windows executable.

```bat
# From the repository root (with .venv activated):
build_exe.bat
```

The output is placed in `dist/RTViewer/RTViewer.exe`. Double-click to launch — both services start automatically and an RT Viewer icon appears in the system tray. Right-click the tray icon to open the viewer or quit.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Required |
| Node.js | 18+ | Required for frontend |
| pip packages | see `requirements.txt` | `fastapi`, `uvicorn`, `numpy`, `pydicom`, `scipy` |
| `watchdog` | optional | Required for live file-watch updates |
| `pystray` | optional | Required for system tray launcher |
| `Pillow` | optional | Required by `pystray` for tray icon rendering |
| RayStation | v2024B+ or v2025 | Required only for RayStation direct export |

---

## Project Structure

```
rt-viewer/
├── api_server.py            # FastAPI application entry point
├── launcher.py              # pystray system tray launcher; starts both services
├── raystation_export.py     # RayStation CPython scripting API export script
├── launcher.spec            # PyInstaller spec file for EXE build
├── build_exe.bat            # One-click Windows EXE build script
├── requirements.txt
│
├── frontend/                # React + TypeScript + WebGL frontend
│   ├── src/
│   │   ├── components/      # MPR viewport, dose overlay, structure panel
│   │   ├── hooks/           # SSE hook, data-fetching hooks
│   │   └── shaders/         # WebGL GLSL shaders
│   ├── package.json
│   └── vite.config.ts
│
├── dicom_data/              # Patient data directory (gitignored)
│   └── HN_PHANTOM_001/      # Included test phantom
│       ├── ct_volume.npz
│       ├── ct_geometry.json
│       ├── structures.json
│       ├── dose_VMAT_66Gy.npz
│       └── manifest.json
│
├── logs/                    # Backend log output (gitignored)
├── docs/
│   └── screenshots/         # Application screenshots
└── tests/                   # Python and frontend test suites
```

---

## RayStation Integration

`raystation_export.py` uses the RayStation CPython scripting API to export treatment plan data directly as numpy arrays — no DICOM export step is required.

### Supported Versions

- RayStation **v2024B**
- RayStation **v2025**

Older versions may work but are not tested.

### How to Run

1. Open the relevant patient and plan in RayStation.
2. Open the RayStation scripting console (**Tools → Scripting**).
3. Run `raystation_export.py` from the scripting console, or configure it as an automation script.

```python
# Example: run from the RayStation scripting console
exec(open(r"C:\path\to\rt-viewer\raystation_export.py").read())
```

### What It Does

| Step | Action |
|---|---|
| 1 | Reads the current patient, case, and plan from the RayStation object model |
| 2 | Extracts the CT image series as a 3-D numpy array |
| 3 | Reads RT structure set ROI geometries and serializes contours to JSON |
| 4 | Extracts the dose matrix as a numpy array |
| 5 | Writes `ct_volume.npz`, `ct_geometry.json`, `structures.json`, `dose_<planname>.npz`, and `manifest.json` to `dicom_data/<patient_id>/` |

The watchdog file watcher detects the new files and automatically pushes an update to any open browser sessions via SSE.

---

## Data Formats

### Native `.npz` + JSON Format

This is the primary format produced by `raystation_export.py`.

| File | Contents |
|---|---|
| `ct_volume.npz` | 3-D HU array, shape `(slices, rows, cols)`, dtype `int16` |
| `ct_geometry.json` | Image position, pixel spacing, slice thickness, orientation cosines, SOP UIDs |
| `structures.json` | Array of ROI objects: name, color, contour points per slice (mm coordinates) |
| `dose_<planname>.npz` | 3-D dose array in Gy, plus dose grid geometry |
| `manifest.json` | Patient ID, name, plan name, export timestamp, file listing |

### DICOM Fallback

Standard DICOM `.dcm` files placed in `dicom_data/<patient_id>/` are parsed directly by the backend using `pydicom`. CT series, RTStruct, and RTDose modalities are all supported. No pre-processing is required.

---

## Test Phantom

The repository includes **HN_PHANTOM_001**, a synthetic head-and-neck phantom for immediate testing without real patient data.

| Property | Value |
|---|---|
| Site | Head & Neck (carcinoma) |
| Structures | 8 ROIs (PTV, brainstem, spinal cord, parotids, mandible, body) |
| Plan | VMAT, 66 Gy prescription |
| CT slices | 90 axial slices |
| Format | Native `.npz` + JSON |

Load it by selecting **HN_PHANTOM_001** from the patient list after starting the application.

---

## Disclaimer

> [!CAUTION]
> **RT Viewer is intended for research and educational review only.**
>
> - RT Viewer is **not FDA 510(k)-cleared** or otherwise approved as a medical device.
> - RT Viewer must **not** be used as the basis for clinical treatment decisions, dose prescription, plan approval, or any other patient-safety-critical workflow.
> - Dose and structure data displayed in RT Viewer may differ from values in the clinical treatment planning system due to interpolation, resampling, or export processing.
> - The authors and contributors accept no liability for clinical misuse.
>
> Users are solely responsible for ensuring that any use of RT Viewer complies with applicable laws, regulations, and institutional policies.

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style guidelines, and the pull request process.

---

## Security

RT Viewer's API has no authentication layer and should not be exposed to the public internet. See [SECURITY.md](SECURITY.md) for PHI handling guidance, known limitations, and deployment hardening recommendations.

---

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
