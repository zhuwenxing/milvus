"""
Base class for CDC sync tests with common utilities.
"""

import time
import random
import string
import logging
from datetime import datetime
from typing import Any, Dict, List, Callable
from pymilvus import MilvusClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)


class TestCDCSyncBase:
    """Base class for CDC sync tests with common utilities."""

    @staticmethod
    def gen_unique_name(prefix: str = "", length: int = 8, max_length: int = None) -> str:
        """Generate a unique string with prefix and timestamp."""
        chars = string.ascii_letters + string.digits
        random_str = ''.join(random.choice(chars) for _ in range(length))
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # milliseconds

        name = f"{prefix}_{timestamp}_{random_str}"

        # If max_length is specified and name exceeds it, truncate intelligently
        if max_length and len(name) > max_length:
            # Keep the random suffix for uniqueness, truncate prefix and timestamp
            suffix_len = length + 1  # +1 for underscore
            available_len = max_length - suffix_len

            if available_len > 0:
                # Use shorter timestamp format for space
                short_timestamp = datetime.now().strftime('%m%d_%H%M%S')  # 11 chars
                truncated_prefix = prefix[:available_len - len(short_timestamp) - 1] if len(prefix) > 0 else ""
                name = f"{truncated_prefix}_{short_timestamp}_{random_str}" if truncated_prefix else f"{short_timestamp}_{random_str}"
            else:
                # Fallback: just use random string
                name = random_str

        return name

    @staticmethod
    def wait_for_sync(check_func: Callable[[], bool], timeout: int = 120,
                      operation_name: str = "operation") -> bool:
        """
        Wait for sync operation to complete with progress logging.

        Args:
            check_func: Function that returns True when sync is complete
            timeout: Timeout in seconds
            operation_name: Name of operation for logging

        Returns:
            True if sync completed, False if timeout
        """
        start_time = time.time()
        check_interval = 2
        last_log_time = start_time

        logger.info(f"Starting sync wait for: {operation_name}")

        while time.time() - start_time < timeout:
            try:
                if check_func():
                    elapsed = time.time() - start_time
                    logger.info(f"[SUCCESS] {operation_name} synced successfully in {elapsed:.2f}s")
                    return True
            except Exception as e:
                elapsed = time.time() - start_time
                logger.warning(f"Sync check failed for {operation_name} at {elapsed:.1f}s: {e}")

            elapsed = time.time() - start_time
            # Log every 10 seconds or on first check
            if elapsed - (last_log_time - start_time) >= 10 or elapsed <= check_interval:
                progress = (elapsed / timeout) * 100
                logger.info(f"[WAITING] {operation_name} sync... {elapsed:.1f}s elapsed ({progress:.1f}% of timeout)")
                last_log_time = time.time()

            time.sleep(check_interval)

        elapsed = time.time() - start_time
        logger.error(f"[FAILED] {operation_name} sync failed after {elapsed:.2f}s timeout")
        return False

    @staticmethod
    def create_default_schema(client):
        """Create default collection schema for testing using MilvusClient API."""
        from pymilvus import DataType

        # Create schema using MilvusClient API like in the example
        schema = client.create_schema(enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=128)

        return schema

    @staticmethod
    def create_manual_id_schema(client):
        """Create collection schema with manual ID for upsert operations."""
        from pymilvus import DataType

        # Create schema using MilvusClient API with manual ID
        schema = client.create_schema(enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=False)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=128)

        return schema

    @staticmethod
    def generate_test_data(count: int = 100) -> List[Dict[str, Any]]:
        """Generate test data for insert operations."""
        return [
            {
                "vector": [random.random() for _ in range(128)],
                "text": f"test_text_{i}",
                "number": i,
                "metadata": {"type": "test", "value": i}
            }
            for i in range(count)
        ]

    @staticmethod
    def generate_test_data_with_id(count: int = 100, start_id: int = 0) -> List[Dict[str, Any]]:
        """Generate test data with manual IDs for upsert operations."""
        return [
            {
                "id": start_id + i,
                "vector": [random.random() for _ in range(128)],
                "text": f"test_text_{i}",
                "number": i,
                "metadata": {"type": "test", "value": i}
            }
            for i in range(count)
        ]

    def cleanup_database(self, client: MilvusClient, db_name: str):
        """Clean up database if exists."""
        try:
            if db_name in client.list_databases():
                logger.info(f"[CLEANUP] Cleaning up database: {db_name}")
                client.drop_database(db_name)
                logger.info(f"[SUCCESS] Database {db_name} cleaned up successfully")
            else:
                logger.debug(f"Database {db_name} does not exist, skipping cleanup")
        except Exception as e:
            logger.warning(f"[FAILED] Failed to cleanup database {db_name}: {e}")

    def cleanup_collection(self, client: MilvusClient, collection_name: str):
        """Clean up collection if exists."""
        try:
            if client.has_collection(collection_name):
                logger.info(f"[CLEANUP] Cleaning up collection: {collection_name}")
                client.drop_collection(collection_name)
                logger.info(f"[SUCCESS] Collection {collection_name} cleaned up successfully")
            else:
                logger.debug(f"Collection {collection_name} does not exist, skipping cleanup")
        except Exception as e:
            logger.warning(f"[FAILED] Failed to cleanup collection {collection_name}: {e}")

    def cleanup_user(self, client: MilvusClient, username: str):
        """Clean up user if exists."""
        try:
            users = client.list_users()
            if username in users:
                logger.info(f"[CLEANUP] Cleaning up user: {username}")
                client.drop_user(username)
                logger.info(f"[SUCCESS] User {username} cleaned up successfully")
            else:
                logger.debug(f"User {username} does not exist, skipping cleanup")
        except Exception as e:
            logger.warning(f"[FAILED] Failed to cleanup user {username}: {e}")

    def cleanup_role(self, client: MilvusClient, role_name: str):
        """Clean up role if exists."""
        try:
            roles = client.list_roles()
            if role_name in roles:
                logger.info(f"[CLEANUP] Cleaning up role: {role_name}")

                # First, revoke all privileges from the role
                try:
                    role_privileges = client.describe_role(role_name)
                    if isinstance(role_privileges, dict) and 'privileges' in role_privileges:
                        privileges_list = role_privileges['privileges']
                    elif isinstance(role_privileges, list):
                        privileges_list = role_privileges
                    else:
                        privileges_list = []

                    for privilege_info in privileges_list:
                        try:
                            client.revoke_privilege(
                                role_name=role_name,
                                object_type=privilege_info.get('object_type', 'Collection'),
                                privilege=privilege_info.get('privilege'),
                                object_name=privilege_info.get('object_name', '*')
                            )
                            logger.debug(f"[CLEANUP] Revoked privilege {privilege_info.get('privilege')} from role {role_name}")
                        except Exception as revoke_e:
                            logger.debug(f"[CLEANUP] Failed to revoke privilege {privilege_info.get('privilege')}: {revoke_e}")
                except Exception as describe_e:
                    logger.debug(f"[CLEANUP] Failed to describe role privileges: {describe_e}")

                # Then drop the role
                client.drop_role(role_name)
                logger.info(f"[SUCCESS] Role {role_name} cleaned up successfully")
            else:
                logger.debug(f"Role {role_name} does not exist, skipping cleanup")
        except Exception as e:
            logger.warning(f"[FAILED] Failed to cleanup role {role_name}: {e}")

    def log_test_start(self, test_name: str, operation_type: str, resource_name: str = ""):
        """Log test case start with detailed information."""
        separator = "=" * 80
        logger.info(f"\n{separator}")
        logger.info(f"[TEST_START] Starting test: {test_name}")
        logger.info(f"[OPERATION] Operation type: {operation_type}")
        if resource_name:
            logger.info(f"[RESOURCE] Resource: {resource_name}")
        logger.info(f"[TIME] Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{separator}")

    def log_test_end(self, test_name: str, success: bool, duration: float = 0):
        """Log test case completion with result."""
        separator = "=" * 80
        status = "PASSED" if success else "FAILED"
        logger.info(f"\n{separator}")
        logger.info(f"[TEST_END] Test completed: {test_name}")
        logger.info(f"[RESULT] Result: {status}")
        if duration > 0:
            logger.info(f"[DURATION] Duration: {duration:.2f}s")
        logger.info(f"[TIME] End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{separator}\n")

    def log_operation(self, operation: str, resource_type: str, resource_name: str, client_type: str = "upstream"):
        """Log CDC operation execution."""
        logger.info(f"[EXECUTE] Executing {operation} on {client_type}: {resource_type} '{resource_name}'")

    def log_sync_verification(self, operation: str, resource_name: str, expected_state: str):
        """Log sync verification attempt."""
        logger.info(f"[VERIFY] Verifying sync for {operation}: {resource_name} should be {expected_state}")

    def log_data_operation(self, operation: str, collection_name: str, count: int = 0, details: str = ""):
        """Log data manipulation operations."""
        if count > 0:
            logger.info(f"[DATA] {operation} operation: {collection_name} - {count} records {details}")
        else:
            logger.info(f"[DATA] {operation} operation: {collection_name} {details}")

    def log_resource_state(self, resource_type: str, resource_name: str, state: str, client_type: str, details: str = ""):
        """Log current resource state."""
        state_prefix = "[EXISTS]" if state == "exists" else "[MISSING]" if state == "missing" else "[UNKNOWN]"
        logger.info(f"{state_prefix} {client_type.capitalize()} {resource_type} '{resource_name}': {state} {details}")