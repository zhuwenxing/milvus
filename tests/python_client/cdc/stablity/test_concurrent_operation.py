import time
import pytest
import json
from time import sleep
from pymilvus import connections
from chaos.checker import (InsertChecker,
                           UpsertChecker,
                           FlushChecker,
                           DeleteChecker,
                           Op,
                           ResultAnalyzer
                           )
from utils.util_k8s import wait_pods_ready, get_milvus_instance_name
from utils.util_log import test_log as log
from chaos import chaos_commons as cc
from common import common_func as cf
from common.milvus_sys import MilvusSys
from common.common_type import CaseLabel
from chaos import constants


def get_all_collections():
    try:
        with open("/tmp/ci_logs/chaos_test_all_collections.json", "r") as f:
            data = json.load(f)
            all_collections = data["all"]
    except Exception as e:
        log.warning(f"get_all_collections error: {e}")
        return [None]
    return all_collections


class TestBase:
    expect_create = constants.SUCC
    expect_insert = constants.SUCC
    expect_flush = constants.SUCC
    expect_compact = constants.SUCC
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
            # log.info(f"connect to {host}:{port} with user {user} and password {password}")
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
            Op.insert: InsertChecker(collection_name=c_name),
            Op.upsert: UpsertChecker(collection_name=c_name),
            Op.flush: FlushChecker(collection_name=c_name),
            Op.delete: DeleteChecker(collection_name=c_name),
        }
        log.info(f"init_health_checkers: {checkers}")
        self.health_checkers = checkers

    @pytest.fixture(scope="function", params=get_all_collections())
    def collection_name(self, request):
        if request.param == [] or request.param == "":
            pytest.skip("The collection name is invalid")
        yield request.param

    @pytest.mark.tags(CaseLabel.L3)
    def test_operations(self, request_duration, collection_name):
        # start the monitor threads to check the milvus ops
        log.info("*********************Test Start**********************")
        log.info(connections.get_connection_addr('default'))
        # event_records = EventRecords()
        c_name = collection_name if collection_name else cf.gen_unique_str("Checker_")
        # event_records.insert("init_health_checkers", "start")
        self.init_health_checkers(collection_name=c_name)
        # event_records.insert("init_health_checkers", "finished")
        cc.start_monitor_threads(self.health_checkers)
        log.info("*********************Load Start**********************")
        request_duration = request_duration.replace("h", "*3600+").replace("m", "*60+").replace("s", "")
        if request_duration[-1] == "+":
            request_duration = request_duration[:-1]
        request_duration = eval(request_duration)
        for i in range(10):
            sleep(request_duration//10)
            for k, v in self.health_checkers.items():
                v.check_result()
        time.sleep(60)
        ra = ResultAnalyzer()
        ra.get_stage_success_rate()
        log.info("*********************Chaos Test Completed**********************")