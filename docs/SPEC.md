## Part B. Full specification (save as docs/SPEC.md)

### B1. Purpose, scope, non-negotiables

Build 'SRS Solar Daily Log', a native Android app (everything runs on the phone, with no server) for ONE customer: M/s. SRS KUMARAN INDIA PVT LTD (1 MW), supplied by the Sunpro Renewable Energy Private Limited 10 MW solar plant at Antichettipalayam, Tamil Nadu (latitude 10.851319, longitude 77.909541, timezone Asia/Kolkata).

**Daily loop:**

1. The operator shares to the app (from WhatsApp or the gallery), picks, or photographs the Sunpro 'DAILY GENERATION REPORT' image.


2. The app reads the report date and only the SRS KUMARAN row.


3. The operator reviews it beside a picture of the row and confirms.


4. The reading is saved and the year's Excel workbook is updated.


5. Weather for that date at the plant is fetched and an automatic remark is proposed.


6. On the 1st of each month the previous month is closed, its PDF is produced, and the new month's sheet starts.



**Non-negotiables:**

* Accuracy over automation: no reading is saved without human confirmation (a setting may relax this later).


* The record date always comes from the image, never from the system clock.


* Only SRS KUMARAN data is stored, displayed, exported or logged. No other customer's figures appear anywhere.


* Every saved number is traceable to an upload, a user and a time (audit trail).


* All monthly jobs are idempotent: running twice never duplicates or corrupts anything.


* Files are written atomically (temp file, then rename), so a crash never leaves a half-written Excel or PDF.



### B2. Lock and PIN (no accounts)

* One phone, one operator profile. There are no usernames and no server accounts.


* App lock (on by default after first run): fingerprint, face or the phone's screen lock (Android BiometricPrompt) after 2 minutes in the background.


* Admin PIN (6 digits, set at first run, stored only as a salted slow hash in Keystore-protected storage). It is required to unlock a LOCKED month, void or edit a reading in a closed month, change thresholds or the plant location, switch on the AI second opinion, and restore a backup. Every use needs a written reason, which goes into the audit log with the time. After 5 wrong tries the app waits 15 minutes, and the wait doubles each time.


* Everything else (share, review, accept, remarks, downloads) needs no PIN.


* The audit log records an actor label (the operator name set in Settings, default 'Operator') instead of a login.



### B3. Architecture and stack (defaults)

Native Android in Kotlin with Jetpack Compose (Material 3), one Activity, Navigation Compose. Minimum SDK 26 (Android 8.0). Compile and target SDK = the current stable level when you build (verify it). Gradle Kotlin DSL with a version catalog; R8 shrinking in release builds.

* **Layers:** domain is a pure Kotlin module with no Android classes (running totals, validation rules, month rules, weather classification, remark building) and needs a unit test for every rule; data holds Room, repositories, file storage and settings; services holds OCR, weather, reports, background work and backup; ui holds Compose screens and ViewModels exposing StateFlow. Hilt for dependency injection.


* **Room database** with exported schemas and tested migrations, foreign keys on.


* **Settings** in Jetpack DataStore. Secrets (optional Open-Meteo key, PIN hash) in Android Keystore-backed storage.


* **Text recognition:** Google ML Kit Text Recognition v2, Latin script, the bundled model (not the one downloaded through Play Services), so it works offline from the first launch.


* **Optional AI second opinion:** the Firebase AI Logic SDK for Android (Gemini) with App Check enforced, so no API key sits inside the app. The model name is a setting; verify the current name at build time.


* **Reports:** Excel through the library chosen in Phase PO (see B8); PDF through Android's built-in PdfDocument with the Carlito font bundled; PdfRenderer for previews and tests.


* **Background work:** WorkManager (unique one-time and periodic work); notifications through NotificationCompat.


* **Networking:** OkHttp with Retrofit (or Ktor) and kotlinx.serialization. The only destinations are Open-Meteo and, if switched on, Firebase.


* **Time:** all business logic uses the fixed zone Asia/Kolkata whatever time zone the phone is set to. An injected java.time.Clock supplies 'now'; nothing else may call now(). Dates are LocalDate; timestamps are stored as UTC epoch milliseconds.


* **Files:** master copies in the app's private storage (workbooks/YYYY/, reports/YYYY/, evidence/YYYY-MM/, backups/). Incoming images live only in cacheDir/incoming/ and are deleted after review and at every app start. Copies go to the folder the user picks through the Storage Access Framework (a persisted folder permission), which works on every Android version without storage permissions.


