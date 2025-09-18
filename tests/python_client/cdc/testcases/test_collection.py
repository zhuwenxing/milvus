"""
CDC sync tests for collection DDL operations.
"""

import time
from base import TestCDCSyncBase, logger


class TestCDCSyncCollection(TestCDCSyncBase):
    """Test CDC sync for collection DDL operations."""

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

    def test_create_collection(self, upstream_client, downstream_client, sync_timeout):
        """Test CREATE_COLLECTION operation sync."""
        start_time = time.time()
        collection_name = self.gen_unique_name("test_col_create")

        # Log test start
        self.log_test_start("test_create_collection", "CREATE_COLLECTION", collection_name)

        # Store upstream client for teardown
        self._upstream_client = upstream_client
        self.resources_to_cleanup.append(('collection', collection_name))

        try:
            # Initial cleanup
            self.cleanup_collection(upstream_client, collection_name)

            # Log operation
            self.log_operation("CREATE_COLLECTION", "collection", collection_name, "upstream")

            # Create collection in upstream
            schema_params = self.create_default_schema()
            logger.info(f"[SCHEMA] Collection schema: {schema_params}")

            upstream_client.create_collection(
                collection_name=collection_name,
                **schema_params
            )

            # Verify upstream creation
            upstream_exists = upstream_client.has_collection(collection_name)
            self.log_resource_state("collection", collection_name, "exists" if upstream_exists else "missing", "upstream")
            assert upstream_exists, f"Collection {collection_name} not created in upstream"

            # Log sync verification start
            self.log_sync_verification("CREATE_COLLECTION", collection_name, "exists in downstream")

            # Wait for sync to downstream
            def check_sync():
                exists = downstream_client.has_collection(collection_name)
                if exists:
                    self.log_resource_state("collection", collection_name, "exists", "downstream", "Sync confirmed")
                return exists

            sync_success = self.wait_for_sync(check_sync, sync_timeout, f"create collection {collection_name}")
            assert sync_success, f"Collection {collection_name} failed to sync to downstream"

            # Log test success
            duration = time.time() - start_time
            self.log_test_end("test_create_collection", True, duration)

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[ERROR] Test failed with error: {e}")
            self.log_test_end("test_create_collection", False, duration)
            raise

    def test_drop_collection(self, upstream_client, downstream_client, sync_timeout):
        """Test DROP_COLLECTION operation sync."""
        start_time = time.time()
        collection_name = self.gen_unique_name("test_col_drop")

        # Log test start
        self.log_test_start("test_drop_collection", "DROP_COLLECTION", collection_name)

        # Store upstream client for teardown
        self._upstream_client = upstream_client
        self.resources_to_cleanup.append(('collection', collection_name))

        try:
            # Initial cleanup
            self.cleanup_collection(upstream_client, collection_name)

            # Create collection first
            self.log_operation("CREATE_COLLECTION", "collection", collection_name, "upstream")
            upstream_client.create_collection(
                collection_name=collection_name,
                **self.create_default_schema()
            )

            # Wait for creation to sync
            def check_create():
                return downstream_client.has_collection(collection_name)
            assert self.wait_for_sync(check_create, sync_timeout, f"create collection {collection_name}")

            # Drop collection in upstream
            self.log_operation("DROP_COLLECTION", "collection", collection_name, "upstream")
            upstream_client.drop_collection(collection_name)

            # Verify upstream drop
            upstream_exists = upstream_client.has_collection(collection_name)
            self.log_resource_state("collection", collection_name, "missing" if not upstream_exists else "exists", "upstream")
            assert not upstream_exists, f"Collection {collection_name} still exists in upstream after drop"

            # Log sync verification start
            self.log_sync_verification("DROP_COLLECTION", collection_name, "missing from downstream")

            # Wait for drop to sync
            def check_drop():
                exists = downstream_client.has_collection(collection_name)
                if not exists:
                    self.log_resource_state("collection", collection_name, "missing", "downstream", "Drop synced")
                return not exists

            sync_success = self.wait_for_sync(check_drop, sync_timeout, f"drop collection {collection_name}")
            assert sync_success, f"Collection {collection_name} drop failed to sync to downstream"

            # Log test success
            duration = time.time() - start_time
            self.log_test_end("test_drop_collection", True, duration)

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[ERROR] Test failed with error: {e}")
            self.log_test_end("test_drop_collection", False, duration)
            raise

    def test_rename_collection(self, upstream_client, downstream_client, sync_timeout):
        """Test RENAME_COLLECTION operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        old_name = self.gen_unique_name("test_col_rename_old")
        new_name = self.gen_unique_name("test_col_rename_new")
        self.resources_to_cleanup.append(('collection', old_name))
        self.resources_to_cleanup.append(('collection', new_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, old_name)
        self.cleanup_collection(upstream_client, new_name)

        # Create collection
        upstream_client.create_collection(
            collection_name=old_name,
            **self.create_default_schema()
        )

        # Wait for creation to sync
        def check_create():
            return downstream_client.has_collection(old_name)
        assert self.wait_for_sync(check_create, sync_timeout, f"create collection {old_name}")

        # Rename collection
        upstream_client.rename_collection(old_name, new_name)
        assert not upstream_client.has_collection(old_name)
        assert upstream_client.has_collection(new_name)

        # Wait for rename to sync
        def check_rename():
            return (not downstream_client.has_collection(old_name) and
                    downstream_client.has_collection(new_name))

        assert self.wait_for_sync(check_rename, sync_timeout, f"rename collection {old_name} to {new_name}")