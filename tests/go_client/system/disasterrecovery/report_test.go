// Copyright 2026 LF AI & Data foundation
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//go:build L3

package disasterrecovery

import (
	"encoding/csv"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
)

type operationStats struct {
	Scheduled     int      `json:"scheduled"`
	Dispatched    int      `json:"dispatched"`
	Completed     int      `json:"completed_logical_operations"`
	Sent          int      `json:"completed_rpc_calls"`
	Succeeded     int      `json:"succeeded"`
	Dropped       int      `json:"generator_dropped"`
	SuccessRate   *float64 `json:"rpc_success_rate"`
	P50           *float64 `json:"p50_seconds"`
	P95           *float64 `json:"p95_seconds"`
	P99           *float64 `json:"p99_seconds"`
	DispatchP99   *float64 `json:"dispatch_delay_p99_seconds"`
	SuccessfulRPS float64  `json:"successful_rps"`
}

func quantile(values []float64, q float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	ordered := slices.Clone(values)
	slices.Sort(ordered)
	return new(ordered[max(0, int(math.Ceil(float64(len(ordered))*q))-1)])
}

func stats(rows []sample, seconds float64) operationStats {
	result := operationStats{Completed: len(rows)}
	latencies, delays := []float64{}, []float64{}
	for _, r := range rows {
		if r.Sent {
			result.Sent++
			delays = append(delays, r.Start-r.Scheduled)
		} else {
			result.Dropped++
		}
		if r.Success {
			result.Succeeded++
			latencies = append(latencies, r.Latency)
		}
	}
	if result.Sent > 0 {
		result.SuccessRate = new(float64(result.Succeeded) / float64(result.Sent))
	}
	result.P50 = quantile(latencies, .5)
	result.P95 = quantile(latencies, .95)
	result.P99 = quantile(latencies, .99)
	result.DispatchP99 = quantile(delays, .99)
	if seconds > 0 {
		result.SuccessfulRPS = float64(result.Succeeded) / seconds
	}
	return result
}

// Arrival, dispatch and completion counters use their own clocks. A slow RPC
// may be offered in one bucket and finish in another; neither count is lost.
func windowStats(rows []sample, start, end float64) operationStats {
	completed := []sample{}
	offered, dispatched := 0, 0
	for _, r := range rows {
		if r.End >= start && r.End < end {
			completed = append(completed, r)
		}
		if r.Scheduled >= start && r.Scheduled < end {
			offered++
		}
		if r.Sent && r.Start >= start && r.Start < end {
			dispatched++
		}
	}
	result := stats(completed, end-start)
	result.Scheduled, result.Dispatched = offered, dispatched
	return result
}

type metricBucket struct {
	Start     float64 `json:"start"`
	End       float64 `json:"end"`
	Operation string  `json:"operation"`
	operationStats
}

func (e *experiment) report() (bool, error) {
	rows := e.traffic.snapshot()
	t0, removed, ended := e.events["fault_requested"], e.events["fault_recovered"], e.events["load_ended"]
	baselineStart := e.events["baseline_started"]
	groups := map[string][]sample{"search": {}, "query": {}, "insert": {}}
	for _, r := range rows {
		groups[r.Operation] = append(groups[r.Operation], r)
	}
	var recovery *float64
	stable := true
	service := map[string]any{}
	for op, opRows := range groups {
		observed, detail := serviceRecovery(opRows, t0, ended, e.cfg.StableSeconds)
		service[op] = detail
		if observed == nil {
			stable = false
		} else if recovery == nil || *observed > *recovery {
			recovery = observed
		}
	}
	if !stable {
		recovery = nil
	}
	buckets := []metricBucket{}
	phases := map[string]any{}
	for op, opRows := range groups {
		phases[op] = map[string]operationStats{"baseline": windowStats(opRows, baselineStart, t0), "fault": windowStats(opRows, t0, removed), "after_fault": windowStats(opRows, removed, ended)}
		for b := range int(math.Ceil((ended - baselineStart) / 5)) {
			begin := baselineStart + float64(b*5)
			end := min(begin+5, ended)
			buckets = append(buckets, metricBucket{Start: begin, End: end, Operation: op, operationStats: windowStats(opRows, begin, end)})
		}
	}
	performance, band := performanceRecovery(buckets, t0, ended, e.cfg.StableSeconds)
	summary := map[string]any{
		"measurement_only": true, "events": e.events, "phases": phases, "service_recovery_seconds": recovery, "service_recovery_observed": stable, "service_by_operation": service,
		"performance_recovery_seconds": performance, "performance_reference_band": band, "stable_window_seconds": e.cfg.StableSeconds,
		"recovery_definition": "Service recovery uses consecutive complete 5-second buckets with at least one success, no failed call or drop, and no uncovered sampling gap after the final degraded bucket; performance recovery uses baseline p90 of 5s p95 latency and p10 of successful RPS. These are observational definitions, not approved SLAs.",
		"limitations":         "A null recovery time is censored at the observation deadline. SDK internal retries are included in logical-call latency; raw RPC attempts are not measured. Topology Ready and configuration convergence are separate from durability. Whole resource-group fault is not proof of host/AZ outage tolerance.",
	}
	if err := writeJSON(filepath.Join(e.cfg.Output, "summary.json"), summary); err != nil {
		return false, err
	}
	if err := writeJSON(filepath.Join(e.cfg.Output, "timeseries.json"), buckets); err != nil {
		return false, err
	}
	if err := writeCSV(filepath.Join(e.cfg.Output, "timeseries.csv"), buckets, t0); err != nil {
		return false, err
	}
	return stable, writeChart(filepath.Join(e.cfg.Output, "impact.svg"), buckets, t0, removed)
}

