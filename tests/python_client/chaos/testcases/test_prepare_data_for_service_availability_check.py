import time
import pytest
from time import sleep
from pymilvus import (
    connections, list_collections,
    FieldSchema, CollectionSchema, DataType,
    Collection, RemoteBulkWriter, BulkInsertState, BulkFileType, utility
)
from chaos.checker import (
                           SearchChecker,
                           QueryChecker,
                           Op)
from utils.util_log import test_log as log
from chaos import chaos_commons as cc
from common.common_type import CaseLabel
from common import common_func as cf
from chaos.chaos_commons import assert_statistic
from chaos import constants
from common.milvus_sys import MilvusSys
import random


class TestBase:
    expect_create = constants.SUCC
    expect_insert = constants.SUCC
    expect_flush = constants.SUCC
    expect_index = constants.SUCC
    expect_search = constants.SUCC
    expect_query = constants.SUCC
    host = '127.0.0.1'
    port = 19530
    _chaos_config = None
    health_checkers = {}


class TestOperations(TestBase):

    @pytest.fixture(scope="function", autouse=True)
    def connection(self, host, port, user, password, minio_host):
        if user and password:
            # log.info(f"connect to {host}:{port} with user {user} and password {password}")
            connections.connect('default', host=host, port=port, user=user, password=password, secure=True)
        else:
            connections.connect('default', host=host, port=port)
        if connections.has_connection("default") is False:
            raise Exception("no connections")
        log.info("connect to milvus successfully")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.minio_endpoint = f"{minio_host}:9000"
        self.ms = MilvusSys()
        self.bucket_name = self.ms.index_nodes[0]["infos"]["system_configurations"]["minio_bucket_name"]

    def init_health_checkers(self, collection_name=None):

        c_name = collection_name
        schema = cf.gen_default_collection_schema(auto_id=False)

        checkers = {
            Op.search: SearchChecker(collection_name=c_name, schema=schema)
        }
        self.health_checkers = checkers

    @pytest.mark.tags(CaseLabel.L3)
    def test_operations(self, data_size):
        # start the monitor threads to check the milvus ops
        log.info("*********************Test Start**********************")
        log.info(connections.get_connection_addr('default'))
        c_name = "Checker_Service_Availability"
        self.init_health_checkers(collection_name=c_name)
        # prepare data by bulk insert
        log.info("*********************Prepare Data by bulk insert**********************")
        schema = self.health_checkers[Op.search].schema
        collection_name = c_name
        c = Collection(collection_name)
        batch_size = 100000
        batch_num = data_size // batch_size
        with RemoteBulkWriter(
                schema=schema,
                file_type=BulkFileType.NUMPY,
                remote_path="bulk_data",
                connect_param=RemoteBulkWriter.ConnectParam(
                    endpoint=self.minio_endpoint,
                    access_key="minioadmin",
                    secret_key="minioadmin",
                    bucket_name=self.bucket_name
                )
        ) as remote_writer:
            for i in range(batch_size):
                row = cf.get_row_data_by_schema(nb=1, schema=schema)[0]
                remote_writer.append_row(row)
            remote_writer.commit()
            batch_files = remote_writer.batch_files
        task_ids = []
        for i in range(batch_num):
            for files in batch_files:
                task_id = utility.do_bulk_insert(collection_name=collection_name, files=files)
                task_ids.append(task_id)
                log.info(f"Create a bulk inert task, task id: {task_id}")

        while len(task_ids) > 0:
            log.info("Wait 30 second to check bulk insert tasks state...")
            time.sleep(30)
            for id in task_ids:
                state = utility.get_bulk_insert_state(task_id=id)
                if state.state == BulkInsertState.ImportFailed or state.state == BulkInsertState.ImportFailedAndCleaned:
                    log.info(f"The task {state.task_id} failed, reason: {state.failed_reason}")
                    task_ids.remove(id)
                elif state.state == BulkInsertState.ImportCompleted:
                    log.info(f"The task {state.task_id} completed with state {state}")
                    task_ids.remove(id)

        log.info(f"inserted vectors: {c.num_entities}")
        log.info("*********************Load Start**********************")
        cc.start_monitor_threads(self.health_checkers)

        # wait request_duration
        request_duration = 120
        for i in range(10):
            sleep(request_duration // 10)
            for k, v in self.health_checkers.items():
                v.check_result()
        for k, v in self.health_checkers.items():
            v.pause()
        for k, v in self.health_checkers.items():
            v.check_result()
        for k, v in self.health_checkers.items():
            log.info(f"{k} failed request: {v.fail_records}")
        for k, v in self.health_checkers.items():
            log.info(f"{k} rto: {v.get_rto()}")
        assert_statistic(self.health_checkers, succ_rate_threshold=1.0)
        # get each checker's rto
        for k, v in self.health_checkers.items():
            log.info(f"{k} rto: {v.get_rto()}")
            rto = v.get_rto()
            pytest.assume(rto < 30,  f"{k} rto expect 30s but get {rto}s")  # rto should be less than 30s
        log.info("*********************Test Completed**********************")
