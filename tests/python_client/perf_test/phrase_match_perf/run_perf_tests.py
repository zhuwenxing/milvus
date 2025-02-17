import os
import time
import subprocess
import argparse
from pathlib import Path
from constants import (
    HOST, TEST_DURATION, FIXED_TEST_DURATION, FIXED_USERS,
    COOLDOWN_TIME, TEST_PHRASES, MODE_PROGRESSIVE, MODE_FIXED,
    TAG_PHRASE_MATCH, TAG_LIKE, TAG_TEXT_MATCH, RESULTS_DIR, HTML_RESULTS_DIR, PROCESS_COUNT
)

def run_test(phrase: str, tag: str, mode: str, duration: int, host: str = HOST) -> None:
    """Run a single performance test with specified parameters."""
    test_name = f"{phrase.replace(' ', '_')}_{tag}_{mode}"
    print(f"Running {tag} test in {mode} mode for phrase: {phrase}")

    # Set environment variables for test mode
    env = os.environ.copy()
    env.update({
        "TEST_MODE": mode,
        "TEST_TIME": str(duration)
    })

    if mode == MODE_FIXED:
        env["FIXED_USERS"] = str(FIXED_USERS)

    # Create results directories if they don't exist
    Path(RESULTS_DIR).mkdir(exist_ok=True)
    Path(HTML_RESULTS_DIR).mkdir(exist_ok=True, parents=True)

    # Construct command
    cmd = [
        "locust",
        "-f", "test_phrase_match_vs_like_query.py",
        "--headless",
        "--only-summary",
        f"--html={HTML_RESULTS_DIR}/{test_name}.html",
        "--tags", tag,
        "--phrase-candidate", phrase,
        "--host", host,
        "--processes", str(PROCESS_COUNT)
    ]

    # Run the test
    try:
        subprocess.run(cmd, env=env, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running test: {e}")
        return

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run performance tests for phrase match vs like query comparison.")
    parser.add_argument(
        "--host",
        type=str,
        default=HOST,
        help=f"Milvus server host URL (default: {HOST})"
    )
    return parser.parse_args()

def main():
    """Main function to run all performance tests."""
    args = parse_args()
    host = args.host

    # Phase 1: Progressive load tests
    print("Phase 1: Running progressive load tests to find optimal QPS")
    for phrase in TEST_PHRASES.keys():
        run_test(phrase, TAG_TEXT_MATCH, MODE_PROGRESSIVE, TEST_DURATION, host=host)
        run_test(phrase, TAG_PHRASE_MATCH, MODE_PROGRESSIVE, TEST_DURATION, host=host)
        run_test(phrase, TAG_LIKE, MODE_PROGRESSIVE, TEST_DURATION, host=host)
        print(f"Cooling down for {COOLDOWN_TIME} seconds...")
        time.sleep(COOLDOWN_TIME)

    # Phase 2: Fixed user tests
    print("Phase 2: Running fixed user tests for performance comparison")
    for phrase in TEST_PHRASES.keys():
        run_test(phrase, TAG_TEXT_MATCH, MODE_FIXED, FIXED_TEST_DURATION, host=host)
        run_test(phrase, TAG_PHRASE_MATCH, MODE_FIXED, FIXED_TEST_DURATION, host=host)
        run_test(phrase, TAG_LIKE, MODE_FIXED, FIXED_TEST_DURATION, host=host)
        print(f"Cooling down for {COOLDOWN_TIME} seconds...")
        time.sleep(COOLDOWN_TIME)

    # Final analysis
    subprocess.run(["python3", "analyze_results.py"], check=True)
    print("All tests completed. Results are in the results directory.")

if __name__ == "__main__":
    main()
