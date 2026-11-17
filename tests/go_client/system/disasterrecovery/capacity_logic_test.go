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
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCapacityArrivalCohort(t *testing.T) {
	rows := []sample{
		{Operation: "insert", Scheduled: 0, Start: 0, End: .1, Sent: true, Success: true, Correct: true, Latency: .1},
		// The last arrival finishes outside the observation window and must be counted.
		{Operation: "insert", Scheduled: 1, Start: 1, End: 3, Sent: true, Correct: true, Latency: 2},
	}
	result := evaluateCapacity(rows, 0, 2, map[string]float64{"insert": 1})
	require.False(t, result.Accepted)
	require.Equal(t, 2, result.Operations["insert"].Sent)
	require.Equal(t, 1, result.Operations["insert"].Succeeded)
	rows[1].Success = true
	require.True(t, evaluateCapacity(rows, 0, 2, map[string]float64{"insert": 1}).Accepted)
}

func TestCapacityMissingDroppedAndDelayedTraffic(t *testing.T) {
	for _, kind := range []string{"missing", "dropped", "delayed"} {
		t.Run(kind, func(t *testing.T) {
			rows := []sample{}
			for i := range 10 {
				rows = append(rows, sample{Operation: "query", Scheduled: float64(i), Start: float64(i), End: float64(i) + .01, Sent: true, Success: true, Correct: true})
			}
			switch kind {
			case "missing":
				rows = rows[:7]
			case "dropped":
				rows[9].Sent = false
				rows[9].Success = false
			case "delayed":
				rows[9].Start += .5
			}
			result := evaluateCapacity(rows, 0, 10, map[string]float64{"query": 1})
			require.False(t, result.Accepted)
			require.True(t, result.DeliveryLimited)
		})
	}
}

func TestCapacitySearchBoundaries(t *testing.T) {
	next, done := nextCapacityScale(1, 0, 1, 8)
	require.Equal(t, 2.0, next)
	require.False(t, done)
	_, done = nextCapacityScale(8, 0, 8, 8)
	require.True(t, done, "accepted ceiling is censored, not a maximum")
	next, done = nextCapacityScale(0, 1, 1, 8)
	require.Equal(t, .5, next)
	require.False(t, done)
	next, done = nextCapacityScale(2, 4, 4, 8)
	require.Equal(t, 3.0, next)
	require.False(t, done)
	_, done = nextCapacityScale(3.75, 4, 3.75, 8)
	require.True(t, done)
}
