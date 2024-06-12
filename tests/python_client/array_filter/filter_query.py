from locust import HttpUser, task, events, LoadTestShape
import random
import pandas as pd
import re
from datetime import datetime
import uuid

def convert_numbers_to_quoted_strings(text):
    result = re.sub(r'\d+', lambda x: f"'{x.group()}'", text)
    return result

@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--filter_field", type=str, env_var="LOCUST_FILTER", default="", help="filter field")
    parser.add_argument("--filter_op", type=str, env_var="LOCUST_FILTER", default="==", help="filter op")
    parser.add_argument("--filter_value", type=str, env_var="LOCUST_FILTER", default="0", help="filter value")


@events.test_start.add_listener
def _(environment, **kw):
    print(f"Custom argument supplied: {environment.parsed_options.filter_field}")
    print(f"Custom argument supplied: {environment.parsed_options.filter_op}")
    print(f"Custom argument supplied: {environment.parsed_options.filter_value}")


class MilvusUser(HttpUser):
    host = "http://10.104.15.106:19530"

    @task
    def search(self):
        filter = f"{self.environment.parsed_options.filter_field} {self.environment.parsed_options.filter_op} '{self.environment.parsed_options.filter_value}'"
        with self.client.post("/v2/vectordb/entities/query",
                              json={"collectionName": "test_restful_perf",
                                    "outputFields": ["id"],
                                    "filter": "ARRAY_CONTAINS(int_array, 10)",
                                    "limit": 1000
                                    },
                              headers={"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"},
                              catch_response=True
                              ) as resp:
            if resp.status_code != 200 or resp.json()["code"] != 0:
                resp.failure(f"query failed with error {resp.text}")

class StagesShape(LoadTestShape):
    """
    A simple load test shape class that has different user and spawn_rate at
    different stages.

    Keyword arguments:

        stages -- A list of dicts, each representing a stage with the following keys:
            duration -- When this many seconds pass the test is advanced to the next stage
            users -- Total user count
            spawn_rate -- Number of users to start/stop per second
            stop -- A boolean that can stop that test at a specific stage

        stop_at_end -- Can be set to stop once all stages have run.
    """

    stages = [
        {"duration": 60, "users": 50, "spawn_rate": 10},
        {"duration": 120, "users": 50, "spawn_rate": 10},
        {"duration": 240, "users": 50, "spawn_rate": 10, "stop": True},
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None
