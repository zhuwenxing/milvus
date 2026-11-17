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
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/cockroachdb/errors"

	"github.com/milvus-io/milvus/client/v3/milvusclient"
)

const maximumOfferedQPS = 100000.0

// These criteria validate a load generator's delivery, not a service latency SLA.
const maximumDispatchP99 = .05

type capacityTrial struct {
	Scale                float64                   `json:"scale"`
	Workers              int                       `json:"workers_per_operation"`
	Confirmation         bool                      `json:"confirmation"`
	Start                float64                   `json:"start"`
	End                  float64                   `json:"end"`
	Accepted             bool                      `json:"accepted"`
	DeliveryLimited      bool                      `json:"delivery_limited"`
	Reasons              []string                  `json:"reasons"`
	Rates                map[string]float64        `json:"offered_qps"`
	Operations           map[string]operationStats `json:"operations"`
	RunnerCPUFraction    *float64                  `json:"runner_cpu_quota_fraction"`
	RunnerCPUObservation string                    `json:"runner_cpu_observation"`
}

// cgroups describe the generator container's CPU use, including its Go runtime.
// Unsupported hosts retain an explicit observation gap rather than a zero value.
func runnerCPU() (usage, quota float64, err error) {
	data, err := os.ReadFile("/sys/fs/cgroup/cpu.stat")
	if err != nil {
		return runnerCPUv1()
	}
	fields := strings.Fields(string(data))
	found := false
	for i := 0; i+1 < len(fields); i += 2 {
		if fields[i] == "usage_usec" {
			usage, err = strconv.ParseFloat(fields[i+1], 64)
			if err != nil {
				return 0, 0, err
			}
			found = true
		}
	}
	if !found {
		return 0, 0, fmt.Errorf("cgroup CPU usage unavailable")
	}
	data, err = os.ReadFile("/sys/fs/cgroup/cpu.max")
	if err != nil {
		return 0, 0, err
	}
	fields = strings.Fields(string(data))
	if len(fields) != 2 || fields[0] == "max" {
		return 0, 0, fmt.Errorf("bounded cgroup CPU quota unavailable")
	}
	limit, err := strconv.ParseFloat(fields[0], 64)
	if err != nil {
		return 0, 0, err
	}
	period, err := strconv.ParseFloat(fields[1], 64)
	if err != nil || period <= 0 || limit <= 0 {
		return 0, 0, fmt.Errorf("invalid cgroup CPU quota")
	}
	return usage / 1e6, limit / period, nil
}

func runnerCPUv1() (usage, quota float64, err error) {
	read := func(path string) (float64, error) {
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return 0, readErr
		}
		return strconv.ParseFloat(strings.TrimSpace(string(data)), 64)
	}
	usage, err = read("/sys/fs/cgroup/cpuacct/cpuacct.usage")
	if err != nil {
		return 0, 0, err
	}
	limit, err := read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
	if err != nil {
		return 0, 0, err
	}
	period, err := read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
	if err != nil || limit <= 0 || period <= 0 {
		return 0, 0, fmt.Errorf("bounded cgroup v1 CPU quota unavailable")
	}
	return usage / 1e9, limit / period, nil
}

func workloadRates(cfg experimentConfig) map[string]float64 {
	return map[string]float64{"search": cfg.SearchQPS, "query": cfg.QueryQPS, "insert": cfg.InsertQPS}
}

func (e *experiment) capacityMetrics(ctx context.Context, output string) error {
	data, err := kubectl(ctx, nil, "get", "--raw", "/apis/metrics.k8s.io/v1beta1/namespaces/"+e.cfg.Namespace+"/pods")
	observation := map[string]any{"observed_at": time.Now().UTC(), "interpretation": "Metrics API rolling window, not peak CPU or proof of saturation"}
	if err != nil {
		observation["unavailable"] = err.Error()
	} else {
		var list struct {
			Items []json.RawMessage `json:"items"`
		}
		if err = json.Unmarshal(data, &list); err != nil {
			return err
		}
		selected := []json.RawMessage{}
		for _, item := range list.Items {
			var identity struct {
				Metadata struct {
					Name string `json:"name"`
				} `json:"metadata"`
			}
			if err = json.Unmarshal(item, &identity); err != nil {
				return err
			}
			if strings.HasPrefix(identity.Metadata.Name, e.cfg.Release+"-") || identity.Metadata.Name == os.Getenv("HOSTNAME") {
				selected = append(selected, item)
			}
		}
		observation["items"] = selected
	}
	return writeJSON(filepath.Join(output, "pod-metrics.json"), observation)
}

