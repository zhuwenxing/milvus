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

# Build performance metrics and monitoring

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT_DIR="$( cd -P "$( dirname "$SOURCE" )/.." && pwd )"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Metrics output file
METRICS_FILE="${ROOT_DIR}/.build/metrics.json"
METRICS_LOG="${ROOT_DIR}/.build/metrics.log"

# Initialize
mkdir -p "${ROOT_DIR}/.build"

# Function to format duration
format_duration() {
    local seconds=$1
    local minutes=$((seconds / 60))
    local secs=$((seconds % 60))

    if [ $minutes -gt 0 ]; then
        echo "${minutes}m ${secs}s"
    else
        echo "${secs}s"
    fi
}

# Collect system information
collect_system_info() {
    local cpu_count=$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo "unknown")
    local mem_total=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || sysctl -n hw.memsize 2>/dev/null | awk '{print int($1/1073741824)}' || echo "unknown")
    local os_type=$(uname -s)

    echo "    \"system\": {"
    echo "      \"os\": \"$os_type\","
    echo "      \"cpu_cores\": $cpu_count,"
    echo "      \"memory_gb\": \"${mem_total}\""
    echo "    },"
}

# Collect ccache statistics
collect_ccache_stats() {
    if ! command -v ccache &>/dev/null; then
        echo "    \"ccache\": null,"
        return
    fi

    local stats=$(ccache -s 2>/dev/null)

    local cache_size=$(echo "$stats" | grep "cache size" | awk '{print $3 " " $4}' | head -n1 || echo "unknown")
    local cache_hits=$(echo "$stats" | grep "cache hit" | grep -v "rate" | awk '{print $3}' | head -n1 || echo "0")
    local cache_miss=$(echo "$stats" | grep "cache miss" | awk '{print $3}' | head -n1 || echo "0")
    local hit_rate=$(echo "$stats" | grep "hit rate" | awk '{print $4}' || echo "0")

    echo "    \"ccache\": {"
    echo "      \"cache_size\": \"$cache_size\","
    echo "      \"hits\": $cache_hits,"
    echo "      \"misses\": $cache_miss,"
    echo "      \"hit_rate\": \"$hit_rate\""
    echo "    },"
}

# Collect code statistics
collect_code_stats() {
    local cpp_files=$(find internal/core/src -name '*.cpp' 2>/dev/null | wc -l || echo "0")
    local go_files=$(find internal cmd pkg -name '*.go' 2>/dev/null | wc -l || echo "0")
    local proto_files=$(find build/proto -name '*.proto' 2>/dev/null | wc -l || echo "0")

    echo "    \"codebase\": {"
    echo "      \"cpp_files\": $cpp_files,"
    echo "      \"go_files\": $go_files,"
    echo "      \"proto_files\": $proto_files"
    echo "    },"
}

# Collect build artifacts size
collect_artifacts_stats() {
    local bin_size="0"
    local lib_size="0"

    if [ -d "bin" ]; then
        bin_size=$(du -sh bin 2>/dev/null | awk '{print $1}' || echo "0")
    fi

    if [ -d "lib" ]; then
        lib_size=$(du -sh lib 2>/dev/null | awk '{print $1}' || echo "0")
    fi

    echo "    \"artifacts\": {"
    echo "      \"bin_size\": \"$bin_size\","
    echo "      \"lib_size\": \"$lib_size\""
    echo "    },"
}

# Collect git information
collect_git_info() {
    local commit=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    local branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

    echo "    \"git\": {"
    echo "      \"commit\": \"$commit\","
    echo "      \"branch\": \"$branch\""
    echo "    },"
}

# Time a build command and collect metrics
time_build() {
    local build_name=$1
    local build_cmd=$2

    echo ""
    echo -e "${BLUE}⏱  Timing: $build_name${NC}"
    echo ""

    local start_time=$(date +%s)

    # Run the build command
    eval "$build_cmd"

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local formatted_duration=$(format_duration $duration)

    echo ""
    echo -e "${GREEN}✓${NC} $build_name completed in $formatted_duration"

    # Append to metrics log
    echo "$(date -Iseconds) | $build_name | ${duration}s" >> "$METRICS_LOG"

    return $duration
}

