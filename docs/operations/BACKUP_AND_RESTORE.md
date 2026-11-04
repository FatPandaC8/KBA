# Gusby Database Backup & Restore Guide

This document describes the backup architecture, retention policies, restore workflows, and disaster recovery verification procedures for the Gusby PostgreSQL database.

---

## 1. Core Principles & Safety Guards

1. **Dedicated Database Only**: All backup and restore operations target the dedicated Gusby database (e.g. `gusby_db`).
2. **Strict Prohibition on `server_lab`**:
   The backup script (`scripts/backup.sh`) and restore script (`scripts/restore.sh`) contain hardcoded safety guards that inspect the connection URL. If the database name matches `server_lab`, execution is immediately halted with a fatal error.
3. **Pre-Migration Safety Snapshots**:
   Whenever [`scripts/migrate.sh up`](file:///home/guts/P2/KBA/scripts/migrate.sh) runs, it automatically triggers a pre-migration snapshot (`gusby_pre-migrate_<timestamp>.sql.gz`) before executing any DDL statements.

---

## 2. Backup Execution (`scripts/backup.sh`)

### Manual Backup
```bash
./scripts/backup.sh manual
```

### Pre-Migration Backup
```bash
./scripts/backup.sh pre-migrate
```

### Automated Scheduled Backup (Cron on Termux)
To configure daily backups at 03:00 AM on the Xperia device:

```bash
# Add to crontab (crontab -e in Termux):
0 3 * * * cd /data/data/com.termux/files/home/KBA && ./scripts/backup.sh scheduled >> /data/data/com.termux/files/home/KBA/shared/logs/backup.log 2>&1
```

### Backup Artifacts & Naming
Backups are saved to `backups/` as compressed gzip files:
```
backups/
├── gusby_manual_20261103_174822Z.sql.gz
├── gusby_pre-migrate_20261104_010000Z.sql.gz
└── gusby_scheduled_20261105_030000Z.sql.gz
```

---

## 3. Backup Retention Policy

The backup runner automatically manages disk space to protect the mobile phone from storage exhaustion:

- **`GUSBY_BACKUP_RETENTION_COUNT`**: Keeps at least the last 10 backups regardless of age (default: 10).
- **`GUSBY_BACKUP_RETENTION_DAYS`**: Automatically prunes backups older than 7 days if the total count exceeds the retention threshold (default: 7 days).

---

## 4. Database Restore Procedure (`scripts/restore.sh`)

To restore from a backup:

```bash
# Interactive restore (prompts for confirmation)
./scripts/restore.sh backups/gusby_manual_20261103_174822Z.sql.gz

# Non-interactive / Automated restore
./scripts/restore.sh backups/gusby_manual_20261103_174822Z.sql.gz --force
```

### Step-by-Step Execution:
1. Validates gzip archive integrity (`gzip -t`).
2. Checks target database connection URL (guaranteeing not `server_lab`).
3. Streams uncompressed SQL into target database.
4. Executes post-restore verification drill.

---

## 5. Post-Restore Verification Drill

The restore tool automatically runs the verification drill:
1. **Schema Check**: Confirms the `gusby` schema exists.
2. **Table Check**: Confirms at least 15 core application tables exist (`users`, `documents`, `concepts`, `propositions`, `processing_jobs`, etc.).
3. **Migration Audit**: Queries `gusby.schema_migrations` to list all applied migration versions.
4. **Application Verification**: Run `./deploy/termux/verify.sh` to confirm backend can connect and authenticate.