* **Permissions:** POST_NOTIFICATIONS (Android 13 and above, asked with an explanation) and INTERNET. Camera capture uses the system camera through a FileProvider, so no camera permission is needed. No location permission: the plant coordinates are settings.


* **Debug builds only:** a developer screen to set a fake 'today' (to rehearse the 1st of a month), load the sample data and trigger jobs by hand. It must not exist in release builds.



### B4. Data model (SQLite)

| Table | Key columns |
| --- | --- |
| plants | id, name, latitude, longitude, timezone, capacity_mw (seed: Sunpro Antichettipalayam, 10.851319, 77.909541, Asia/Kolkata, 10)

 |
| customers | id, plant_id, display_name ('M/s. SRS KUMARAN INDIA PVT LTD'), aliases (list), capacity_mw (1), is_target (true). Only the target customer is processed; the table lets another customer be added later without a rewrite.

 |
| uploads | id, sha256 (unique), evidence_path (the three-part crop only), received_via (SHARE, PICKER, CAMERA, MANUAL), received_at, status (PENDING_REVIEW, ACCEPTED, REJECTED, SUPERSEDED), engine (MLKIT, AI_SECOND_OPINION, MANUAL), parser_version, prompt_version, extraction (json, SRS fields only), validation (json)

 |
| readings | id, customer_id, report_date (unique per customer), inverter_kwh, eb_export_kwh, eb_6to10_kwh, reported_monthly_kwh, reported_yearly_kwh, inverter_availability_pct, grid_availability_pct, fault_text, plant_weather_text, plant_temp_c, manual_remark, auto_remark, source_upload_id, entry_method (IMAGE, MANUAL, IMPORT), status (ACTIVE, VOID), version, actor_label, timestamps

 |
| reading_revisions | id, reading_id, version, snapshot (json), changed_at, actor_label, reason

 |
| ocr_corrections | id, upload_id, field, recognised_value, corrected_value, at (feeds the parser improvement loop in B5)

 |
| weather_daily | id, plant_id, date, provider, quality (PROVISIONAL, FINAL), fetched_at, metrics (json), sky_class, rain_class, remark_text, raw_response (json)

 |
| months | id, customer_id, ym (for example 2026-05), status (OPEN, CLOSED, LOCKED), closed_at, locked_at, pdf_revision, workbook_path

 |
| report_files | id, month_id, kind (PDF), revision, path, sha256, created_at, exported_to_folder_at, reason (CLOSE, LATE_ENTRY, MANUAL, POST_LOCK_AMENDMENT)

 |
| job_runs | id, job_name, period (unique together), started_at, finished_at, status, message

 |
| audit_log | id, at, actor_label, action, entity, entity_id, before (json), after (json), reason

 |

Settings are not a table; they live in DataStore (see B3 and the Appendix). Running totals are never stored. They are computed from active readings in date order, so they cannot drift.

### B5. Image ingestion and extraction

**Getting an image in.** Three routes, all ending at the same Review screen:

1. Share: the app registers for ACTION_SEND and ACTION_SEND_MULTIPLE with image types, so the daily report can be shared from WhatsApp, Gallery or Files straight into the app.


2. Picker: the Android Photo Picker (no storage permission needed).


3. Camera: the system camera through a FileProvider address.



Accept JPG, PNG, WEBP and HEIC (where the phone supports it), up to 25 MB each, several at once (queued and reviewed one by one). Decode with down-sampling (longest side at most 3000 px for recognition), apply the EXIF rotation, and compute the SHA-256 of the original bytes. If that hash exists already, stop and link to the existing upload. Copy the image into cacheDir/incoming/ only; never into the gallery or public storage. Only content addresses given by the system intent are accepted, and they are copied with a size limit.

**Reading the image, on the phone, offline (Engine A, the default).** ML Kit returns text blocks, lines and elements with bounding boxes. A deterministic parser (ReportParser, versioned in parser_version, pure Kotlin so it is unit-testable) then works as follows:

1. Date: find a DD/MM/YYYY date in the top 25% of the image, preferably on the same line as 'Date'. Never take the date from anywhere else and never from the clock.


