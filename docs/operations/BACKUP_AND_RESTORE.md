# Gusby Database Backup & Restore Guide

This document describes the backup architecture, retention policies, restore workflows, safety boundaries, and post-restore verification procedures for the Gusby PostgreSQL database on Sony Xperia (Android Termux).

---

## 1. Core Principles & Safety Guards

1. **Dedicated Database Only**: All backup and restore operations target the dedicated Gusby database (e.g. `gusby_db`).
2. **Strict Prohibition on `server_lab`**:
   The backup script (`scripts/backup.sh`) and restore script (`scripts/restore.sh`) enforce two tiers of protection:
   - Regex URL inspection: strictly rejects any URL pointing to `/server_lab`.
   - Engine query: queries PostgreSQL directly via `SELECT current_database()` and halts immediately if connected to `server_lab`.
3. **Atomic File Creation**:
   Backups stream into a temporary staging file (`.tmp.<pid>`), pass archive integrity validation (`gzip -t`), and only then atomically move to the final filename. Incomplete or corrupted dumps never receive a valid backup filename.
4. **Explicit Restore Confirmation**:
   The restore script requires the operator to type the target database name interactively, or pass `--confirm-target-db=<dbname>` in non-interactive scripts.
5. **Decoupled from Deployments**:
   Application deployments **never** automatically run backups or restores. Backups are run manually or via scheduled cron jobs.

---

## 2. Scope & Limitations

- **In Scope**: All tables, sequences, constraints, and data within the dedicated `gusby` schema.
- **Out of Scope**:
  - Other databases (such as `server_lab` or `postgres`).
  - Global PostgreSQL cluster roles and passwords.
  - Tablespace definitions.

---

## 3. Backup Execution (`scripts/backup.sh`)

### Manual Backup
```bash
cd ~/apps/gusby
./scripts/backup.sh manual
```

### Pre-Migration Backup (Recommended Prior to Manual Migration)
Run manually before executing `./scripts/migrate.sh up`:
```bash
./scripts/backup.sh pre-migrate
```

### Automated Scheduled Backup (Cron in Termux)
To configure automated daily backups at 03:00 AM:

```bash
# In Termux: crontab -e
0 3 * * * cd /data/data/com.termux/files/home/apps/gusby && ./scripts/backup.sh scheduled >> /data/data/com.termux/files/home/services/gusby/logs/backup.log 2>&1
```

### Backup Artifacts & Naming
Backups are saved to `~/backups/gusby/`:
```text
~/backups/gusby/
├── gusby_manual_20261104_120000Z.sql.gz
├── gusby_pre-migrate_20261104_140000Z.sql.gz
└── gusby_scheduled_20261105_030000Z.sql.gz
```

---

## 4. Backup Retention Policy

To conserve flash storage on the mobile phone:
- **`GUSBY_BACKUP_RETENTION_COUNT`**: Guarantees at least 10 recent backups are retained (default: 10).
- **`GUSBY_BACKUP_RETENTION_DAYS`**: Automatically prunes backups older than 7 days if the total count exceeds 10 (default: 7 days).

---

## 5. Database Restore Procedure (`scripts/restore.sh`)

To restore from a backup:

```bash
cd ~/apps/gusby

# Interactive restore (prompts to type the target database name to confirm):
./scripts/restore.sh ~/backups/gusby/gusby_manual_20261104_120000Z.sql.gz

# Automated / Scripted restore (must provide matching target database name):
./scripts/restore.sh ~/backups/gusby/gusby_manual_20261104_120000Z.sql.gz --confirm-target-db=gusby_db
```

### Restore Execution Flow:
1. Validates archive integrity with `gzip -t`.
2. Connects to PostgreSQL and verifies `current_database()` is `gusby_db` (strictly not `server_lab`).
3. Prompts for target database confirmation.
4. Ensures required extensions (`pg_trgm`) exist.
5. Streams SQL dump into the `gusby` schema with `ON_ERROR_STOP=1`.
6. Executes post-restore read-only verification drill.

---

## 6. Post-Restore Verification Drill

The restore script executes an automated drill after restoring:
1. **Schema Check**: Confirms `gusby` schema exists.
2. **Table Check**: Confirms application tables exist (`users`, `documents`, `concepts`, `propositions`, `processing_jobs`, etc.).
3. **Migration Audit**: Lists applied versions from `gusby.schema_migrations`.
4. **Application Probe**: Run `./deploy/termux/verify.sh` to confirm the backend can authenticate and query data without errors.
