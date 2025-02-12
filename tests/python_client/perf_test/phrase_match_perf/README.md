# Phrase Match Performance Test Suite

This test suite is designed to evaluate and compare the performance of Milvus's phrase match functionality against traditional LIKE queries. It provides comprehensive performance testing capabilities using Locust as the load testing framework.

## Overview

The test suite implements two main testing modes:
1. Progressive Load Test - To find optimal QPS (Queries Per Second)
2. Fixed User Test - For steady-state performance comparison

## Project Structure

- `run_perf_tests.py` - Main script to orchestrate performance tests
- `test_phrase_match_vs_like_query.py` - Locust test implementation for phrase match and LIKE queries
- `analyze_results.py` - Script for analyzing test results
- `constants.py` - Configuration constants
- `prepare_data.py` - Data preparation script

## Prerequisites

- Python 3.x
- Locust
- Milvus server running and accessible

## Configuration

Key configuration parameters are defined in `constants.py`:
- `HOST` - Milvus server host
- `TEST_DURATION` - Duration of the test
- `FIXED_USERS` - Number of concurrent users for fixed mode testing
- `COOLDOWN_TIME` - Cool down period between tests
- `PROCESS_COUNT` - Number of processes for parallel testing

## Test Modes

### Progressive Mode
- Gradually increases load to find optimal performance
- Consists of multiple stages:
  1. Warmup (5% of total time)
  2. Progressive increase stages (19% each)
  3. Maximum load stage

### Fixed Mode
- Maintains steady number of concurrent users
- Useful for consistent performance comparison
- Quick ramp-up followed by steady-state testing

## Running Tests

1. Execute the test suite:
```bash
./run_perf_tests.sh
```

2. Or run specific tests using Python:
```bash
python run_perf_tests.py --phrase "your search phrase"
```

## Results

Test results are stored in:
- CSV format: `results/`
- HTML reports: `results/html/`

The results include metrics such as:
- Response times
- Request rates
- Error rates
- Performance comparisons between phrase match and LIKE queries

## Analyzing Results

Use the `analyze_results.py` script to process and visualize test results:
```bash
python analyze_results.py
```