2. Row anchor: find the line with 'KUMARAN' and 'SRS' beside it. Match fuzzily (upper case, punctuation removed, one edit allowed per word) and tolerate the name being split across lines.


3. Row band: use the serial-number column (the small integers 1, 2, 3 down the left edge) and take the midpoints to the neighbouring serials as the row's top and bottom. If serials are not found, use the anchor's line height x 1.6 above and below.


4. Numbers: collect numeric tokens inside the band, left to right. Expected order: serial, MW, inverter today, monthly, yearly, grid export, 6am-10am, inverter availability %, grid availability %. Exactly 9 tokens are expected; any other count flags the row.


5. Header cross-check: find the header texts ('Inverter Generation Today', 'Monthly Generated', 'Yearly Generated', 'Grid Export', '6am TO 10am', 'Inverter Availability', 'Grid Availability') and assign each token to the nearest header centre. Where this disagrees with the order-based result, flag those fields.


6. Number cleaning: inside numeric tokens fix look-alike letters (O or o to 0, I or l to 1) and treat a comma as a decimal point only when exactly two digits follow. Format check: this report prints kWh values with exactly two decimals (7625.00), so a token without them is flagged, because that usually means a lost decimal point.


7. Fault or alarm text: any text in the row band to the right of the availability percentages; blank when none.


8. Weather and temperature: best-effort read of the 'WEATHER CONDITION' and 'TEMPERATURE' lines near the bottom. Never block on them.


9. Each field ends as OK, CHECK or FAILED, using the recogniser's confidence where the SDK provides it and otherwise the agreement between steps 4 and 5 plus the format check.



**AI second opinion (Engine B, off by default).** Only after Engine A has located the row, the app cuts out three pieces of the image: the top band with the title and date, the table header row, and the SRS row, and sends only those pixels to Gemini through Firebase AI Logic. Switching it on needs the Admin PIN and shows a one-line privacy notice. If Engine A cannot find the SRS row at all, the operator may drag a box over the row by hand and then use Engine B on that crop, or type the values. Engine B never overwrites Engine A silently: the Review screen shows both and highlights every difference. Prompt (versioned in prompt_version):

> You are reading a cropped picture from a 'DAILY GENERATION REPORT' of Sunpro Renewable Energy Private Limited.
> The picture holds the report date, the table header row and ONE customer row.
> Return only the JSON object that matches the schema.
> 
> 
> 1. Read the date as printed (DD/MM/YYYY) into date_raw.
> 
> 
> 2. Read only the customer row that is shown. Do not infer or mention any other row.
> 
> 
> 3. Copy each number exactly as printed. Remove thousands separators only. Keep decimals.
> 
> 
> 4. If a value is blurry, cut off or ambiguous, return null for it and a low confidence. Never guess or estimate.
> 
> 
> 
> 

The extraction result (the same shape from both engines, each field carrying a status and, where available, a 0 to 1 confidence): date_raw, date_iso, customer_name_raw, serial_no, capacity_mw, inverter_generation_today_kwh, monthly_generated_kwh, yearly_generated_kwh, grid_export_kwh, reading_6am_10am_kwh, inverter_availability_pct, grid_availability_pct, fault_alarm_text, weather_condition_text, temperature_c, row_bbox.

**Post-processing and safety (both engines, in code).**

* Parse the date strictly as DD/MM/YYYY and check that it is a real calendar date. If an engine's ISO date disagrees, the strict parse wins and the field is flagged.


* Match the customer name against the stored aliases ('SRS KUMARAN INDIA PVT LTD', 'SRS KUMARAN') and require capacity 1 MW. No match means rejection with a clear message.


* Every CHECK or FAILED field is highlighted, and the Accept button stays disabled until the operator has edited or ticked each highlighted field.


* Evidence: store only the three-part crop (date band, header row, SRS row, stitched in one picture, pixels unchanged). The full image is never stored. If no row was found, show the full image only as an in-memory picture inside the Review screen and discard it when the screen closes.


* Learning loop: every correction the operator makes is saved locally in ocr_corrections with the crop. Settings has 'Export corrections' (a zip) so the parser can be improved from real mistakes; it contains no other customer's pixels.


* Keep adding real images (screenshots and photos) to the golden test set as they arrive; the parser must never be tuned to one image only.



**Review screen (the core of the app).** On a phone: the zoomable row crop on top, editable fields below. On a tablet: side by side. It must show:

