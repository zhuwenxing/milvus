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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/milvus-io/milvus/client/v3/entity"
	"github.com/milvus-io/milvus/client/v3/milvusclient"
)

type pod struct {
	Metadata struct {
		Name   string            `json:"name"`
		UID    string            `json:"uid"`
		Labels map[string]string `json:"labels"`
	} `json:"metadata"`
	Spec struct {
		NodeName string `json:"nodeName"`
	} `json:"spec"`
	Status struct {
		PodIP      string      `json:"podIP"`
		Conditions []condition `json:"conditions"`
	} `json:"status"`
}
type condition struct {
	Type   string `json:"type"`
	Status string `json:"status"`
}
type chaosStatus struct {
	Metadata struct {
		Labels map[string]string `json:"labels"`
	} `json:"metadata"`
	Status struct {
		Conditions []condition `json:"conditions"`
		Experiment struct {
			Records []struct {
				ID             string `json:"id"`
				InjectedCount  int    `json:"injectedCount"`
				RecoveredCount int    `json:"recoveredCount"`
				Phase          string `json:"phase"`
			} `json:"containerRecords"`
		} `json:"experiment"`
	} `json:"status"`
}

func kubectl(ctx context.Context, body any, args ...string) ([]byte, error) {
	callCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	// Arguments are constructed by this test; no shell or arbitrary command is accepted.
	command := exec.CommandContext(callCtx, "kubectl", append([]string{"--request-timeout=20s"}, args...)...) // #nosec G204
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		command.Stdin = bytes.NewReader(data)
	}
	var stderr bytes.Buffer
	command.Stderr = &stderr
	result, err := command.Output()
	if err != nil {
		return nil, fmt.Errorf("kubectl failed: %w: %s", err, stderr.String())
	}
	return result, nil
}

func (e *experiment) pods(ctx context.Context) ([]pod, error) {
	data, err := kubectl(ctx, nil, "-n", e.cfg.Namespace, "get", "pods", "-l", "app.kubernetes.io/instance="+e.cfg.Release, "-o", "json")
	if err != nil {
		return nil, err
	}
	var result struct {
		Items []pod `json:"items"`
	}
	err = json.Unmarshal(data, &result)
	return result.Items, err
}

func (e *experiment) topology(ctx context.Context, suffix string) (bool, error) {
	pods, err := e.pods(ctx)
	if err != nil {
		return false, err
	}
	// Capture WAL observations independently before SDK topology calls, which may
	// time out during the fault. Registration state is not an RPC health verdict.
	if err := e.observeStreaming(ctx, pods, suffix); err != nil {
		return false, err
	}
	replicas, err := e.client.DescribeReplica(ctx, milvusclient.NewDescribeReplicaOption(e.collection))
	if err != nil {
		return false, err
	}
	ready := len(pods) > 0 && len(replicas) == len(e.cfg.Groups)
	resourceGroups := map[string]*entity.ResourceGroup{}
	queryNodeGroups := map[int64]string{}
	for _, group := range e.cfg.Groups {
		rg, rgErr := e.client.DescribeResourceGroup(ctx, milvusclient.NewDescribeResourceGroupOption(group))
		if rgErr != nil {
			return false, rgErr
		}
		resourceGroups[group] = rg
		for _, node := range rg.Nodes {
			queryNodeGroups[node.NodeID] = group
		}
		if rg.NumAvailableNode == 0 || len(rg.Nodes) == 0 {
			ready = false
		}
	}
	groups := []string{}
	for _, replica := range replicas {
		groups = append(groups, replica.ResourceGroupName)
		if len(replica.Nodes) == 0 || len(replica.Shards) == 0 {
			ready = false
		}
		// DescribeReplica also includes streaming/WAL-serving nodes. The RG API's
		// membership list describes QueryNodes, so compare only known QueryNodes.
		queryNodes := 0
		for _, node := range replica.Nodes {
			if group, knownQueryNode := queryNodeGroups[node]; knownQueryNode {
				queryNodes++
				if group != replica.ResourceGroupName {
					ready = false
				}
			}
		}
		if queryNodes == 0 {
			ready = false
		}
		for _, shard := range replica.Shards {
			if shard.ShardLeader == 0 || len(shard.ShardNodes) == 0 {
				ready = false
			}
		}
	}
	slices.Sort(groups)
	if !slices.Equal(groups, e.cfg.Groups) {
		ready = false
	}
	var compliance any
	for _, p := range pods {
		if !hasCondition(p.Status.Conditions, "Ready") {
			ready = false
		}
		if p.Metadata.Labels["component"] == "mixcoord" && p.Status.PodIP != "" {
			// This is configuration convergence, not a general durability audit.
			request, reqErr := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+p.Status.PodIP+":9091/management/replica/loadconfig/compliance?output=per_resource_group", nil)
			if reqErr != nil {
				return false, reqErr
			}
			response, callErr := (&http.Client{Timeout: 3 * time.Second}).Do(request)
			if callErr != nil {
				compliance = map[string]string{"error": callErr.Error()}
			} else {
				var value map[string]any
				decodeErr := json.NewDecoder(response.Body).Decode(&value)
				response.Body.Close()
				compliance = map[string]any{"http_status": response.StatusCode, "body": value}
				if decodeErr == nil && response.StatusCode == http.StatusOK && value["state"] == "Ready" {
					if _, exists := e.events["replica_config_converged_observed"]; !exists && suffix != "before" {
						if err := e.event("replica_config_converged_observed"); err != nil {
							return false, err
						}
					}
				}
			}
		}
	}
	return ready, writeJSON(filepath.Join(e.cfg.Output, "topology-"+suffix+".json"), map[string]any{"elapsed": e.now(), "replicas": replicas, "resource_groups": resourceGroups, "pods": pods, "replica_config_compliance": compliance, "topology_ready": ready})
}

