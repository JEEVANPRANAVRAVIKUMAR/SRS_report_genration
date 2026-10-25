-- SQLite schema and seed data for Phase P1
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS plants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    timezone VARCHAR(50) NOT NULL DEFAULT 'Asia/Kolkata',
    capacity_mw FLOAT NOT NULL DEFAULT 10.0
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plant_id INTEGER NOT NULL REFERENCES plants(id),
    display_name VARCHAR(100) NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    capacity_mw FLOAT NOT NULL DEFAULT 1.0,
    is_target BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    salt VARCHAR(64) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'OPERATOR',
    actor_label VARCHAR(50) NOT NULL DEFAULT 'Operator',
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS months (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    ym VARCHAR(7) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    closed_at DATETIME,
    locked_at DATETIME,
    pdf_revision INTEGER NOT NULL DEFAULT 1,
    workbook_path VARCHAR(255),
    CONSTRAINT uq_customer_month_ym UNIQUE (customer_id, ym)
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    report_date DATE NOT NULL,
    inverter_kwh FLOAT NOT NULL,
    eb_export_kwh FLOAT NOT NULL,
    eb_6to10_kwh FLOAT NOT NULL,
    reported_monthly_kwh FLOAT,
    reported_yearly_kwh FLOAT,
    inverter_availability_pct FLOAT DEFAULT 100.0,
    grid_availability_pct FLOAT DEFAULT 100.0,
    fault_text VARCHAR(255) DEFAULT '',
    plant_weather_text VARCHAR(100) DEFAULT '',
    plant_temp_c FLOAT,
    manual_remark VARCHAR(255) DEFAULT '',
    auto_remark VARCHAR(255) DEFAULT '',
    source_upload_id INTEGER,
    entry_method VARCHAR(20) NOT NULL DEFAULT 'IMPORT',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    version INTEGER NOT NULL DEFAULT 1,
    actor_label VARCHAR(50) NOT NULL DEFAULT 'Importer',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_customer_report_date UNIQUE (customer_id, report_date)
);

CREATE TABLE IF NOT EXISTS reading_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_id INTEGER NOT NULL REFERENCES readings(id),
    version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_label VARCHAR(50) NOT NULL,
    reason VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_label VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    entity VARCHAR(50) NOT NULL,
    entity_id VARCHAR(50),
    before TEXT,
    after TEXT,
    reason VARCHAR(255)
);

-- Plant Seed
INSERT OR IGNORE INTO plants (id, name, latitude, longitude, timezone, capacity_mw)
VALUES (1, 'Sunpro Antichettipalayam', 10.851319, 77.909541, 'Asia/Kolkata', 10.0);

-- Customer Seed
INSERT OR IGNORE INTO customers (id, plant_id, display_name, aliases, capacity_mw, is_target)
VALUES (1, 1, 'M/s. SRS KUMARAN INDIA PVT LTD', '["M/s. SRS KUMARAN INDIA PVT LTD", "SRS KUMARAN INDIA PVT LTD", "SRS KUMARAN"]', 1.0, 1);

-- Month Seed
INSERT OR IGNORE INTO months (id, customer_id, ym, status, pdf_revision)
VALUES (1, 1, '2026-05', 'OPEN', 1);

-- 1 to 18 May Readings Seed (matching seed/may_2026.csv)
INSERT OR REPLACE INTO readings (customer_id, report_date, inverter_kwh, eb_export_kwh, eb_6to10_kwh, reported_monthly_kwh, manual_remark, entry_method, status, version, actor_label)
VALUES
(1, '2026-05-01', 6489.0, 6336.0, 1236.0, 6489.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-02', 7003.0, 6840.0, 1488.0, 13492.0, 'Reading taken', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-03', 7574.0, 7392.0, 1500.0, 21066.0, 'vaani burried', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-04', 6001.0, 5856.0, 1380.0, 27067.0, 'm sand bought', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-05', 6827.0, 6672.0, 1116.0, 33894.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-06', 6998.0, 6840.0, 1476.0, 40892.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-07', 5497.0, 5388.0, 1128.0, 46389.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-08', 5765.0, 5640.0, 1376.0, 52154.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-09', 3311.0, 3240.0, 348.0, 55465.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-10', 7076.0, 6924.0, 1104.0, 62541.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-11', 7188.0, 7020.0, 1380.0, 69729.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-12', 7150.0, 6984.0, 1644.0, 76879.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-13', 6611.0, 6456.0, 1440.0, 83490.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-14', 4280.0, 4200.0, 984.0, 87770.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-15', 2989.0, 2928.0, 888.0, 90759.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-16', 765.0, 756.0, 744.0, 91524.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-17', 5148.0, 5028.0, 996.0, 96672.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer'),
(1, '2026-05-18', 6393.0, 6240.0, 1668.0, 103065.0, '', 'IMPORT', 'ACTIVE', 1, 'Seed Importer');

-- Audit Log Entry
INSERT INTO audit_log (actor_label, action, entity, entity_id, reason)
VALUES ('Seed Importer', 'IMPORT_CSV', 'readings', '1..18', 'Initial import of seed/may_2026.csv');
