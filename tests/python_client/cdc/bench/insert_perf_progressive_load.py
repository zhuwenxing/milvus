from faker import Faker
from locust import events, task, tag, between, LoadTestShape
from locust.contrib.milvus import MilvusUser
from pymilvus import CollectionSchema, DataType, FieldSchema
import uuid
from typing import List, Dict, Any
import numpy as np

faker = Faker()

class MilvusInsertTestUser(MilvusUser):
    """Simplified Milvus user class for insert performance testing with step load"""

    wait_time = between(1, 3)

    def __init__(self, environment):
        # Define collection schema
        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=500, is_primary=True),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=768),
            ],
            description="insert test collection",
        )

        super().__init__(
            environment,
            uri=environment.parsed_options.milvus_uri,
            token=environment.parsed_options.milvus_token,
            collection_name="insert_test_collection",
            schema=schema,
        )


    def _random_embedding(self):
        return np.random.random([768]).tolist()

    def _generate_batch_data(self, batch_size: int) -> List[Dict[str, Any]]:
        """Generate batch data for insert operations"""
        return [
            {
                "id": str(uuid.uuid4()),
                "text": faker.text(max_nb_chars=300),
                "embedding": self._random_embedding(),
            }
            for _ in range(batch_size)
        ]

    @tag("insert")
    @task
    def insert_data(self):
        """Insert data into Milvus collection"""
        batch_size = self.environment.parsed_options.milvus_insert_batch_size
        data = self._generate_batch_data(batch_size)
        self.insert(data)

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
    init_stage = [
        {"duration": 60, "users": 1, "spawn_rate": 1},
    ]
    user_rate = 5
    time_each_stage = 120
    total_users = 100
    for i in range(1, total_users // user_rate + 1):
        stage = {
            "duration": time_each_stage * i,
            "users": i * user_rate,
            "spawn_rate": user_rate
        }
        init_stage.append(stage)

    stages = init_stage
    stages[-1]["stop"] = True

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                tick_data = (stage["users"], stage["spawn_rate"])
                return tick_data

        return None


@events.init_command_line_parser.add_listener
def _(parser):
    milvus_options = parser.add_argument_group("Milvus-specific options")
    milvus_options.add_argument(
        "--milvus-uri",
        type=str,
        metavar="<str>",
        default="http://127.0.0.1:19530",
        help="Milvus URI. Defaults to http://127.0.0.1:19530.",
    ) 
    milvus_options.add_argument(
        "--milvus-token",
        type=str,
        metavar="<str>",
        default="root:Milvus",
        help="Milvus token. Defaults to root:Milvus.",
    )
    milvus_options.add_argument(
        "--milvus-insert-batch-size",
        type=int,
        metavar="<str>",
        default=5000,
        help="Milvus insert batch size. Defaults to 5000.",
    )