// serviceRecovery reports the sustained tail, not the first isolated successful call.
// Buckets with no completed successful requests are unknown/unavailable observations.
func serviceRecovery(rows []sample, t0, end float64, window int) (*float64, map[string]any) {
	lastBad := t0
	var firstSuccess *float64
	errors, dropped, currentZero, longestZero := 0, 0, 0.0, 0.0
	for _, r := range rows {
		if r.End < t0 {
			continue
		}
		if r.Success && (firstSuccess == nil || r.End-t0 < *firstSuccess) {
			firstSuccess = new(r.End - t0)
		}
		if !r.Success {
			if r.Sent {
				errors++
			} else {
				dropped++
			}
		}
	}
	completeEnd := t0
	for b := range int((end - t0) / 5) {
		begin := t0 + float64(b*5)
		success, bad := 0, false
		for _, r := range rows {
			if r.End >= begin && r.End < begin+5 {
				if r.Success {
					success++
				} else {
					bad = true
				}
			}
			// A failed call that overlaps this bucket prevents declaring recovery.
			if !r.Success && r.Start < begin+5 && r.End >= begin {
				bad = true
			}
		}
		if success == 0 {
			currentZero += 5
			longestZero = max(longestZero, currentZero)
		} else {
			currentZero = 0
		}
		if success == 0 || bad {
			lastBad = begin + 5
		}
		completeEnd = begin + 5
	}
	var recovery *float64
	if completeEnd-lastBad >= float64(window) {
		recovery = new(lastBad - t0)
	}
	// A failure in the final partial bucket invalidates an otherwise stable tail.
	for _, r := range rows {
		if !r.Success && r.End >= completeEnd {
			recovery = nil
		}
	}
	return recovery, map[string]any{"recovery_seconds": recovery, "first_success_seconds": firstSuccess, "failed_calls": errors, "unsent_operations": dropped, "longest_complete_zero_success_bucket_run_seconds": longestZero, "resolution_seconds": 5}
}

func performanceRecovery(buckets []metricBucket, t0, end float64, window int) (*float64, map[string]any) {
	limits := map[string]any{}
	lastBad := t0
	for _, op := range []string{"search", "query", "insert"} {
		latencies, rates := []float64{}, []float64{}
		for _, b := range buckets {
			if b.Operation == op && b.End < t0 && b.End-b.Start >= 4.99 && b.P95 != nil {
				latencies = append(latencies, *b.P95)
				rates = append(rates, b.SuccessfulRPS)
			}
		}
		latency, rate := quantile(latencies, .9), quantile(rates, .1)
		limits[op] = map[string]any{"latency_p95_ceiling": latency, "successful_rps_floor": rate}
		if latency == nil || rate == nil || *rate == 0 {
			return nil, limits
		}
		for _, b := range buckets {
			if b.Operation == op && b.End > t0 && b.End-b.Start >= 4.99 && (b.P95 == nil || *b.P95 > *latency || b.SuccessfulRPS < *rate || b.Dropped > 0) {
				lastBad = max(lastBad, b.End)
			}
		}
	}
	if end-lastBad < float64(window) {
		return nil, limits
	}
	return new(lastBad - t0), limits
}

