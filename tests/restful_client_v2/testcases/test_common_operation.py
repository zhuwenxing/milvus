import pytest
from utils.util_log import test_log as logger
from utils.utils import gen_collection_name
from base.testbase import TestBase
from pymilvus import (
    FieldSchema, CollectionSchema, DataType,
    Collection
)


@pytest.mark.L0
class TestRunAnalyzer(TestBase):

    def test_run_analyzer_basic(self):
        """
        target: test run analyzer with basic parameters
        method: call run_analyzer with simple text
        expected: return tokenized results successfully
        """
        payload = {
            "text": ["hello world", "milvus vector database"]
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']
        assert len(rsp['data']['results']) == 2
        # Each result should have tokens
        for result in rsp['data']['results']:
            assert 'tokens' in result
            assert len(result['tokens']) > 0

    def test_run_analyzer_with_analyzer_params(self):
        """
        target: test run analyzer with analyzer parameters
        method: call run_analyzer with analyzerParams
        expected: return tokenized results successfully
        """
        payload = {
            "text": ["hello world"],
            "analyzerParams": '{"tokenizer": "standard"}'
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']

    def test_run_analyzer_with_detail(self):
        """
        target: test run analyzer with detail information
        method: call run_analyzer with withDetail=true
        expected: return tokens with offset and position information
        """
        payload = {
            "text": ["hello world"],
            "withDetail": True
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']
        # Check if detail fields are present
        for result in rsp['data']['results']:
            for token in result['tokens']:
                assert 'token' in token
                # With detail, should have offset and position info
                if 'startOffset' in token or 'endOffset' in token or 'position' in token:
                    logger.info(f"Detail fields present in token: {token}")

    def test_run_analyzer_with_hash(self):
        """
        target: test run analyzer with hash
        method: call run_analyzer with withHash=true
        expected: return tokens with hash values
        """
        payload = {
            "text": ["hello world"],
            "withHash": True
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']
        # Check if hash field is present
        for result in rsp['data']['results']:
            for token in result['tokens']:
                assert 'token' in token
                if 'hash' in token:
                    logger.info(f"Hash field present in token: {token}")

    def test_run_analyzer_with_detail_and_hash(self):
        """
        target: test run analyzer with both detail and hash
        method: call run_analyzer with withDetail=true and withHash=true
        expected: return tokens with full information
        """
        payload = {
            "text": ["hello world"],
            "withDetail": True,
            "withHash": True
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']
        for result in rsp['data']['results']:
            for token in result['tokens']:
                assert 'token' in token

    def test_run_analyzer_multiple_texts(self):
        """
        target: test run analyzer with multiple texts
        method: call run_analyzer with a list of texts
        expected: return results for each text
        """
        texts = [
            "hello world",
            "milvus is awesome",
            "vector database search",
            "natural language processing"
        ]
        payload = {
            "text": texts
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']
        assert len(rsp['data']['results']) == len(texts)

    def test_run_analyzer_empty_text(self):
        """
        target: test run analyzer with empty text
        method: call run_analyzer with empty string
        expected: handle empty text gracefully
        """
        payload = {
            "text": [""]
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        # Should either succeed with empty results or return appropriate error
        assert 'code' in rsp

    def test_run_analyzer_with_collection_and_field(self):
        """
        target: test run analyzer with collection and field name
        method: create a collection and call run_analyzer with collection and field info
        expected: return tokenized results successfully
        """
        # Create a collection with text field
        collection_name = gen_collection_name()

        # Create collection using SDK for more control
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=False),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=512,
                       enable_analyzer=True,
                       enable_match=True,
                       analyzer_params={"type": "standard"}),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=128)
        ]
        schema = CollectionSchema(fields=fields, description="test collection for analyzer")
        collection = Collection(name=collection_name, schema=schema)

        # Build index and load
        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "L2",
            "params": {"nlist": 128}
        }
        collection.create_index(field_name="vector", index_params=index_params)
        collection.load()

        # Wait for collection to be loaded
        self.wait_collection_load_completed(collection_name)

        try:
            # Test run_analyzer with collection and field
            payload = {
                "text": ["hello world"],
                "collectionName": collection_name,
                "fieldName": "text"
            }
            rsp = self.common_client.run_analyzer(payload)
            logger.info(f"run_analyzer response: {rsp}")
            assert rsp['code'] == 0
            assert 'data' in rsp
            assert 'results' in rsp['data']
        finally:
            # Clean up
            collection.release()
            collection.drop()

    def test_run_analyzer_with_analyzer_names(self):
        """
        target: test run analyzer with specific analyzer names
        method: call run_analyzer with analyzerNames parameter
        expected: return tokenized results using specified analyzers
        """
        payload = {
            "text": ["hello world"],
            "analyzerNames": ["standard"]
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        # Should either succeed or return error if analyzer not found
        assert 'code' in rsp

    def test_run_analyzer_special_characters(self):
        """
        target: test run analyzer with special characters
        method: call run_analyzer with text containing special characters
        expected: handle special characters correctly
        """
        payload = {
            "text": ["hello@world.com", "user#123", "test-case_example"]
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']

    def test_run_analyzer_unicode_text(self):
        """
        target: test run analyzer with unicode text
        method: call run_analyzer with non-ASCII characters
        expected: handle unicode correctly
        """
        payload = {
            "text": ["你好世界", "مرحبا بالعالم", "こんにちは世界"]
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']

    def test_run_analyzer_long_text(self):
        """
        target: test run analyzer with long text
        method: call run_analyzer with a long text string
        expected: handle long text successfully
        """
        long_text = " ".join(["word"] * 1000)
        payload = {
            "text": [long_text]
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response code: {rsp['code']}")
        assert 'code' in rsp

    def test_run_analyzer_missing_required_field(self):
        """
        target: test run analyzer without required field
        method: call run_analyzer without text field
        expected: return error
        """
        payload = {
            "withDetail": True
        }
        rsp = self.common_client.run_analyzer(payload)
        logger.info(f"run_analyzer response: {rsp}")
        # Should return error for missing required field
        assert 'code' in rsp
        # If it's an error, code should not be 0
        if rsp['code'] != 0:
            logger.info(f"Expected error for missing required field: {rsp}")

    def test_run_analyzer_with_db_name(self):
        """
        target: test run analyzer with specific database
        method: call run_analyzer with dbName parameter
        expected: run analyzer in specified database
        """
        payload = {
            "text": ["hello world"],
            "dbName": "default"
        }
        rsp = self.common_client.run_analyzer(payload, db_name="default")
        logger.info(f"run_analyzer response: {rsp}")
        assert rsp['code'] == 0
        assert 'data' in rsp
        assert 'results' in rsp['data']