// Evaluate the arrival cohort only after workers drain. In-flight calls cannot
// disappear from the capacity decision just because they finish after the window.
func evaluateCapacity(rows []sample, start, end float64, rates map[string]float64) capacityTrial {
	trial := capacityTrial{Start: start, End: end, Accepted: true, Rates: rates, Operations: map[string]operationStats{}}
	for op, rate := range rates {
		cohort := []sample{}
		for _, row := range rows {
			if row.Operation == op && row.Scheduled >= start && row.Scheduled < end {
				cohort = append(cohort, row)
			}
		}
		observed := stats(cohort, end-start)
		observed.Scheduled = len(cohort)
		observed.Dispatched = observed.Sent
		trial.Operations[op] = observed
		if end <= start || len(cohort) < max(1, int(math.Floor((end-start)*rate))-1) {
			trial.Reasons = append(trial.Reasons, op+": arrival slots missing")
			trial.DeliveryLimited = true
		}
		if observed.Dropped > 0 {
			trial.Reasons = append(trial.Reasons, op+": unsent arrivals")
			trial.DeliveryLimited = true
		}
		if observed.Succeeded != observed.Sent || observed.Succeeded == 0 {
			trial.Reasons = append(trial.Reasons, op+": unsuccessful calls")
		}
		if observed.DispatchP99 == nil || *observed.DispatchP99 > maximumDispatchP99 {
			trial.Reasons = append(trial.Reasons, op+": dispatch p99 exceeds 50ms")
			trial.DeliveryLimited = true
		}
	}
	trial.Accepted = len(trial.Reasons) == 0
	return trial
}

func nextCapacityScale(low, high, current, ceiling float64) (float64, bool) {
	if high == 0 {
		return min(current*2, ceiling), current >= ceiling
	}
	if low == 0 {
		return current / 2, false
	}
	return (low + high) / 2, high/low <= 1.1
}

func (e *experiment) capacityTrial(ctx context.Context, number int, scale float64, confirmation bool, logf func(string, ...any)) (result capacityTrial, err error) {
	cfg := e.cfg
	cfg.Output = filepath.Join(cfg.Output, "calibration", fmt.Sprintf("trial-%02d", number))
	cfg.SearchQPS *= scale
	cfg.QueryQPS *= scale
	cfg.InsertQPS *= scale
	if err = os.MkdirAll(cfg.Output, 0o700); err != nil {
		return result, err
	}
	trial := &experiment{cfg: cfg, client: e.client, collection: fmt.Sprintf("%s_cal_%02d", e.collection, number), origin: e.origin}
	load, err := newTraffic(trial)
	if err != nil {
		return result, err
	}
	defer func() {
		err = errors.Join(err, load.stop())
		cleanupCtx, cancel := context.WithTimeout(context.Background(), time.Minute)
		defer cancel()
		err = errors.Join(err, e.client.DropCollection(cleanupCtx, milvusclient.NewDropCollectionOption(trial.collection)))
	}()
	if err = load.prepare(ctx); err != nil {
		return result, err
	}
	if err = writeJSON(filepath.Join(cfg.Output, "config.json"), cfg); err != nil {
		return result, err
	}
	seconds := cfg.CalibrationSeconds
	if confirmation {
		seconds = max(60, cfg.BaselineSeconds)
	}
	logf("capacity trial %d: scale=%.3f rates=%v workers=%d confirmation=%t", number, scale, workloadRates(cfg), cfg.Workers, confirmation)
	load.start()
	if err = wait(ctx, 5*time.Second); err != nil {
		return result, err
	}
	start := e.now()
	cpuBefore, cpuQuota, cpuErr := runnerCPU()
	if err = wait(ctx, time.Duration(seconds)*time.Second); err != nil {
		return result, err
	}
	end := e.now()
	cpuAfter, _, cpuAfterErr := runnerCPU()
	// Let the scheduler account for the final arrival slots before stopping it.
	if err = wait(ctx, time.Second); err != nil {
		return result, err
	}
	if err = load.stop(); err != nil {
		return result, err
	}
	if err = e.capacityMetrics(ctx, cfg.Output); err != nil {
		return result, err
	}
	result = evaluateCapacity(load.snapshot(), start, end, workloadRates(cfg))
	result.Scale, result.Workers, result.Confirmation = scale, cfg.Workers, confirmation
	result.RunnerCPUObservation = "unavailable; server saturation cannot be inferred from this trial"
	if cpuErr == nil && cpuAfterErr == nil && cpuAfter >= cpuBefore {
		result.RunnerCPUFraction = new((cpuAfter - cpuBefore) / (end - start) / cpuQuota)
		result.RunnerCPUObservation = "cgroup averaged generator CPU / quota, not peak CPU"
		if *result.RunnerCPUFraction >= .85 {
			result.Accepted = false
			result.Reasons = append(result.Reasons, "generator CPU headroom below 15 percent; capacity inconclusive")
		}
	}
	if err = writeJSON(filepath.Join(cfg.Output, "result.json"), result); err != nil {
		return result, err
	}
	// Failed load requests may have unknown outcomes. Reconcile them independently
	// before dropping the calibration collection, including rejected trials.
	if err = load.verify(ctx); err != nil {
		return result, err
	}
	logf("capacity trial %d: accepted=%t reasons=%v", number, result.Accepted, result.Reasons)
	return result, nil
}

