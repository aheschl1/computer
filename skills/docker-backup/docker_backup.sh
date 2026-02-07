#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="/home/andrew/docker_deployments"
DEFAULT_BACKUP_DIR="/data/backups/docker"

# Parse arguments
SERVICE=""
DRY_RUN=false
COMPRESS="zstd"
KEEP_N=5
BACKUP_DIR="$DEFAULT_BACKUP_DIR"

while [[ $# -gt 0 ]]; do
    case $1 in
        --service)
            SERVICE="$2"
            shift 2
            ;;
        --output)
            BACKUP_DIR="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --compress)
            COMPRESS="$2"
            shift 2
            ;;
        --keep-n)
            KEEP_N="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate compress option
if [[ "$COMPRESS" != "gzip" && "$COMPRESS" != "zstd" ]]; then
    echo "Error: --compress must be 'gzip' or 'zstd'"
    exit 1
fi

# Determine file extension
if [[ "$COMPRESS" == "gzip" ]]; then
    EXT="gz"
else
    EXT="zst"
fi

# Create backup directory
if ! $DRY_RUN; then
    mkdir -p "$BACKUP_DIR"
fi

# Function to get backup filename
get_backup_name() {
    local svc="$1"
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    echo "${ts}_${svc}.tar.${EXT}"
}

# Function to backup a service
backup_service() {
    local svc="$1"
    local src="${DEPLOY_DIR}/${svc}"
    local backup_name
    backup_name=$(get_backup_name "$svc")
    local backup_path="${BACKUP_DIR}/${backup_name}"
    
    if [[ ! -d "$src" ]]; then
        echo "Warning: Service directory not found: $src"
        return 1
    fi
    
    echo "Processing: $svc"
    
    if $DRY_RUN; then
        echo "  Would backup: $src -> $backup_path"
        echo "  Files:"
        find "$src" -type f \( -name "*.yml" -o -name "*.yaml" -o -name ".env*" -o -name "docker-compose*" -o -name "*.conf" -o -name "*.ini" -o -name "*.json" -o -name "*.pem" -o -name "*_privatekey" -o -name "*_publickey" \) 2>/dev/null | sed 's/^/    /' || echo "    (none)"
        return 0
    fi
    
    # Create tarball with manifest
    local tmp_dir
    tmp_dir=$(mktemp -d)
    local manifest="${tmp_dir}/MANIFEST.txt"
    
    # Log backup info
    {
        echo "Backup created: $(date -Iseconds)"
        echo "Service: $svc"
        echo "Source: $src"
        echo "Compression: $COMPRESS"
        echo "Hostname: $(hostname)"
        echo "---"
        echo "Files included:"
    } > "$manifest"
    
    # Find and log config files
    find "$src" -type f \( -name "*.yml" -o -name "*.yaml" -o -name ".env*" -o -name "docker-compose*" -o -name "*.conf" -o -name "*.ini" -o -name "*.json" -o -name "*.pem" -o -name "*_privatekey" -o -name "*_publickey" \) 2>/dev/null >> "$manifest" || true
    
    # Build tar command
    local tar_opts="-cf - -C \"$src\" ."
    local compress_cmd
    
    case "$COMPRESS" in
        gzip)  compress_cmd="gzip -c" ;;
        zstd)  compress_cmd="zstd -c" ;;
    esac
    
    # Create tarball (excluding common build artifacts, caches, and immich data folder)
    tar --exclude="node_modules" --exclude="__pycache__" --exclude="*.pyc" \
        --exclude=".git" --exclude="builds" --exclude="dist" \
        --exclude="*.log" --exclude=".cache" \
        --exclude="immich/data" \
        --add-file="${manifest}" \
        $tar_opts | $compress_cmd > "$backup_path"
    
    # Create symlink to latest backup for this service
    ln -sf "$backup_name" "${BACKUP_DIR}/latest_${svc}.tar.${EXT}"
    
    # Cleanup old backups
    ls -t "${BACKUP_DIR}/${svc}"*."tar.${EXT}" 2>/dev/null | tail -n +$((KEEP_N + 1)) | while read -r old_backup; do
        rm -f "$old_backup"
    done
    
    rm -rf "$tmp_dir"
    
    echo "  Backed up: $backup_path"
}

# Main logic
if [[ -n "$SERVICE" ]]; then
    # Backup single service
    if [[ ! -d "${DEPLOY_DIR}/${SERVICE}" ]]; then
        echo "Error: Service directory not found: ${DEPLOY_DIR}/${SERVICE}"
        exit 1
    fi
    backup_service "$SERVICE"
else
    # Backup all services (exclude common non-service dirs)
    for svc in "$DEPLOY_DIR"/*/; do
        svc_name=$(basename "$svc")
        case "$svc_name" in
            builds|actual|haos|dad) continue ;;  # Skip non-Docker directories
        esac
        if [[ -d "$svc" && -f "${svc}docker-compose.yml" ]]; then
            backup_service "$svc_name"
        fi
    done
fi

echo "Backup complete."
