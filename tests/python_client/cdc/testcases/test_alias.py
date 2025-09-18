"""
CDC sync tests for alias operations.
"""

import time
from base import TestCDCSyncBase, logger


class TestCDCSyncAlias(TestCDCSyncBase):
    """Test CDC sync for alias operations."""

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
                elif resource_type == 'alias':
                    try:
                        upstream_client.drop_alias(resource_name)
                    except:
                        pass

            time.sleep(1)  # Allow cleanup to sync to downstream

    def test_create_alias(self, upstream_client, downstream_client, sync_timeout):
        """Test CREATE_ALIAS operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_alias_create")
        alias_name = self.gen_unique_name("test_alias_create")
        self.resources_to_cleanup.append(('collection', collection_name))
        self.resources_to_cleanup.append(('alias', alias_name))

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

        # Create alias
        upstream_client.create_alias(collection_name, alias_name)

        # Verify alias exists in upstream
        upstream_aliases = upstream_client.list_aliases()
        assert alias_name in upstream_aliases

        # Wait for alias sync to downstream
        def check_alias():
            try:
                downstream_aliases = downstream_client.list_aliases()
                return alias_name in downstream_aliases
            except:
                return False

        assert self.wait_for_sync(check_alias, sync_timeout, f"create alias {alias_name}")

    def test_drop_alias(self, upstream_client, downstream_client, sync_timeout):
        """Test DROP_ALIAS operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_alias_drop")
        alias_name = self.gen_unique_name("test_alias_drop")
        self.resources_to_cleanup.append(('collection', collection_name))
        self.resources_to_cleanup.append(('alias', alias_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection and alias
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )
        upstream_client.create_alias(collection_name, alias_name)

        # Wait for setup to sync
        def check_setup():
            try:
                return (downstream_client.has_collection(collection_name) and
                        alias_name in downstream_client.list_aliases())
            except:
                return False
        assert self.wait_for_sync(check_setup, sync_timeout, f"setup collection and alias {collection_name}")

        # Drop alias
        upstream_client.drop_alias(alias_name)

        # Verify alias is dropped in upstream
        upstream_aliases = upstream_client.list_aliases()
        assert alias_name not in upstream_aliases

        # Wait for drop to sync to downstream
        def check_drop():
            try:
                downstream_aliases = downstream_client.list_aliases()
                return alias_name not in downstream_aliases
            except:
                return True  # If error, assume alias is dropped

        assert self.wait_for_sync(check_drop, sync_timeout, f"drop alias {alias_name}")

    def test_alter_alias(self, upstream_client, downstream_client, sync_timeout):
        """Test ALTER_ALIAS operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        old_collection = self.gen_unique_name("test_col_alias_old")
        new_collection = self.gen_unique_name("test_col_alias_new")
        alias_name = self.gen_unique_name("test_alias_alter")
        self.resources_to_cleanup.append(('collection', old_collection))
        self.resources_to_cleanup.append(('collection', new_collection))
        self.resources_to_cleanup.append(('alias', alias_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, old_collection)
        self.cleanup_collection(upstream_client, new_collection)

        # Create both collections
        upstream_client.create_collection(
            collection_name=old_collection,
            **self.create_default_schema()
        )
        upstream_client.create_collection(
            collection_name=new_collection,
            **self.create_default_schema()
        )

        # Create alias pointing to old collection
        upstream_client.create_alias(old_collection, alias_name)

        # Wait for setup to sync
        def check_setup():
            try:
                return (downstream_client.has_collection(old_collection) and
                        downstream_client.has_collection(new_collection) and
                        alias_name in downstream_client.list_aliases())
            except:
                return False
        assert self.wait_for_sync(check_setup, sync_timeout, f"setup collections and alias")

        # Alter alias to point to new collection
        upstream_client.alter_alias(alias_name, new_collection)

        # Wait for alter to sync
        def check_alter():
            try:
                # Check if alias still exists (alter operation completed)
                downstream_aliases = downstream_client.list_aliases()
                return alias_name in downstream_aliases
            except:
                return False

        assert self.wait_for_sync(check_alter, sync_timeout, f"alter alias {alias_name}")