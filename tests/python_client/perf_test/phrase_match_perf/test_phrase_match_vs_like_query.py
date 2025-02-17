import gevent.monkey
gevent.monkey.patch_all()

from locust import HttpUser, task, events, tag, LoadTestShape
from typing import Optional
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MilvusUser(HttpUser):
    host = "http://10.104.1.205:19530"
    phrase_candidate: Optional[str] = None
    gt = []
    recall_list = []
    ts_list = []
    recall = 0

    def __init__(self, environment):
        super().__init__(environment)
        # logger.debug("Initializing MilvusUser")

        # Get phrase_candidate from command line args
        self.phrase_candidate = environment.parsed_options.phrase_candidate
        # logger.info(f"Using phrase_candidate: {self.phrase_candidate}")

        # Initialize filters
        self.text_match_filter = f"text_match(sentence, '{self.phrase_candidate}')"
        self.phrase_match_filter = f"phrase_match(sentence, '{self.phrase_candidate}')"
        self.like_filter = f"sentence like '%{self.phrase_candidate}%'"

    @tag('phrase_match')
    @task
    def query_with_phrase_match(self):
        with self.client.post("/v2/vectordb/entities/query",
                              json={"collectionName": "test_phrase_match_perf",
                                    "outputFields": ["id"],
                                    "filter": self.phrase_match_filter,
                                    "limit": 1000
                                    },
                              headers={"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"},
                              catch_response=True
                              ) as resp:
            if resp.status_code != 200 or resp.json()["code"] != 0:
                resp.failure(f"query failed with error {resp.text}")
                print(resp.text)
            else:
                pass


    @tag('text_match')
    @task
    def query_with_text_match(self):
        with self.client.post("/v2/vectordb/entities/query",
                              json={"collectionName": "test_phrase_match_perf",
                                    "outputFields": ["id"],
                                    "filter": self.text_match_filter,
                                    "limit": 1000
                                    },
                              headers={"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"},
                              catch_response=True
                              ) as resp:
            if resp.status_code != 200 or resp.json()["code"] != 0:
                resp.failure(f"query failed with error {resp.text}")
                print(resp.text)
            else:
                pass

    @tag('like')
    @task
    def query_with_like(self):
        with self.client.post("/v2/vectordb/entities/query",
                              json={"collectionName": "test_phrase_match_perf",
                                    "outputFields": ["id"],
                                    "filter": self.like_filter,
                                    "limit": 1000
                                    },
                              headers={"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"},
                              catch_response=True
                              ) as resp:
            if resp.status_code != 200 or resp.json()["code"] != 0:
                resp.failure(f"query failed with error {resp.text}")
                print(resp.text)
            else:
                pass


# 命令行参数配置
@events.init_command_line_parser.add_listener
def _(parser):
    phrase_options = parser.add_argument_group("Phrase-match specific options")
    phrase_options.add_argument(
        "--phrase-candidate",
        type=str,
        default="vector",
        help="Phrase to use for phrase match testing (default: %(default)s)"
    )


class StagesShape(LoadTestShape):
    """
    A load test shape class that implements two test modes:
    1. Progressive load test to find optimal QPS
    2. Fixed user test for performance comparison
    """
    def __init__(self):
        super().__init__()
        self.mode = os.getenv("TEST_MODE", "progressive")  # progressive or fixed
        self.test_time = int(os.getenv("TEST_TIME", "600"))  # total test time in seconds

        if self.mode == "progressive":
            # Calculate stage durations based on total test time
            warmup_ratio = 0.05  # 5% of total time for warmup
            stage_ratio = 0.19  # 19% for each main stage (5 stages = 95%)

            warmup_time = int(self.test_time * warmup_ratio)
            stage_time = int(self.test_time * stage_ratio)

            # Progressive stages to find optimal QPS
            self.stages = [
                # Warmup stage
                {"duration": warmup_time, "users": 1, "spawn_rate": 1},
                # Progressive increase stages
                {"duration": warmup_time + stage_time,
                 "users": 10, "spawn_rate": 5},
                {"duration": warmup_time + stage_time * 2,
                 "users": 50, "spawn_rate": 10},
                {"duration": warmup_time + stage_time * 3,
                 "users": 100, "spawn_rate": 10},
                {"duration": warmup_time + stage_time * 4,
                 "users": 150, "spawn_rate": 10},
                {"duration": self.test_time,
                 "users": 200, "spawn_rate": 10, "stop": True},
            ]

            # Log stage information
            logger.info(f"Progressive test configuration:")
            logger.info(f"Total test time: {self.test_time}s")
            logger.info(f"Warmup time: {warmup_time}s")
            logger.info(f"Time per stage: {stage_time}s")
            for i, stage in enumerate(self.stages):
                logger.info(f"Stage {i}: {stage}")
        else:
            # Fixed user test for steady-state performance
            fixed_users = int(os.getenv("FIXED_USERS", "1"))
            warmup_time = int(self.test_time * 0.1)  # 10% of time for warmup

            self.stages = [
                # Quick ramp-up
                {"duration": warmup_time,
                 "users": fixed_users, "spawn_rate": fixed_users},
                # Steady state
                {"duration": self.test_time,
                 "users": fixed_users, "spawn_rate": fixed_users, "stop": True},
            ]

            # Log fixed test configuration
            logger.info(f"Fixed test configuration:")
            logger.info(f"Total test time: {self.test_time}s")
            logger.info(f"Warmup time: {warmup_time}s")
            logger.info(f"Users: {fixed_users}")

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None
