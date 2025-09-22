import time

import pytest
from time import sleep
from pymilvus import connections
from chaos.checker import (CollectionCreateChecker,
                           InsertChecker,
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
from chaos import chaos_commons as cc
from common.common_type import CaseLabel
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
    def connection(self, upstream_uri, upstream_token):
        if upstream_token:
            connections.connect('default', uri=upstream_uri, token=upstream_token)
        else:
            connections.connect('default', uri=upstream_uri)
        if connections.has_connection("default") is False:
            raise Exception("no connections")
        log.info("connect to milvus successfully")
        self.upstream_uri = upstream_uri
        self.upstream_token = upstream_token

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
        time.sleep(60)
        cc.check_thread_status(tasks)
        for k, v in self.health_checkers.items():
            v.pause()
        ra = ResultAnalyzer()
        ra.get_stage_success_rate()
        ra.show_result_table()
        log.info("*********************Chaos Test Completed**********************")