from minio import Minio
import glob
from pymilvus import (
    connections, list_collections,
    FieldSchema, CollectionSchema, DataType,
    Collection, BulkInsertState, utility
)

import time
import argparse
from loguru import logger
import faker

fake = faker.Faker()


def prepare_data(host="127.0.0.1", port=19530, minio_host="127.0.0.1", partition_key="scalar_3", data_dir="/root/dataset/laion_with_scalar_medium_10m"):

    connections.connect(
        host=host,
        port=port,
    )
    collection_name = "test_restful_perf"
    if collection_name in list_collections():
        logger.info(f"collection {collection_name} exists, drop it")
        Collection(name=collection_name).drop()
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
        FieldSchema(name="scalar_3", dtype=DataType.VARCHAR, max_length=1000, is_partition_key=bool(partition_key == "scalar_3")),
        FieldSchema(name="scalar_6", dtype=DataType.VARCHAR, max_length=1000, is_partition_key=bool(partition_key == "scalar_6")),
        FieldSchema(name="scalar_9", dtype=DataType.VARCHAR, max_length=1000, is_partition_key=bool(partition_key == "scalar_9")),
        FieldSchema(name="scalar_12", dtype=DataType.VARCHAR, max_length=1000, is_partition_key=bool(partition_key == "scalar_12")),
        FieldSchema(name="scalar_5_linear", dtype=DataType.VARCHAR, max_length=1000, is_partition_key=bool(partition_key == "scalar_5_linear")),
        FieldSchema(name="emb", dtype=DataType.FLOAT_VECTOR, dim=768)
    ]
    schema = CollectionSchema(fields=fields, description="test collection", enable_dynamic_field=True, num_partitions=1)
    collection = Collection(name=collection_name, schema=schema, num_partitions=1)
    logger.info(f"collection {collection_name} created: {collection.describe()}")
    index_params = {"metric_type": "L2", "index_type": "HNSW", "params": {"M": 30, "efConstruction": 360}}
    logger.info(f"collection {collection_name} created")

    batch_files = glob.glob(f"{data_dir}/train*.parquet")
    logger.info(f"files {batch_files}")
    # copy file to minio
    client = Minio(
            f"{minio_host}:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False,
        )
    for file in batch_files:
        f_name = file.split("/")[-1]
        client.fput_object("milvus-bucket", f_name, file)
        logger.info(f"upload file {file}")
    batch_files = [file.split("/")[-1] for file in batch_files]
    task_ids = []
    for files in batch_files:
        task_id = utility.do_bulk_insert(collection_name=collection_name, files=[files])
        task_ids.append(task_id)
        logger.info(f"Create a bulk inert task, task id: {task_id}")

    while len(task_ids) > 0:
        logger.info("Wait 1 second to check bulk insert tasks state...")
        time.sleep(1)
        for id in task_ids:
            state = utility.get_bulk_insert_state(task_id=id)
            if state.state == BulkInsertState.ImportFailed or state.state == BulkInsertState.ImportFailedAndCleaned:
                logger.info(f"The task {state.task_id} failed, reason: {state.failed_reason}")
                task_ids.remove(id)
            elif state.state == BulkInsertState.ImportCompleted:
                logger.info(f"The task {state.task_id} completed with state {state}")
                task_ids.remove(id)

    collection.create_index("emb", index_params=index_params)
    index_list = utility.list_indexes(collection_name=collection_name)
    for index_name in index_list:
        progress = utility.index_building_progress(collection_name=collection_name, index_name=index_name)
        while progress["pending_index_rows"] > 0:
            time.sleep(30)
            progress = utility.index_building_progress(collection_name=collection_name, index_name=index_name)
            logger.info(f"collection {collection_name} index {index_name} progress: {progress}")
        logger.info(f"collection {collection_name} index {index_name} progress: {progress}")
    collection.load()
    num = collection.num_entities
    logger.info(f"collection {collection_name} loaded, num_entities: {num}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="prepare data for perf test")
    parser.add_argument("--host", type=str, default="10.104.18.39")
    parser.add_argument("--minio_host", type=str, default="10.104.18.174")
    parser.add_argument("--port", type=int, default=19530)
    parser.add_argument("--partition_key", type=str, default="scalar_3")
    parser.add_argument("--data_dir", type=str, default="/root/dataset/laion_with_scalar_medium_10m")
    args = parser.parse_args()
    prepare_data(host=args.host, port=args.port, minio_host=args.minio_host, partition_key=args.partition_key, data_dir=args.data_dir)