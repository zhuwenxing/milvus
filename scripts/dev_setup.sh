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

# Development environment setup script

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT_DIR="$( cd -P "$( dirname "$SOURCE" )/.." && pwd )"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

echo "🚀 Milvus Development Environment Setup"
echo ""

# Check OS
OS_TYPE="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS_TYPE="macos"
    log_info "Detected macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
    log_info "Detected Linux"
else
    log_warning "Unknown OS: $OSTYPE"
fi

# Check required tools
log_info "Checking required tools..."

check_tool() {
    local tool=$1
    local install_cmd=$2

    if command -v "$tool" &>/dev/null; then
        log_success "$tool found ($(command -v $tool))"
        return 0
    else
        log_error "$tool not found"
        if [ -n "$install_cmd" ]; then
            echo "  Install with: $install_cmd"
        fi
        return 1
    fi
}

MISSING_TOOLS=false

# Essential tools
check_tool "git" "apt-get install git" || MISSING_TOOLS=true
check_tool "make" "apt-get install build-essential" || MISSING_TOOLS=true
check_tool "cmake" "apt-get install cmake (>= 3.18)" || MISSING_TOOLS=true
check_tool "go" "https://golang.org/dl/" || MISSING_TOOLS=true

# Optional but recommended
log_info "Checking optional tools..."

if ! check_tool "ninja" ""; then
    log_warning "Ninja not found (recommended for faster builds)"
    if [ "$OS_TYPE" = "macos" ]; then
        echo "  Install with: brew install ninja"
    else
        echo "  Install with: apt-get install ninja-build"
    fi
fi

if ! check_tool "ccache" ""; then
    log_warning "ccache not found (recommended for caching)"
    if [ "$OS_TYPE" = "macos" ]; then
        echo "  Install with: brew install ccache"
    else
        echo "  Install with: apt-get install ccache"
    fi
else
    # Configure ccache
    log_info "Configuring ccache..."
    mkdir -p ~/.cache/ccache

    if [ -f "${ROOT_DIR}/.ccache.conf" ]; then
        export CCACHE_CONFIGPATH="${ROOT_DIR}/.ccache.conf"
        ccache --max-size=20G
        ccache --set-config=compression=true
        ccache --set-config=compression_level=6
        log_success "ccache configured (max size: 20GB)"
    fi
fi

if ! check_tool "conan" ""; then
    log_warning "Conan not found"
    echo "  Install with: pip3 install conan"
fi

if $MISSING_TOOLS; then
    echo ""
    log_error "Some required tools are missing. Please install them first."
    exit 1
fi

echo ""
log_success "All required tools are installed!"

# Setup ccache environment
if command -v ccache &>/dev/null; then
    log_info "Setting up ccache environment..."

    cat >> "${ROOT_DIR}/.env.local" <<'EOF'
# ccache configuration
export CCACHE_DIR="${CCACHE_DIR:-$HOME/.cache/ccache}"
export CCACHE_CONFIGPATH="$(pwd)/.ccache.conf"
export CCACHE_BASEDIR="$(pwd)"
export CMAKE_C_COMPILER_LAUNCHER=ccache
export CMAKE_CXX_COMPILER_LAUNCHER=ccache
EOF

    log_success "ccache environment configured (see .env.local)"
fi

# Setup build directories
log_info "Creating build directories..."
mkdir -p "${ROOT_DIR}/.build"
mkdir -p "${ROOT_DIR}/bin"
mkdir -p "${ROOT_DIR}/lib"
log_success "Build directories created"

# Generate compile_commands.json for IDE support
if [ -f "${ROOT_DIR}/CMakePresets.json" ]; then
    log_info "Generating compile_commands.json for IDE support..."

    if command -v cmake &>/dev/null; then
        cd "${ROOT_DIR}"
        cmake --preset dev 2>/dev/null || log_warning "Could not generate compile_commands.json (run after first build)"

        if [ -f "cmake_build/compile_commands.json" ]; then
            ln -sf cmake_build/compile_commands.json compile_commands.json
            log_success "compile_commands.json generated"
        fi
    fi
fi

# Setup git hooks
log_info "Setting up git hooks..."

mkdir -p "${ROOT_DIR}/.git/hooks"

# Pre-commit hook for formatting
cat > "${ROOT_DIR}/.git/hooks/pre-commit" <<'EOF'
#!/bin/bash
# Pre-commit hook for code formatting

echo "Running format check..."

# Check if we're in the project root
if [ ! -f "Makefile" ]; then
    echo "Error: Not in project root"
    exit 1
fi

# Run format check on staged files
STAGED_GO_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.go$' || true)

if [ -n "$STAGED_GO_FILES" ]; then
    echo "Checking Go format..."

    # Use gofmt to check
    UNFORMATTED=$(gofmt -l $STAGED_GO_FILES 2>&1)

    if [ -n "$UNFORMATTED" ]; then
        echo "Error: Some files are not formatted:"
        echo "$UNFORMATTED"
        echo ""
        echo "Run 'make fmt' to format these files"
        exit 1
    fi

    echo "✓ Go format check passed"
fi

exit 0
EOF

chmod +x "${ROOT_DIR}/.git/hooks/pre-commit"
log_success "Git hooks configured"

# Create .gitignore additions
log_info "Updating .gitignore..."

cat >> "${ROOT_DIR}/.gitignore" <<'EOF'

# Build optimization files
.build/
.env.local
compile_commands.json

# ccache
.ccache/

EOF

log_success ".gitignore updated"

# Print summary
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✓ Development environment setup complete!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Quick Start Commands:"
echo ""
echo "  Using optimized build system:"
echo "    make -f Makefile.optimized help      # Show all available commands"
echo "    make -f Makefile.optimized milvus-opt # Full optimized build"
echo "    make -f Makefile.optimized quick      # Quick build (skip checks)"
echo ""
echo "  Using CMake presets:"
echo "    cmake --preset dev                    # Configure for development"
echo "    cmake --build --preset dev            # Build"
echo ""
echo "  Development workflow:"
echo "    make -f Makefile.optimized cache-status  # Check cache status"
echo "    make -f Makefile.optimized rebuild-go    # Rebuild Go only"
echo "    make -f Makefile.optimized rebuild-cpp   # Rebuild C++ only"
echo ""
echo "  Testing:"
echo "    make test-go                          # Run Go tests"
echo "    make test-cpp                         # Run C++ tests"
echo ""
echo "Environment:"
if [ -f "${ROOT_DIR}/.env.local" ]; then
    echo "  Source environment: source .env.local"
fi
echo ""
echo "Documentation:"
echo "  Build system docs: docs/developer_guides/"
echo "  CMake presets: CMakePresets.json"
echo "  Optimized make: Makefile.optimized"
echo ""
echo "═══════════════════════════════════════════════════════════"
