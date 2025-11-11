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

# Intelligent proto file generation with caching

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT_DIR="$( cd -P "$( dirname "$SOURCE" )/.." && pwd )"

# Source build utilities
source "${ROOT_DIR}/scripts/build_utils.sh"

INSTALL_PATH="${INSTALL_PATH:-${ROOT_DIR}/bin}"

# Proto source directory
PROTO_DIR="${ROOT_DIR}/build/proto"

# Check if proto generation is needed
check_proto_generation() {
    log_info "Checking proto files..."

    # If proto directory doesn't exist, need to download
    if [ ! -d "$PROTO_DIR" ]; then
        log_info "Proto directory not found, download required"
        return 0
    fi

    # Check if proto files have changed
    local proto_files=()
    if [ -d "$PROTO_DIR" ]; then
        while IFS= read -r -d '' file; do
            proto_files+=("$file")
        done < <(find "$PROTO_DIR" -name "*.proto" -print0 2>/dev/null || true)
    fi

    if need_rebuild "proto-download" "${proto_files[@]}"; then
        return 0
    fi

    return 1
}

# Download milvus proto
download_proto() {
    log_info "Downloading milvus proto..."

    local start_time=$(date +%s)

    bash "${ROOT_DIR}/scripts/download_milvus_proto.sh"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log_success "Proto downloaded in ${duration}s"

    # Mark proto download as complete
    local proto_files=()
    if [ -d "$PROTO_DIR" ]; then
        while IFS= read -r -d '' file; do
            proto_files+=("$file")
        done < <(find "$PROTO_DIR" -name "*.proto" -print0 2>/dev/null || true)
    fi
    mark_build_complete "proto-download" "${proto_files[@]}"
}

# Check if proto code generation is needed
check_proto_codegen() {
    log_info "Checking generated proto code..."

    # Find all proto files
    local proto_files=()
    if [ -d "$PROTO_DIR" ]; then
        while IFS= read -r -d '' file; do
            proto_files+=("$file")
        done < <(find "$PROTO_DIR" -name "*.proto" -print0 2>/dev/null || true)
    fi

    if [ ${#proto_files[@]} -eq 0 ]; then
        log_warning "No proto files found"
        return 1
    fi

    if need_rebuild "proto-codegen" "${proto_files[@]}"; then
        return 0
    fi

    # Check if generated files exist
    if [ ! -d "${ROOT_DIR}/internal/proto" ]; then
        log_info "Generated proto directory not found"
        return 0
    fi

    return 1
}

# Generate proto code
generate_proto() {
    log_info "Generating proto code..."

    local start_time=$(date +%s)

    bash "${ROOT_DIR}/scripts/generate_proto.sh" "${INSTALL_PATH}"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log_success "Proto code generated in ${duration}s"

    # Mark codegen as complete
    local proto_files=()
    if [ -d "$PROTO_DIR" ]; then
        while IFS= read -r -d '' file; do
            proto_files+=("$file")
        done < <(find "$PROTO_DIR" -name "*.proto" -print0 2>/dev/null || true)
    fi
    mark_build_complete "proto-codegen" "${proto_files[@]}"
}

# Main entry point
main() {
    log_info "=== Proto Manager ==="
    echo ""

    # Step 1: Download proto if needed
    if check_proto_generation; then
        download_proto
    else
        log_success "Proto files are up to date"
    fi

    # Step 2: Generate code if needed
    if check_proto_codegen; then
        generate_proto
    else
        log_success "Generated proto code is up to date"
    fi

    echo ""
    log_success "Proto management complete!"
    echo ""
}

# Run if executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