* Each field with its validation chip (OK, warning, error).


* The preview of the effect, for example: '22 May: Monthly Inverter Total becomes 110,690.00. Plant reports 130,428. Difference 19,738 kWh = 19, 20, 21 May not yet recorded.'


* The weather panel (once fetched) with the proposed remark and the plant-reported weather side by side.


* A manual remark box.


* Buttons: Accept, Reject (with reason), Save as draft.



**On Accept**, in one database transaction: upsert the reading, write a revision and an audit entry, mark the upload ACCEPTED. After the commit: rebuild the workbook atomically, queue the weather fetch, and (if the month is CLOSED) queue a new PDF revision.

**Rejections and blocks.** Not a Sunpro report, no SRS row, unreadable date, or a date in the future (later than today in India): block. A date more than 7 days in the past (setting BACKDATE_WARN_DAYS): allowed after the user ticks 'I am entering a past date'. A date in a LOCKED month: Admin only. Same date with a different image: show a field-by-field difference and require confirmation to replace; the old values stay in the revision history.

### B6. Validation rules

| # | Rule | Result |
| --- | --- | --- |
| 1 | Date, inverter, EB export and 6am-10am are present

 | Error

 |
| 2 | All numbers are 0 or more

 | Error

 |
| 3 | EB export is not above inverter generation

 | Error (Admin may override with a reason)

 |
| 4 | EB divided by inverter is between 0.95 and 1.00 (your May data: 0.976 to 0.988)

 | Warning

 |
| 5 | EB and 6am-10am are multiples of EB_MF (default 12, inferred from your data; set 1 to disable)

 | Warning

 |
| 6 | 6am-10am is not above EB export

 | Error

 |
| 7 | Inverter is at most 12,000 kWh (1 MW for 12 hours); above 1.3 times the best day of the last 60 days is suspicious

 | Error; Warning

 |
| 8 | Zero generation or zero export

 | Warning ('outage? add a remark')

 |
| 9 | Computed month-to-date total versus the plant's 'Monthly Generated' (tolerance 1 kWh). Plant higher: 'missing days' with the kWh gap. Computed higher: 'possible duplicate or wrong digit'

 | Info; Warning

 |
| 10 | Availability below 100% or fault text not empty

 | Warning and a prompt to add a remark; always stored

 |
| 11 | Gaps between recorded dates

 | Dashboard list of missing dates

 |
| 12 | Plant-reported temperature differs from the weather-service temperature by more than 6°C

 | Info

 |

Rule 9 is the self-check that catches missing days and mistyped digits. Every threshold is a setting, not a constant in code.

### B7. Weather and remarks

**Provider.** Open-Meteo, with the location taken from the plant record (10.851319, 77.909541) and timezone Asia/Kolkata. For dates older than 7 days use the historical archive endpoint; for the last 7 days use the forecast endpoint's past-days or date-range options. At build time the agent must read the current Open-Meteo documentation and confirm endpoint names, parameter names and limits; it must not rely on memory. If OPEN_METEO_API_KEY is set (entered in Settings and stored encrypted on the phone), use the commercial host and key. Show a notice in Settings that the free tier is for non-commercial use.

**Data to fetch (hourly, for the report date):** temperature, cloud cover, precipitation, shortwave (solar) radiation, weather code. Compute:

* Daytime window 06:00 to 18:00 IST: mean cloud cover, and total solar energy in kWh per square metre (sum of hourly W/m2 divided by 1000).


* Morning window 06:00 to 10:00 IST: mean cloud cover and solar energy. This explains the 6am-10am column.


* 24-hour rain total in mm and the day's maximum temperature.



**Quality flag.** A day is PROVISIONAL if it is within the last 7 days, or was fetched before 20:00 IST on that same day; otherwise FINAL. A nightly job refetches PROVISIONAL days. If a refreshed remark changes and the month is CLOSED, issue a new PDF revision.

**Classification (deterministic, no AI).**

| Daytime mean cloud cover | Sky wording | 24-hour rain | Wording (IMD categories) |
| --- | --- | --- | --- |
| below 20% | Sunny

 | 0.1 to 2.4 mm | Drizzle

 |
| 20% to under 50% | Partly cloudy

 | 2.5 to 15.5 mm | Light rain

 |
| 50% to under 80% | Mostly cloudy

 | 15.6 to 64.4 mm | Moderate rain

 |