func number(value *float64) string {
	if value == nil {
		return ""
	}
	return strconv.FormatFloat(*value, 'f', 6, 64)
}

func writeCSV(path string, buckets []metricBucket, t0 float64) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()
	writer := csv.NewWriter(file)
	if err = writer.Write([]string{"seconds_from_fault", "operation", "scheduled", "dispatched", "completed_logical_operations", "completed_rpc_calls", "succeeded", "generator_dropped", "rpc_success_rate", "p50_s", "p95_s", "p99_s", "successful_rps", "dispatch_p99_s"}); err != nil {
		return err
	}
	for _, b := range buckets {
		if err = writer.Write([]string{fmt.Sprintf("%.3f", b.Start-t0), b.Operation, strconv.Itoa(b.Scheduled), strconv.Itoa(b.Dispatched), strconv.Itoa(b.Completed), strconv.Itoa(b.Sent), strconv.Itoa(b.Succeeded), strconv.Itoa(b.Dropped), number(b.SuccessRate), number(b.P50), number(b.P95), number(b.P99), fmt.Sprintf("%.3f", b.SuccessfulRPS), number(b.DispatchP99)}); err != nil {
			return err
		}
	}
	writer.Flush()
	return writer.Error()
}

func writeChart(path string, buckets []metricBucket, t0, removed float64) error {
	if len(buckets) == 0 {
		return fmt.Errorf("no observations to chart")
	}
	begin, end := buckets[0].Start, buckets[0].End
	for _, b := range buckets {
		begin = min(begin, b.Start)
		end = max(end, b.End)
	}
	colors := map[string]string{"search": "#2166ac", "query": "#1b9e77", "insert": "#d95f02"}
	var svg strings.Builder
	svg.WriteString(`<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="760" viewBox="0 0 1100 760"><rect width="1100" height="760" fill="white"/><g font-family="sans-serif" font-size="14">`)
	svg.WriteString(`<text x="70" y="25">Single-fault HA experiment: client observations (5-second buckets)</text>`)
	for panel, label := range []string{"RPC success fraction", "Successful request p95 latency (seconds)", "Successful requests / second"} {
		ymax := 1.0
		value := func(b metricBucket) *float64 {
			switch panel {
			case 0:
				return b.SuccessRate
			case 1:
				return b.P95
			default:
				return new(b.SuccessfulRPS)
			}
		}
		for _, b := range buckets {
			if v := value(b); v != nil {
				ymax = max(ymax, *v)
			}
		}
		top := float64(70 + panel*220)
		x := func(t float64) float64 { return 80 + 950*(t-begin)/(end-begin) }
		fmt.Fprintf(&svg, `<text x="80" y="%.1f">%s (max %.3g)</text><rect x="%.1f" y="%.1f" width="%.1f" height="160" fill="#fee"/><path d="M80 %.1f V%.1f H1030" fill="none" stroke="#777"/>`, top-10, label, ymax, x(t0), top, x(removed)-x(t0), top, top+160)
		for _, op := range []string{"search", "query", "insert"} {
			points := ""
			flush := func() {
				if points != "" {
					fmt.Fprintf(&svg, `<polyline points="%s" fill="none" stroke="%s" stroke-width="1.5"/>`, points, colors[op])
					points = ""
				}
			}
			for _, b := range buckets {
				if b.Operation != op {
					continue
				}
				v := value(b)
				if v == nil {
					flush()
					continue
				}
				points += fmt.Sprintf("%.1f,%.1f ", x(b.Start), top+160-160**v/ymax)
			}
			flush()
		}
		fmt.Fprintf(&svg, `<text x="80" y="%.1f">%.0fs</text><text x="%.1f" y="%.1f">fault requested</text><text x="980" y="%.1f">%.0fs</text>`, top+180, begin-t0, x(t0), top+180, top+180, end-t0)
	}
	svg.WriteString(`<text x="80" y="745" fill="#2166ac">search</text><text x="170" y="745" fill="#1b9e77">query</text><text x="260" y="745" fill="#d95f02">insert</text><text x="350" y="745">Shading: fault request to observed fault recovery. No SLA asserted.</text></g></svg>`)
	file, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = file.WriteString(svg.String())
	return err
}
