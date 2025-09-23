import pytest
import time
import random
import string
import numpy as np
import logging
from datetime import datetime
from typing import Any, Dict, List, Callable
from pymilvus import MilvusClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    """Add command line options for pytest."""
    parser.addoption("--upstream-uri", action="store", default="http://10.104.6.33:19530",
                     help="Upstream Milvus uri")
    parser.addoption("--upstream-token", action="store", default="root:Milvus",
                     help="Upstream Milvus token")
    parser.addoption("--downstream-uri", action="store", default="http://10.104.6.32:19530",
                     help="Downstream Milvus uri")
    parser.addoption("--downstream-token", action="store", default="root:Milvus",
                     help="Downstream Milvus token")
    parser.addoption("--sync-timeout", action="store", default="120",
                     help="Sync timeout in seconds")
    parser.addoption("--source-cluster-id", action="store", default="cdc-test-source-0919",
                     help="Source cluster ID for CDC topology")
    parser.addoption("--target-cluster-id", action="store", default="cdc-test-target-0919",
                     help="Target cluster ID for CDC topology")
    parser.addoption("--pchannel-num", action="store", default="16",
                     help="Number of physical channels for CDC")


@pytest.fixture(scope="session")
def upstream_client(request):
    """Create upstream MilvusClient."""
    uri = request.config.getoption("--upstream-uri")
    token = request.config.getoption("--upstream-token")
    client = MilvusClient(uri=uri, token=token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def downstream_client(request):
    """Create downstream MilvusClient."""
    uri = request.config.getoption("--downstream-uri")
    token = request.config.getoption("--downstream-token")
    client = MilvusClient(uri=uri, token=token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def sync_timeout(request):
    """Get sync timeout from command line."""
    return int(request.config.getoption("--sync-timeout"))

@pytest.fixture(scope="session")
def downstream_uri(request):
    """Get downstream uri from command line."""
    return request.config.getoption("--downstream-uri")

@pytest.fixture(scope="session", autouse=True)
def cdc_topology_setup(request, upstream_client, downstream_client):
    """Setup CDC topology at the beginning of test session."""
    upstream_uri = request.config.getoption("--upstream-uri")
    downstream_uri = request.config.getoption("--downstream-uri")
    source_cluster_id = request.config.getoption("--source-cluster-id")
    target_cluster_id = request.config.getoption("--target-cluster-id")
    pchannel_num = int(request.config.getoption("--pchannel-num"))

    logger.info(f"Setting up CDC topology: {source_cluster_id} -> {target_cluster_id} (channels: {pchannel_num})...")

    # Create CDC replication configuration
    config = {
        "clusters": [
            {
                "cluster_id": source_cluster_id,
                "connection_param": {
                    "uri": upstream_uri,
                    "token": request.config.getoption("--upstream-token")
                },
                "pchannels": [f"{source_cluster_id}-rootcoord-dml_{i}" for i in range(pchannel_num)]
            },
            {
                "cluster_id": target_cluster_id,
                "connection_param": {
                    "uri": downstream_uri,
                    "token": request.config.getoption("--downstream-token")
                },
                "pchannels": [f"{target_cluster_id}-rootcoord-dml_{i}" for i in range(pchannel_num)]
            }
        ],
        "cross_cluster_topology": [
            {
                "source_cluster_id": source_cluster_id,
                "target_cluster_id": target_cluster_id
            }
        ]
    }

    try:
        # Update replication configuration on both clusters
        upstream_client.update_replicate_configuration(**config)
        downstream_client.update_replicate_configuration(**config)
        logger.info("CDC topology setup completed successfully")

        # Allow some time for CDC to initialize
        time.sleep(5)

    except Exception as e:
        logger.error(f"Failed to setup CDC topology: {e}")
        raise

    yield

    # Cleanup can be added here if needed
    logger.info("CDC topology teardown completed")