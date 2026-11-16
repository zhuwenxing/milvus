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
	"os"
	"path/filepath"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"

	"github.com/milvus-io/milvus-proto/go-api/v3/milvuspb"
	"github.com/milvus-io/milvus/client/v3/milvusclient"
)

type experimentConfig struct {
	Address         string   `json:"address"`
	Namespace       string   `json:"namespace"`
	Release         string   `json:"release"`
	Output          string   `json:"output"`
	Groups          []string `json:"groups"`
	Fault           string   `json:"fault"`
	Scope           string   `json:"scope"`
	Component       string   `json:"component"`
	TargetGroup     string   `json:"target_group"`
	BaselineSeconds int      `json:"baseline_seconds"`
	FaultSeconds    int      `json:"fault_seconds"`
	RecoverySeconds int      `json:"recovery_seconds"`
	StableSeconds   int      `json:"stable_seconds"`
	RequestTimeout  float64  `json:"request_timeout"`
	SearchQPS       float64  `json:"search_qps"`
	QueryQPS        float64  `json:"query_qps"`
	InsertQPS       float64  `json:"insert_qps"`
	Workers         int      `json:"workers"`
}

type experiment struct {
	cfg          experimentConfig
	client       *milvusclient.Client
	collection   string
	origin       time.Time
	events       map[string]float64
	faultName    string
	faultKind    string
	faultCreated bool
	faultTargets []string
	traffic      *traffic
}

func (e *experiment) now() float64 { return time.Since(e.origin).Seconds() }
func (e *experiment) event(name string) error {
	e.events[name] = e.now()
	return writeJSON(filepath.Join(e.cfg.Output, "events.json"), e.events)
}

func writeJSON(path string, value any) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()
	encoder := json.NewEncoder(file)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

func readConfig() (experimentConfig, error) {
	var cfg experimentConfig
	path := os.Getenv("HA_CONFIG_FILE")
	if path == "" {
		return cfg, fmt.Errorf("set HA_CONFIG_FILE for this isolated L3 high-availability scenario")
	}
	file, err := os.Open(path)
	if err != nil {
		return cfg, err
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&cfg); err != nil {
		return cfg, err
	}
	if cfg.Namespace != "chaos-testing" || !regexp.MustCompile(`^ha-[a-z0-9-]{1,40}$`).MatchString(cfg.Release) {
		return cfg, fmt.Errorf("use an isolated ha-* release in chaos-testing")
	}
	if cfg.Address == "" || cfg.Output == "" || len(cfg.Groups) < 1 || len(cfg.Groups) > 2 || cfg.Groups[0] != "rg1" || (len(cfg.Groups) == 2 && cfg.Groups[1] != "rg2") {
		return cfg, fmt.Errorf("address, output and one/two explicit resource groups are required")
	}
	if cfg.BaselineSeconds < cfg.StableSeconds || cfg.RecoverySeconds < cfg.StableSeconds || cfg.StableSeconds < 5 || cfg.BaselineSeconds > 1800 || cfg.RecoverySeconds > 1800 || cfg.FaultSeconds < 1 || cfg.FaultSeconds > 600 || cfg.RequestTimeout <= 0 || cfg.RequestTimeout > 30 || cfg.Workers < 1 || cfg.Workers > 256 {
		return cfg, fmt.Errorf("invalid bounded timing or worker parameters")
	}
	for _, qps := range []float64{cfg.SearchQPS, cfg.QueryQPS, cfg.InsertQPS} {
		if qps < 1 || qps > 10000 {
			return cfg, fmt.Errorf("QPS must be in [1, 10000]")
		}
	}
	if cfg.Scope != "worker" && cfg.Scope != "replica" {
		return cfg, fmt.Errorf("unknown fault scope")
	}
	if cfg.TargetGroup == "" {
		cfg.TargetGroup = cfg.Groups[0]
	}
	if cfg.TargetGroup != cfg.Groups[0] && (len(cfg.Groups) < 2 || cfg.TargetGroup != cfg.Groups[1]) {
		return cfg, fmt.Errorf("target group must belong to this deployment")
	}
	if cfg.Component != "querynode" && cfg.Component != "streamingnode" {
		return cfg, fmt.Errorf("unknown worker component")
	}
	switch cfg.Fault {
	case "pod-failure", "pod-kill", "network-delay", "network-loss":
	default:
		return cfg, fmt.Errorf("unsupported fault")
	}
	return cfg, nil
}

