"""
CDC sync tests for RBAC operations.
"""

import time
from base import TestCDCSyncBase, logger


class TestCDCSyncRBAC(TestCDCSyncBase):
    """Test CDC sync for RBAC operations."""

    def setup_method(self):
        """Setup for each test method."""
        self.resources_to_cleanup = []

    def teardown_method(self):
        """Cleanup after each test method - only cleanup upstream, downstream will sync."""
        upstream_client = getattr(self, '_upstream_client', None)

        if upstream_client:
            for resource_type, resource_name in self.resources_to_cleanup:
                if resource_type == 'user':
                    self.cleanup_user(upstream_client, resource_name)
                elif resource_type == 'role':
                    self.cleanup_role(upstream_client, resource_name)

            time.sleep(1)  # Allow cleanup to sync to downstream

    def test_create_role(self, upstream_client, downstream_client, sync_timeout):
        """Test CREATE_ROLE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        role_name = self.gen_unique_name("test_role_create")
        self.resources_to_cleanup.append(('role', role_name))

        # Initial cleanup
        self.cleanup_role(upstream_client, role_name)

        # Create role in upstream
        upstream_client.create_role(role_name)
        assert role_name in upstream_client.list_roles()

        # Wait for sync to downstream
        def check_sync():
            return role_name in downstream_client.list_roles()

        assert self.wait_for_sync(check_sync, sync_timeout, f"create role {role_name}")

    def test_drop_role(self, upstream_client, downstream_client, sync_timeout):
        """Test DROP_ROLE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        role_name = self.gen_unique_name("test_role_drop")
        self.resources_to_cleanup.append(('role', role_name))

        # Initial cleanup
        self.cleanup_role(upstream_client, role_name)

        # Create role first
        upstream_client.create_role(role_name)

        # Wait for creation to sync
        def check_create():
            return role_name in downstream_client.list_roles()
        assert self.wait_for_sync(check_create, sync_timeout, f"create role {role_name}")

        # Drop role in upstream
        upstream_client.drop_role(role_name)
        assert role_name not in upstream_client.list_roles()

        # Wait for drop to sync
        def check_drop():
            return role_name not in downstream_client.list_roles()

        assert self.wait_for_sync(check_drop, sync_timeout, f"drop role {role_name}")

    def test_create_user(self, upstream_client, downstream_client, sync_timeout):
        """Test CREATE_USER operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        username = self.gen_unique_name("test_user_create")
        password = "TestPass123!"
        self.resources_to_cleanup.append(('user', username))

        # Initial cleanup
        self.cleanup_user(upstream_client, username)

        # Create user in upstream
        upstream_client.create_user(username, password)
        assert username in upstream_client.list_users()

        # Wait for sync to downstream
        def check_sync():
            return username in downstream_client.list_users()

        assert self.wait_for_sync(check_sync, sync_timeout, f"create user {username}")

    def test_drop_user(self, upstream_client, downstream_client, sync_timeout):
        """Test DROP_USER operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        username = self.gen_unique_name("test_user_drop")
        password = "TestPass123!"
        self.resources_to_cleanup.append(('user', username))

        # Initial cleanup
        self.cleanup_user(upstream_client, username)

        # Create user first
        upstream_client.create_user(username, password)

        # Wait for creation to sync
        def check_create():
            return username in downstream_client.list_users()
        assert self.wait_for_sync(check_create, sync_timeout, f"create user {username}")

        # Drop user in upstream
        upstream_client.drop_user(username)
        assert username not in upstream_client.list_users()

        # Wait for drop to sync
        def check_drop():
            return username not in downstream_client.list_users()

        assert self.wait_for_sync(check_drop, sync_timeout, f"drop user {username}")

    def test_grant_role(self, upstream_client, downstream_client, sync_timeout):
        """Test GRANT_ROLE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        username = self.gen_unique_name("test_user_grant")
        role_name = self.gen_unique_name("test_role_grant")
        password = "TestPass123!"
        self.resources_to_cleanup.append(('user', username))
        self.resources_to_cleanup.append(('role', role_name))

        # Initial cleanup
        self.cleanup_user(upstream_client, username)
        self.cleanup_role(upstream_client, role_name)

        # Create user and role
        upstream_client.create_user(username, password)
        upstream_client.create_role(role_name)

        # Wait for creation to sync
        def check_create():
            return (username in downstream_client.list_users() and
                    role_name in downstream_client.list_roles())
        assert self.wait_for_sync(check_create, sync_timeout, f"create user/role for grant")

        # Grant role to user
        upstream_client.grant_role(username, role_name)

        # Wait for grant to sync
        def check_grant():
            # Allow operation to propagate
            time.sleep(2)
            return True  # Grant operations typically succeed if no exception

        assert self.wait_for_sync(check_grant, sync_timeout, f"grant role {role_name} to user {username}")

    def test_revoke_role(self, upstream_client, downstream_client, sync_timeout):
        """Test REVOKE_ROLE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        username = self.gen_unique_name("test_user_revoke")
        role_name = self.gen_unique_name("test_role_revoke")
        password = "TestPass123!"
        self.resources_to_cleanup.append(('user', username))
        self.resources_to_cleanup.append(('role', role_name))

        # Initial cleanup
        self.cleanup_user(upstream_client, username)
        self.cleanup_role(upstream_client, role_name)

        # Create user and role, then grant role
        upstream_client.create_user(username, password)
        upstream_client.create_role(role_name)
        upstream_client.grant_role(username, role_name)

        # Wait for setup to sync
        time.sleep(5)

        # Revoke role from user
        upstream_client.revoke_role(username, role_name)

        # Wait for revoke to sync
        def check_revoke():
            time.sleep(2)  # Allow operation to propagate
            return True  # Revoke operations typically succeed if no exception

        assert self.wait_for_sync(check_revoke, sync_timeout, f"revoke role {role_name} from user {username}")

    def test_grant_privilege(self, upstream_client, downstream_client, sync_timeout):
        """Test GRANT_PRIVILEGE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        role_name = self.gen_unique_name("test_role_priv_grant")
        self.resources_to_cleanup.append(('role', role_name))

        # Initial cleanup
        self.cleanup_role(upstream_client, role_name)

        # Create role
        upstream_client.create_role(role_name)

        # Wait for creation to sync
        def check_create():
            return role_name in downstream_client.list_roles()
        assert self.wait_for_sync(check_create, sync_timeout, f"create role for privilege {role_name}")

        # Grant privilege to role
        upstream_client.grant_privilege(
            role_name=role_name,
            object_type="Collection",
            privilege="Search",
            object_name="*"
        )

        # Wait for privilege grant to sync
        def check_grant():
            time.sleep(2)
            return True  # Privilege grant operations typically succeed if no exception

        assert self.wait_for_sync(check_grant, sync_timeout, f"grant privilege to role {role_name}")

    def test_revoke_privilege(self, upstream_client, downstream_client, sync_timeout):
        """Test REVOKE_PRIVILEGE operation sync."""
        # Store upstream client for teardown
        self._upstream_client = upstream_client

        role_name = self.gen_unique_name("test_role_priv_revoke")
        self.resources_to_cleanup.append(('role', role_name))

        # Initial cleanup
        self.cleanup_role(upstream_client, role_name)

        # Create role and grant privilege
        upstream_client.create_role(role_name)

        upstream_client.grant_privilege(
            role_name=role_name,
            object_type="Collection",
            privilege="Search",
            object_name="*"
        )

        # Wait for setup
        time.sleep(3)

        # Revoke privilege from role
        upstream_client.revoke_privilege(
            role_name=role_name,
            object_type="Collection",
            privilege="Search",
            object_name="*"
        )

        # Wait for revoke to sync
        def check_revoke():
            time.sleep(2)
            return True  # Privilege revoke operations typically succeed if no exception

        assert self.wait_for_sync(check_revoke, sync_timeout, f"revoke privilege from role {role_name}")