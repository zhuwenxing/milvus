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

# Intelligent dependency manager with caching

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

BUILD_OPENDAL="${BUILD_OPENDAL:-OFF}"
BUILD_TYPE="${BUILD_TYPE:-Release}"

# Dependency files to track
CONAN_FILES=(
    "internal/core/conanfile.txt"
)

RUST_FILES=(
    "internal/core/thirdparty/tantivy/tantivy-binding/Cargo.toml"
    "internal/core/thirdparty/tantivy/tantivy-binding/Cargo.lock"
)

# Check if 3rdparty dependencies need rebuild
check_conan_deps() {
    log_info "Checking Conan dependencies..."

    # Check if explicitly skipped
    if [[ "${SKIP_3RDPARTY:-0}" -eq 1 ]]; then
        log_warning "SKIP_3RDPARTY is set, skipping dependency check"
        return 1
    fi

    # Use stamp-based checking
    if need_rebuild "conan-deps" "${CONAN_FILES[@]}"; then
        return 0
    fi

    # Additional check: verify conan directory exists and is valid
    if [ ! -d "${ROOT_DIR}/cmake_build/conan" ]; then
        log_warning "Conan directory not found, rebuild required"
        return 0
    fi

    if [ ! -f "${ROOT_DIR}/cmake_build/conan/conanbuildinfo.cmake" ]; then
        log_warning "Conan build info not found, rebuild required"
        return 0
    fi

    return 1
}

# Build Conan dependencies
build_conan_deps() {
    log_info "Building Conan dependencies..."

    local start_time=$(date +%s)

    # Call original 3rdparty build script
    bash "${ROOT_DIR}/scripts/3rdparty_build.sh" -o "${BUILD_OPENDAL}" -t "${BUILD_TYPE}"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log_success "Conan dependencies built in ${duration}s"

    # Mark as complete
    mark_build_complete "conan-deps" "${CONAN_FILES[@]}"
}

# Check if Rust dependencies need rebuild
check_rust_deps() {
    log_info "Checking Rust dependencies..."

    # Check if Rust source exists
    if [ ! -d "${ROOT_DIR}/internal/core/thirdparty/tantivy" ]; then
        log_info "Tantivy not found, skipping Rust check"
        return 1
    fi

    if need_rebuild "rust-deps" "${RUST_FILES[@]}"; then
        return 0
    fi

    return 1
}

# Build Rust dependencies
build_rust_deps() {
    log_info "Building Rust dependencies..."

    if ! command_exists cargo; then
        log_warning "Cargo not found, skipping Rust build"
        return
    fi

    local start_time=$(date +%s)

    pushd "${ROOT_DIR}/internal/core/thirdparty/tantivy/tantivy-binding" > /dev/null
    cargo build --release
    popd > /dev/null

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    log_success "Rust dependencies built in ${duration}s"

    mark_build_complete "rust-deps" "${RUST_FILES[@]}"
}

# Main entry point
main() {
    log_info "=== Dependency Manager ==="
    echo ""

    local rebuild_needed=false

    # Check and build Conan dependencies
    if check_conan_deps; then
        build_conan_deps
        rebuild_needed=true
    else
        log_success "Conan dependencies are up to date"
    fi

    # Check and build Rust dependencies
    if check_rust_deps; then
        build_rust_deps
        rebuild_needed=true
    else
        log_success "Rust dependencies are up to date"
    fi

    if [ "$rebuild_needed" = false ]; then
        echo ""
        log_success "All dependencies are up to date!"
    fi

    echo ""
}

# Run if executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
