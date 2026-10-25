# SRS Solar Daily Log

A daily generation logger, validation engine, and reporting system for **M/s. SRS KUMARAN INDIA PVT LTD (1 MW)**, supplied by the Sunpro Renewable Energy Private Limited 10 MW solar power plant at Antichettipalayam, Tamil Nadu (Asia/Kolkata timezone).

---

## Key Features

1. **Strict Privacy by Design**:
   - Ingests multi-customer Sunpro daily report images, extracts only the SRS Kumaran row, and immediately purges the full uploaded image from disk.
   - Zero leakage of other customers' figures or identities across database tables, logs, Excel sheets, and PDFs.
2. **Injected Clock & Timezone Isolation**:
   - Pinned strictly to `Asia/Kolkata`.
   - The record date always comes from the report image itself, never from the system clock.
3. **Pure Domain Logic & Rules Engine**:
   - Implements all 12 validation rules from the specification (power ceiling checks, EB/inverter ratios, multiples of 12, availability and fault alerts, and missing date gap detection).
4. **Automated Report Generation**:
   - **Excel**: Generates annual workbooks (`SRS_Kumaran_Generation_YYYY.xlsx`) with Calibri 11 styling, `#DDEBF7` banding, thin `#5B9BD5` grid lines, and formula injection escaping.
   - **PDF**: Single-page A4 monthly reports matching official layouts without page overflow or stray marks.
   - **Crash-Resilient Atomic Writes**: Output files are written to temporary files, synced to disk, and atomically replaced (`os.replace`).
5. **Human-in-the-Loop Review Screen**:
   - Side-by-side evidence crop verification with prospective effect previews before acceptance.
   - Field-by-field diff comparison and versioned revision tracking on replacement.

---

## Quick Setup

### 1. Requirements
- Python 3.10+
- Virtual environment recommended

### 2. Installation
```bash
git clone https://github.com/JEEVANPRANAVRAVIKUMAR/SRS_report_genration.git
cd SRS_report_genration
pip install -e .
```

### 3. Initialize Database & Seeds
```bash
python -m app.cli init-db
python -m app.cli import-csv seed/may_2026.csv
```

### 4. Run Unit & Acceptance Tests
```bash
python run_tests.py
```

---

## Repository Structure

```text
srs-solar-log/
  ├── app/
  │   ├── domain/       # Pure models, totals, validation rules, weather remarks
  │   ├── infra/        # Database models, injected clock, settings, audit logging, security
  │   ├── services/     # Extraction, crop pipeline, review screen, reports (excel, pdf)
  │   └── cli.py        # CLI interface (init-db, create-admin, import-csv, process-image)
  ├── docs/
  │   └── SPEC.md       # Complete system specification
  ├── seed/
  │   └── may_2026.csv  # Historical generation records (May 1-18, 2026)
  ├── tests/
  │   ├── golden/       # Reference sample PDF and report images
  │   └── unit/         # Unit and Acceptance Criteria test suites (AC-01 through AC-18)
  ├── pyproject.toml
  ├── run_tests.py
  └── README.md
```
