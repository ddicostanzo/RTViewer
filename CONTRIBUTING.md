# Contributing to RT Viewer

Thank you for taking the time to contribute. RT Viewer is a research-focused project built for medical physicists, dosimetrists, and radiation oncology researchers, and every improvement — whether a bug fix, a new clinical use case, or a better phantom dataset — makes the tool more useful for that community.

---

## Ways to Contribute

| Type | Description |
|---|---|
| **Bug reports** | Found something broken? Open an issue with reproduction steps and logs. See [Bug Reports](#bug-reports) below. |
| **Feature requests** | Missing a clinical workflow or viewer capability? Open a feature request issue and describe the use case. |
| **Pull requests** | Code contributions for fixes, new features, or documentation improvements are welcome. See [Pull Request Process](#pull-request-process). |
| **Clinical use case feedback** | Feedback from practicing medical physicists and dosimetrists on real workflow gaps is especially valued — open a discussion or issue tagged `clinical-feedback`. |
| **Phantom datasets** | Synthetic or anonymized phantom datasets that exercise edge cases (e.g., unusual dose grids, multi-arc plans, non-standard orientations) are welcome via pull request to `dicom_data/`. All phantom data must be fully de-identified and free of PHI. |

---

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/<your-org>/rt-viewer.git
cd rt-viewer
```

### 2. Install Python Dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

For development tooling (linting, testing):

```bash
pip install -r requirements-dev.txt
```

### 3. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 4. Run Both Services

**Terminal 1 — Backend (FastAPI on port 8000)**

```bash
# From repository root, with .venv activated
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend (Vite dev server on port 5000)**

```bash
cd frontend
npm run dev
```

Open `http://localhost:5000`. The frontend proxies API requests to `http://localhost:8000`.

---

## Code Style

### Python

- **Formatter:** [`black`](https://black.readthedocs.io/) — run `black .` before committing.
- **Linter:** `flake8` with the project's `.flake8` config.
- **Type hints:** Encouraged on all public functions and API route handlers. Use `mypy` for type checking where practical.
- **Docstrings:** NumPy-style docstrings for public functions and classes.

### TypeScript / React

- **Linter:** ESLint with the project's `.eslintrc` config — run `npm run lint` before committing.
- **Strict mode:** TypeScript `strict: true` is enabled in `tsconfig.json`. Do not disable it.
- **Formatting:** Prettier is configured via `.prettierrc`. Run `npm run format` before committing.
- **No `any`:** Avoid `any` types; prefer explicit typing or `unknown` with narrowing.

### General

- **No secrets in commits — ever.** Do not commit API keys, tokens, passwords, or credentials of any kind. Use environment variables or `.env` files (which are gitignored).
- **No PHI in commits — ever.** Do not commit real patient data, real DICOM files, or any information that could identify a patient. Use the provided phantom data (`HN_PHANTOM_001`) or a fully synthetic dataset for all development and reproduction cases. See [PHI Policy](#phi-policy).

---

## Pull Request Process

1. **Branch from `main`.**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/your-feature-name
   ```
   Use a descriptive branch name: `fix/dose-overlay-colormap`, `feat/sagittal-zoom`, `docs/security-hardening`.

2. **Write descriptive commits.** Follow [Conventional Commits](https://www.conventionalcommits.org/) style where practical (`fix:`, `feat:`, `docs:`, `refactor:`, `test:`).

3. **Add tests where applicable.** Python unit tests live in `tests/` and run with `pytest`. Frontend tests use Vitest. New backend API routes and data-parsing logic should have accompanying tests.

4. **Run linting and formatting** before pushing:
   ```bash
   # Python
   black .
   flake8 .

   # Frontend
   cd frontend && npm run lint && npm run format
   ```

5. **Open a pull request against `main`.** Fill out the PR template:
   - What does this change do?
   - Is there a related issue? (`Closes #<issue-number>`)
   - How was it tested?
   - Any clinical or data-format considerations?

6. **One reviewer required.** PRs require at least one approving review before merge. Maintainers aim to review within 5 business days.

7. **Do not squash merge with unrelated changes.** Keep the commit history clean and meaningful.

---

## Bug Reports

Good bug reports dramatically reduce the time needed to diagnose and fix issues. Please include:

| Field | Details |
|---|---|
| **Operating system** | e.g., Windows 11 22H2, Ubuntu 22.04 |
| **Python version** | Output of `python --version` |
| **Node version** | Output of `node --version` |
| **RT Viewer version / commit** | Git tag or commit SHA |
| **Backend logs** | Full contents of the relevant log file from the `logs/` directory |
| **Steps to reproduce** | Numbered, minimal steps to reproduce the issue |
| **Expected behavior** | What should happen |
| **Actual behavior** | What actually happens, including any error messages or stack traces |
| **Dataset** | Which dataset triggers the issue (use phantom data if at all possible; do not attach real patient data) |

Use the **Bug Report** issue template, which prompts for these fields.

---

## Clinical Feedback

Feedback from medical physicists and dosimetrists on clinical workflows is especially valued. If a viewer layout, colormap, window/level default, or contour rendering behavior does not match expectations from a clinical TPS (e.g., Eclipse, Pinnacle, Monaco), please open an issue tagged `clinical-feedback` and describe:

- The clinical workflow or review task
- What RT Viewer currently does
- What the expected behavior is (with reference to the TPS or clinical standard if applicable)

This kind of feedback directly shapes prioritization.

---

## PHI Policy

> [!CAUTION]
> **No PHI or real patient data in issues, pull requests, or discussions — ever.**
>
> This applies to:
> - DICOM files or exports from real patients
> - Screenshots showing real patient names, MRNs, or dates of birth
> - Log files containing patient identifiers
> - Any data that could reasonably identify a patient
>
> Use **HN_PHANTOM_001** or another fully synthetic dataset for all reproduction cases. If a bug cannot be reproduced with phantom data, describe the dataset characteristics (image dimensions, dose grid size, number of structures) without including the data itself.
>
> Violations may result in immediate closure of the issue or PR without further review.

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, all contributors are expected to uphold these standards. Instances of unacceptable behavior may be reported to the project maintainers.

---

## License

By contributing to RT Viewer, contributors agree that their contributions will be licensed under the [MIT License](LICENSE).
