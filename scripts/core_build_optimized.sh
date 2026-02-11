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

# Optimized C++ core build script with intelligent caching

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

CPP_SRC_DIR="${ROOT_DIR}/internal/core"
BUILD_OUTPUT_DIR="${ROOT_DIR}/cmake_build"
BUILD_TYPE="${BUILD_TYPE:-Release}"
BUILD_UNITTEST="${BUILD_UNITTEST:-OFF}"
INSTALL_PREFIX="${INSTALL_PREFIX:-${CPP_SRC_DIR}/output}"
BUILD_COVERAGE="OFF"
GPU_VERSION="OFF"
CUDA_ARCH="DEFAULT"
BUILD_DISK_ANN="OFF"
USE_ASAN="OFF"
USE_DYNAMIC_SIMD="ON"
USE_OPENDAL="OFF"
TANTIVY_FEATURES=""
INDEX_ENGINE="KNOWHERE"
ENABLE_AZURE_FS="ON"
ENABLE_GCP_NATIVE="${ENABLE_GCP_NATIVE:-OFF}"
USE_NINJA="${USE_NINJA:-ON}"

# Parse arguments
while getopts "p:t:n:a:y:x:o:f:ucgh" arg; do
  case $arg in
    p) INSTALL_PREFIX=$OPTARG ;;
    t) BUILD_TYPE=$OPTARG ;;
    u) BUILD_UNITTEST="ON" ;;
    c) BUILD_COVERAGE="ON" ;;
    g) GPU_VERSION="ON" ;;
    n) BUILD_DISK_ANN=$OPTARG ;;
    a) [[ ${OPTARG} == 'ON' ]] && USE_ASAN="ON" ;;
    y) USE_DYNAMIC_SIMD=$OPTARG ;;
    x) INDEX_ENGINE=$OPTARG ;;
    o) USE_OPENDAL=$OPTARG ;;
    f) TANTIVY_FEATURES=$OPTARG ;;
    h)
      echo "Optimized Milvus C++ build script"
      echo ""
      echo "Options:"
      echo "  -p: Install prefix (default: internal/core/output)"
      echo "  -t: Build type (Debug|Release, default: Release)"
      echo "  -u: Build unit tests (default: OFF)"
      echo "  -c: Enable coverage (default: OFF)"
      echo "  -g: Build GPU version (default: OFF)"
      echo "  -n: Build with disk index (ON|OFF)"
      echo "  -a: Enable AddressSanitizer (ON|OFF)"
      echo "  -y: Use dynamic SIMD (ON|OFF, default: ON)"
      echo "  -x: Index engine (default: KNOWHERE)"
      echo "  -o: Use OpenDAL (ON|OFF, default: OFF)"
      echo "  -f: Tantivy features"
      echo "  -h: Show this help"
      exit 0
      ;;
    ?) exit 1 ;;
  esac
done

# Determine build generator
CMAKE_GENERATOR="Unix Makefiles"
if [ "$USE_NINJA" = "ON" ] && command_exists ninja; then
    CMAKE_GENERATOR="Ninja"
    log_info "Using Ninja build system"
else
    log_info "Using Make build system"
fi

# Auto-enable disk index on supported platforms
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    if [ "$OS" = "ubuntu" ] || [ "$OS" = "rocky" ] || [ "$OS" = "amzn" ]; then
        BUILD_DISK_ANN=ON
    fi
fi

# Get optimal job count
jobs=$(get_num_jobs)
log_info "Building with ${jobs} parallel jobs"

# Create build directory
if [ ! -d "${BUILD_OUTPUT_DIR}" ]; then
    mkdir -p "${BUILD_OUTPUT_DIR}"
fi

source "${ROOT_DIR}/scripts/setenv.sh"

pushd "${BUILD_OUTPUT_DIR}" > /dev/null

