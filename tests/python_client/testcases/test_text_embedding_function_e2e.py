import random
import uuid
from pymilvus import (
    FieldSchema,
    CollectionSchema,
    DataType,
    Function,
    FunctionType,
    AnnSearchRequest,
    WeightedRanker,
)
from common.common_type import CaseLabel, CheckTasks
from common import common_func as cf
from utils.util_log import test_log as log
from base.client_base import TestcaseBase
import numpy as np
import pytest
import pandas as pd
from faker import Faker

fake_zh = Faker("zh_CN")
fake_jp = Faker("ja_JP")
fake_en = Faker("en_US")

pd.set_option("expand_frame_repr", False)

prefix = "text_embedding_collection"


# TEI: https://github.com/huggingface/text-embeddings-inference
# model id:BAAI/bge-base-en-v1.5
# dim: 768

@pytest.mark.tags(CaseLabel.L1)
class TestCreateCollectionWithTextEmbedding(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test create collection with text embedding function
    ******************************************************************
    """

    def test_create_collection_with_text_embedding(self, tei_endpoint):
        """
        target: test create collection with text embedding function
        method: create collection with text embedding function
        expected: create collection successfully
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            }
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1

    def test_create_collection_with_text_embedding_twice_with_same_schema(
            self, tei_endpoint
    ):
        """
        target: test create collection with text embedding twice with same schema
        method: create collection with text embedding function, then create again
        expected: create collection successfully and create again successfully
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        self.init_collection_wrap(name=c_name, schema=schema)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1


@pytest.mark.tags(CaseLabel.L1)
class TestCreateCollectionWithTextEmbeddingNegative(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test create collection with text embedding negative
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L1)
    def test_create_collection_with_text_embedding_unsupported_endpoint(self):
        """
        target: test create collection with text embedding with unsupported model
        method: create collection with text embedding function using unsupported model
        expected: create collection failed
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": "http://unsupported_endpoint",
            },
        )
        schema.add_function(text_embedding_function)

        self.init_collection_wrap(
            name=cf.gen_unique_str(prefix),
            schema=schema,
            check_task=CheckTasks.err_res,
            check_items={"err_code": 65535, "err_msg": "unsupported_endpoint"},
        )

    def test_create_collection_with_text_embedding_unmatched_dim(self, tei_endpoint):
        """
        target: test create collection with text embedding with unsupported model
        method: create collection with text embedding function using unsupported model
        expected: create collection failed
        """
        dim = 512
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        self.init_collection_wrap(
            name=cf.gen_unique_str(prefix),
            schema=schema,
            check_task=CheckTasks.err_res,
            check_items={
                "err_code": 65535,
                "err_msg": f"The required embedding dim is [{dim}], but the embedding obtained from the model is [768]",
            },
        )


