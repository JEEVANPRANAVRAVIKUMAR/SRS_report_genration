# SRS Solar Daily Log

> Dedicated Daily Generation Logger and Automated Report Generator for **M/s. SRS KUMARAN INDIA PVT LTD (1 MW)**, supplied by the **Sunpro Renewable Energy Private Limited 10 MW** solar power plant at Antichettipalayam, Tamil Nadu (Lat: 10.851319, Lon: 77.909541, Zone: Asia/Kolkata).

---

## 🔒 Privacy & AI Vision Notice (SPEC Section B13)

* **Image Processing & Privacy Notice**:
  When you upload or share a generation report image, the image is processed using the configured Google Gemini Vision API (`gemini-2.5-flash`) exclusively to locate and extract the **SRS KUMARAN** row (Serial 5, 1 MW).
  - All other customer figures on the sheet (Aaurvin, Prabhu, Jayaramm, Ganeshaa, Ranga) are discarded and never persisted, logged, or displayed.
  - The full incoming image is stored only temporarily during extraction and is **permanently purged** from disk immediately upon review.
* **How to Switch to Manual-Only Mode (Zero Cloud Vision)**:
  If you do not wish to use external AI vision services, you can operate entirely offline:
  1. Simply leave `GEMINI_API_KEY` unset or empty in your `.env` file.
  2. Use the **+ Manual Day** button on the **Month View** screen or the manual CLI command:
     ```bash
     python -m app.cli import-csv seed/may_2026.csv
     ```
  All reports, Excel workbooks, PDF exports, and database features function identically in manual entry mode.

---

## ⚡ 10-Minute Quickstart

### Prerequisites
* Python 3.10 or newer (tested on Python 3.11)
* Git

### 1. Clone & Setup
```bash
git clone https://github.com/JEEVANPRANAVRAVIKUMAR/SRS_report_genration.git
cd SRS_report_genration

# Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -e .
```

### 2. Configure Environment
```bash
# Copy template
cp .env.example .env
```
Edit `.env` as desired:
```ini
APP_ENV=development
SECRET_KEY=srs-solar-insecure-secret-key-change-me
DATABASE_URL=sqlite:///data/srs_solar.db
GEMINI_API_KEY=your_gemini_api_key_here
OPEN_METEO_API_KEY=
CLOSE_TIME=00:05
GRACE_DAYS=3
```

### 3. Initialize Database & Admin
```bash
# Initialize schema and seed customer / plant records
python -m app.cli init-db

# Create an Admin account
python -m app.cli create-admin --username admin --secret "admin123" --actor-label "Plant Admin"

# Import historical seed data (May 1-18)
python -m app.cli import-csv seed/may_2026.csv
```

### 4. Run the Application
```bash
# Start web server on http://localhost:8000
python -m app.web.app

# Or on Windows:
run.bat

# Or via Docker:
docker compose up -d
```

Open `http://localhost:8000` in your browser.

---

## 📱 Mobile-First PWA & WhatsApp Share Target

* **Install to Home Screen**:
  - **Android (Chrome)**: Tap the browser menu `⋮` $\rightarrow$ **Install App** or **Add to Home screen**.
  - **iPhone (Safari)**: Tap the Share button $\rightarrow$ **Add to Home Screen**.
* **WhatsApp Share Target (Android)**:
  - When the daily generation report image arrives on WhatsApp, tap **Share** on the image and pick **SRS Solar Log**. The image will open directly in the Review screen with the SRS row extracted and ready for confirmation.

---

## 🛠️ CLI Operations Reference

```bash
# Initialize database schema
python -m app.cli init-db

# Import historical generation CSV
python -m app.cli import-csv seed/may_2026.csv

# Fetch live Open-Meteo weather for date
python -m app.cli fetch-weather 2026-05-18

# Close month manually (Admin)
python -m app.cli close-month --ym 2026-05 --reason "Manual close"

# Reopen closed or locked month (Admin, reason mandatory)
python -m app.cli reopen-month --ym 2026-05 --reason "Late billing reconciliation"

# Regenerate official PDF revision
python -m app.cli regenerate-pdf --ym 2026-05

# Create on-demand backup
python -m app.cli backup --label manual

# Restore from backup
python -m app.cli restore --from 2026-06-01_020000_nightly
```

---

## 🧪 Running Automated Unit Tests

Run the complete self-contained acceptance test runner:
```bash
python run_tests.py
```
This executes all 23 acceptance suites verifying:
- **AC-01**: Gemini structured extraction & Prabhu row exclusion
- **AC-02**: Seed import reconciliation on 18 May
- **AC-03 & AC-04**: 22 May missing day gap calculations
- **AC-05**: Duplicate blocking and revision diff replacement
- **AC-06**: Pixel-perfect PDF layout matching golden May 1-18 sample
- **AC-07**: Month close at 00:05 IST on 1st & idempotency
- **AC-08**: Grace period late entries with 2-minute debounce & Rev 2
- **AC-09**: Offline startup catch-up & `'late close'` audit entry
- **AC-10**: Month locking on day 4 & post-lock amendment
- **AC-11**: UTC clock conversion accuracy
- **AC-12**: Weather service outage resilience & 7-day finalization
- **AC-13**: Rejection of corrupted, future, or oversized files
- **AC-14**: Full coverage of B6 validation rules 1 through 12
- **AC-15**: Search for other customer names across DB, logs, and files
- **AC-16**: Excel formula injection escaping & atomic write crash-safety
- **AC-17**: Leap year calendar row counts (Feb 2027, Feb 2028, Apr, May)
- **AC-18**: IMD weather classification boundaries
- **AC-19**: Backup & restore round-trip reproducing identical SHA-256 hashes
- **AC-20**: CSRF protection & role-based access control matrix
