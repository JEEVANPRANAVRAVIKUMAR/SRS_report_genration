# SRS Solar Daily Log - Operations & Maintenance Manual

This operations guide covers daily routine workflows, backup and restore procedures, monthly lifecycle operations, health monitoring, and disaster recovery for **M/s. SRS KUMARAN INDIA PVT LTD (1 MW)** at Sunpro Antichettipalayam, Tamil Nadu.

---

## 1. Daily Operator Routine

1. **Obtain Daily Generation Report**:
   - Receive the daily Sunpro plant generation report image (via WhatsApp or physical photograph).
2. **Ingest / Share to App**:
   - Open **SRS Solar Log** on mobile or PC browser (`http://localhost:8000`).
   - Tap **Upload**, select the image or photograph directly with the camera.
   - *Android Chrome*: Use native Share Target to share image directly from WhatsApp into the app.
3. **Review & Confirm (Accuracy over Automation)**:
   - Check the cropped evidence image displaying the **SRS KUMARAN** row (Serial 5, 1 MW).
   - Review extracted numbers: Date, Inverter Generation (kWh), Monthly Plant Total, EB Export, and 6am-10am.
   - Verify the prospective effect on monthly running totals and missing days list.
   - Check proposed weather remark (e.g., `Sunny, 35°C`); if plant weather reports a mismatch, resolve via the mismatch chip.
   - Tap **Accept Reading**.
   - After acceptance:
     - Excel annual workbook (`SRS_Kumaran_Generation_YYYY.xlsx`) is rebuilt atomically.
     - Full incoming report image is purged from cache.

---

## 2. Backup & Restore Procedures (SPEC B14, AC-19)

### Automatic Nightly Backup
* Scheduled automatically at **02:00 IST** every night via APScheduler.
* Generates a consistent copy of the SQLite database (`srs_solar.db`) using the SQLite Online Backup API (zero lockups, crash-safe).
* Copies all annual Excel workbooks and monthly PDF reports into `data/backups/YYYY-MM-DD_HHMMSS/`.
* Computes and writes `manifest.json` containing SHA-256 checksums of every file.
* Automatically prunes backups older than **30 days** (`keep_days = 30`).

### Manual Backup via CLI
```bash
# Create an on-demand manual backup
python -m app.cli backup --label pre_maintenance --actor-label "Admin"
```

### Restore Procedure (AC-19 Verified)
In case of hardware failure or database corruption:
```bash
# 1. List available backups
python -m app.cli list-backups

# 2. Restore from a specific backup directory
python -m app.cli restore --from 2026-06-01_020000_nightly --reason "Disaster recovery restore"
```
The restore command:
- Restores `srs_solar.db`, `workbooks/`, and `reports/`.
- Verifies SHA-256 checksums against `manifest.json`.
- Logs the restoration event and reason in the audit log.

---

## 3. Month Lifecycle & Scheduler Operations (SPEC B10)

### Automated Schedule (Asia/Kolkata)
* **00:05 IST on 1st of Month**: Previous month is transitioned from `OPEN` to `CLOSED`.
  - Finalizes provisional weather data.
  - Rebuilds the annual Excel workbook.
  - Issues official PDF Revision 1.
  - Automatically copies the PDF to `EXPORT_COPY_DIR` (e.g., plant PC Documents).
  - Initializes the new month's sheet in the workbook.
  - Dispatches `'May 2026 PDF ready'` in-app download banner.
* **Days 1 to 3 (Grace Period)**:
  - Operators can still enter or correct readings for the closed month.
  - Rapid bursts of changes are held in a 2-minute debounce queue; upon flush, consolidated PDF Revision 2+ is generated.
* **End of Day 3 (23:59:59 IST on 3rd)**:
  - Month becomes `LOCKED`.
  - Operator edits are blocked.
  - Admin edits require a written reason, issuing a revision marked `'post-lock amendment'`.

### Startup Catch-Up (Offline Computer Recovery)
* If the plant PC or server was powered off during the 1st of the month, the app automatically executes `run_catchup_at_startup()` when booted.
* Closes the month, generates Revision 1, and records `'late close'` in the audit log and job history.

### Admin Controls CLI
```bash
# Close a month immediately
python -m app.cli close-month --ym 2026-05 --reason "Manual administrative close"

# Reopen a closed or locked month (written reason mandatory)
python -m app.cli reopen-month --ym 2026-05 --reason "Late billing adjustment from TANGEDCO"

# Regenerate official PDF revision
python -m app.cli regenerate-pdf --ym 2026-05
```

---

## 4. Operational Health Monitoring (/healthz)

Access the live health endpoint:
```bash
curl http://localhost:8000/healthz
```
Response format:
```json
{
  "status": "HEALTHY",
  "database": "CONNECTED",
  "db_size_mb": 0.45,
  "free_disk_gb": 128.4,
  "scheduler": "ALIVE",
  "timezone": "Asia/Kolkata",
  "timestamp": "2026-06-01T10:00:00+05:30"
}
```

---

## 5. Troubleshooting & FAQ

| Problem | Cause | Solution |
|---|---|---|
| **Weather Pending** remark shown on review | Open-Meteo API unreachable or network offline | Expected resilience behavior. Reading is saved safely; background job retries hourly for 3 days and updates automatically once online. |
| **EB / Inverter multiple of 12 warning** | Meter pulse calculation mismatch | Confirm reading against physical EB meter image. Operator can confirm or Admin can override. |
| **Month is LOCKED error** | Attempting to edit a reading after grace period (day 4+) | Log in as Admin and provide a written reason to issue a `'post-lock amendment'` revision. |
| **Database file locked (SQLite busy)** | Multiple concurrent write attempts | SQLite WAL mode is enabled. Wait 1 second and retry; file operations are atomic. |