# Determine CPU architecture
function get_cpu_arch {
  local CPU_ARCH=$1
  local OS=$(uname)
  local MACHINE=$(uname -m)

  if [ -z "$CPU_ARCH" ]; then
    if [ "$OS" = "Darwin" ]; then
      if [ "$MACHINE" = "x86_64" ]; then
        local CPU_CAPABILITIES=$(sysctl -a | grep machdep.cpu.features | awk '{print tolower($0)}')
        if [[ $CPU_CAPABILITIES =~ "avx" ]]; then
          CPU_ARCH="avx"
        else
          CPU_ARCH="sse"
        fi
      elif [[ $(sysctl -a | grep machdep.cpu.brand_string) =~ "Apple" ]]; then
        CPU_ARCH="arm64"
      fi
    else
      local CPU_CAPABILITIES=$(cat /proc/cpuinfo | grep flags | head -n 1 | awk '{print tolower($0)}')
      if [[ "$CPU_CAPABILITIES" =~ "avx" ]]; then
        CPU_ARCH="avx"
      elif [[ "$CPU_CAPABILITIES" =~ "sse" ]]; then
        CPU_ARCH="sse"
      elif [ "$MACHINE" = "aarch64" ]; then
        CPU_ARCH="aarch64"
      fi
    fi
  fi
  echo -n $CPU_ARCH
}

CPU_ARCH=$(get_cpu_arch $CPU_TARGET)
arch=$(uname -m)

# Check if CMake reconfiguration is needed
NEED_RECONFIGURE=false

if [ ! -f "CMakeCache.txt" ]; then
    log_info "No CMake cache found, configuration required"
    NEED_RECONFIGURE=true
elif [ "${CPP_SRC_DIR}/CMakeLists.txt" -nt "CMakeCache.txt" ]; then
    log_info "CMakeLists.txt changed, reconfiguration required"
    NEED_RECONFIGURE=true
fi

# Configure CMake if needed
if [ "$NEED_RECONFIGURE" = true ]; then
    log_info "Configuring CMake..."

    CMAKE_CMD="cmake \
${CMAKE_EXTRA_ARGS} \
-DBUILD_UNIT_TEST=${BUILD_UNITTEST} \
-DCMAKE_INSTALL_PREFIX=${INSTALL_PREFIX} \
-DCMAKE_BUILD_TYPE=${BUILD_TYPE} \
-DCMAKE_LIBRARY_ARCHITECTURE=${arch} \
-DBUILD_COVERAGE=${BUILD_COVERAGE} \
-DMILVUS_GPU_VERSION=${GPU_VERSION} \
-DMILVUS_CUDA_ARCH=${CUDA_ARCH} \
-DBUILD_DISK_ANN=${BUILD_DISK_ANN} \
-DUSE_ASAN=${USE_ASAN} \
-DUSE_DYNAMIC_SIMD=${USE_DYNAMIC_SIMD} \
-DCPU_ARCH=${CPU_ARCH} \
-DUSE_OPENDAL=${USE_OPENDAL} \
-DINDEX_ENGINE=${INDEX_ENGINE} \
-DTANTIVY_FEATURES_LIST=${TANTIVY_FEATURES} \
-DENABLE_GCP_NATIVE=${ENABLE_GCP_NATIVE} \
-DENABLE_AZURE_FS=${ENABLE_AZURE_FS} \
-DMILVUS_USE_CCACHE=ON"

    if command_exists ccache; then
        CMAKE_CMD="${CMAKE_CMD} \
-DCMAKE_C_COMPILER_LAUNCHER=ccache \
-DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
    fi

    CMAKE_CMD="${CMAKE_CMD} ${CPP_SRC_DIR}"

    log_info "CMake command: ${CMAKE_CMD}"
    ${CMAKE_CMD} -G "${CMAKE_GENERATOR}"

    log_success "CMake configuration completed"
else
    log_success "Using existing CMake cache"
fi

# Build
log_info "Building C++ core..."
build_start=$(date +%s)

if [ "$CMAKE_GENERATOR" = "Ninja" ]; then
    ninja -j ${jobs} install
else
    make -j ${jobs} install
fi

build_end=$(date +%s)
build_duration=$((build_end - build_start))

log_success "C++ core built in ${build_duration}s"

# Show ccache statistics
if command_exists ccache; then
    echo ""
    log_info "=== ccache Statistics ==="
    ccache -s
fi

popd > /dev/null

log_success "Build completed successfully!"
