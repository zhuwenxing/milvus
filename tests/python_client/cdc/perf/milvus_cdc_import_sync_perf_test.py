import time
import random
import threading
import os
import uuid
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pymilvus import connections, Collection, DataType, FieldSchema, CollectionSchema, utility
from pymilvus.bulk_writer import bulk_import, get_import_progress, list_import_jobs
from loguru import logger

class MilvusCDCPerformanceTest:
    def __init__(self, source_alias, target_alias, source_url, target_url):
        self.source_alias = source_alias
        self.target_alias = target_alias
        self.source_url = source_url
        self.target_url = target_url
        self.source_collection = None
        self.target_collection = None
        self.data_dir = 'import_data'
        self.source_jobs = {}  # Dict of {job_id: (files, start_time, complete_time)}
        self.target_jobs = {}  # Dict of {job_id: (files, start_time, complete_time)}
        self.target_completed_files = set()  # Set of completed file paths in target
        self.latencies = []  # List of (files, source_complete_time, target_complete_time) tuples
        self.stop_import = False

    def setup_collections(self):
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="timestamp", dtype=DataType.INT64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=128)
        ]
        schema = CollectionSchema(fields, "Milvus CDC test collection")
        c_name = "milvus_cdc_perf_test"
        # Create collections
        self.source_collection = Collection(c_name, schema, using=self.source_alias, num_shards=4)
        time.sleep(5)
        self.target_collection = Collection(c_name, using=self.target_alias)
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

        # Create data directory if it doesn't exist
        os.makedirs(self.data_dir, exist_ok=True)
        # prepare import data to minio



    def generate_data(self, num_entities):
        current_ts = int(time.time() * 1000)
        data = {
            'id': list(range(num_entities)),
            'timestamp': [current_ts] * num_entities,
            'vector': [[random.random() for _ in range(128)] for _ in range(num_entities)]
        }
        return pd.DataFrame(data)

    def prepare_import_data(self, num_entities, num_files=10):
        """Prepare parquet files for import testing"""
        entities_per_file = num_entities // num_files
        file_paths = []

        for i in range(num_files):
            df = self.generate_data(entities_per_file)
            file_name = f'{uuid.uuid4()}.parquet'
            file_path = os.path.join(self.data_dir, file_name)
            df.to_parquet(file_path)
            file_paths.append([file_path])

        return file_paths


    def do_import(self, file_paths):
        """Start an import job and return the job ID"""
        resp = bulk_import(
            url=self.source_url,
            collection_name=self.source_collection.name,
            files=file_paths
        )

        job_id = resp.json()['data']['jobId']
        self.source_jobs[job_id] = (tuple(sorted(file_paths)), time.time(), None)
        return job_id

    def continuous_import(self, duration, data_size):
        """Continuously start import jobs for the duration"""
        end_time = time.time() + duration
        while time.time() < end_time and not self.stop_import:
            file_paths = self.prepare_import_data(data_size)
            job_id = self.do_import(file_paths)
            logger.info(f"Started import job {job_id}")
            time.sleep(1)  # Small delay between imports


    def monitor_import_progress(self):
        """Monitor import progress on both source and target clusters"""
        while not self.stop_import or self.source_jobs:
            # Check source jobs that haven't completed
            for job_id, (files, start_time, complete_time) in list(self.source_jobs.items()):
                if complete_time is None:
                    source_resp = get_import_progress(
                        url=self.source_url,
                        job_id=job_id
                    ).json()

                    if source_resp['data']['state'] == 'Completed':
                        source_complete_time = datetime.strptime(
                            source_resp['data']['completeTime'].split('+')[0],
                            '%Y-%m-%dT%H:%M:%S'
                        ).timestamp()
                        self.source_jobs[job_id] = (files, start_time, source_complete_time)

            # Check target jobs
            target_resp = list_import_jobs(
                url=self.target_url,
                collection_name=self.source_collection.name
            ).json()

            for job in target_resp['data']['records']:
                if job['state'] == 'Completed':
                    target_job_details = get_import_progress(
                        url=self.target_url,
                        job_id=job['jobId']
                    ).json()

                    # Get list of files in this target job
                    target_files = tuple(sorted(
                        detail['fileName'].strip('[]')
                        for detail in target_job_details['data']['details']
                    ))

                    # Skip if we've already processed these files
                    if target_files in self.target_completed_files:
                        continue

                    # Find matching source job
                    for src_job_id, (src_files, _, src_complete_time) in self.source_jobs.items():
                        if src_files == target_files and src_complete_time is not None:
                            target_complete_time = datetime.strptime(
                                target_job_details['data']['completeTime'].split('+')[0],
                                '%Y-%m-%dT%H:%M:%S'
                            ).timestamp()

                            # Calculate latency
                            latency = target_complete_time - src_complete_time
                            self.latencies.append((src_files, src_complete_time, target_complete_time))
                            self.target_completed_files.add(target_files)
                            logger.info(f"Import job for files {src_files} completed. Latency: {latency:.2f}s")
                            break

            time.sleep(1)  # Check interval

    def measure_performance(self, duration, batch_size):
        """Measure import sync performance"""
        self.latencies = []
        self.source_jobs = {}
        self.target_completed_files = set()
        self.stop_import = False

        # Start monitoring thread
        monitor_thread = threading.Thread(target=self.monitor_import_progress)
        monitor_thread.start()

        # Start import thread
        import_thread = threading.Thread(target=self.continuous_import, args=(duration, batch_size))
        import_thread.start()

        # Wait for duration
        time.sleep(duration)
        self.stop_import = True

        # Wait for threads to complete
        import_thread.join()
        monitor_thread.join()

        # Calculate statistics
        if self.latencies:
            latencies = [lat[2] - lat[1] for lat in self.latencies]
            avg_latency = sum(latencies) / len(latencies)
            max_latency = max(latencies)
            min_latency = min(latencies)
            p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]

            logger.info("\nPerformance Results:")
            logger.info(f"Total Jobs: {len(self.latencies)}")
            logger.info(f"Average Latency: {avg_latency:.2f}s")
            logger.info(f"Max Latency: {max_latency:.2f}s")
            logger.info(f"Min Latency: {min_latency:.2f}s")
            logger.info(f"P99 Latency: {p99_latency:.2f}s")
        else:
            logger.warning("No import jobs completed during the test duration")

    def run_all_tests(self, duration=300, batch_size=1000):
        logger.info("Starting Milvus CDC Performance Tests")
        self.setup_collections()
        self.measure_performance(duration, batch_size)
        logger.info("Milvus CDC Performance Tests Completed")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='CDC import sync performance test')
    parser.add_argument('--source-alias', type=str, default='source', help='Source Milvus alias')
    parser.add_argument('--target-alias', type=str, default='target', help='Target Milvus alias')
    parser.add_argument('--source-url', type=str, required=True, help='Source Milvus URL')
    parser.add_argument('--target-url', type=str, required=True, help='Target Milvus URL')
    parser.add_argument('--source-minio-url', type=str, required=True, help='Source Minio URL')
    parser.add_argument('--target-minio-url', type=str, required=True, help='Target Minio URL')
    parser.add_argument('--source-minio-bucket', type=str, required=True, help='Source Minio bucket')
    parser.add_argument('--target-minio-bucket', type=str, required=True, help='Target Minio bucket')
    parser.add_argument('--duration', type=int, default=300, help='Test duration in seconds')
    parser.add_argument('--batch-size', type=int, default=10000, help='Number of entities per import batch')

    args = parser.parse_args()

    test = MilvusCDCPerformanceTest(
        source_alias=args.source_alias,
        target_alias=args.target_alias,
        source_url=args.source_url,
        target_url=args.target_url
    )

    test.setup_collections()
    test.measure_performance(args.duration, args.batch_size)
