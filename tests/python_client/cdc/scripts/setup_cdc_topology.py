from pymilvus import MilvusClient
from concurrent.futures import ThreadPoolExecutor, as_completed

def setup_cdc_topology(upstream_uri, downstream_uri, upstream_token, downstream_token, source_cluster_id, target_cluster_id, pchannel_num):
    print(f"DEBUG: upstream_uri: {upstream_uri}, downstream_uri: {downstream_uri}, upstream_token: {upstream_token}, downstream_token: {downstream_token}, source_cluster_id: {source_cluster_id}, target_cluster_id: {target_cluster_id}, pchannel_num: {pchannel_num}")
    upstream_client = MilvusClient(uri=upstream_uri, token=upstream_token)

    # Parse comma-separated lists
    if isinstance(downstream_uri, str) and ',' in downstream_uri:
        downstream_uris = [uri.strip() for uri in downstream_uri.split(',')]
    else:
        downstream_uris = [downstream_uri] if isinstance(downstream_uri, str) else downstream_uri

    if isinstance(target_cluster_id, str) and ',' in target_cluster_id:
        target_cluster_ids = [cluster_id.strip() for cluster_id in target_cluster_id.split(',')]
    else:
        target_cluster_ids = [target_cluster_id] if isinstance(target_cluster_id, str) else target_cluster_id

    # Ensure we have matching numbers of downstream URIs and cluster IDs
    if len(downstream_uris) != len(target_cluster_ids):
        raise ValueError(f"Number of downstream URIs ({len(downstream_uris)}) must match number of target cluster IDs ({len(target_cluster_ids)})")

    # Create downstream clients
    downstream_clients = []
    for downstream_uri_single in downstream_uris:
        print(f"DEBUG: downstream_uri_single: {downstream_uri_single}, downstream_token: {downstream_token}")
        downstream_clients.append(MilvusClient(uri=downstream_uri_single, token=downstream_token))

    # Build clusters configuration
    clusters = [
        {
            "cluster_id": source_cluster_id,
            "connection_param": {
                "uri": upstream_uri,
                "token": upstream_token
            },
            "pchannels": [f"{source_cluster_id}-rootcoord-dml_{i}" for i in range(pchannel_num)]
        }
    ]

    # Add all target clusters
    for target_id, target_uri in zip(target_cluster_ids, downstream_uris):
        clusters.append({
            "cluster_id": target_id,
            "connection_param": {
                "uri": target_uri,
                "token": downstream_token
            },
            "pchannels": [f"{target_id}-rootcoord-dml_{j}" for j in range(pchannel_num)]
        })

    # Build cross-cluster topology
    cross_cluster_topology = []
    for target_id in target_cluster_ids:
        cross_cluster_topology.append({
            "source_cluster_id": source_cluster_id,
            "target_cluster_id": target_id
        })

    config = {
        "clusters": clusters,
        "cross_cluster_topology": cross_cluster_topology
    }

    # Update configuration on all clients using multi-threading
    print(f"DEBUG: config: {config}")

    def update_client_config(client):
        try:
            client.update_replicate_configuration(**config)
            return "Client updated successfully"
        except Exception as e:
            print(f"Failed to update client: {e}")
            raise e

    # Collect all clients for concurrent update
    all_clients = [upstream_client] + downstream_clients

    # Use ThreadPoolExecutor to update all clients concurrently
    with ThreadPoolExecutor(max_workers=len(all_clients)) as executor:
        # Submit all update tasks
        futures = [executor.submit(update_client_config, client) for client in all_clients]

        # Wait for all tasks to complete
        for future in as_completed(futures):
            try:
                result = future.result()
                print(f"Task completed: {result}")
            except Exception as e:
                print(f"Task failed with error: {e}")
                raise e


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
    setup_cdc_topology(args.upstream_uri, 
                        args.downstream_uri, 
                        args.upstream_token, 
                        args.downstream_token, 
                        args.source_cluster_id, 
                        args.target_cluster_id,
                        args.pchannel_num)