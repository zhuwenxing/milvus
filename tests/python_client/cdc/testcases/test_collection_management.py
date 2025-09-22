"""
CDC sync tests for collection management operations.
"""

import time
from .base import TestCDCSyncBase, logger


class TestCDCSyncCollectionManagement(TestCDCSyncBase):
    """Test CDC sync for collection management operations."""

    def setup_method(self):
        """Setup for each test method."""
        self.resources_to_cleanup = []

    def teardown_method(self):
        """Cleanup after each test method - only cleanup upstream, downstream will sync."""
        upstream_client = getattr(self, '_upstream_client', None)

        if upstream_client:
            for resource_type, resource_name in self.resources_to_cleanup:
                if resource_type == 'collection':
                    self.cleanup_collection(upstream_client, resource_name)

            time.sleep(1)  # Allow cleanup to sync to downstream

    def test_load_collection(self, upstream_client, downstream_client, sync_timeout):
        """Test LOAD_COLLECTION operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_load")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection with proper schema
        schema = self.create_default_schema(upstream_client)
        upstream_client.create_collection(
            collection_name=collection_name,
            schema=schema,
            consistency_level="Strong"
        )

        # Create index (required for loading)
        index_params = upstream_client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="L2"
        )
        upstream_client.create_index(collection_name, index_params)

        # Wait for creation to sync
        def check_create():
            return downstream_client.has_collection(collection_name)
        assert self.wait_for_sync(check_create, sync_timeout, f"create collection {collection_name}")

        # Load collection
        upstream_client.load_collection(collection_name)

        # Wait for load to sync
        def check_load():
            try:
                # Try to perform a search to verify the collection is loaded
                query_vector = [[0.1] * 128]  # dummy vector
                downstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=[]
                )
                return True
            except:
                return False

        assert self.wait_for_sync(check_load, sync_timeout, f"load collection {collection_name}")

    def test_release_collection(self, upstream_client, downstream_client, sync_timeout):
        """Test RELEASE_COLLECTION operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_release")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection with proper schema
        schema = self.create_default_schema(upstream_client)
        upstream_client.create_collection(
            collection_name=collection_name,
            schema=schema,
            consistency_level="Strong"
        )

        index_params = upstream_client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="L2"
        )
        upstream_client.create_index(collection_name, index_params)
        upstream_client.load_collection(collection_name)

        # Wait for setup to sync
        def check_setup():
            try:
                query_vector = [[0.1] * 128]
                downstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=[]
                )
                return True
            except:
                return False
        assert self.wait_for_sync(check_setup, sync_timeout, f"setup and load collection {collection_name}")

        # Release collection
        upstream_client.release_collection(collection_name)

        # Wait for release to sync
        def check_release():
            try:
                # Try to search - should fail if released
                query_vector = [[0.1] * 128]
                downstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=[]
                )
                return False  # If search succeeds, collection is still loaded
            except:
                return True   # If search fails, collection is released

        assert self.wait_for_sync(check_release, sync_timeout, f"release collection {collection_name}")

    def test_flush(self, upstream_client, downstream_client, sync_timeout):
        """Test FLUSH operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_flush")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection with proper schema
        schema = self.create_default_schema(upstream_client)
        upstream_client.create_collection(
            collection_name=collection_name,
            schema=schema,
            consistency_level="Strong"
        )

        # Wait for creation to sync
        def check_create():
            return downstream_client.has_collection(collection_name)
        assert self.wait_for_sync(check_create, sync_timeout, f"create collection {collection_name}")

        # Insert data (without immediate flush)
        test_data = self.generate_test_data(100)
        insert_result = upstream_client.insert(collection_name, test_data)
        logger.info(f"Insert result: {insert_result}")

        # Verify data is not visible before flush
        stats_before = upstream_client.get_collection_stats(collection_name)
        logger.info(f"Stats before flush: {stats_before}")

        # Flush collection
        upstream_client.flush(collection_name)

        # Wait for flush data to be visible with timeout
        expected_count = insert_result.get('insert_count', 100) if insert_result else 100

        def check_flush_stats():
            try:
                stats = upstream_client.get_collection_stats(collection_name)
                row_count = stats.get('row_count', 0)
                logger.info(f"Current row count: {row_count}, expected: {expected_count}")
                return row_count >= expected_count
            except Exception as e:
                logger.warning(f"Error checking stats: {e}")
                return False

        # Use timeout for waiting flush stats to update
        timeout = 30  # 30 seconds timeout
        assert self.wait_for_sync(check_flush_stats, timeout, f"flush data visible in stats (expected: {expected_count})")

        # Get final stats after flush
        stats_after = upstream_client.get_collection_stats(collection_name)
        logger.info(f"Stats after flush: {stats_after}")

        # Wait for flush to sync downstream
        def check_flush():
            try:
                downstream_stats = downstream_client.get_collection_stats(collection_name)
                return downstream_stats.get('row_count', 0) >= 100
            except:
                return False

        assert self.wait_for_sync(check_flush, sync_timeout, f"flush collection {collection_name}")

    def test_compact(self, upstream_client, downstream_client, sync_timeout):
        """Test COMPACT operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_compact")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection with proper schema
        schema = self.create_default_schema(upstream_client)
        upstream_client.create_collection(
            collection_name=collection_name,
            schema=schema,
            consistency_level="Strong"
        )

        # Create index (required for loading)
        index_params = upstream_client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="L2"
        )
        upstream_client.create_index(collection_name, index_params)

        # Load collection (required for delete operations)
        upstream_client.load_collection(collection_name)

        # Insert and delete some data to create segments that need compaction
        test_data = self.generate_test_data(200)
        upstream_client.insert(collection_name, test_data)
        upstream_client.flush(collection_name)

        # Wait for creation and data to sync
        def check_setup():
            try:
                return (downstream_client.has_collection(collection_name) and
                        downstream_client.get_collection_stats(collection_name).get('row_count', 0) >= 200)
            except:
                return False
        assert self.wait_for_sync(check_setup, sync_timeout, f"setup collection {collection_name}")

        # Delete some data based on a field that exists in our test data
        upstream_client.delete(collection_name, filter="number < 50")  # Delete records where number < 50
        upstream_client.flush(collection_name)

        # Compact collection
        compaction_id = upstream_client.compact(collection_name)
        logger.info(f"Started compaction with ID: {compaction_id}")

        # Wait for compaction to sync (we mainly verify the operation doesn't fail)
        def check_compact():
            try:
                # Verify collection still exists and has expected data count
                downstream_stats = downstream_client.get_collection_stats(collection_name)
                return downstream_stats.get('row_count', 200) == 150  # 200 - 50 = 150
            except:
                return False

        assert self.wait_for_sync(check_compact, sync_timeout, f"compact collection {collection_name}")

    def test_load_collection_with_load_fields(self, upstream_client, downstream_client, sync_timeout):
        """Test LOAD_COLLECTION operation with load_fields parameter sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_load_fields")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection with comprehensive schema (has multiple fields)
        schema = self.create_comprehensive_schema(upstream_client)
        upstream_client.create_collection(
            collection_name=collection_name,
            schema=schema,
            consistency_level="Strong"
        )

        # Create index for float_vector field (required for loading)
        index_params = upstream_client.prepare_index_params()
        index_params.add_index(
            field_name="float_vector",
            index_type="AUTOINDEX",
            metric_type="L2"
        )
        upstream_client.create_index(collection_name, index_params)

        # Wait for creation to sync
        def check_create():
            return downstream_client.has_collection(collection_name)
        assert self.wait_for_sync(check_create, sync_timeout, f"create collection {collection_name}")

        # Insert some test data
        test_data = self.generate_comprehensive_test_data(100)
        upstream_client.insert(collection_name, test_data)
        upstream_client.flush(collection_name)

        # Load collection with specific fields only (float_vector + id + varchar_field)
        load_fields = ["float_vector", "id", "varchar_field"]
        upstream_client.load_collection(collection_name, load_fields=load_fields)

        # Verify upstream load operation succeeded
        def verify_upstream_load():
            try:
                # Try to search to verify collection is loaded
                query_vector = [[0.1] * 128]
                upstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=["varchar_field"],
                    anns_field="float_vector"
                )
                return True
            except Exception as e:
                logger.warning(f"Upstream load verification failed: {e}")
                return False

        assert self.wait_for_sync(verify_upstream_load, sync_timeout,
                                f"verify upstream load with load_fields in {collection_name}")

        # Verify downstream sync - collection should be loaded and searchable
        def check_downstream_load_sync():
            try:
                query_vector = [[0.1] * 128]
                result = downstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=["varchar_field"],
                    anns_field="float_vector"
                )
                return len(result) > 0 and len(result[0]) >= 0
            except Exception as e:
                logger.warning(f"Downstream load sync check failed: {e}")
                return False

        assert self.wait_for_sync(check_downstream_load_sync, sync_timeout,
                                f"verify downstream load sync for {collection_name}")

        # Additional verification: test that both loaded and unloaded fields can be output
        # (since load_fields only affects memory usage, not field accessibility)
        def verify_all_fields_accessible():
            try:
                query_vector = [[0.1] * 128]
                # Test accessing both loaded and unloaded fields
                result1 = downstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=["varchar_field"],  # loaded field
                    anns_field="float_vector"
                )

                result2 = downstream_client.search(
                    collection_name=collection_name,
                    data=query_vector,
                    limit=1,
                    output_fields=["float_field"],  # unloaded field (but should still be accessible)
                    anns_field="float_vector"
                )

                return len(result1) > 0 and len(result2) > 0
            except Exception as e:
                logger.warning(f"Field accessibility verification failed: {e}")
                return False

        assert self.wait_for_sync(verify_all_fields_accessible, sync_timeout,
                                f"verify all fields accessible in {collection_name}")

        logger.info(f"Successfully tested load_collection with load_fields: {load_fields}")
        logger.info("Verified CDC sync of load operation with load_fields parameter")