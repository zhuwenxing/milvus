import time
import random
import threading
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pymilvus import connections, Collection, DataType, FieldSchema, CollectionSchema, utility
from pymilvus.bulk_writer import RemoteBulkWriter, BulkFileType
from loguru import logger

from minio import Minio
from minio.error import S3Error


class MinioSyncer:
    """MinioSyncer provides methods to sync data between Minio buckets.

    Supports:
    1. Syncing entire folders with sync_folder()
    2. Syncing specific files with sync_files()
    """

    def __init__(self, src_endpoint, src_access_key, src_secret_key,
                 dst_endpoint=None, dst_access_key=None, dst_secret_key=None,
                 secure=False):
        """Initialize MinioSyncer with source and destination Minio credentials.
        If destination credentials are not provided, they will be same as source.
        """
        self.src_client = Minio(
            src_endpoint,
            access_key=src_access_key,
            secret_key=src_secret_key,
            secure=secure
        )

        # If destination credentials not provided, use same as source
        dst_endpoint = dst_endpoint or src_endpoint
        dst_access_key = dst_access_key or src_access_key
        dst_secret_key = dst_secret_key or src_secret_key

        self.dst_client = Minio(
            dst_endpoint,
            access_key=dst_access_key,
            secret_key=dst_secret_key,
            secure=secure
        )

    def _compare_objects(self, src_stat, dst_stat):
        """Compare source and destination objects using metadata.

        Args:
            src_stat: Source object stats from stat_object()
            dst_stat: Destination object stats from stat_object()

        Returns:
            bool: True if objects are identical, False if they need sync
        """
        # Compare size
        if src_stat.size != dst_stat.size:
            return False

        # Compare etag (MD5 hash)
        if src_stat.etag != dst_stat.etag:
            return False

        # Compare last modified time
        if src_stat.last_modified > dst_stat.last_modified:
            return False

        return True

    def sync_folder(self, src_bucket, dst_bucket, folder_path):
        """Sync a folder from source bucket to destination bucket.

        Args:
            src_bucket (str): Source bucket name
            dst_bucket (str): Destination bucket name
            folder_path (str): Folder path to sync (without leading/trailing slash)

        Returns:
            tuple: (success_count, error_count, skipped_count)
        """
        # Ensure folder_path doesn't start/end with slash
        folder_path = folder_path.strip('/')
        if folder_path:
            folder_path += '/'

        success_count = 0
        error_count = 0
        skipped_count = 0
        total_objects = 0

        try:
            # First count total objects for progress tracking
            print(f"\nScanning objects in {src_bucket}/{folder_path}...")
            objects = list(self.src_client.list_objects(src_bucket, prefix=folder_path, recursive=True))
            total_objects = len(objects)
            print(f"Found {total_objects} objects to scan")

            # Now process each object
            for i, obj in enumerate(objects, 1):
                try:
                    print(f"\nProcessing [{i}/{total_objects}] {obj.object_name}")

                    # Get source object stats
                    src_stat = self.src_client.stat_object(src_bucket, obj.object_name)
                    print(f"Source size: {src_stat.size / 1024 / 1024:.2f} MB")

                    # Check if object exists in destination with same metadata
                    try:
                        dst_stat = self.dst_client.stat_object(dst_bucket, obj.object_name)
                        if self._compare_objects(src_stat, dst_stat):
                            print(f"Object {obj.object_name} already synced (identical metadata)")
                            skipped_count += 1
                            continue
                        else:
                            print(f"Object {obj.object_name} exists but needs update")
                    except S3Error as e:
                        if 'NoSuchKey' in str(e) or 'Not Found' in str(e):
                            print(f"Object {obj.object_name} not found in destination")
                        else:
                            raise

                    # Get object data from source and upload
                    print(f"Uploading to {dst_bucket}/{obj.object_name}...")
                    data = self.src_client.get_object(src_bucket, obj.object_name)

                    self.dst_client.put_object(
                        bucket_name=dst_bucket,
                        object_name=obj.object_name,
                        data=data,
                        length=src_stat.size,
                        content_type=src_stat.content_type,
                        metadata=src_stat.metadata
                    )
                    success_count += 1
                    print(f"Successfully synced {obj.object_name}")
                    print(f"Progress: {success_count + error_count + skipped_count}/{total_objects} files processed")

                except S3Error as e:
                    print(f"Error syncing object {obj.object_name}: {str(e)}")
                    error_count += 1
                    continue

        except S3Error as e:
            print(f"Error listing objects in folder {folder_path}: {str(e)}")
            return 0, 1, 0

        print("\nSync Summary:")
        print(f"Total objects: {total_objects}")
        print(f"Successfully synced: {success_count}")
        print(f"Skipped (already synced): {skipped_count}")
        print(f"Failed to sync: {error_count}")
        return success_count, error_count, skipped_count

    def sync_files(self, src_bucket, dst_bucket, files):
        """Sync specific files from source bucket to destination bucket.

        Args:
            src_bucket (str): Source bucket name
            dst_bucket (str): Destination bucket name
            files (list): List of file paths to sync

        Returns:
            tuple: (success_count, error_count, skipped_count)
        """
        success_count = 0
        error_count = 0
        skipped_count = 0
        total_files = len(files)

        print(f"\nPreparing to sync {total_files} files...")

        for i, file_path in enumerate(files, 1):
            try:
                print(f"\nProcessing [{i}/{total_files}] {file_path}")

                # Get source object stats
                src_stat = self.src_client.stat_object(src_bucket, file_path)
                print(f"Source size: {src_stat.size / 1024 / 1024:.2f} MB")

                # Check if object exists in destination with same metadata
                try:
                    dst_stat = self.dst_client.stat_object(dst_bucket, file_path)
                    if self._compare_objects(src_stat, dst_stat):
                        print(f"File {file_path} already synced (identical metadata)")
                        skipped_count += 1
                        continue
                    else:
                        print(f"File {file_path} exists but needs update")
                except S3Error as e:
                    if 'NoSuchKey' in str(e) or 'Not Found' in str(e):
                        print(f"File {file_path} not found in destination")
                    else:
                        raise

                # Get object data from source and upload
                print(f"Uploading to {dst_bucket}/{file_path}...")
                data = self.src_client.get_object(src_bucket, file_path)

                self.dst_client.put_object(
                    bucket_name=dst_bucket,
                    object_name=file_path,
                    data=data,
                    length=src_stat.size,
                    content_type=src_stat.content_type,
                    metadata=src_stat.metadata
                )
                success_count += 1
                print(f"Successfully synced {file_path}")
                print(f"Progress: {success_count + error_count + skipped_count}/{total_files} files processed")

            except S3Error as e:
                print(f"Error syncing file {file_path}: {str(e)}")
                error_count += 1
                continue

        print("\nSync Summary:")
        print(f"Total files: {total_files}")
        print(f"Successfully synced: {success_count}")
        print(f"Skipped (already synced): {skipped_count}")
        print(f"Failed to sync: {error_count}")
        return success_count, error_count, skipped_count

