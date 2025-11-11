#!/usr/bin/env bash

# Licensed to the LF AI & Data foundation under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Build utilities for intelligent caching and dependency management

set -euo pipefail

STAMP_DIR=".build"
BUILD_ROOT="${BUILD_ROOT:-$(pwd)}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}→${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Initialize stamp directory
init_stamp_dir() {
    mkdir -p "${BUILD_ROOT}/${STAMP_DIR}"
}

# Compute hash of files
compute_hash() {
    local files=("$@")
    if [ ${#files[@]} -eq 0 ]; then
        echo "empty"
        return
    fi

    local hash=""
    for file in "${files[@]}"; do
        if [ -f "$file" ]; then
            # Use only the hash part, not the filename
            hash="${hash}$(sha256sum "$file" | cut -d' ' -f1)"
        elif [ -d "$file" ]; then
            # For directories, hash all files sorted by path
            hash="${hash}$(find "$file" -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum 2>/dev/null | cut -d' ' -f1 || true)"
        fi
    done

    echo -n "$hash" | sha256sum | cut -d' ' -f1
}

# Check if rebuild is needed based on file changes
need_rebuild() {
    local stamp_name=$1
    shift
    local source_files=("$@")

    init_stamp_dir

    local stamp_file="${BUILD_ROOT}/${STAMP_DIR}/${stamp_name}.stamp"

    # If stamp doesn't exist, rebuild needed
    if [ ! -f "$stamp_file" ]; then
        log_info "No previous build found for ${stamp_name}"
        return 0
    fi

    # Compute current hash
    local current_hash=$(compute_hash "${source_files[@]}")
    local previous_hash=$(cat "$stamp_file" 2>/dev/null || echo "")

    # Compare hashes
    if [ "$current_hash" != "$previous_hash" ]; then
        log_info "Changes detected in ${stamp_name}"
        return 0
    fi

    log_success "No changes in ${stamp_name}, using cache"
    return 1
}

# Mark build as complete
mark_build_complete() {
    local stamp_name=$1
    shift
    local source_files=("$@")

    init_stamp_dir

    local stamp_file="${BUILD_ROOT}/${STAMP_DIR}/${stamp_name}.stamp"
    local current_hash=$(compute_hash "${source_files[@]}")

    echo "$current_hash" > "$stamp_file"
    log_success "Build ${stamp_name} completed and cached"
}

# Check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Get optimal number of jobs
get_num_jobs() {
    if [[ ! ${jobs+1} ]]; then
        if command_exists nproc; then
            jobs=$(nproc)
        elif command_exists sysctl; then
            jobs=$(sysctl -n hw.logicalcpu)
        else
            jobs=4
        fi
    fi
    echo "$jobs"
}

# Clean stamp files
clean_stamps() {
    log_info "Cleaning build stamps..."
    rm -rf "${BUILD_ROOT}/${STAMP_DIR}"
    log_success "Build stamps cleaned"
}

# Show cache status
show_cache_status() {
    init_stamp_dir

    echo ""
    echo "=== Build Cache Status ==="
    echo ""

    if [ -d "${BUILD_ROOT}/${STAMP_DIR}" ] && [ "$(ls -A ${BUILD_ROOT}/${STAMP_DIR} 2>/dev/null)" ]; then
        for stamp in "${BUILD_ROOT}/${STAMP_DIR}"/*.stamp; do
            if [ -f "$stamp" ]; then
                local name=$(basename "$stamp" .stamp)
                local timestamp=$(stat -c %y "$stamp" 2>/dev/null || stat -f "%Sm" "$stamp" 2>/dev/null || echo "unknown")
                echo "  ✓ ${name}: ${timestamp}"
            fi
        done
    else
        echo "  (no cached builds)"
    fi

    echo ""

    # Show ccache stats if available
    if command_exists ccache; then
        echo "=== ccache Statistics ==="
        ccache -s
    fi
}

# Export functions
export -f log_info
export -f log_success
export -f log_warning
export -f log_error
export -f need_rebuild
export -f mark_build_complete
export -f compute_hash
export -f get_num_jobs
export -f command_exists
