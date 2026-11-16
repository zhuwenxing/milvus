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
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"math/rand/v2"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"time"

	"github.com/milvus-io/milvus/client/v3/column"
	"github.com/milvus-io/milvus/client/v3/entity"
	"github.com/milvus-io/milvus/client/v3/index"
	"github.com/milvus-io/milvus/client/v3/milvusclient"
)

type sample struct {
	Operation string  `json:"operation"`
	Start     float64 `json:"start"`
	End       float64 `json:"end"`
	Latency   float64 `json:"latency"`
	Scheduled float64 `json:"scheduled"`
	Sent      bool    `json:"sent"`
	Success   bool    `json:"success"`
	Correct   bool    `json:"correct"`
	Error     string  `json:"error,omitempty"`
	Key       int64   `json:"key,omitempty"`
}

type traffic struct {
	e              *experiment
	vectors        [][]float32
	queries        [][]float32
	mu             sync.Mutex
	records        []sample
	acknowledged   map[int64]bool
	out            *os.File
	buffer         *bufio.Writer
	encoder        *json.Encoder
	journal        *os.File
	journalEncoder *json.Encoder
	ioError        error
	stopScheduling chan struct{}
	stopOnce       sync.Once
	wg             sync.WaitGroup
}

func newTraffic(e *experiment) (*traffic, error) {
	out, err := os.OpenFile(filepath.Join(e.cfg.Output, "requests.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	journal, err := os.OpenFile(filepath.Join(e.cfg.Output, "write-ledger.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		out.Close()
		return nil, err
	}
	buffer := bufio.NewWriterSize(out, 256*1024)
	return &traffic{e: e, vectors: syntheticVectors(10000, 19530), queries: syntheticVectors(100, 19531), acknowledged: map[int64]bool{}, out: out, buffer: buffer, encoder: json.NewEncoder(buffer), journal: journal, journalEncoder: json.NewEncoder(journal), stopScheduling: make(chan struct{})}, nil
}

// Use unequal clusters, unequal variance, dimension scales and neighbor correlation.
// This controlled synthetic population is not a real embedding benchmark.
func syntheticVectors(count int, seed uint64) [][]float32 {
	centersRNG := rand.New(rand.NewPCG(42, 17))
	centers := make([][]float64, 4)
	for i := range centers {
		centers[i] = make([]float64, 64)
		for d := range centers[i] {
			centers[i][d] = .8 * centersRNG.NormFloat64()
		}
	}
	rng := rand.New(rand.NewPCG(seed, seed+1))
	values := make([][]float32, count)
	for i := range count {
		u, cluster := rng.Float64(), 0
		switch {
		case u >= .9:
			cluster = 3
		case u >= .7:
			cluster = 2
		case u >= .4:
			cluster = 1
		}
		raw := make([]float64, 64)
		for d := range raw {
			raw[d] = (centers[cluster][d] + (.6+.2*float64(cluster))*rng.NormFloat64()) * (.75 + .5*float64(d)/63)
		}
		values[i] = make([]float32, 64)
		for d := range raw {
			values[i][d] = float32(raw[d] + .2*raw[(d+63)%64])
		}
	}
	return values
}

func (l *traffic) prepare(ctx context.Context) error {
	c, name := l.e.client, l.e.collection
	schema := entity.NewSchema().WithName(name).
		WithField(entity.NewField().WithName("id").WithDataType(entity.FieldTypeInt64).WithIsPrimaryKey(true)).
		WithField(entity.NewField().WithName("value").WithDataType(entity.FieldTypeInt64)).
		WithField(entity.NewField().WithName("vector").WithDataType(entity.FieldTypeFloatVector).WithDim(64))
	if err := c.CreateCollection(ctx, milvusclient.NewCreateCollectionOption(name, schema)); err != nil {
		return err
	}
	for offset := 0; offset < len(l.vectors); offset += 1000 {
		keys := make([]int64, 1000)
		for i := range keys {
			keys[i] = int64(offset + i)
		}
		_, err := c.Insert(ctx, milvusclient.NewColumnBasedInsertOption(name, column.NewColumnInt64("id", keys), column.NewColumnInt64("value", keys), column.NewColumnFloatVector("vector", 64, l.vectors[offset:offset+1000])))
		if err != nil {
			return err
		}
	}
	flush, err := c.Flush(ctx, milvusclient.NewFlushOption(name))
	if err != nil {
		return err
	}
	if err = flush.Await(ctx); err != nil {
		return err
	}
	idx, err := c.CreateIndex(ctx, milvusclient.NewCreateIndexOption(name, "vector", index.NewHNSWIndex(entity.L2, 16, 100)))
	if err != nil {
		return err
	}
	if err = idx.Await(ctx); err != nil {
		return err
	}
	// Exercise the chart's cluster-managed replica/RG configuration. An explicit
	// WithReplica override would switch this collection to user-managed mode.
	loaded, err := c.LoadCollection(ctx, milvusclient.NewLoadCollectionOption(name))
	if err != nil {
		return err
	}
	if err = loaded.Await(ctx); err != nil {
		return err
	}
	return writeJSON(filepath.Join(l.e.cfg.Output, "data.json"), map[string]any{"profile": "ha-clustered-v1", "seed": 19530, "query_seed": 19531, "weights": []float64{.4, .3, .2, .1}, "dimension_scale": []float64{.75, 1.25}, "neighbor_correlation": .2, "corpus": l.vectors, "queries": l.queries})
}

func (l *traffic) add(s sample) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.records = append(l.records, s)
	if err := l.encoder.Encode(s); err != nil {
		l.ioError = err
	}
	if s.Operation == "insert" && s.Success {
		l.acknowledged[s.Key] = true
		if err := l.journalEncoder.Encode(map[string]any{"event": "ack", "id": s.Key}); err != nil {
			l.ioError = err
		}
	}
}