class MilvusCDCPerformanceTest:
    def __init__(self, source_alias, target_alias, source_minio_endpoint, source_minio_bucket_name, target_minio_endpoint, target_minio_bucket_name):
        self.source_alias = source_alias
        self.target_alias = target_alias
        self.source_collection = None
        self.target_collection = None
        self.source_minio_endpoint = source_minio_endpoint
        self.source_minio_bucket_name = source_minio_bucket_name
        self.target_minio_endpoint = target_minio_endpoint
        self.target_minio_bucket_name = target_minio_bucket_name
        self.insert_count = 0
        self.sync_count = 0
        self.import_lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.latest_insert_ts = 0
        self.latest_query_ts = 0
        self.stop_query = False
        self.latencies = []
        self.latest_insert_status = {
            "latest_ts": 0,
            "latest_count": 0
        }

        self.schema = None
        self.collection_name = None
        self.files = None

    def setup_collections(self):
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="timestamp", dtype=DataType.INT64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=128)
        ]
        schema = CollectionSchema(fields, "Milvus CDC test collection")
        self.schema = schema
        c_name = "milvus_cdc_perf_test"
        self.collection_name = c_name
        # Create collections
        self.source_collection = Collection(c_name, schema, using=self.source_alias)
        time.sleep(5)
        self.target_collection = Collection(c_name, using=self.target_alias)
        connections.connect("default",)
        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "L2",
            "params": {"nlist": 1024}
        }
        self.source_collection.create_index("vector", index_params)
        self.source_collection.load()
        time.sleep(1)
        logger.info(f"source collection: {self.source_collection.describe()}")
        logger.info(f"target collection: {self.target_collection.describe()}")

    def generate_data(self, num_entities):
        df = pd.DataFrame(
            {
                "timestamp": [int(time.time() * 1000) for _ in range(num_entities)],  #
                "vector": [[random.random() for _ in range(128)] for _ in range(num_entities)]  # vector
            }
        )
        return df

    def prepare_data(self, num_entities=30000):
        data = self.generate_data(num_entities)
        files = []
        with RemoteBulkWriter(
            schema=self.schema,
            remote_path="bulk_data",
            connect_param=RemoteBulkWriter.ConnectParam(
                bucket_name=self.source_minio_bucket_name,
                endpoint=self.source_minio_endpoint,
                access_key="minioadmin",
                secret_key="minioadmin",
            ),
            file_type= BulkFileType.PARQUET,
        ) as remote_writer:
            for _, row in data.iterrows():
                remote_writer.append_row(row.to_dict())
            remote_writer.commit()
            files = remote_writer.batch_files
        # sync data from upstream to downstream
        syncer = MinioSyncer(
            src_endpoint=self.source_minio_endpoint,
            src_access_key="minioadmin",
            src_secret_key="minioadmin",
            dst_endpoint=self.target_minio_endpoint,
            dst_access_key="minioadmin",
            dst_secret_key="minioadmin",
            secure=False
        )
        # Sync only the specific files generated by RemoteBulkWriter
        all_files = [file for batch in files for file in batch]  # Flatten the list of files
        success, errors, skipped = syncer.sync_files(
            src_bucket=self.source_minio_bucket_name,
            dst_bucket=self.target_minio_bucket_name,
            files=all_files
        )
        if success != len(all_files):
            return [], []
        return files, data

    def do_import(self):
        files, data = self.prepare_data()
        for f in files:
            t0 = time.time()
            logger.info(f"start to bulk insert {f}")
            task_id = utility.do_bulk_insert(self.collection_name, files=f)
            logger.info(f"bulk insert task ids: {task_id}")
            states = utility.get_bulk_insert_state(task_id=task_id)
            while states.state != utility.BulkInsertState.ImportCompleted:
                time.sleep(5)
                states = utility.get_bulk_insert_state(task_id=task_id)
            tt = time.time() - t0
            logger.info(f"bulk insert state: {states} in {tt} with states: {states}")
            assert states.state == utility.BulkInsertState.ImportCompleted
        return files, data

    def continuous_import(self, duration, batch_size):
        end_time = time.time() + duration
        while time.time() < end_time:
            files, data = self.do_import()
            with (self.import_lock):
                self.insert_count += batch_size
                self.latest_insert_status = {
                    "latest_ts": data["timestamp"].iloc[-1],
                    "latest_count": self.insert_count
                }  # Update the latest insert timestamp
                # logger.info(f"insert_count: {self.insert_count}, latest_ts: {self.latest_insert_status['latest_ts']}")
            time.sleep(0.01)  # Small delay to prevent overwhelming the system

    def continuous_query(self):
        while not self.stop_query:
            with self.import_lock:
                latest_insert_ts = self.latest_insert_status["latest_ts"]
                latest_insert_count = self.latest_insert_status["latest_count"]
            print(f"latest_insert_ts: {latest_insert_ts}, latest_insert_count: {latest_insert_count}, "
                  f"latest_query_ts:  {self.latest_query_ts}")
            if latest_insert_ts > self.latest_query_ts:
                t0 = time.time()
                results = self.target_collection.query(
                    expr=f"timestamp == {latest_insert_ts}",
                    output_fields=["timestamp"],
                    limit=1
                )
                tt = time.time() - t0
                # logger.info(f"start to query, latest_insert_ts: {latest_insert_ts}, results: {results}")
                if len(results) > 0 and results[0]["timestamp"] == latest_insert_ts:

                    end_time = time.time()
                    latency = end_time - (latest_insert_ts / 1000) - tt  # Convert milliseconds to seconds
                    with self.sync_lock:
                        self.latest_query_ts = latest_insert_ts
                        self.sync_count = latest_insert_count
                        self.latencies.append(latency)
            time.sleep(0.01)  # Query interval

    def measure_performance(self, duration, batch_size, concurrency):
        self.insert_count = 0
        self.sync_count = 0
        self.latest_insert_ts = 0
        self.latest_query_ts = int(time.time() * 1000)
        self.latencies = []
        self.stop_query = False

        start_time = time.time()

        # Start continuous query thread
        query_thread = threading.Thread(target=self.continuous_query)
        query_thread.start()

        # Start continuous insert threads
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self.continuous_import, duration, batch_size) for _ in range(concurrency)]

        # Wait for all insert operations to complete
        for future in futures:
            future.result()

        self.stop_query = True
        query_thread.join()

        # self.source_collection.flush()

        end_time = time.time()
        total_time = end_time - start_time
        insert_throughput = self.insert_count / total_time
        sync_throughput = self.sync_count / total_time
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0

        logger.info(f"Test duration: {total_time:.2f} seconds")
        logger.info(f"Total inserted: {self.insert_count}")
        logger.info(f"Total synced: {self.sync_count}")
        logger.info(f"Insert throughput: {insert_throughput:.2f} entities/second")
        logger.info(f"Sync throughput: {sync_throughput:.2f} entities/second")
        logger.info(f"Average latency: {avg_latency:.2f} seconds")
        logger.info(f"Min latency: {min(self.latencies):.2f} seconds")
        logger.info(f"Max latency: {max(self.latencies):.2f} seconds")

        return total_time, self.insert_count, self.sync_count, insert_throughput, sync_throughput, avg_latency, min(
            self.latencies), max(self.latencies)

    def test_scalability(self, max_duration=300, batch_size=1000, max_concurrency=10):
        results = []
        for concurrency in range(1, max_concurrency + 1, max_concurrency//3):
            logger.info(f"\nTesting with concurrency: {concurrency}")
            total_time, insert_count, sync_count, insert_throughput, sync_throughput, avg_latency, min_latency, max_latency = self.measure_performance(
                max_duration, batch_size, concurrency)
            results.append((concurrency, total_time, insert_count, sync_count, insert_throughput, sync_throughput,
                            avg_latency, min_latency, max_latency))

        logger.info("\nScalability Test Results:")
        for concurrency, total_time, insert_count, sync_count, insert_throughput, sync_throughput, avg_latency, min_latency, max_latency in results:
            logger.info(f"Concurrency: {concurrency}")
            logger.info(f"  Insert Throughput: {insert_throughput:.2f} entities/second")
            logger.info(f"  Sync Throughput: {sync_throughput:.2f} entities/second")
            logger.info(f"  Avg Latency: {avg_latency:.2f} seconds")

        return results

    def run_all_tests(self, duration=300, batch_size=1000, max_concurrency=10):
        logger.info("Starting Milvus CDC Performance Tests")
        self.setup_collections()
        self.test_scalability(duration, batch_size, max_concurrency)
        logger.info("Milvus CDC Performance Tests Completed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='cdc perf test')
    parser.add_argument('--source_uri', type=str, default='http://10.104.14.100:19530', help='source uri')
    parser.add_argument('--source_token', type=str, default='root:Milvus', help='source token')
    parser.add_argument('--target_uri', type=str, default='http://10.104.27.56:19530', help='target uri')
    parser.add_argument('--target_token', type=str, default='root:Milvus', help='target token')
    parser.add_argument('--source_minio_endpoint', type=str, default='10.104.23.220:9000', help='source minio endpoint')
    parser.add_argument('--source_minio_bucket_name', type=str, default='cdc-test-upstream-19', help='source minio bucket name')
    parser.add_argument('--target_minio_endpoint', type=str, default='10.104.21.239:9000', help='target uri')
    parser.add_argument('--target_minio_bucket_name', type=str, default='cdc-test-downstream-19', help='target token')

    args = parser.parse_args()

    connections.connect("source", uri=args.source_uri, token=args.source_token)
    connections.connect("target", uri=args.target_uri, token=args.target_token)
    connections.connect("default", uri=args.source_uri, token=args.source_token)
    source_minio_endpoint = args.source_minio_endpoint
    source_minio_bucket_name = args.source_minio_bucket_name
    target_minio_endpoint = args.target_minio_endpoint
    target_minio_bucket_name = args.target_minio_bucket_name
    cdc_test = MilvusCDCPerformanceTest("source", "target", source_minio_endpoint, source_minio_bucket_name, target_minio_endpoint, target_minio_bucket_name)
    cdc_test.run_all_tests(duration=300, batch_size=1000, max_concurrency=10)
