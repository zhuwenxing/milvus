import time

import pytest
from time import sleep
from pymilvus import connections, db
from chaos.checker import (CollectionCreateChecker,
                           InsertChecker,
                           BulkInsertChecker,
                           UpsertChecker,
                           FlushChecker,
                           IndexCreateChecker,
                           DeleteChecker,
                           CollectionDropChecker,
                           Op,
                           EventRecords,
                           ResultAnalyzer
                           )
from utils.util_log import test_log as log
from utils.util_k8s import wait_pods_ready, get_milvus_instance_name
from chaos import chaos_commons as cc
from common.common_type import CaseLabel
from common.milvus_sys import MilvusSys
from chaos import constants


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
    def connection(self, host, port, user, password, milvus_ns, minio_host, database_name,
                   downstream_minio_host, downstream_minio_bucket):
        if user and password:
            # log.info(f"connect to {host}:{port} with user {user} and password {password}")
            connections.connect('default', host=host, port=port, user=user, password=password, secure=True)
        else:
            connections.connect('default', host=host, port=port)
        if connections.has_connection("default") is False:
            raise Exception("no connections")
        all_dbs = db.list_database()
        if database_name not in all_dbs:
            try:
                db.create_database(database_name)
            except Exception as e:
                log.error(f"create database {database_name} error: {e}")
        db.using_database(database_name)
        log.info(f"connect to milvus {host}:{port}, db {database_name} successfully")
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.milvus_sys = MilvusSys(alias='default')
        self.milvus_ns = milvus_ns
        self.release_name = get_milvus_instance_name(self.milvus_ns, milvus_sys=self.milvus_sys)
        self.minio_endpoint = f"{minio_host}:9000"
        self.ms = MilvusSys()
        self.bucket_name = self.ms.index_nodes[0]["infos"]["system_configurations"]["minio_bucket_name"]
        self.downstream_minio_endpoint = f"{downstream_minio_host}:9000"
        self.downstream_minio_bucket = downstream_minio_bucket

    def init_health_checkers(self, collection_name=None):
        c_name = collection_name
        checkers = {
            Op.create: CollectionCreateChecker(collection_name=c_name),
            Op.insert: InsertChecker(collection_name=c_name),
            Op.upsert: UpsertChecker(collection_name=c_name),
            Op.flush: FlushChecker(collection_name=c_name),
            Op.index: IndexCreateChecker(collection_name=c_name),
            Op.delete: DeleteChecker(collection_name=c_name),
            Op.drop: CollectionDropChecker(collection_name=c_name),
            Op.bulk_insert: BulkInsertChecker(collection_name=c_name,
                                              bucket_name=self.bucket_name,
                                              minio_endpoint=self.minio_endpoint,
                                              downstream_minio_endpoint=self.downstream_minio_endpoint,
                                              downstream_bucket_name=self.downstream_minio_bucket,
                                              )
        }
        self.health_checkers = checkers

    @pytest.mark.tags(CaseLabel.L3)
    def test_operations(self, request_duration):
        # start the monitor threads to check the milvus ops
        log.info("*********************Test Start**********************")
        log.info(connections.get_connection_addr('default'))
        event_records = EventRecords()
        c_name = None
        event_records.insert("init_health_checkers", "start")
        self.init_health_checkers(collection_name=c_name)
        event_records.insert("init_health_checkers", "finished")
        tasks = cc.start_monitor_threads(self.health_checkers)
        log.info("*********************Load Start**********************")
        # wait request_duration
        request_duration = request_duration.replace("h", "*3600+").replace("m", "*60+").replace("s", "")
        if request_duration[-1] == "+":
            request_duration = request_duration[:-1]
        request_duration = eval(request_duration)
        for i in range(10):
            sleep(request_duration // 10)
            # add an event so that the chaos can start to apply
            if i == 3:
                event_records.insert("init_chaos", "ready")
            for k, v in self.health_checkers.items():
                v.check_result()
        # wait all pod ready
        wait_pods_ready(self.milvus_ns, f"app.kubernetes.io/instance={self.release_name}")
        time.sleep(60)
        cc.check_thread_status(tasks)
        for k, v in self.health_checkers.items():
            v.pause()
        ra = ResultAnalyzer()
        ra.get_stage_success_rate()
        ra.show_result_table()
        log.info("*********************Chaos Test Completed**********************")
