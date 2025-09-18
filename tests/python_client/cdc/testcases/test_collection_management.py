"""
CDC sync tests for collection management operations.
"""

import time
from base import TestCDCSyncBase, logger


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

        # Create collection and index
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
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

        # Create collection, index, and load
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
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

        # Create collection
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )

        # Wait for creation to sync
        def check_create():
            return downstream_client.has_collection(collection_name)
        assert self.wait_for_sync(check_create, sync_timeout, f"create collection {collection_name}")

        # Insert data (without immediate flush)
        test_data = self.generate_test_data(100)
        upstream_client.insert(collection_name, test_data)

        # Verify data is not visible before flush
        stats_before = upstream_client.get_collection_stats(collection_name)
        logger.info(f"Stats before flush: {stats_before}")

        # Flush collection
        upstream_client.flush(collection_name)

        # Verify data is visible after flush
        stats_after = upstream_client.get_collection_stats(collection_name)
        logger.info(f"Stats after flush: {stats_after}")
        assert stats_after.get('row_count', 0) >= 100

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

        # Create collection and add data
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )

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

        # Delete some data
        delete_ids = list(range(50))  # Delete first 50 records
        upstream_client.delete(collection_name, filter=f"id in {delete_ids}")
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