| 80% or more | Overcast

 | 64.5 mm or more | Heavy rain

 |

**Remark builder.** Rain of 2.5 mm or more replaces the sky wording. Format: wording, then the rain amount if any, then the maximum temperature. At most 40 characters. Examples: 'Sunny, 35°C', 'Partly cloudy, 33°C', 'Overcast, rain 14 mm, 29°C'. Show the plant-reported weather beside it. If one says sunny and the other says overcast or rain, show a 'Weather mismatch' chip and let the operator choose.

**Performance insight (screen only, never printed).** yield_index = inverter kWh divided by solar energy in kWh/m2. Baseline = median yield_index of the last 30 clear days (cloud under 30%, no rain), and only when at least 7 such days exist. Expected kWh = baseline x the day's solar energy. Flag 'Below expected for the sunshine' when actual is under 85% of expected (possible outage, soiling or curtailment) and 'Check data' when it is above 115%. Show this on the review screen and on an Insights page. The app never writes a cause into the customer-facing PDF; the operator may copy a suggestion into the manual remark.

**Failure handling.** 10 second timeout, 3 retries with backoff. If the service is down, save the reading anyway with the remark 'Weather pending', retry hourly for 3 days, then alert the Admin. Store the raw response for audit.

**Attribution.** Show 'Weather data: Open-Meteo.com (CC BY 4.0)' on the app's About screen and in the PDF footer.

### B8. Excel workbook

* **File:** workbooks/2026/SRS_Kumaran_Generation_2026.xlsx, one per calendar year. Setting WORKBOOK_MODE is yearly (default) or monthly (one file per month).


* **Sheets:** one per month that has started or has data, named like MAY-2026 (the report layout); Year Summary (per month: days recorded, inverter total, EB total, average per day, status, PDF revision); Details (one row per day with every field: plant-reported monthly and yearly figures, availability, fault text, plant weather, weather-service figures, yield index, source upload, user, timestamps).


* **Month sheet layout (match the sample):** columns A to G with the headers 'Date', 'Inverter', 'Monthly Inverter Total', 'EB Reading', 'EB Reading Total', '6am-10am', 'Remarks'. Headers A to F are bold, wrapped and merged over two rows; G1 holds the month label ('MAY-2026') in a box and G2 holds 'Remarks'. One row for every calendar day of the month (28 to 31 rows) from the 1st, so gaps are visible. Days without data have empty cells, never zeros.


* **Number formats (copied from the sample):** Date m/d/yyyy (setting DATE_FORMAT; alternative dd-mmm-yyyy); Inverter 0.00; Monthly Inverter Total 0.00; EB Reading 0; EB Reading Total 0.00; 6am-10am 0.00. The sample shows EB Reading without decimals but its total with decimals, which is probably unintentional, so keep all formats in one config object that is easy to change.


