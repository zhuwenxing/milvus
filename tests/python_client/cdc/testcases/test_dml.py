"""
CDC sync tests for data manipulation operations.
"""

import time
from base import TestCDCSyncBase, logger


class TestCDCSyncDML(TestCDCSyncBase):
    """Test CDC sync for data manipulation operations."""

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

    def test_insert(self, upstream_client, downstream_client, sync_timeout):
        """Test INSERT operation sync."""
        start_time = time.time()
        collection_name = self.gen_unique_name("test_col_insert")

        # Log test start
        self.log_test_start("test_insert", "INSERT", collection_name)

        # Store upstream client for teardown
        self._upstream_client = upstream_client
        self.resources_to_cleanup.append(('collection', collection_name))

        try:
            # Initial cleanup
            self.cleanup_collection(upstream_client, collection_name)

            # Create collection
            self.log_operation("CREATE_COLLECTION", "collection", collection_name, "upstream")
            upstream_client.create_collection(
                collection_name=collection_name,
                **self.create_default_schema()
            )

            # Wait for creation to sync
            def check_create():
                return downstream_client.has_collection(collection_name)
            assert self.wait_for_sync(check_create, sync_timeout, f"create collection {collection_name}")

            # Generate and insert data
            test_data = self.generate_test_data(100)
            logger.info(f"[GENERATED] Generated test data: {len(test_data)} records")

            self.log_data_operation("INSERT", collection_name, len(test_data), "- starting data insertion")

            result = upstream_client.insert(collection_name, test_data)
            inserted_count = result.get('insert_count', len(test_data))

            self.log_data_operation("INSERT", collection_name, inserted_count, "- insertion completed upstream")

            # Flush to ensure data is persisted
            logger.info(f"[FLUSH] Flushing collection {collection_name} in upstream")
            upstream_client.flush(collection_name)

            # Log sync verification start
            self.log_sync_verification("INSERT", collection_name, f"{inserted_count} records in downstream")

            # Wait for data sync by querying actual data
            def check_data():
                try:
                    # Query data to verify insertion
                    downstream_client.flush(collection_name)  # Ensure visibility
                    result = downstream_client.query(
                        collection_name=collection_name,
                        filter="",  # Get all records
                        output_fields=["count(*)"]
                    )
                    count = result[0]["count(*)"] if result else 0

                    if count >= inserted_count:
                        logger.info(f"[SYNC_OK] Data sync confirmed: {count} records found in downstream")
                    else:
                        logger.info(f"[SYNC_PROGRESS] Data sync in progress: {count}/{inserted_count} records in downstream")

                    return count >= inserted_count
                except Exception as e:
                    logger.warning(f"Data sync check failed: {e}")
                    return False

            sync_success = self.wait_for_sync(check_data, sync_timeout, f"insert data to {collection_name}")
            assert sync_success, f"Data insertion failed to sync to downstream for {collection_name}"

            # Log test success
            duration = time.time() - start_time
            self.log_test_end("test_insert", True, duration)

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[ERROR] Test failed with error: {e}")
            self.log_test_end("test_insert", False, duration)
            raise

    def test_delete(self, upstream_client, downstream_client, sync_timeout):
        """Test DELETE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_delete")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection and insert data
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )

        test_data = self.generate_test_data(100)
        upstream_client.insert(collection_name, test_data)
        upstream_client.flush(collection_name)

        # Wait for initial data sync by querying
        def check_data():
            try:
                downstream_client.flush(collection_name)
                result = downstream_client.query(
                    collection_name=collection_name,
                    filter="",
                    output_fields=["count(*)"]
                )
                count = result[0]["count(*)"] if result else 0
                return count >= 100
            except:
                return False
        assert self.wait_for_sync(check_data, sync_timeout, f"initial data sync {collection_name}")

        # Delete some data
        delete_ids = list(range(10))  # Delete first 10 records
        upstream_client.delete(collection_name, filter=f"id in {delete_ids}")
        upstream_client.flush(collection_name)

        # Wait for delete to sync by querying remaining data
        def check_delete():
            try:
                downstream_client.flush(collection_name)
                # Query for the deleted records - should return empty
                deleted_result = downstream_client.query(
                    collection_name=collection_name,
                    filter=f"id in {delete_ids}",
                    output_fields=["id"]
                )
                # Query total count
                count_result = downstream_client.query(
                    collection_name=collection_name,
                    filter="",
                    output_fields=["count(*)"]
                )
                deleted_count = len(deleted_result) if deleted_result else 0
                total_count = count_result[0]["count(*)"] if count_result else 0

                # Verify deleted records are gone and total count is correct
                return deleted_count == 0 and total_count == 90
            except:
                return False

        assert self.wait_for_sync(check_delete, sync_timeout, f"delete data from {collection_name}")

    def test_upsert(self, upstream_client, downstream_client, sync_timeout):
        """Test UPSERT operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_upsert")
        self.resources_to_cleanup.append(('collection', collection_name))

        # Initial cleanup
        self.cleanup_collection(upstream_client, collection_name)

        # Create collection and insert initial data
        upstream_client.create_collection(
            collection_name=collection_name,
            **self.create_default_schema()
        )

        initial_data = self.generate_test_data(50)
        upstream_client.insert(collection_name, initial_data)
        upstream_client.flush(collection_name)

        # Wait for initial data sync
        def check_initial():
            try:
                downstream_client.flush(collection_name)
                result = downstream_client.query(
                    collection_name=collection_name,
                    filter="",
                    output_fields=["count(*)"]
                )
                count = result[0]["count(*)"] if result else 0
                return count >= 50
            except:
                return False
        assert self.wait_for_sync(check_initial, sync_timeout, f"initial data sync {collection_name}")

        # Upsert data (update existing + insert new)
        upsert_data = self.generate_test_data(75)  # 50 updates + 25 new
        # Modify some existing data for verification
        for i in range(25):
            upsert_data[i]["text"] = f"updated_text_{i}"
            upsert_data[i]["number"] = i + 1000  # Update with different value

        upstream_client.upsert(collection_name, upsert_data)
        upstream_client.flush(collection_name)

        # Wait for upsert to sync by verifying updated data
        def check_upsert():
            try:
                downstream_client.flush(collection_name)
                # Check total count (should be 75: 50 original + 25 new)
                count_result = downstream_client.query(
                    collection_name=collection_name,
                    filter="",
                    output_fields=["count(*)"]
                )
                total_count = count_result[0]["count(*)"] if count_result else 0

                # Check if updated records exist with new values
                updated_result = downstream_client.query(
                    collection_name=collection_name,
                    filter="number >= 1000 and number < 1025",  # Updated numbers
                    output_fields=["id", "number", "text"]
                )
                updated_count = len(updated_result) if updated_result else 0

                # Verify both total count and updated records
                return total_count >= 75 and updated_count >= 25
            except:
                return False

        assert self.wait_for_sync(check_upsert, sync_timeout, f"upsert data to {collection_name}")

    def test_bulk_insert(self, upstream_client, downstream_client, sync_timeout):
        """Test BULK_INSERT operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        collection_name = self.gen_unique_name("test_col_bulk_insert")
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

        # Bulk insert data
        bulk_data = self.generate_test_data(1000)

        # Use regular insert for bulk insert simulation
        batch_size = 100
        total_inserted = 0
        for i in range(0, len(bulk_data), batch_size):
            batch = bulk_data[i:i + batch_size]
            result = upstream_client.insert(collection_name, batch)
            total_inserted += result.get('insert_count', len(batch))

        upstream_client.flush(collection_name)

        # Wait for bulk data sync by querying
        def check_bulk():
            try:
                downstream_client.flush(collection_name)
                result = downstream_client.query(
                    collection_name=collection_name,
                    filter="",
                    output_fields=["count(*)"]
                )
                count = result[0]["count(*)"] if result else 0
                return count >= total_inserted
            except:
                return False

        assert self.wait_for_sync(check_bulk, sync_timeout, f"bulk insert data to {collection_name}")