// TestSingleFaultRecovery is an opt-in L3 system test. No service SLA is assumed.
func TestSingleFaultRecovery(t *testing.T) {
	if os.Getenv("HA_CONFIG_FILE") == "" {
		t.Skip("HA_CONFIG_FILE is required for the opt-in HA experiment")
	}
	cfg, err := readConfig()
	require.NoError(t, err)
	require.NoError(t, os.MkdirAll(cfg.Output, 0o700))
	ctx, cancel := context.WithTimeout(t.Context(), 60*time.Minute)
	defer cancel()
	// The public GetServerVersion method returns only the version string. Preserve
	// the connection handshake's build/commit identity without recording auth data.
	identity := func(ctx context.Context, method string, req, reply any, cc *grpc.ClientConn, invoker grpc.UnaryInvoker, options ...grpc.CallOption) error {
		if err := invoker(ctx, method, req, reply, cc, options...); err != nil {
			return err
		}
		if connected, ok := reply.(*milvuspb.ConnectResponse); ok {
			return writeJSON(filepath.Join(cfg.Output, "server-info.json"), connected.GetServerInfo())
		}
		return nil
	}
	client, err := milvusclient.New(ctx, &milvusclient.ClientConfig{Address: cfg.Address, APIKey: os.Getenv("MILVUS_TOKEN"), DialOptions: []grpc.DialOption{grpc.WithChainUnaryInterceptor(identity)}})
	require.NoError(t, err)
	e := &experiment{cfg: cfg, client: client, collection: fmt.Sprintf("HA_%d", time.Now().UnixNano()), origin: time.Now(), events: map[string]float64{}, faultName: fmt.Sprintf("ha-%d", time.Now().UnixNano())}
	t.Cleanup(func() {
		cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), 3*time.Minute)
		defer cleanupCancel()
		if e.faultCreated {
			if err := e.removeFault(cleanupCtx); err != nil {
				t.Errorf("fault cleanup: %v", err)
			}
		}
		if e.traffic != nil {
			if err := e.traffic.stop(); err != nil {
				t.Errorf("traffic cleanup: %v", err)
			}
		}
		if err := client.DropCollection(cleanupCtx, milvusclient.NewDropCollectionOption(e.collection)); err != nil {
			t.Errorf("collection cleanup: %v", err)
		}
		if err := client.Close(cleanupCtx); err != nil {
			t.Errorf("client cleanup: %v", err)
		}
	})
	e.traffic, err = newTraffic(e)
	require.NoError(t, err)
	require.NoError(t, e.traffic.prepare(ctx))
	ready := false
	for deadline := time.Now().Add(2 * time.Minute); time.Now().Before(deadline); {
		probeCtx, probeCancel := context.WithTimeout(ctx, 15*time.Second)
		ready, err = e.topology(probeCtx, "before")
		probeCancel()
		if err == nil && ready {
			break
		}
		t.Logf("waiting for replica/RG topology: ready=%t, error=%v", ready, err)
		require.NoError(t, wait(ctx, 5*time.Second))
	}
	require.NoError(t, err)
	require.True(t, ready, "loaded replica topology must be healthy before injection")
	version, err := client.GetServerVersion(ctx, milvusclient.NewGetServerVersionOption())
	require.NoError(t, err)
	require.NoError(t, writeJSON(filepath.Join(cfg.Output, "run.json"), map[string]any{"config": cfg, "server_version": version, "clock_epoch": e.origin.UTC(), "collection": e.collection, "load_generator": "Go SDK; open-loop schedule; bounded workers per operation; SDK retries included in RPC latency"}))
	e.traffic.start()
	require.NoError(t, e.event("baseline_started"))
	require.NoError(t, wait(ctx, time.Duration(cfg.BaselineSeconds)*time.Second))
	require.NoError(t, e.traffic.baselineCheck())
	require.NoError(t, e.event("fault_requested"))
	require.NoError(t, e.createFault(ctx))
	require.NoError(t, e.waitFault(ctx, "AllInjected", 45*time.Second))
	require.NoError(t, e.event("fault_injected_observed"))
	for e.now()-e.events["fault_requested"] < float64(cfg.FaultSeconds) {
		probeCtx, probeCancel := context.WithTimeout(ctx, 5*time.Second)
		_, probeErr := e.topology(probeCtx, fmt.Sprintf("during-%.0f", e.now()))
		probeCancel()
		if probeErr != nil {
			t.Logf("fault topology observation: %v", probeErr)
		}
		require.NoError(t, wait(ctx, time.Second))
	}
	require.NoError(t, e.event("fault_removal_requested"))
	require.NoError(t, e.pauseFault(ctx))
	require.NoError(t, e.waitFault(ctx, "AllRecovered", 90*time.Second))
	require.NoError(t, e.event("fault_recovered"))
	end := time.Now().Add(time.Duration(cfg.RecoverySeconds) * time.Second)
	for time.Now().Before(end) {
		probeCtx, probeCancel := context.WithTimeout(ctx, 15*time.Second)
		ready, probeErr := e.topology(probeCtx, fmt.Sprintf("recovery-%.0f", e.now()))
		probeCancel()
		if probeErr == nil && ready {
			if _, exists := e.events["topology_ready_observed"]; !exists {
				require.NoError(t, e.event("topology_ready_observed"))
			}
		} else if probeErr != nil {
			t.Logf("topology observation: %v", probeErr)
		}
		require.NoError(t, wait(ctx, min(5*time.Second, time.Until(end))))
	}
	require.NoError(t, e.traffic.stop())
	require.NoError(t, e.event("load_ended"))
	measured, err := e.report()
	require.NoError(t, err)
	require.NoError(t, e.traffic.verify(ctx))
	ready, err = e.topology(ctx, "final")
	require.NoError(t, err)
	t.Logf("observation budget ended: service recovery observed=%t, all observed pods and replica metadata ready=%t; no SLA threshold applied", measured, ready)
}

func wait(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(max(0, duration))
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