* **Style:** Calibri 11, right-aligned numbers, alternate rows light blue (#DDEBF7), thin blue grid lines (#5B9BD5), frozen header, column widths like the sample, print setup A4 portrait fitted to one page wide, header row repeated.


* Totals are calculated in Python and written as numbers, not formulas, so phone previews and other tools show real values. The Details sheet is the audit view.


* Text cells (remarks, fault text) are always written as plain strings, so a remark that starts with =, +, or @ can never run as a formula.


* **Regeneration:** every accepted change rebuilds the whole workbook from the database, writes it to a temp file, flushes it to disk, then renames it over the old one. A test must kill the process mid-write and prove the old file is intact. The file must open in Excel and LibreOffice without a repair prompt.


* **Library choice (decided in Phase PO).** Desktop Excel libraries cannot be assumed to work on Android. Candidates: Apache POI configured for Android, a pure-Kotlin XLSX writer (for example Kexcel or CellarKt), fastexcel with an extra StAX dependency, or a small hand-written OOXML writer (a zip of XML parts, which is enough for this one fixed layout). Choose the one that runs on Android 8 and newer; supports merged cells, fills, borders, number formats, column widths, a frozen header and A4 fit-to-width print setup; writes strings as plain text; adds the least APK size; and passes AC-16. Whichever is chosen must be proven on a real phone, not only in a JVM test.



### B9. PDF report

* **Purpose:** reproduce your sample PDF. Library: Android's built-in PdfDocument drawing on a Canvas, with the Carlito font bundled in the app (A4 is 595x842 points).


* **Page:** A4 portrait (setting PDF_PAGE; alternative Letter, which your sample uses), about 0.6 inch margins, table at the top left. Same seven columns and headers as the Excel report sheet, the 'MAY-2026' box above Remarks, the same number formats, the same light-blue banding and blue grid, right-aligned numbers, Remarks wrapped to at most 2 lines. A full month (31 rows) must fit on one page with no stray marks, unlike page 2 of your sample.


* Footer in small grey type: 'Generated 01-Jun-2026 00:05 IST, revision 1. Weather data: Open-Meteo.com (CC BY 4.0)'.


* Optional extras, off by default: PDF_SHOW_TITLE (customer and plant name above the table) and PDF_SHOW_SUMMARY (total, daily average, best and lowest day under the table).


* Date-range export: the user can export any range of days in a month, for example 1 to 18 May like your sample. Running totals always start from day 1 of the month.


* The month-close PDF lists every calendar day. Missing days show empty cells with 'Not recorded' in Remarks, and the footer adds 'n day(s) not recorded'. A PDF is always produced even if the month is incomplete; the Admin gets an alert.


* Remarks cell: manual note first, then the automatic weather note, separated by '.' (setting REMARK_MODE: both, manual_only, auto_only).


* **Naming and storage:** reports/2026/SRS_Kumaran_Generation_2026-05_rev1.pdf. The latest revision is the official one; older revisions stay downloadable. Store each file's SHA-256 and show it on the Reports page.


* **Golden test:** render May 1 to 18 from the seed CSV and compare every cell with the sample PDF's values, plus an image comparison (render the PDF with Android's PdfRenderer) with tests/golden/may_2026_sample_page1.png (allow a small tolerance for fonts).



### B10. Monthly lifecycle and scheduler

A month moves OPEN, then CLOSED, then LOCKED.

| Moment | What happens |
| --- | --- |
| Any upload dated in a month | The month and its sheet are created if missing. This also covers the very first month and back-entry.

 |
| 00:05 IST on the 1st (setting CLOSE_TIME) | The previous month becomes CLOSED: refresh provisional weather, rebuild the workbook, generate PDF revision 1, store its hash, copy it to EXPORT_COPY_DIR if set, notify (in-app banner always, email with the PDF attached if configured), and create the new month's sheet.

 |
| While CLOSED (late-entry window, GRACE_DAYS = 3) | Operators can still add or fix days of that month. Each change rebuilds the workbook and, after a 2 minute wait that merges bursts of changes, issues the next PDF revision and notifies, for example 'revision 2: 31 May added'.

 |
| End of day 3 after month end | The month becomes LOCKED. Only an Admin can change it, with a reason; the change creates a new PDF revision marked 'post-lock amendment'.

 |

* **Scheduler:** APScheduler with a cron trigger (00:05 on day 1, Asia/Kolkata) plus a safety job every 15 minutes that checks which transitions are due and runs them. The same check runs at app start-up. If the computer was off on the 1st, the month closes as soon as the app starts and the audit log records 'late close'.


* **Idempotency:** a unique key on (job name, period) in job_runs, plus unique (month, PDF revision). Running a job twice, or two workers at once, changes nothing the second time.


* 'Downloaded as PDF' means: the file is saved on the server, shown with a red badge 'May 2026 PDF ready' on the Dashboard and Reports page, optionally emailed, and optionally copied to a folder (EXPORT_COPY_DIR, for example a Documents folder on the plant PC). A browser cannot download a file by itself while nobody is looking, so the first login after the 1st shows a one-click download banner.


* **Admin controls:** Close month now, Regenerate PDF, Reopen month (reason required).


