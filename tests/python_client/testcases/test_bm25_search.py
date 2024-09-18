import utils.util_pymilvus as ut
from utils.util_log import test_log as log
from common.common_type import CaseLabel, CheckTasks
from common import common_type as ct
from common import common_func as cf
from common.code_mapping import CollectionErrorMessage as clem
from common.code_mapping import ConnectionErrorMessage as cem
from base.client_base import TestcaseBase
from pymilvus import (
    connections, list_collections,
    FieldSchema, CollectionSchema, DataType, Function, FunctionType,
    Collection
)
from pymilvus.orm.types import CONSISTENCY_STRONG, CONSISTENCY_BOUNDED, CONSISTENCY_EVENTUALLY
import threading
from pymilvus import DefaultConfig
from datetime import datetime
import time
import pytest
import random
import numpy as np
import pandas as pd
from faker import Faker
import ast
pd.set_option("expand_frame_repr", False)
fake_en = Faker('en_US')



class TestBM25Search(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test query iterator
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L0)
    def test_bm25_search_normal(self):
        """
        target: test query iterator normal
        method: 1. query iterator
                2. check the result, expect pk
        expected: query successfully
        """
        # 1. initialize with data
        prefix = "test_bm25_search_normal"
        analyzer_params = {
            "tokenizer": "default",
        }
        dim = 128
        default_fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="word", dtype=DataType.VARCHAR, max_length=65535, enable_match=True,
                        analyzer_params=analyzer_params),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=65535, enable_match=True,
                        analyzer_params=analyzer_params),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535, enable_match=True,
                        analyzer_params=analyzer_params),
            FieldSchema(name="word_sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="title_sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="text_sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="dense_emb", dtype=DataType.FLOAT_VECTOR, dim=dim)
        ]
        default_schema = CollectionSchema(fields=default_fields, description="test collection")
        for field in ["word", "title", "text"]:
            bm25_func = Function(
            name=f"bm25_{field}",
            function_type=FunctionType.BM25,
            inputs=[field],
            outputs=[f"{field}_sparse"],
            params={"bm25_k1": 1.2, "bm25_b": 0.75},
            )
            default_schema.add_function(bm25_func)
        print(f"\nCreate collection")

        collection_w = self.init_collection_wrap(name=cf.gen_unique_str(prefix), schema=default_schema)
        nb = 3000
        data = []
        for i in range(nb):
            d = {
                "id": i,
                "word": " ".join([fake_en.word() for x in range(10)]),
                "title": fake_en.sentence(),
                "text":fake_en.paragraph(),
                "dense_emb": cf.gen_vectors(1, dim)[0]
            }
            data.append(d)
        df = pd.DataFrame(data)
        log.info(f"data\n{df}")
        collection_w.insert(data)
        collection_w.create_index("dense_emb", {"index_type": "IVF_FLAT", "metric_type": "L2", "params": {"nlist": 64}})
        index = {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "BM25",
            'params': {"bm25_k1": 1.2, "bm25_b": 0.75},
        }
        for field in ["word_sparse", "title_sparse", "text_sparse"]:
            collection_w.create_index(field, index)
        collection_w.load()
        search_params = {
            "metric_type": "BM25",
            "params": {},
        }
        for field in ["word", "title", "text"]:
            nq = 10
            limit = 100
            texts_to_search = df[field].tolist()[:nq]
            res, _ = collection_w.search(texts_to_search, f"{field}_sparse", search_params, limit=limit, output_fields=["id",field])
            assert len(res) == nq
            for i in range(len(res)):
                r = res[i]
                q = texts_to_search[i]
                log.info(f"query: {q} res: {len(r)}")
                assert len(r) <= limit and r[-1].distance >=0



class TestBM25SearchInvalid(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test query iterator
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L0)
    def test_bm25_function_output_non_exist_field(self):
        """
        target: test query iterator normal
        method: 1. query iterator
                2. check the result, expect pk
        expected: query successfully
        """
        # 1. initialize with data
        prefix = "test_bm25_search"
        analyzer_params = {
            "tokenizer": "default",
        }
        dim = 128
        default_fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="word", dtype=DataType.VARCHAR, max_length=65535, enable_match=True,
                        analyzer_params=analyzer_params),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=65535, enable_match=True,
                        analyzer_params=analyzer_params),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535, enable_match=True,
                        analyzer_params=analyzer_params),
            FieldSchema(name="word_sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="title_sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="text_sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="dense_emb", dtype=DataType.FLOAT_VECTOR, dim=dim)
        ]
        default_schema = CollectionSchema(fields=default_fields, description="test collection")
        for field in ["word", "title"]:
            bm25_func = Function(
            name=f"bm25_{field}",
            function_type=FunctionType.BM25,
            inputs=[field],
            outputs=[f"{field}_sparse"],
            params={"bm25_k1": 1.2, "bm25_b": 0.75},
            )
            default_schema.add_function(bm25_func)

        text_bm25_func = Function(
            name="bm25_text",
            function_type=FunctionType.BM25,
            inputs=[field],
            outputs=[f"{field}_sparse_non_exist"],
            params={"bm25_k1": 1.2, "bm25_b": 0.75},
            )
        default_schema.add_function(text_bm25_func)

        self.init_collection_wrap(name=cf.gen_unique_str(prefix), schema=default_schema,
                                                 check_task=CheckTasks.err_res,
                                                 check_items={"err_code": 1,
                                                              "err_msg": f"Function output field not found in collection schema"}
                                                 )

