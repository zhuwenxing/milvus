"""Constants for performance testing."""

# Test configuration
HOST = "http://10.104.25.110:19530"
TEST_DURATION = 100  # 10 minutes for progressive test
FIXED_TEST_DURATION = 60  # 5 minutes for fixed user test
FIXED_USERS = 50  # Default number of users for fixed test mode
COOLDOWN_TIME = 60  # Time to wait between tests in seconds

# Test phrases with their probabilities
TEST_PHRASES = {
    "vector similarity": 0.1,        # Most common phrase
    "milvus search": 0.01,         # Medium frequency phrase
    "nearest neighbor": 0.001,  # Less common phrase
    "high dimensional": 0.0001,  # Rare phrase
}

# Test modes
MODE_PROGRESSIVE = "progressive"
MODE_FIXED = "fixed"

# Test tags
TAG_PHRASE_MATCH = "phrase_match"
TAG_LIKE = "like"

# Results directories
RESULTS_DIR = "/tmp/ci_logs/results"
HTML_RESULTS_DIR = "/tmp/ci_logs/results/html"

# Number of worker processes for Locust
PROCESS_COUNT = 8  # Adjust this based on your CPU cores or -1 for auto detection