func managementJSON(ctx context.Context, endpoint string) map[string]any {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	response, err := (&http.Client{Timeout: 2 * time.Second}).Do(request)
	if err != nil {
		return map[string]any{"error": err.Error()}
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	result := map[string]any{"http_status": response.StatusCode}
	if err != nil {
		result["error"] = err.Error()
	} else if !json.Valid(body) {
		result["error"] = "non-JSON or oversized management response"
	} else {
		result["body"] = json.RawMessage(body)
	}
	return result
}

func (e *experiment) observeStreaming(ctx context.Context, pods []pod, suffix string) error {
	observations := []map[string]any{}
	for _, coordinator := range pods {
		if coordinator.Metadata.Labels["component"] != "mixcoord" || coordinator.Status.PodIP == "" {
			continue
		}
		endpoint := "http://" + net.JoinHostPort(coordinator.Status.PodIP, "9091")
		listing := managementJSON(ctx, endpoint+"/management/streaming/nodes")
		observation := map[string]any{"coordinator": coordinator.Metadata.Name, "listing": listing}
		var nodes struct {
			Nodes []struct {
				ID      int64  `json:"ID"`
				Address string `json:"address"`
				State   string `json:"state"`
			} `json:"nodeInfos"`
		}
		if body, ok := listing["body"].(json.RawMessage); ok && listing["http_status"] == http.StatusOK && json.Unmarshal(body, &nodes) == nil {
			placements := []map[string]any{}
			for _, node := range nodes.Nodes {
				host, _, splitErr := net.SplitHostPort(node.Address)
				placement := map[string]any{"node_id": node.ID, "registration_state": node.State, "resource_group": nil}
				for _, p := range pods {
					if splitErr == nil && p.Metadata.Labels["component"] == "streamingnode" && p.Status.PodIP == host {
						placement["resource_group"] = p.Metadata.Labels["milvus.io/resource-group"]
						placement["pod"] = p.Metadata.Name
						placement["uid"] = p.Metadata.UID
					}
				}
				placement["confirmed_assignments"] = managementJSON(ctx, fmt.Sprintf("%s/management/streaming/nodes/distribution?node_id=%d", endpoint, node.ID))
				placements = append(placements, placement)
			}
			observation["placements"] = placements
		}
		observations = append(observations, observation)
	}
	return writeJSON(filepath.Join(e.cfg.Output, "wal-"+suffix+".json"), map[string]any{"elapsed": e.now(), "observations": observations, "interpretation": "Registration active is not RPC health. Distribution lists confirmed ASSIGNED channels only; missing/unsupported responses are unavailable observations."})
}

func hasCondition(conditions []condition, name string) bool {
	return slices.ContainsFunc(conditions, func(c condition) bool { return c.Type == name && c.Status == "True" })
}

func (e *experiment) createFault(ctx context.Context) error {
	pods, err := e.pods(ctx)
	if err != nil {
		return err
	}
	selected := []string{}
	components := map[string]int{}
	peerPods := []pod{}
	for _, p := range pods {
		component := p.Metadata.Labels["component"]
		if p.Metadata.Labels["milvus.io/resource-group"] == e.cfg.TargetGroup && ((e.cfg.Scope == "replica" && (component == "querynode" || component == "streamingnode")) || (e.cfg.Scope == "worker" && component == e.cfg.Component)) {
			selected = append(selected, p.Metadata.Name)
			components[component]++
		} else {
			peerPods = append(peerPods, p)
		}
	}
	slices.Sort(selected)
	if len(selected) == 0 {
		return fmt.Errorf("no owned pods matched requested fault")
	}
	if e.cfg.Scope == "worker" {
		selected = selected[:1]
	} else if components["querynode"] == 0 || components["streamingnode"] == 0 {
		return fmt.Errorf("whole-RG fault requires both QueryNode and StreamingNode targets")
	}
	e.faultTargets = slices.Clone(selected)
	if err := writeJSON(filepath.Join(e.cfg.Output, "fault-targets.json"), map[string]any{"selected": selected, "pods_before": pods, "unselected_peers": peerPods, "target_group": e.cfg.TargetGroup, "primary_group": e.cfg.Groups[0]}); err != nil {
		return err
	}
	spec := map[string]any{"selector": map[string]any{"namespaces": []string{e.cfg.Namespace}, "pods": map[string]any{e.cfg.Namespace: selected}}, "mode": "all"}
	kind := "PodChaos"
	e.faultKind = "podchaos"
	switch e.cfg.Fault {
	case "pod-kill":
		spec["action"] = "pod-kill"
		spec["gracePeriod"] = 0
	case "pod-failure":
		spec["action"] = "pod-failure"
		spec["duration"] = fmt.Sprintf("%ds", e.cfg.FaultSeconds)
	default:
		kind = "NetworkChaos"
		e.faultKind = "networkchaos"
		spec["direction"] = "both"
		spec["duration"] = fmt.Sprintf("%ds", e.cfg.FaultSeconds)
		if e.cfg.Fault == "network-delay" {
			spec["action"] = "delay"
			spec["delay"] = map[string]string{"latency": "200ms", "jitter": "50ms"}
		} else {
			spec["action"] = "loss"
			spec["loss"] = map[string]string{"loss": "10"}
		}
	}
	manifest := map[string]any{"apiVersion": "chaos-mesh.org/v1alpha1", "kind": kind, "metadata": map[string]any{"name": e.faultName, "namespace": e.cfg.Namespace, "labels": map[string]string{"ha.milvus.io/release": e.cfg.Release}}, "spec": spec}
	if err := writeJSON(filepath.Join(e.cfg.Output, "fault-manifest.json"), manifest); err != nil {
		return err
	}
	e.faultCreated = true
	_, err = kubectl(ctx, manifest, "create", "-f", "-", "-o", "json")
	return err
}

func (e *experiment) faultStatus(ctx context.Context) (chaosStatus, []byte, error) {
	var status chaosStatus
	data, err := kubectl(ctx, nil, "-n", e.cfg.Namespace, "get", e.faultKind, e.faultName, "--ignore-not-found", "-o", "json")
	if err != nil {
		return status, nil, err
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return status, nil, nil
	}
	if err = json.Unmarshal(data, &status); err != nil {
		return status, nil, err
	}
	if status.Metadata.Labels["ha.milvus.io/release"] != e.cfg.Release {
		return status, nil, fmt.Errorf("fault ownership mismatch")
	}
	return status, data, nil
}

func (e *experiment) waitFault(ctx context.Context, desired string, budget time.Duration) error {
	until := time.Now().Add(budget)
	for time.Now().Before(until) {
		status, raw, err := e.faultStatus(ctx)
		if err != nil {
			return err
		}
		if err = writeJSON(filepath.Join(e.cfg.Output, fmt.Sprintf("fault-status-%.3f.json", e.now())), map[string]any{"elapsed": e.now(), "resource": json.RawMessage(raw)}); err != nil {
			return err
		}
		if hasCondition(status.Status.Conditions, desired) {
			if desired == "AllInjected" {
				if len(status.Status.Experiment.Records) == 0 {
					return fmt.Errorf("AllInjected without target records")
				}
				seen := map[string]bool{}
				for _, record := range status.Status.Experiment.Records {
					parts := strings.Split(record.ID, "/")
					if record.InjectedCount == 0 || len(parts) < 2 || parts[0] != e.cfg.Namespace || !slices.Contains(e.faultTargets, parts[1]) {
						return fmt.Errorf("fault target not verified: %s", record.ID)
					}
					seen[parts[1]] = true
				}
				if len(seen) != len(e.faultTargets) {
					return fmt.Errorf("only %d of %d intended pods received the fault", len(seen), len(e.faultTargets))
				}
			}
			return nil
		}
		if err = wait(ctx, time.Second); err != nil {
			return err
		}
	}
	return fmt.Errorf("%s was not observed within %s", desired, budget)
}

func (e *experiment) pauseFault(ctx context.Context) error {
	_, raw, err := e.faultStatus(ctx)
	if err != nil || len(raw) == 0 {
		return err
	}
	_, err = kubectl(ctx, nil, "-n", e.cfg.Namespace, "annotate", e.faultKind, e.faultName, "experiment.chaos-mesh.org/pause=true", "--overwrite", "-o", "json")
	return err
}

func (e *experiment) removeFault(ctx context.Context) error {
	_, raw, err := e.faultStatus(ctx)
	if err != nil || len(raw) == 0 {
		return err
	}
	if err = e.pauseFault(ctx); err != nil {
		return err
	}
	if err = e.waitFault(ctx, "AllRecovered", 90*time.Second); err != nil {
		return err
	}
	_, err = kubectl(ctx, nil, "-n", e.cfg.Namespace, "delete", e.faultKind, e.faultName, "--wait=true", "--timeout=60s", "-o", "name")
	return err
}