func (l *traffic) call(op string, sequence int64, scheduled float64) {
	s := sample{Operation: op, Start: l.e.now(), Scheduled: scheduled, Sent: true, Correct: true}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(l.e.cfg.RequestTimeout*float64(time.Second)))
	defer cancel()
	c, name := l.e.client, l.e.collection
	var err error
	switch op {
	case "search":
		var result []milvusclient.ResultSet
		result, err = c.Search(ctx, milvusclient.NewSearchOption(name, 10, []entity.Vector{entity.FloatVector(l.queries[sequence%int64(len(l.queries))])}).WithFilter("id < 10000").WithConsistencyLevel(entity.ClStrong))
		if err == nil {
			if len(result) != 1 || result[0].ResultCount != 10 || result[0].Err != nil {
				s.Correct = false
				err = fmt.Errorf("incomplete search result")
			} else {
				for i := range 10 {
					id, idErr := result[0].IDs.GetAsInt64(i)
					if idErr != nil || id < 0 || id >= 10000 || math.IsNaN(float64(result[0].Scores[i])) {
						s.Correct = false
						err = fmt.Errorf("incorrect search result")
						break
					}
				}
			}
		}
	case "query":
		key := sequence % 10000
		var result milvusclient.ResultSet
		result, err = c.Query(ctx, milvusclient.NewQueryOption(name).WithFilter(fmt.Sprintf("id == %d", key)).WithOutputFields("id", "value").WithConsistencyLevel(entity.ClStrong))
		if err == nil {
			if result.ResultCount != 1 || result.GetColumn("value") == nil {
				s.Correct = false
				err = fmt.Errorf("missing query row")
			} else {
				value, valueErr := result.GetColumn("value").GetAsInt64(0)
				if valueErr != nil || value != key {
					s.Correct = false
					err = fmt.Errorf("query value mismatch")
				}
			}
		}
	case "insert":
		s.Key = 100000 + sequence
		l.mu.Lock()
		err = l.journalEncoder.Encode(map[string]any{"event": "intent", "id": s.Key, "value": s.Key})
		if err != nil {
			l.ioError = err
			s.Sent = false
		}
		l.mu.Unlock()
		if err == nil {
			var result milvusclient.InsertResult
			result, err = c.Insert(ctx, milvusclient.NewColumnBasedInsertOption(name, column.NewColumnInt64("id", []int64{s.Key}), column.NewColumnInt64("value", []int64{s.Key}), column.NewColumnFloatVector("vector", 64, [][]float32{l.vectors[sequence%int64(len(l.vectors))]})))
			if err == nil && result.InsertCount != 1 {
				s.Correct = false
				err = fmt.Errorf("incomplete insert acknowledgement")
			}
		}
	}
	s.End = l.e.now()
	s.Latency = s.End - s.Start
	s.Success = err == nil
	if err != nil {
		s.Error = err.Error()
	}
	l.add(s)
}

func (l *traffic) start() {
	for op, qps := range map[string]float64{"search": l.e.cfg.SearchQPS, "query": l.e.cfg.QueryQPS, "insert": l.e.cfg.InsertQPS} {
		type request struct {
			sequence  int64
			scheduled float64
		}
		jobs := make(chan request, l.e.cfg.Workers)
		for range l.e.cfg.Workers {
			l.wg.Go(func() {
				for job := range jobs {
					l.call(op, job.sequence, job.scheduled)
				}
			})
		}
		l.wg.Go(func() {
			defer close(jobs)
			interval := 1 / qps
			started := l.e.now()
			ticker := time.NewTicker(time.Duration(float64(time.Second) / qps))
			defer ticker.Stop()
			var sequence int64
			for {
				select {
				case <-l.stopScheduling:
					return
				case <-ticker.C:
					// Tickers may coalesce delayed ticks. Account for every offered slot,
					// instead of silently lowering offered load when this process stalls.
					due := int64((l.e.now() - started) * qps)
					for sequence < due {
						when := started + float64(sequence+1)*interval
						if sequence+1 < due {
							now := l.e.now()
							l.add(sample{Operation: op, Start: now, End: now, Scheduled: when, Correct: true, Error: "load_generator_schedule_lag"})
							sequence++
							continue
						}
						select {
						case jobs <- request{sequence, when}:
						default:
							now := l.e.now()
							l.add(sample{Operation: op, Start: now, End: now, Scheduled: when, Correct: true, Error: "load_generator_saturated"})
						}
						sequence++
					}
				}
			}
		})
	}
}

