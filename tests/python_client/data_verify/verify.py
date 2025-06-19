import os
import argparse

from dotenv import load_dotenv

from pymilvus_pg import MilvusPGClient as MilvusClient

load_dotenv()



def main():
    parser = argparse.ArgumentParser(description="Verify Milvus and PostgreSQL consistency")
    parser.add_argument("--uri", type=str, default=os.getenv("MILVUS_URI", "http://localhost:19530"), help="Milvus server URI")
    parser.add_argument("--pg_conn", type=str, default=os.getenv("PG_CONN", "postgresql://postgres:admin@localhost:5432/default"), help="PostgreSQL DSN")
    parser.add_argument("--collection_name_prefix", type=str, default="data_correctness_checker", help="Collection name prefix")
    args = parser.parse_args()
    milvus_client = MilvusClient(uri=args.uri, pg_conn_str=args.pg_conn)
    collections = milvus_client.list_collections()
    for collection in collections:
        if collection.startswith(args.collection_name_prefix):
            milvus_client.entity_compare(collection, full_scan=True)

if __name__ == "__main__":
    main()