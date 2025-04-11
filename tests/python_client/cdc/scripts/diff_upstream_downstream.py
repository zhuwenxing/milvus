"""
db --> collection --> partition

status:
entities num
load status
index status


then load partition
query all data
compare result

"""
import time

from loguru import logger
import json
import collections.abc
from deepdiff import DeepDiff
from py import log
from pymilvus import connections, Collection, db, list_collections
import threading


def convert_deepdiff(diff):
    if isinstance(diff, dict):
        return {k: convert_deepdiff(v) for k, v in diff.items()}
    elif isinstance(diff, collections.abc.Set):
        return list(diff)
    return diff


def get_collection_info(info, db_name, c_name, enable_compact):
    info[db_name][c_name] = {}
    c = Collection(c_name)
    if enable_compact:
        # flush and compact
        logger.info(f"start flush and compact {db_name}.{c_name}")
        try:
            c.flush(timeout=10)
            c.compact(timeout=10)
            logger.info(f"finished flush and compact {db_name}.{c_name}")
        except Exception as e:
            logger.warning(f"failed to flush and compact {db_name}.{c_name}: {e}")
    info[db_name][c_name]['name'] = c.name
    # logger.info(c.num_entities)
    info[db_name][c_name]['num_entities'] = c.num_entities
    # logger.info(c.schema)
    info[db_name][c_name]['schema'] = len([f.name for f in c.schema.fields])
    # logger.info(c.indexes)
    info[db_name][c_name]['indexes'] = sorted([x.index_name for x in c.indexes])
    # logger.info(c.partitions)
    info[db_name][c_name]['partitions'] = sorted([p.name for p in c.partitions])
    try:
        replicas = len(c.get_replicas().groups)
    except Exception as e:
        logger.warning(e)
        # logger.info(f"no replica for {db_name}.{c_name}")
        replicas = 0
    # logger.info(replicas)
    info[db_name][c_name]['replicas'] = replicas
    if replicas > 0:
        try:
            # logger.info(f"start query {db_name}.{c_name}")
            res = c.query(expr="", output_fields=["count(*)"], timeout=60)
            cnt = res[0]["count(*)"]
            # logger.info(cnt)
            info[db_name][c_name]['cnt'] = cnt
        except Exception as e:
            # logger.warning(f"failed to query {db_name}.{c_name}: {e}")
            info[db_name][c_name]['cnt'] = -1


def get_cluster_info(host, port, user, password, enable_compact=False):
    try:
        connections.disconnect(alias='default')
    except Exception as e:
        logger.warning(e)
    if user and password:
        connections.connect(host=host, port=port, user=user, password=password)
    else:
        connections.connect(host=host, port=port)
    info = {}
    all_db = db.list_database()
    # logger.info(all_db)
    for db_name in all_db:
        info[db_name] = {}
        db.using_database(db_name)
        all_collection = list_collections()
        # logger.info(all_collection)
        threads = []
        for collection_name in all_collection:
            t = threading.Thread(target=get_collection_info, args=(info, db_name, collection_name, enable_compact))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

    # logger.info(json.dumps(info, indent=2))
    return info


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='connection info')
    parser.add_argument('--upstream_host', type=str, default='10.100.36.179', help='milvus host')
    parser.add_argument('--downstream_host', type=str, default='10.100.36.178', help='milvus host')
    parser.add_argument('--upstream_port', type=str, default='19530', help='milvus host')
    parser.add_argument('--downstream_port', type=str, default='19530', help='milvus host')
    parser.add_argument('--port', type=str, default='19530', help='milvus port')
    parser.add_argument('--user', type=str, default='', help='milvus user')
    parser.add_argument('--password', type=str, default='', help='milvus password')
    parser.add_argument('--enable_compact', type=bool, default=False, help='enable compact')
    args = parser.parse_args()
    diff_cnt = 0
    diff = None
    t0 = time.time()
    while diff_cnt < 10:
        if diff_cnt == 0:
            enable_compact = args.enable_compact
            if enable_compact in ["True", "true", "1"]:
                enable_compact = True
            if enable_compact in ["False", "false", "0"]:
                enable_compact = False
        else:
            enable_compact = False
        upstream = get_cluster_info(args.upstream_host, args.upstream_port, args.user, args.password,
                                    enable_compact)
        downstream = get_cluster_info(args.downstream_host, args.downstream_port, args.user, args.password,
                                      enable_compact)
        # logger.info(f"upstream info: {json.dumps(upstream, indent=2)}")
        # logger.info(f"downstream info: {json.dumps(downstream, indent=2)}")
        diff = DeepDiff(upstream, downstream)
        diff = convert_deepdiff(diff)
        logger.info(f"diff: {diff}")
        logger.info(f"diff: {json.dumps(diff, indent=2)}")
        with open("diff.json", "w") as f:
            json.dump(diff, f, indent=2)
        excludedRegex = [r"root(\[\'\w+\'\])*\['num_entities'\]"]
        diff = DeepDiff(upstream, downstream, exclude_regex_paths=excludedRegex)
        diff = convert_deepdiff(diff)
        logger.info(f"diff exclude num entities: {diff}")
        logger.info(f"diff exclude num entities: {json.dumps(diff, indent=2)}")
        diff_cnt += 1
        if diff:
            logger.info(f"diff exclude num entities found between upstream and downstream {json.dumps(diff, indent=2)}")
            time.sleep(60)

        else:
            logger.info("no diff exclude num entities found between upstream and downstream")
            break
    tt = time.time() - t0
    logger.info(f"total time cost: {tt:.2f} seconds")
    if diff:
        assert False, f"diff found between upstream and downstream {json.dumps(diff, indent=2)}"
