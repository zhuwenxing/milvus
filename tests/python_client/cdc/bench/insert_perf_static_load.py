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