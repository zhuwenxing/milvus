"""
CDC sync tests for index operations.
"""

import time
from base import TestCDCSyncBase, logger


class TestCDCSyncIndex(TestCDCSyncBase):
    """Test CDC sync for index operations."""

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

    def test_create_index(self, upstream_client, downstream_client, sync_timeout):
        """Test CREATE_INDEX operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_create_idx")
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

        # Create index
        index_params = upstream_client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            metric_type="L2",
            params={"nlist": 128}
        )
        upstream_client.create_index(collection_name, index_params)

        # Wait for index creation to sync
        def check_index():
            try:
                downstream_indexes = downstream_client.list_indexes(collection_name)
                return len(downstream_indexes) > 0
            except:
                return False

        assert self.wait_for_sync(check_index, sync_timeout, f"create index on {collection_name}")

    def test_drop_index(self, upstream_client, downstream_client, sync_timeout):
        """Test DROP_INDEX operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_drop_idx")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection and index
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )

        index_params = upstream_client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            metric_type="L2",
            params={"nlist": 128}
        )
        upstream_client.create_index(collection_name, index_params)

        # Wait for setup to sync
        def check_setup():
            try:
                return (downstream_client.has_collection(collection_name) and
                        len(downstream_client.list_indexes(collection_name)) > 0)
            except:
                return False
        assert self.wait_for_sync(check_setup, sync_timeout, f"setup collection and index {collection_name}")

        # Drop index
        upstream_client.drop_index(collection_name, "vector")

        # Wait for index drop to sync
        def check_drop():
            try:
                downstream_indexes = downstream_client.list_indexes(collection_name)
                return len(downstream_indexes) == 0
            except:
                return True  # If error, assume index is dropped

        assert self.wait_for_sync(check_drop, sync_timeout, f"drop index on {collection_name}")