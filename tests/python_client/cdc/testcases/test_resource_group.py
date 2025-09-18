"""
CDC sync tests for resource group operations.
"""

import time
from base import TestCDCSyncBase, logger


class TestCDCSyncResourceGroup(TestCDCSyncBase):
    """Test CDC sync for resource group operations."""

    def setup_method(self):
        """Setup for each test method."""
        self.resources_to_cleanup = []

    def teardown_method(self):
        """Cleanup after each test method - only cleanup upstream, downstream will sync."""
        upstream_client = getattr(self, '_upstream_client', None)

        if upstream_client:
            for resource_type, resource_name in self.resources_to_cleanup:
                if resource_type == 'resource_group':
                    try:
                        if resource_name in upstream_client.list_resource_groups():
                            upstream_client.drop_resource_group(resource_name)
                    except:
                        pass
                elif resource_type == 'collection':
                    self.cleanup_collection(upstream_client, resource_name)

            time.sleep(1)  # Allow cleanup to sync to downstream

    def test_create_resource_group(self, upstream_client, downstream_client, sync_timeout):
        """Test CREATE_RESOURCE_GROUP operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        rg_name = self.gen_unique_name("test_rg_create")
        self.resources_to_cleanup.append(('resource_group', rg_name))

        # Create resource group in upstream
        upstream_client.create_resource_group(rg_name)
        assert rg_name in upstream_client.list_resource_groups()

        # Wait for sync to downstream
        def check_sync():
            return rg_name in downstream_client.list_resource_groups()

        assert self.wait_for_sync(check_sync, sync_timeout, f"create resource group {rg_name}")

    def test_drop_resource_group(self, upstream_client, downstream_client, sync_timeout):
        """Test DROP_RESOURCE_GROUP operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        rg_name = self.gen_unique_name("test_rg_drop")
        self.resources_to_cleanup.append(('resource_group', rg_name))

        # Create resource group first
        upstream_client.create_resource_group(rg_name)

        # Wait for creation to sync
        def check_create():
            return rg_name in downstream_client.list_resource_groups()
        assert self.wait_for_sync(check_create, sync_timeout, f"create resource group {rg_name}")

        # Drop resource group in upstream
        upstream_client.drop_resource_group(rg_name)
        assert rg_name not in upstream_client.list_resource_groups()

        # Wait for drop to sync
        def check_drop():
            return rg_name not in downstream_client.list_resource_groups()

        assert self.wait_for_sync(check_drop, sync_timeout, f"drop resource group {rg_name}")

    def test_transfer_node(self, upstream_client, downstream_client, sync_timeout):
        """Test TRANSFER_NODE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        source_rg = "default"  # Use default resource group
        target_rg = self.gen_unique_name("test_rg_target")
        self.resources_to_cleanup.append(('resource_group', target_rg))

        # Create target resource group
        upstream_client.create_resource_group(target_rg)

        # Wait for target RG to sync
        def check_rg():
            return target_rg in downstream_client.list_resource_groups()
        assert self.wait_for_sync(check_rg, sync_timeout, f"create target resource group {target_rg}")

        # Transfer node
        upstream_client.transfer_node(source_rg, target_rg, 1)
        logger.info(f"Node transfer from {source_rg} to {target_rg} initiated")

        # For node transfer, we mainly verify the operation doesn't fail
        # The actual verification would require checking node distribution
        time.sleep(5)  # Allow operation to propagate

    def test_transfer_replica(self, upstream_client, downstream_client, sync_timeout):
        """Test TRANSFER_REPLICA operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_replica")
        source_rg = "default"
        target_rg = self.gen_unique_name("test_rg_replica")
        self.resources_to_cleanup.append(('resource_group', target_rg))
        self.resources_to_cleanup.append(('collection', collection_name))

        # Create target resource group and collection
        upstream_client.create_resource_group(target_rg)
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )

        # Wait for sync
        def check_sync():
            return (target_rg in downstream_client.list_resource_groups() and
                    downstream_client.has_collection(collection_name))
        assert self.wait_for_sync(check_sync, sync_timeout, f"setup for replica transfer")

        # Transfer replica
        upstream_client.transfer_replica(source_rg, target_rg, collection_name, 1)
        logger.info(f"Replica transfer for {collection_name} initiated")

        # Verify operation doesn't fail
        time.sleep(5)  # Allow operation to propagate