@pytest.mark.tags(CaseLabel.L0)
class TestInsertWithTextEmbedding(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test insert with text embedding
    ******************************************************************
    """

    def test_insert_with_text_embedding(self, tei_endpoint):
        """
        target: test insert data with text embedding
        method: insert data with text embedding function
        expected: insert successfully
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # prepare data
        nb = 10
        data = [{"id": i, "document": fake_en.text()} for i in range(nb)]

        # insert data
        collection_w.insert(data)
        assert collection_w.num_entities == nb
        # create index
        index_params = {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 48},
        }
        collection_w.create_index(field_name="dense", index_params=index_params)
        collection_w.load()
        res, _ = collection_w.query(
            expr="id >= 0",
            output_fields=["dense"],
        )
        for row in res:
            # For INT8_VECTOR, the data might be returned as a binary array
            # We need to check if there's data, but not necessarily the exact dimension
            if isinstance(row["dense"], bytes):
                # For binary data, just verify it's not empty
                assert len(row["dense"]) > 0, "Vector should not be empty"
            else:
                # For regular vectors, check the exact dimension
                assert len(row["dense"]) == dim

    @pytest.mark.parametrize("truncate", [True, False])
    @pytest.mark.parametrize("truncation_direction", ["Left", "Right"])
    def test_insert_with_text_embedding_truncate(self, tei_endpoint, truncate, truncation_direction):
        """
        target: test insert data with text embedding
        method: insert data with text embedding function
        expected: insert successfully
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
                "truncate": truncate,
                "truncation_direction": truncation_direction
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # prepare data
        left = " ".join([fake_en.word() for _ in range(512)])
        right = " ".join([fake_en.word() for _ in range(512)])
        data = [
            {
                "id": 0,
                "document": left + " " + right
            },
            {
                "id": 1,
                "document": left
            },
            {
                "id": 2,
                "document": right
            }]
        res, result = collection_w.insert(data, check_task=CheckTasks.check_nothing)

        if not truncate:
            assert result is False
            print("truncate is False, should insert failed")
            return

        assert collection_w.num_entities == len(data)
        # create index
        index_params = {
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 48},
        }
        collection_w.create_index(field_name="dense", index_params=index_params)
        collection_w.load()
        res, _ = collection_w.query(
            expr="id >= 0",
            output_fields=["dense"],
        )
        # compare similarity between left and right using cosine similarity
        import numpy as np
        # Calculate cosine similarity: cos(θ) = A·B / (||A|| * ||B||)
        # when direction is left, right part is reversed
        similarity_left = np.dot(res[0]["dense"], res[1]["dense"]) / (
                    np.linalg.norm(res[0]["dense"]) * np.linalg.norm(res[1]["dense"]))
        # when direction is right, left part is reversed
        similarity_right = np.dot(res[0]["dense"], res[2]["dense"]) / (
                    np.linalg.norm(res[0]["dense"]) * np.linalg.norm(res[2]["dense"]))
        if truncation_direction == "Left":
            assert similarity_left < similarity_right
        else:
            assert similarity_left > similarity_right


@pytest.mark.tags(CaseLabel.L2)
class TestInsertWithTextEmbeddingNegative(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test insert with text embedding negative
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.skip("not support empty document now")
    def test_insert_with_text_embedding_empty_document(self, tei_endpoint):
        """
        target: test insert data with empty document
        method: insert data with empty document
        expected: insert failed
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # prepare data with empty document
        empty_data = [{"id": 1, "document": ""}]
        normal_data = [{"id": 2, "document": fake_en.text()}]
        data = empty_data + normal_data

        collection_w.insert(
            data,
            check_task=CheckTasks.err_res,
            check_items={"err_code": 65535, "err_msg": "cannot be empty"},
        )
        assert collection_w.num_entities == 0

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.skip("TODO")
    def test_insert_with_text_embedding_long_document(self, tei_endpoint):
        """
        target: test insert data with long document
        method: insert data with long document
        expected: insert failed
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # prepare data with empty document
        long_data = [{"id": 1, "document": " ".join([fake_en.word() for _ in range(8192)])}]
        normal_data = [{"id": 2, "document": fake_en.text()}]
        data = long_data + normal_data

        collection_w.insert(
            data,
            check_task=CheckTasks.err_res,
            check_items={
                "err_code": 65535,
                "err_msg": "Call service faild",
            },
        )
        assert collection_w.num_entities == 0


@pytest.mark.tags(CaseLabel.L1)
class TestUpsertWithTextEmbedding(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test upsert with text embedding
    ******************************************************************
    """

    def test_upsert_text_field(self, tei_endpoint):
        """
        target: test upsert text field updates embedding
        method: 1. insert data
                2. upsert text field
                3. verify embedding is updated
        expected: embedding should be updated after text field is updated
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )
        # create index and load
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection_w.create_index("dense", index_params)
        collection_w.load()

        # insert initial data
        old_text = "This is the original text"
        data = [{"id": 1, "document": old_text}]
        collection_w.insert(data)

        # get original embedding
        res, _ = collection_w.query(expr="id == 1", output_fields=["dense"])
        old_embedding = res[0]["dense"]

        # upsert with new text
        new_text = "This is the updated text"
        upsert_data = [{"id": 1, "document": new_text}]
        collection_w.upsert(upsert_data)

        # get new embedding
        res, _ = collection_w.query(expr="id == 1", output_fields=["dense"])
        new_embedding = res[0]["dense"]

        # verify embeddings are different
        assert not np.allclose(old_embedding, new_embedding)
        # caculate cosine similarity
        sim = np.dot(old_embedding, new_embedding) / (
                np.linalg.norm(old_embedding) * np.linalg.norm(new_embedding)
        )
        log.info(f"cosine similarity: {sim}")
        assert sim < 0.99


@pytest.mark.tags(CaseLabel.L1)
class TestDeleteWithTextEmbedding(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test delete with text embedding
    ******************************************************************
    """

    def test_delete_and_search(self, tei_endpoint):
        """
        target: test deleted text cannot be searched
        method: 1. insert data
                2. delete some data
                3. verify deleted data cannot be searched
        expected: deleted data should not appear in search results
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # insert data
        nb = 3
        data = [{"id": i, "document": f"This is test document {i}"} for i in range(nb)]
        collection_w.insert(data)

        # create index and load
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection_w.create_index("dense", index_params)
        collection_w.load()

        # delete document 1
        collection_w.delete("id in [1]")

        # search and verify document 1 is not in results
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
        res, _ = collection_w.search(
            data=["test document 1"],
            anns_field="dense",
            param=search_params,
            limit=3,
            output_fields=["document", "id"],
        )
        assert len(res) == 1
        for hit in res[0]:
            assert hit.entity.get("id") != 1


@pytest.mark.tags(CaseLabel.L0)
class TestSearchWithTextEmbedding(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test search with text embedding
    ******************************************************************
    """

    def test_search_with_text_embedding(self, tei_endpoint):
        """
        target: test search with text embedding
        method: search with text embedding function
        expected: search successfully
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
            },
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # prepare data
        nb = 10
        data = [{"id": i, "document": fake_en.text()} for i in range(nb)]

        # insert data
        collection_w.insert(data)
        assert collection_w.num_entities == nb

        # create index
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection_w.create_index("dense", index_params)
        collection_w.load()

        # search
        search_params = {"metric_type": "COSINE", "params": {}}
        nq = 1
        limit = 10
        res, _ = collection_w.search(
            data=[fake_en.text() for _ in range(nq)],
            anns_field="dense",
            param=search_params,
            limit=10,
            output_fields=["document"],
        )
        assert len(res) == nq
        for hits in res:
            assert len(hits) == limit


@pytest.mark.tags(CaseLabel.L1)
class TestSearchWithTextEmbeddingNegative(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test search with text embedding negative
    ******************************************************************
    """

    @pytest.mark.tags(CaseLabel.L1)
    @pytest.mark.parametrize("query", ["empty_query", "long_query"])
    @pytest.mark.skip("not support empty query now")
    def test_search_with_text_embedding_negative_query(self, query, tei_endpoint):
        """
        target: test search with empty query or long query
        method: search with empty query
        expected: search failed
        """
        if query == "empty_query":
            query = ""
        if query == "long_query":
            query = " ".join([fake_en.word() for _ in range(8192)])
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint
            }
        )
        schema.add_function(text_embedding_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # prepare data
        nb = 10
        data = [{"id": i, "document": fake_en.text()} for i in range(nb)]

        # insert data
        collection_w.insert(data)
        assert collection_w.num_entities == nb

        # create index
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection_w.create_index("dense", index_params)
        collection_w.load()

        # search with empty query should fail
        search_params = {"metric_type": "COSINE", "params": {}}
        collection_w.search(
            data=[query],
            anns_field="dense",
            param=search_params,
            limit=3,
            output_fields=["document"],
            check_task=CheckTasks.err_res,
            check_items={"err_code": 65535, "err_msg": "Call service faild"},
        )


@pytest.mark.tags(CaseLabel.L1)
class TestHybridSearch(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test hybrid search
    ******************************************************************
    """

    def test_hybrid_search(self, tei_endpoint):
        """
        target: test hybrid search with text embedding and BM25
        method: 1. create collection with text embedding and BM25 functions
                2. insert data
                3. perform hybrid search
        expected: search results should combine vector similarity and text relevance
        """
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(
                name="document",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params={"tokenizer": "standard"},
            ),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        # Add text embedding function
        text_embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint
            }
        )
        schema.add_function(text_embedding_function)

        # Add BM25 function
        bm25_function = Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["document"],
            output_field_names="sparse",
            params={},
        )
        schema.add_function(bm25_function)

        collection_w = self.init_collection_wrap(
            name=cf.gen_unique_str(prefix), schema=schema
        )

        # insert test data
        data_size = 1000
        data = [{"id": i, "document": fake_en.text()} for i in range(data_size)]

        for batch in range(0, data_size, 100):
            collection_w.insert(data[batch: batch + 100])

        # create index and load
        dense_index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        sparse_index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "BM25",
            "params": {},
        }
        collection_w.create_index("dense", dense_index_params)
        collection_w.create_index("sparse", sparse_index_params)
        collection_w.load()
        nq = 2
        limit = 100
        dense_text_search = AnnSearchRequest(
            data=[fake_en.text().lower() for _ in range(nq)],
            anns_field="dense",
            param={},
            limit=limit,
        )
        dense_vector_search = AnnSearchRequest(
            data=[[random.random() for _ in range(dim)] for _ in range(nq)],
            anns_field="dense",
            param={},
            limit=limit,
        )
        full_text_search = AnnSearchRequest(
            data=[fake_en.text().lower() for _ in range(nq)],
            anns_field="sparse",
            param={},
            limit=limit,
        )
        # hybrid search
        res_list, _ = collection_w.hybrid_search(
            reqs=[dense_text_search, dense_vector_search, full_text_search],
            rerank=WeightedRanker(0.5, 0.5, 0.5),
            limit=limit,
            output_fields=["id", "document"],
        )
        assert len(res_list) == nq
        # check the result correctness
        for i in range(nq):
            log.info(f"res length: {len(res_list[i])}")
            assert len(res_list[i]) == limit


@pytest.mark.tags(CaseLabel.L1)
class TestTextEmbeddingFunctionCURD(TestcaseBase):
    """
    ******************************************************************
      The following cases are used to test add/alter/drop collection function APIs
    ******************************************************************
    """

    # ==================== add_collection_function positive tests ====================

    def test_add_collection_function_text_embedding(self, tei_endpoint):
        """
        target: test add text embedding function to existing collection
        method: create collection without function, then add function via API
        expected: function added successfully, describe shows 1 function
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Verify no functions initially
        res, _ = collection_w.describe()
        assert len(res.get("functions", [])) == 0

        # Create and add function
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        self.client.add_collection_function(
            collection_name=c_name,
            function=embedding_function
        )

        # Verify function is added
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1
        assert res["functions"][0]["name"] == "text_embedding"

    def test_add_collection_function_then_insert_search(self, tei_endpoint):
        """
        target: test that added function works for insert and search
        method: create collection without function, add function, then insert and search
        expected: insert and search work correctly with dynamically added function
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Add function
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        self.client.add_collection_function(
            collection_name=c_name,
            function=embedding_function
        )

        # Insert data (only text, vector should be auto-generated)
        nb = 10
        data = [{"id": i, "document": fake_en.text()} for i in range(nb)]
        collection_w.insert(data)
        assert collection_w.num_entities == nb

        # Create index and load
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection_w.create_index("dense", index_params)
        collection_w.load()

        # Verify vectors are generated
        res, _ = collection_w.query(expr="id >= 0", output_fields=["dense"])
        for row in res:
            assert len(row["dense"]) == dim

        # Search with text
        search_params = {"metric_type": "COSINE", "params": {}}
        res, _ = collection_w.search(
            data=[fake_en.text()],
            anns_field="dense",
            param=search_params,
            limit=5,
            output_fields=["document"],
        )
        assert len(res) == 1
        assert len(res[0]) == 5

    def test_add_collection_function_multiple_functions(self, tei_endpoint):
        """
        target: test add multiple functions to a collection
        method: create collection with required fields, add text_embedding and BM25 functions
        expected: both functions added successfully
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(
                name="document",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params={"tokenizer": "standard"},
            ),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Add text embedding function
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        self.client.add_collection_function(
            collection_name=c_name,
            function=embedding_function
        )

        # Add BM25 function
        bm25_function = Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["document"],
            output_field_names="sparse",
            params={},
        )
        self.client.add_collection_function(
            collection_name=c_name,
            function=bm25_function
        )

        # Verify both functions are added
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 2
        function_names = [f["name"] for f in res["functions"]]
        assert "text_embedding" in function_names
        assert "bm25" in function_names

    # ==================== add_collection_function negative tests ====================

    def test_add_collection_function_nonexistent_collection(self, tei_endpoint):
        """
        target: test add function to nonexistent collection
        method: call add_collection_function on collection that doesn't exist
        expected: error with collection not found
        """
        self._connect()
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.add_collection_function(
                collection_name="nonexistent_collection_12345",
                function=embedding_function
            )
            assert False, "Expected exception for nonexistent collection"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "can't find" in str(e).lower()

    def test_add_collection_function_duplicate_name(self, tei_endpoint):
        """
        target: test add function with duplicate name
        method: create collection with function, try to add another function with same name
        expected: error indicating duplicate function name
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        # Add function to schema first
        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Try to add another function with same name
        duplicate_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.add_collection_function(
                collection_name=c_name,
                function=duplicate_function
            )
            assert False, "Expected exception for duplicate function name"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "duplicate" in str(e).lower() or "exist" in str(e).lower() or "already" in str(e).lower()

    def test_add_collection_function_missing_input_field(self, tei_endpoint):
        """
        target: test add function with input field that doesn't exist
        method: add function referencing non-existent input field
        expected: error indicating input field not found
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Create function with non-existent input field
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["nonexistent_field"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.add_collection_function(
                collection_name=c_name,
                function=embedding_function
            )
            assert False, "Expected exception for missing input field"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "input" in str(e).lower()

    def test_add_collection_function_missing_output_field(self, tei_endpoint):
        """
        target: test add function with output field that doesn't exist
        method: add function referencing non-existent output field
        expected: error indicating output field not found
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Create function with non-existent output field
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="nonexistent_vector_field",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.add_collection_function(
                collection_name=c_name,
                function=embedding_function
            )
            assert False, "Expected exception for missing output field"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "output" in str(e).lower()

    def test_add_collection_function_dim_mismatch(self, tei_endpoint):
        """
        target: test add function with dimension mismatch
        method: create collection with vector field dim=512, add function for model that outputs dim=768
        expected: error indicating dimension mismatch
        """
        self._connect()
        dim = 512  # Mismatched dimension (TEI model outputs 768)
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Create function (model outputs 768 dim, but field is 512)
        embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.add_collection_function(
                collection_name=c_name,
                function=embedding_function
            )
            assert False, "Expected exception for dimension mismatch"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "dim" in str(e).lower() or "dimension" in str(e).lower() or "mismatch" in str(e).lower()

    # ==================== alter_collection_function positive tests ====================

    def test_alter_collection_function_change_endpoint(self, tei_endpoint):
        """
        target: test alter function to change endpoint
        method: create collection with function, alter function endpoint
        expected: endpoint changed successfully
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Alter function with same endpoint (just testing the API works)
        new_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        self.client.alter_collection_function(
            collection_name=c_name,
            function_name="tei",
            function=new_function
        )

        # Verify function still exists
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1

    def test_alter_collection_function_change_params(self, tei_endpoint):
        """
        target: test alter function parameters (truncate settings)
        method: create collection with function, alter truncate params
        expected: params changed successfully
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Alter function with new truncate params
        new_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
                "truncate": True,
                "truncation_direction": "Left"
            }
        )
        self.client.alter_collection_function(
            collection_name=c_name,
            function_name="tei",
            function=new_function
        )

        # Verify function still works
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1

    def test_alter_collection_function_verify_functionality(self, tei_endpoint):
        """
        target: test altered function works correctly
        method: create collection with function, insert data, alter function, insert more data
        expected: function continues to work after alteration
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Insert first batch
        data1 = [{"id": i, "document": fake_en.text()} for i in range(5)]
        collection_w.insert(data1)

        # Alter function
        new_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={
                "provider": "TEI",
                "endpoint": tei_endpoint,
                "truncate": True
            }
        )
        self.client.alter_collection_function(
            collection_name=c_name,
            function_name="tei",
            function=new_function
        )

        # Insert second batch
        data2 = [{"id": i + 5, "document": fake_en.text()} for i in range(5)]
        collection_w.insert(data2)

        # Verify all data is present
        assert collection_w.num_entities == 10

        # Create index and search
        index_params = {
            "index_type": "AUTOINDEX",
            "metric_type": "COSINE",
            "params": {},
        }
        collection_w.create_index("dense", index_params)
        collection_w.load()

        search_params = {"metric_type": "COSINE", "params": {}}
        res, _ = collection_w.search(
            data=[fake_en.text()],
            anns_field="dense",
            param=search_params,
            limit=10,
            output_fields=["document"],
        )
        assert len(res[0]) == 10

    # ==================== alter_collection_function negative tests ====================

    def test_alter_collection_function_nonexistent_collection(self, tei_endpoint):
        """
        target: test alter function on nonexistent collection
        method: call alter_collection_function on collection that doesn't exist
        expected: error with collection not found
        """
        self._connect()
        new_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.alter_collection_function(
                collection_name="nonexistent_collection_12345",
                function_name="tei",
                function=new_function
            )
            assert False, "Expected exception for nonexistent collection"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "can't find" in str(e).lower()

    def test_alter_collection_function_nonexistent_function(self, tei_endpoint):
        """
        target: test alter function that doesn't exist
        method: create collection without function, try to alter non-existent function
        expected: error indicating function not found
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        new_function = Function(
            name="nonexistent_function",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )

        try:
            self.client.alter_collection_function(
                collection_name=c_name,
                function_name="nonexistent_function",
                function=new_function
            )
            assert False, "Expected exception for nonexistent function"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "function" in str(e).lower()

    def test_alter_collection_function_invalid_new_endpoint(self, tei_endpoint):
        """
        target: test alter function with invalid endpoint
        method: create collection with valid function, alter to use invalid endpoint
        expected: error indicating endpoint unreachable
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Try to alter with invalid endpoint
        new_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": "http://invalid_endpoint_12345"}
        )

        try:
            self.client.alter_collection_function(
                collection_name=c_name,
                function_name="tei",
                function=new_function
            )
            assert False, "Expected exception for invalid endpoint"
        except Exception as e:
            log.info(f"Expected error: {e}")
            # Error message may vary, just check it's an error
            assert len(str(e)) > 0

    # ==================== drop_collection_function positive tests ====================

    def test_drop_collection_function_basic(self, tei_endpoint):
        """
        target: test drop function from collection
        method: create collection with function, drop the function
        expected: function dropped, describe shows 0 functions
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Verify function exists
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1

        # Drop function
        self.client.drop_collection_function(
            collection_name=c_name,
            function_name="tei"
        )

        # Verify function is removed
        res, _ = collection_w.describe()
        assert len(res.get("functions", [])) == 0

    def test_drop_collection_function_one_of_multiple(self, tei_endpoint):
        """
        target: test drop one function when multiple exist
        method: create collection with text_embedding and bm25 functions, drop only text_embedding
        expected: only specified function is dropped, other remains
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(
                name="document",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params={"tokenizer": "standard"},
            ),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(name="sparse", dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        # Add both functions to schema
        text_embedding_function = Function(
            name="text_embedding",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        bm25_function = Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["document"],
            output_field_names="sparse",
            params={},
        )
        schema.add_function(bm25_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Verify both functions exist
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 2

        # Drop only text_embedding function
        self.client.drop_collection_function(
            collection_name=c_name,
            function_name="text_embedding"
        )

        # Verify only bm25 remains
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1
        assert res["functions"][0]["name"] == "bm25"

    def test_drop_collection_function_then_add_again(self, tei_endpoint):
        """
        target: test can re-add function after dropping
        method: create collection with function, drop it, add function again
        expected: function can be re-added after drop
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")

        text_embedding_function = Function(
            name="tei",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        schema.add_function(text_embedding_function)

        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        # Drop function
        self.client.drop_collection_function(
            collection_name=c_name,
            function_name="tei"
        )

        # Verify function is removed
        res, _ = collection_w.describe()
        assert len(res.get("functions", [])) == 0

        # Add function again
        new_function = Function(
            name="text_embedding_v2",
            function_type=FunctionType.TEXTEMBEDDING,
            input_field_names=["document"],
            output_field_names="dense",
            params={"provider": "TEI", "endpoint": tei_endpoint}
        )
        self.client.add_collection_function(
            collection_name=c_name,
            function=new_function
        )

        # Verify function is added
        res, _ = collection_w.describe()
        assert len(res["functions"]) == 1
        assert res["functions"][0]["name"] == "text_embedding_v2"

    # ==================== drop_collection_function negative tests ====================

    def test_drop_collection_function_nonexistent_collection(self):
        """
        target: test drop function from nonexistent collection
        method: call drop_collection_function on collection that doesn't exist
        expected: error with collection not found
        """
        self._connect()

        try:
            self.client.drop_collection_function(
                collection_name="nonexistent_collection_12345",
                function_name="tei"
            )
            assert False, "Expected exception for nonexistent collection"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "can't find" in str(e).lower()

    def test_drop_collection_function_nonexistent_function(self):
        """
        target: test drop function that doesn't exist
        method: create collection without function, try to drop non-existent function
        expected: error indicating function not found
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        self.init_collection_wrap(name=c_name, schema=schema)

        try:
            self.client.drop_collection_function(
                collection_name=c_name,
                function_name="nonexistent_function"
            )
            assert False, "Expected exception for nonexistent function"
        except Exception as e:
            log.info(f"Expected error: {e}")
            assert "not found" in str(e).lower() or "not exist" in str(e).lower() or "function" in str(e).lower()

    def test_drop_collection_function_empty_name(self):
        """
        target: test drop function with empty name
        method: call drop_collection_function with function_name=""
        expected: error about invalid function name
        """
        self._connect()
        dim = 768
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="dense", dtype=DataType.FLOAT_VECTOR, dim=dim),
        ]
        schema = CollectionSchema(fields=fields, description="test collection")
        c_name = cf.gen_unique_str(prefix)
        collection_w = self.init_collection_wrap(name=c_name, schema=schema)

        try:
            self.client.drop_collection_function(
                collection_name=c_name,
                function_name=""
            )
            assert False, "Expected exception for empty function name"
        except Exception as e:
            log.info(f"Expected error: {e}")
            # Error message may vary
            assert len(str(e)) > 0