import gevent.monkey

gevent.monkey.patch_all()
import grpc.experimental.gevent as grpc_gevent

grpc_gevent.init_gevent()

from locust import User, events, tag, task
from locust.runners import MasterRunner, WorkerRunner
from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    FunctionType,
    Function,
)
import numpy as np
import time
import logging
from faker import Faker

faker = Faker()

PHRASE_PROBABILITIES = {
    "vector_similarity": 0.1,  # Most common phrase
    "milvus_search": 0.01,  # Medium frequency phrase
    "nearest_neighbor_search": 0.001,  # Less common phrase
    "high_dimensional_vector_index": 0.0001,  # Rare phrase
}


def gen_text(phrase_probabilities):
    for phrase, prob in phrase_probabilities.items():
        if np.random.rand() < prob:
            return phrase + " " + faker.text()
    return faker.sentence()


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

dim = 16
collection_name = "test_tokenization_perf"
data = [
    {
        "id": int(time.time() * (10 ** 6)),
        "text": gen_text(PHRASE_PROBABILITIES),
        "dense_emb": np.random.random([dim]).tolist()
    }
    for _ in range(1000)
]


def setup_collection(environment):
    """在master上执行collection的初始化"""
    logger.info("Setting up collection in master...")

    # 获取配置参数

    logger.info(
        f"Collection name: {collection_name}"
    )
    connections.connect(uri=environment.host)
    analyzer_params = {"type": "standard"}
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
        FieldSchema(
            name="text",
            dtype=DataType.VARCHAR,
            max_length=25536,
            enable_analyzer=True,
            analyzer_params=analyzer_params,
            enable_match=True,
        ),
        FieldSchema(
            name="dense_emb",
            dtype=DataType.FLOAT_VECTOR,
            dim=dim,
        ),
        FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
    ]
    schema = CollectionSchema(fields=fields, description="fts test collection")
    bm25_function = Function(
        name="text_bm25_emb",
        function_type=FunctionType.BM25,
        input_field_names=["text"],
        output_field_names=["sparse"],
        params={},
    )
    schema.add_function(bm25_function)
    Collection(f"{collection_name}_fts", schema)
    logger.info("FTS collection setup completed successfully")

    # normal collection
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
        FieldSchema(
            name="text",
            dtype=DataType.VARCHAR,
            max_length=25536
        ),
        FieldSchema(
            name="dense_emb",
            dtype=DataType.FLOAT_VECTOR,
            dim=dim
        )
    ]
    schema = CollectionSchema(fields=fields, description="normal test collection")
    Collection(f"{collection_name}_normal", schema)
    logger.info("Normal collection setup completed successfully")


@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    """初始化事件监听器，仅在master上执行setup"""
    if isinstance(environment.runner, MasterRunner):
        logger.info("Initializing in master...")
        setup_collection(environment)

    # 为所有runner添加setup状态标记
    environment.setup_completed = False


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    """测试开始时的处理"""
    if isinstance(environment.runner, MasterRunner):
        logger.info("Test starting in master...")
        # Master已经完成setup
        environment.setup_completed = True
        logger.info(f"environment.setup_completed: {environment.setup_completed}")
        logger.info(" master setup confirmed completed")
    elif isinstance(environment.runner, WorkerRunner):
        logger.info("Test starting in worker...")
        # Worker等待master完成setup
        wait_for_setup(environment)
        logger.info("worker setup confirmed completed")


def wait_for_setup(environment):
    """等待setup完成"""
    connections.connect(uri=environment.host)
    normal_collection = Collection(f"{collection_name}_normal")
    fts_collection = Collection(f"{collection_name}_fts")
    logger.info(f"Setup confirmed completed, normal collection: {normal_collection}, fts collection: {fts_collection}")


class MilvusBaseUser(User):
    """Base Milvus user class that handles common functionality"""

    abstract = True

    def __init__(self, environment):
        super().__init__(environment)
        logger.debug("Initializing MilvusBaseUser")

        # These will be initialized in on_start
        self.fts_client = None
        self.normal_client = None

    def on_start(self):
        """Called when a User starts running"""
        logger.debug("Starting MilvusBaseUser setup")
        connections.connect(uri=self.environment.host)
        self._init_client()

    def _init_client(self):
        """Initialize the appropriate client based on mode"""
        logger.debug(f"Initializing client")
        self.fts_client = MilvusORMClient(f"{collection_name}_fts", meta_data={"insert": "fts"})
        self.normal_client = MilvusORMClient(f"{collection_name}_normal", meta_data={"insert": "normal"})

    def wait_time(self):
        return 0.1


class MilvusUser(MilvusBaseUser):
    """Main Milvus user class that defines the test tasks"""

    @task(1)
    @tag("fts_insert")
    def fts_insert(self):
        """Insert random vectors"""
        self.fts_client.insert(data)

    @task(1)
    @tag("normal_insert")
    def normal_insert(self):
        """Insert data into the normal collection"""
        self.normal_client.insert(data)


class MilvusORMClient:
    """Wrapper for Milvus ORM"""

    def __init__(self, name, meta_data=None):
        logger.debug("Initializing MilvusORMClient")
        self.request_type = "ORM"
        self.meta_data = meta_data if meta_data else {}
        self.collection_name = name
        self.collection = Collection(self.collection_name)
        self.sleep_time = 1

    def insert(self, data):
        start = time.time()
        try:
            self.collection.insert(data)
            total_time = (time.time() - start) * 1000
            events.request.fire(
                request_type=self.request_type,
                name=f"Insert_{self.meta_data.get('insert', '')}",
                response_time=total_time,
                response_length=0,
                exception=None,
            )
            self.sleep_time = 0.1
        except Exception as e:
            if "memory" in str(e) or "deny" in str(e) or "limit" in str(e):
                time.sleep(self.sleep_time)
                self.sleep_time *= 2
            else:
                events.request.fire(
                    request_type=self.request_type,
                    name="Insert",
                    response_time=(time.time() - start) * 1000,
                    response_length=0,
                    exception=e,
                )