func (l *traffic) snapshot() []sample {
	l.mu.Lock()
	defer l.mu.Unlock()
	return slices.Clone(l.records)
}

func (l *traffic) stop() error {
	l.stopOnce.Do(func() {
		close(l.stopScheduling)
		l.wg.Wait()
		l.mu.Lock()
		defer l.mu.Unlock()
		if err := l.buffer.Flush(); err != nil {
			l.ioError = err
		}
		l.out.Close()
		l.journal.Close()
	})
	return l.ioError
}

func (l *traffic) baselineCheck() error {
	records := l.snapshot()
	counts := map[string]int{}
	for _, r := range records {
		if !r.Sent {
			return fmt.Errorf("load generator saturated before fault; increase workers or reduce QPS")
		}
		if r.Success {
			counts[r.Operation]++
		}
		if !r.Correct {
			return fmt.Errorf("incorrect baseline response")
		}
	}
	for _, op := range []string{"search", "query", "insert"} {
		if counts[op] == 0 {
			return fmt.Errorf("no successful baseline %s requests", op)
		}
	}
	return nil
}

func (l *traffic) verify(ctx context.Context) error {
	keys := make([]int64, 0, len(l.acknowledged))
	for key := range l.acknowledged {
		keys = append(keys, key)
	}
	for key := int64(0); key < 10000; key++ {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	for start := 0; start < len(keys); start += 100 {
		chunk := keys[start:min(start+100, len(keys))]
		rpcCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		result, err := l.e.client.Query(rpcCtx, milvusclient.NewQueryOption(l.e.collection).WithFilter("id in {ids}").WithTemplateParam("ids", chunk).WithOutputFields("id", "value").WithConsistencyLevel(entity.ClStrong))
		cancel()
		if err != nil {
			return err
		}
		if result.ResultCount != len(chunk) {
			return fmt.Errorf("acknowledged rows missing: expected %d got %d", len(chunk), result.ResultCount)
		}
		ids, values := result.GetColumn("id"), result.GetColumn("value")
		if ids == nil || values == nil {
			return fmt.Errorf("missing correctness fields")
		}
		seen := map[int64]bool{}
		for i := range result.ResultCount {
			key, idErr := ids.GetAsInt64(i)
			value, valueErr := values.GetAsInt64(i)
			if idErr != nil || valueErr != nil || key != value || !slices.Contains(chunk, key) || seen[key] {
				return fmt.Errorf("acknowledged data changed or duplicated")
			}
			seen[key] = true
		}
	}
	unknownKeys := []int64{}
	for _, r := range l.records {
		if !r.Correct {
			return fmt.Errorf("incorrect result during fault")
		}
		if r.Operation == "insert" && r.Sent && !r.Success {
			unknownKeys = append(unknownKeys, r.Key)
		}
	}
	unknownPresent := 0
	for start := 0; start < len(unknownKeys); start += 100 {
		chunk := unknownKeys[start:min(start+100, len(unknownKeys))]
		rpcCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		result, err := l.e.client.Query(rpcCtx, milvusclient.NewQueryOption(l.e.collection).WithFilter("id in {ids}").WithTemplateParam("ids", chunk).WithOutputFields("id", "value").WithConsistencyLevel(entity.ClStrong))
		cancel()
		if err != nil {
			return fmt.Errorf("unknown-write reconciliation incomplete: %w", err)
		}
		ids, values := result.GetColumn("id"), result.GetColumn("value")
		seen := map[int64]bool{}
		for i := range result.ResultCount {
			if ids == nil || values == nil {
				return fmt.Errorf("missing reconciliation fields")
			}
			key, keyErr := ids.GetAsInt64(i)
			value, valueErr := values.GetAsInt64(i)
			if keyErr != nil || valueErr != nil || key != value || !slices.Contains(chunk, key) || seen[key] {
				return fmt.Errorf("unknown-write payload mismatch")
			}
			seen[key] = true
		}
		unknownPresent += len(seen)
	}
	return writeJSON(filepath.Join(l.e.cfg.Output, "integrity.json"), map[string]any{"acknowledged_writes_checked": len(keys), "unknown_write_outcomes": len(unknownKeys), "unknown_found_present": unknownPresent, "unknown_not_visible_at_verification": len(unknownKeys) - unknownPresent, "acknowledged_data_lost": 0})
}