func (e *experiment) calibrate(ctx context.Context, logf func(string, ...any)) (err error) {
	original := e.cfg
	ceiling := min(e.cfg.CalibrationMaxScale, maximumOfferedQPS/max(e.cfg.SearchQPS, e.cfg.QueryQPS, e.cfg.InsertQPS))
	low, high, current := 0.0, 0.0, 1.0
	trials := []capacityTrial{}
	status := "incomplete"
	defer func() {
		var selected map[string]float64
		if status == "confirmed" {
			selected = workloadRates(e.cfg)
		}
		err = errors.Join(err, writeJSON(filepath.Join(original.Output, "capacity.json"), map[string]any{
			"status": status, "original_rates": workloadRates(original), "selected_rates": selected,
			"selected_scale": low, "rejected_scale": high, "search_ceiling_scale": ceiling, "trials": trials,
			"relative_bracket_tolerance": .1, "dispatch_p99_limit_seconds": maximumDispatchP99,
			"definition":  "Highest confirmed stable offered mixed rate found in this bounded search; 100% of that rate is used during the fault. Arrival cohorts must have no failures/drops/missing slots and dispatch p99 <= 50ms. No service SLA asserted.",
			"limitations": "Capacity is specific to this corpus, mix, deadline, runner and server resources. A client-delivery boundary does not prove server saturation. Raw histories and rejected trials are retained. Each trial uses a fresh equivalent collection.",
		}))
	}()
	for len(trials) < 20 {
		if min(original.SearchQPS, original.QueryQPS, original.InsertQPS)*current < 1 {
			status = "no_stable_rate"
			return fmt.Errorf("no stable mixed rate found")
		}
		trial, trialErr := e.capacityTrial(ctx, len(trials)+1, current, false, logf)
		trials = append(trials, trial)
		if trialErr != nil {
			return trialErr
		}
		if trial.RunnerCPUFraction != nil && *trial.RunnerCPUFraction >= .85 {
			status = "generator_cpu_limited"
			return fmt.Errorf("generator CPU capacity limits calibration; no fault injected")
		}
		if !trial.Accepted && trial.DeliveryLimited && e.cfg.Workers < 256 {
			// Retry the same rate with a larger pool before treating a client queue
			// boundary as a capacity boundary. Never shrink offered load silently.
			e.cfg.Workers = min(256, e.cfg.Workers*2)
			high = 0 // A rejected boundary from a smaller worker pool is no longer valid.
			logf("retrying capacity trial at the same offered rate with %d workers", e.cfg.Workers)
			continue
		}
		if trial.Accepted {
			low = current
		} else {
			high = current
		}
		next, done := nextCapacityScale(low, high, current, ceiling)
		if done {
			if high == 0 {
				status = "search_ceiling_reached"
				return fmt.Errorf("capacity remains above search ceiling; increase calibration_max_scale or initial QPS; no fault injected")
			}
			break
		}
		current = next
	}
	if low == 0 || high == 0 || high/low > 1.1 {
		status = "search_budget_exhausted"
		return fmt.Errorf("capacity search did not converge; no fault injected")
	}
	for range 3 {
		trial, trialErr := e.capacityTrial(ctx, len(trials)+1, low, true, logf)
		trials = append(trials, trial)
		if trialErr != nil {
			return trialErr
		}
		if trial.Accepted {
			e.cfg.SearchQPS = original.SearchQPS * low
			e.cfg.QueryQPS = original.QueryQPS * low
			e.cfg.InsertQPS = original.InsertQPS * low
			status = "confirmed"
			return writeJSON(filepath.Join(original.Output, "effective-config.json"), e.cfg)
		}
		high = low
		low *= .95
	}
	status = "confirmation_failed"
	return fmt.Errorf("capacity confirmation failed; no fault injected")
}
