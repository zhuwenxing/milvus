from pymilvus import MilvusClient

def switch_cdc_topology(upstream_uri, downstream_uri, upstream_token, downstream_token, source_cluster_id, target_cluster_id, pchannel_num):
    upstream_client = MilvusClient(uri=upstream_uri, token=upstream_token)
    downstream_client = MilvusClient(uri=downstream_uri, token=downstream_token)
    config = {
        "clusters": [
            {
                "cluster_id": source_cluster_id,
                "connection_param": {
                    "uri": upstream_uri,
                    "token": upstream_token
                },
                "pchannels": [f"{source_cluster_id}-rootcoord-dml_{i}" for i in range(pchannel_num)]
            },
            {
                "cluster_id": target_cluster_id,
                "connection_param": {
                    "uri": downstream_uri,
                    "token": downstream_token
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
    upstream_client.update_replicate_configuration(**config)
    downstream_client.update_replicate_configuration(**config)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='connection info')
    parser.add_argument('--upstream_uri', type=str, default='10.100.36.179', help='milvus host')
    parser.add_argument('--downstream_uri', type=str, default='10.100.36.178', help='milvus host')
    parser.add_argument('--upstream_token', type=str, default='root:Milvus', help='milvus token')
    parser.add_argument('--downstream_token', type=str, default='root:Milvus', help='milvus token')
    parser.add_argument('--source_cluster_id', type=str, default='cdc-test-source', help='source cluster id')
    parser.add_argument('--target_cluster_id', type=str, default='cdc-test-target', help='target cluster id')
    parser.add_argument('--pchannel_num', type=int, default=16, help='pchannel num')
    args = parser.parse_args()
    switch_cdc_topology(args.upstream_uri, 
                        args.downstream_uri, 
                        args.upstream_token, 
                        args.downstream_token, 
                        args.source_cluster_id, 
                        args.target_cluster_id,
                        args.pchannel_num)