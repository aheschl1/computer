---
name: docker-backup
description: Backup Docker Compose configurations and persistent data to /data/backups/docker/.
---

# Docker Backup

## When to use this skill
Use this skill to back up Docker Compose configurations, environment files, and persistent data from `~/docker_deployments` to `/data/backups/docker/`.

## How to use this skill

### Full backup (default)
```bash
./docker_backup.sh
```
Creates a timestamped tarball of all docker deployments.

### Backup a single service
```bash
./docker_backup.sh --service immich
```
Backs up only the `immich` directory.

### Dry-run mode (preview without copying)
```bash
./docker_backup.sh --dry-run
```

### Options
- `--service <name>`: Backup only specified service
- `--output <path>`: Specify custom backup destination (default: `/data/backups/docker/`)
- `--dry-run`: Show what would be backed up without writing
- `--compress <gzip|zstd>`: Compression method (default: zstd)
- `--keep-n <n>`: Keep only the last N backups per service (default: 5)

## Output location
Backups are stored in `/data/backups/docker/YYYYMMDD_HHMMSS_service.tar.gz` with a manifest included.