# Generate full metrics report
generate_metrics_report() {
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  Build Performance Metrics"
    echo "═══════════════════════════════════════════════════════"
    echo ""

    # Generate JSON report
    cat > "$METRICS_FILE" <<EOF
{
  "timestamp": "$(date -Iseconds)",
$(collect_system_info)
$(collect_ccache_stats)
$(collect_code_stats)
$(collect_artifacts_stats)
$(collect_git_info)
  "build_history": []
}
EOF

    # Display summary
    echo "System Information:"
    echo "─────────────────────────────────────────────────────"

    if command -v nproc &>/dev/null; then
        echo "  CPU Cores:    $(nproc)"
    fi

    if command -v free &>/dev/null; then
        echo "  Memory:       $(free -h | awk '/^Mem:/{print $2}')"
    fi

    echo ""
    echo "Codebase Statistics:"
    echo "─────────────────────────────────────────────────────"
    echo "  C++ Files:    $(find internal/core/src -name '*.cpp' 2>/dev/null | wc -l || echo '0')"
    echo "  Go Files:     $(find internal cmd pkg -name '*.go' 2>/dev/null | wc -l || echo '0')"
    echo "  Proto Files:  $(find build/proto -name '*.proto' 2>/dev/null | wc -l || echo '0')"

    echo ""
    echo "Build Artifacts:"
    echo "─────────────────────────────────────────────────────"

    if [ -d "bin" ]; then
        echo "  Binaries:     $(du -sh bin 2>/dev/null | awk '{print $1}' || echo '0')"
    fi

    if [ -d "lib" ]; then
        echo "  Libraries:    $(du -sh lib 2>/dev/null | awk '{print $1}' || echo '0')"
    fi

    if command -v ccache &>/dev/null; then
        echo ""
        echo "ccache Statistics:"
        echo "─────────────────────────────────────────────────────"

        ccache -s | grep -E "(cache size|cache hit|hit rate)" | sed 's/^/  /'
    fi

    echo ""
    echo "Build History (last 10 builds):"
    echo "─────────────────────────────────────────────────────"

    if [ -f "$METRICS_LOG" ]; then
        tail -n 10 "$METRICS_LOG" | while IFS='|' read -r timestamp name duration; do
            echo "  $timestamp | $name | $duration"
        done
    else
        echo "  (no build history)"
    fi

    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  Metrics saved to: $METRICS_FILE"
    echo "  Build log:        $METRICS_LOG"
    echo "═══════════════════════════════════════════════════════"
    echo ""
}

# Show quick statistics
show_quick_stats() {
    echo ""
    echo "Quick Build Statistics:"
    echo "─────────────────────────────────────────────────────"

    if [ -f "$METRICS_LOG" ]; then
        echo "  Total builds: $(wc -l < "$METRICS_LOG")"

        local last_build=$(tail -n 1 "$METRICS_LOG")
        if [ -n "$last_build" ]; then
            local last_duration=$(echo "$last_build" | awk -F'|' '{print $3}' | tr -d ' ')
            local last_name=$(echo "$last_build" | awk -F'|' '{print $2}' | tr -d ' ')
            echo "  Last build:   $last_name ($last_duration)"
        fi

        # Average build time
        local avg_duration=$(awk -F'|' '{sum+=$3; count++} END {if(count>0) print int(sum/count); else print 0}' "$METRICS_LOG" | tr -d 's ')
        if [ "$avg_duration" -gt 0 ]; then
            echo "  Average time: $(format_duration $avg_duration)"
        fi
    else
        echo "  No build history available"
    fi

    if command -v ccache &>/dev/null; then
        local hit_rate=$(ccache -s | grep "hit rate" | awk '{print $4}' || echo "0%")
        echo "  ccache hit:   $hit_rate"
    fi

    echo ""
}

# Main menu
main() {
    case "${1:-report}" in
        report)
            generate_metrics_report
            ;;
        quick)
            show_quick_stats
            ;;
        time)
            shift
            time_build "$@"
            ;;
        *)
            echo "Usage: $0 [report|quick|time <name> <command>]"
            echo ""
            echo "Commands:"
            echo "  report          - Generate full metrics report (default)"
            echo "  quick           - Show quick statistics"
            echo "  time NAME CMD   - Time a build command"
            echo ""
            echo "Examples:"
            echo "  $0 report"
            echo "  $0 quick"
            echo "  $0 time 'Full Build' 'make milvus'"
            exit 1
            ;;
    esac
}

# Run if executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    cd "$ROOT_DIR"
    main "$@"
fi