* **Edge cases to handle and test:** months of 28, 29, 30 and 31 days; an upload at 23:59:59 IST on the 31st; a server clock set to UTC (18:35 UTC on 31 May is 00:05 IST on 1 June); two uploads at the same instant; back-entry for a month before data started; a future month (blocked); year rollover (new workbook on 1 January, previous year's Year Summary completed).



### B11. User interface (mobile-first, installable)

Design: clean and calm; solar amber and deep blue accents; large tap targets; works at 360 px width; light and dark mode; English. The app shows numbers in Indian grouping (1,03,065.00); Excel and PDF follow the sample, with no separators. Installable as a home-screen app (manifest and service worker). Where the phone supports it (Android Chrome over HTTPS), register as a share target so the daily WhatsApp image can be shared straight into the app. iPhone does not support that, so the camera and file picker stay the main route.

**Screens:**

1. Login.


2. Dashboard: current month and status; progress ('17 of 31 days recorded'); a day strip coloured recorded, missing or today; month-to-date inverter and EB totals and daily average; latest reading with its weather icon; alerts (missing days, pending reviews, provisional weather, 'PDF ready'); a large Upload button.


3. Upload: camera, gallery or drag-and-drop; several files; progress; then the Review screen for each one.


4. Review: as described in B5.


5. Month view: the report table exactly as in the PDF. Tap a row to see details, edit or add a manual remark, or add a day manually (entry method MANUAL, reason required). Buttons: Download Excel, Export PDF (whole month or a day range).


6. Reports archive: every month, newest first, with a status chip, days recorded, totals, PDF revisions with their SHA-256, and an Excel download; filter by year; Year Summary.


7. Insights: per month chart of generation against solar energy; flagged days; weather mismatches.


8. Settings (Admin): customer name and aliases, plant location, thresholds, EB_MF, remark mode, report style options, close time and grace days, email and notification settings, users.


9. Audit log and System status: job history, last backup, weather provider status, app version.



Every error message says what happened and what to do next. Loading, empty and offline states are designed for each screen.

### B12. HTTP API (JSON, authenticated)

* POST /api/uploads (multipart, one or many) returns upload ids with extraction results.


* GET /api/uploads/{id}, POST /api/uploads/{id}/accept, POST /api/uploads/{id}/reject.


* GET /api/months, GET /api/months/{ym}, POST /api/months/{ym}/close (Admin), POST /api/months/{ym}/reopen (Admin).


* GET /api/readings?from=&to=, PATCH /api/readings/{date}, POST /api/readings (manual entry, reason required).


* GET /api/months/{ym}/pdf?from_day=&to_day=, GET /api/months/{ym}/pdf/revisions, GET /api/years/{yyyy}/workbook.


* GET /api/weather/{date}, POST /api/weather/{date}/refresh.


* GET /api/insights/{ym}, GET /api/audit, GET /healthz.



Rules: request and response bodies are validated with Pydantic models; one consistent error format; all downloads are authenticated and use database ids, never user-supplied paths.

### B13. Security and privacy

* Uploads: verify the image really opens, enforce the size limit, use random stored file names, never execute anything from an upload, strip EXIF.


* Other customers' data: the extraction prompt asks for the SRS row only; the code discards anything else the model returns; logs never contain image data or full model responses; the full image is deleted after review; a test searches the database, files and logs for the other customers' names.


* Secrets only in .env, which is listed in .gitignore. Never print keys in logs.


* Rate-limit login and upload; lock out after repeated failures; session expiry (Admin: 30 minutes idle).


* HTTPS is required when the app is reachable beyond the local network (reverse proxy such as Caddy; include a sample Caddyfile).


* Downloads check permissions and use ids, so path traversal is impossible by construction.


* Pin dependencies and run a vulnerability scan (pip-audit) in the test script.


* The README must tell the user that images go to the configured vision service, and how to switch to manual entry only.



### B14. Reliability and operations

* Nightly backup at 02:00 IST: a consistent SQLite copy (backup API) plus workbooks and PDFs into backups/YYYY-MM-DD/; keep 30 days; optional copy to a second folder or drive; a documented, tested restore command.


* /healthz reports database, disk space, scheduler alive and last successful job; the System status screen shows the same.


* Structured logs with rotation and a request id on every line.


* Alembic migrations; the app refuses to start on a schema mismatch and says why.


* CLI commands: create-admin, import-csv, close-month, rebuild-all (regenerate every workbook and PDF from the database), backup, restore.


* Packaging: Dockerfile, docker-compose.yml, and plain-Python run scripts for Windows (run.bat) and Linux (run.sh), with instructions to run as a service that restarts after a reboot.


* Performance target: from Accept to updated workbook in under 3 seconds on a basic PC (excluding the model call).



### B15. Testing and acceptance

Automated tests (pytest) must cover every item below using a fake clock, a fake extraction provider and a fake weather provider. A few optional live tests may exist, off by default.

| ID | Test |
| --- | --- |
| AC-01 | Extraction on the sample image: report date 2026-05-22; SRS row; serial 5; 1 MW; inverter 7625; monthly 130428; yearly 565368; EB 7452; 6am-10am 1584; availability 100 and 100; weather 'sunny'; temperature 35. It must NOT return the Prabhu Textiles row (7640, 7476, 1608).

 |
| AC-02 | Import seed/may_2026.csv (1 to 18 May). Totals on 18 May: inverter 103065, EB 100740.

 |
| AC-03 | Accept the 22 May reading. Missing days 19, 20, 21 are listed. Month-to-date inverter 110690 against plant 130428 gives a reported gap of 19738. EB total 108192.

 |
| AC-04 | Adding 19, 20 and 21 May later with an inverter sum of exactly 19738 clears the gap warning; any other sum shows the remaining difference.

 |
| AC-05 | The same image twice is blocked by hash. The same date with a different image shows a difference and needs confirmation; the old values are kept in revision history.

 |
| AC-06 | PDF export for 1 to 18 May equals the sample PDF cell by cell, on one page, with the right headers, 'MAY-2026' box and number formats.

 |
| AC-07 | Fake clock at 2026-06-01 00:05 IST: May becomes CLOSED, PDF revision 1 exists, the June sheet exists. Running the job again changes nothing.

 |
| AC-08 | An upload for 31 May made on 1 June at 09:00 goes into May, issues PDF revision 2 after the debounce, and nothing goes into June.

 |
| AC-09 | App not running on the 1st and started on the 3rd: May is closed at start-up with a 'late close' audit entry.

 |
| AC-10 | Four days after month end May is LOCKED. An Operator cannot edit it; an Admin can, with a reason, which creates a 'post-lock amendment' revision.

 |
| AC-11 | Server timezone UTC: 18:35 UTC on 31 May triggers the close; 18:20 UTC does not.

 |
| AC-12 | Weather service down: the reading is saved, the remark says 'Weather pending', retries run, nothing crashes. Provisional weather is replaced by final data after 7 days and the remark updates.

 |
| AC-13 | Bad inputs (blurry image, non-report image, SRS row missing, future date, 20 MB file, wrong file type) are each rejected with a clear message and nothing is saved.

 |
| AC-14 | Each rule in B6 has a passing and a failing test, including 8 May 6am-10am = 1376 raising the multiple-of-12 warning.

 |
| AC-15 | Privacy: after processing the sample image, searching the database, evidence folder, workbooks, PDFs and logs for AAURVIN, RANGA, JAYARAMM, GANESHAA and PRABHU finds nothing.

 |
| AC-16 | Excel opens in Excel and LibreOffice without a repair prompt; a remark of =HYPERLINK(...) appears as text; killing the process mid-write leaves the previous file intact.

 |
| AC-17 | Months with 28, 29, 30 and 31 days render the right number of rows (test February 2027, February 2028, April and May).

 |
| AC-18 | Weather classification boundaries: cloud at 19.9, 20, 49.9, 50, 79.9 and 80 percent; rain at 2.4, 2.5, 15.5, 15.6, 64.4 and 64.5 mm.

 |
| AC-19 | A backup and restore round trip reproduces identical workbooks and PDF hashes.

 |
| AC-20 | Every route enforces the role matrix; state-changing requests without a CSRF token fail.

 |

### B16. Repository structure and deliverables

```text
srs-solar-log/
  README.md .env.example Dockerfile docker-compose.yml run.bat run.sh
  pyproject.toml
  SPEC.md OPERATIONS.md (backup, restore, month close, troubleshooting)
  CHANGELOG.md
  app/
    domain/
      totals.py validation.py months.py remarks.py models.py
    services/
      extraction/ weather/ reports/ (excel.py, pdf.py)
      scheduler.py notify.py backup.py
    infra/
      db.py files.py clock.py settings.py
    web/
      routes/ templates/ static/
    cli.py
  migrations/
  seed/
    may_2026.csv
  tests/
    unit/ integration/ golden/

```

Deliverables: the working app; migrations; seed data; passing tests; a README with a 10-minute setup; the OPERATIONS guide; a one-page user guide for the daily routine; and a written list of assumptions and any deviations from this spec.

### B17. Out of scope for version 1

Other customers' data or any multi-customer screens; billing or tariff calculations; inverter-level or SCADA integration; reading WhatsApp automatically; native mobile apps; a Tamil-language interface (write all text so it can be translated later).