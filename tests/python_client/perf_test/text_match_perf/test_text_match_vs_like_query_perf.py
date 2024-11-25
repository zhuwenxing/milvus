from locust import HttpUser, task, tag, LoadTestShape, events

@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--token_candidate", type=str, env_var="TOKEN", default="vector", help="word for text match")


@events.test_start.add_listener
def _(environment, **kw):
    print(f"Custom argument supplied: {environment.parsed_options.token_candidate}")

class MilvusUser(HttpUser):
    host = "http://10.104.1.205:19530"

    @tag('text_match')
    @task
    def query_with_text_match(self):
        text_match_filter = f"text_match(sentence, '{self.environment.parsed_options.token_candidate}')"
        with self.client.post("/v2/vectordb/entities/query",
                              json={"collectionName": "test_text_match_perf",
                                    "outputFields": ["id"],
                                    "filter": text_match_filter,
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
        like_filter = f"sentence like '%{self.environment.parsed_options.token_candidate}%'"
        with self.client.post("/v2/vectordb/entities/query",
                              json={"collectionName": "test_text_match_perf",
                                    "outputFields": ["id"],
                                    "filter": like_filter,
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
        {"duration": 60, "users": 1, "spawn_rate": 1},
        {"duration": 120, "users": 10, "spawn_rate": 10},
        {"duration": 180, "users": 50, "spawn_rate": 10},
        {"duration": 240, "users": 100, "spawn_rate": 10},
        {"duration": 300, "users": 150, "spawn_rate": 10},
        {"duration": 360, "users": 200, "spawn_rate": 10, "stop": True},
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None

