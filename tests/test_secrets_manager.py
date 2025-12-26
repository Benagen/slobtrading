"""
Tests for SecretsManager (Phase 1).

Run with: pytest tests/test_secrets_manager.py -v
"""

import pytest
import os
import tempfile
from pathlib import Path

from slob.config.secrets import SecretsManager, get_secret


@pytest.fixture
def temp_secrets_dir():
    """Create temporary secrets directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        secrets_dir = Path(tmpdir) / "secrets"
        secrets_dir.mkdir(mode=0o700)
        yield secrets_dir


@pytest.fixture
def temp_docker_secrets():
    """Create temporary Docker secrets directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        docker_secrets = Path(tmpdir) / "run" / "secrets"
        docker_secrets.mkdir(parents=True, mode=0o700)
        yield docker_secrets


class TestSecretsManager:
    """Test suite for SecretsManager"""

    def test_initialization(self):
        """Test SecretsManager initialization."""
        manager = SecretsManager(use_docker_secrets=True, use_local_secrets=True)

        assert manager.use_docker_secrets is True
        assert manager.use_local_secrets is True

    def test_initialization_docker_only(self):
        """Test initialization with Docker secrets only."""
        manager = SecretsManager(use_docker_secrets=True, use_local_secrets=False)

        assert manager.use_docker_secrets is True
        assert manager.use_local_secrets is False

    def test_get_secret_from_local_file(self, temp_secrets_dir):
        """Test getting secret from local file."""
        # Create secret file
        secret_file = temp_secrets_dir / "test_secret.txt"
        secret_file.write_text("my_secret_value")
        secret_file.chmod(0o600)

        # Update SecretsManager to use temp directory
        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        # Get secret
        value = manager.get_secret('test_secret')

        assert value == "my_secret_value"

    def test_get_secret_from_docker(self, temp_docker_secrets):
        """Test getting secret from Docker secrets."""
        # Create Docker secret file
        secret_file = temp_docker_secrets / "docker_secret"
        secret_file.write_text("docker_value")
        secret_file.chmod(0o600)

        # Update SecretsManager to use temp directory
        manager = SecretsManager(use_docker_secrets=True, use_local_secrets=False)
        manager.DOCKER_SECRETS_DIR = temp_docker_secrets

        # Get secret
        value = manager.get_secret('docker_secret')

        assert value == "docker_value"

    def test_get_secret_priority(self, temp_docker_secrets, temp_secrets_dir):
        """Test secret priority: Docker > Local > Env."""
        # Create Docker secret
        (temp_docker_secrets / "priority_test.txt").write_text("docker_value")

        # Create local secret
        (temp_secrets_dir / "priority_test.txt").write_text("local_value")

        # Set env variable
        os.environ['PRIORITY_TEST'] = 'env_value'

        # Setup manager
        manager = SecretsManager(use_docker_secrets=True, use_local_secrets=True)
        manager.DOCKER_SECRETS_DIR = temp_docker_secrets
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        # Should get Docker value (highest priority)
        value = manager.get_secret('priority_test', env_var='PRIORITY_TEST')

        assert value == "docker_value"

        # Cleanup
        del os.environ['PRIORITY_TEST']

    def test_get_secret_from_env_var(self):
        """Test getting secret from environment variable."""
        os.environ['TEST_SECRET'] = 'env_secret_value'

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=False)
        value = manager.get_secret('test_secret', env_var='TEST_SECRET')

        assert value == "env_secret_value"

        # Cleanup
        del os.environ['TEST_SECRET']

    def test_get_secret_with_default(self):
        """Test getting secret with default value."""
        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=False)

        value = manager.get_secret('nonexistent_secret', default='default_value')

        assert value == "default_value"

    def test_get_secret_required_missing(self):
        """Test getting required secret that doesn't exist."""
        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=False)

        with pytest.raises(ValueError, match="Required secret"):
            manager.get_secret('nonexistent_secret', required=True)

    def test_get_secret_required_exists(self, temp_secrets_dir):
        """Test getting required secret that exists."""
        secret_file = temp_secrets_dir / "required_secret.txt"
        secret_file.write_text("required_value")

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        value = manager.get_secret('required_secret', required=True)

        assert value == "required_value"

    def test_get_secret_strips_whitespace(self, temp_secrets_dir):
        """Test that secrets are stripped of whitespace."""
        secret_file = temp_secrets_dir / "whitespace_secret.txt"
        secret_file.write_text("  value_with_spaces  \n")

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        value = manager.get_secret('whitespace_secret')

        assert value == "value_with_spaces"

    def test_get_all_secrets(self, temp_secrets_dir):
        """Test getting all secrets."""
        # Create multiple secret files
        (temp_secrets_dir / "secret1.txt").write_text("value1")
        (temp_secrets_dir / "secret2.txt").write_text("value2")
        (temp_secrets_dir / "secret3.txt").write_text("value3")

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        secrets = manager.get_all_secrets()

        assert len(secrets) == 3
        assert secrets['secret1'] == 'value1'
        assert secrets['secret2'] == 'value2'
        assert secrets['secret3'] == 'value3'

    def test_validate_secrets_all_found(self, temp_secrets_dir):
        """Test validating secrets when all are present."""
        (temp_secrets_dir / "secret_a.txt").write_text("value_a")
        (temp_secrets_dir / "secret_b.txt").write_text("value_b")

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        all_found, missing = manager.validate_secrets(['secret_a', 'secret_b'])

        assert all_found is True
        assert len(missing) == 0

    def test_validate_secrets_some_missing(self, temp_secrets_dir):
        """Test validating secrets when some are missing."""
        (temp_secrets_dir / "secret_a.txt").write_text("value_a")

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        all_found, missing = manager.validate_secrets(['secret_a', 'secret_b', 'secret_c'])

        assert all_found is False
        assert len(missing) == 2
        assert 'secret_b' in missing
        assert 'secret_c' in missing

    def test_get_secret_file_suffix(self, temp_secrets_dir):
        """Test getting secret from environment variable with _FILE suffix."""
        # Create secret file
        secret_file = temp_secrets_dir / "file_secret.txt"
        secret_file.write_text("file_value")

        # Set env variable pointing to file
        os.environ['FILE_SECRET_FILE'] = str(secret_file)

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=False)

        value = manager.get_secret('file_secret', env_var='FILE_SECRET')

        assert value == "file_value"

        # Cleanup
        del os.environ['FILE_SECRET_FILE']

    def test_secret_file_not_found(self, temp_secrets_dir):
        """Test handling of missing secret file."""
        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir

        # Should return None when not required
        value = manager.get_secret('nonexistent', required=False)

        assert value is None

    def test_docker_secrets_disabled(self):
        """Test that Docker secrets are skipped when disabled."""
        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=False)

        # Even if /run/secrets exists, shouldn't use it
        value = manager.get_secret('any_secret', default='default')

        assert value == 'default'

    def test_local_secrets_disabled(self):
        """Test that local secrets are skipped when disabled."""
        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=False)

        # Even if ./secrets exists, shouldn't use it
        value = manager.get_secret('any_secret', default='default')

        assert value == 'default'


class TestSecretHelperFunctions:
    """Test helper functions for common secrets."""

    def test_get_ib_account(self, temp_secrets_dir):
        """Test getting IB account from secrets."""
        (temp_secrets_dir / "ib_account.txt").write_text("DU123456")

        # Mock the global secrets manager
        from slob.config import secrets
        original_manager = secrets._secrets_manager

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir
        secrets._secrets_manager = manager

        try:
            from slob.config.secrets import get_ib_account
            account = get_ib_account()
            assert account == "DU123456"
        finally:
            # Restore original manager
            secrets._secrets_manager = original_manager

    def test_get_redis_password(self, temp_secrets_dir):
        """Test getting Redis password with default."""
        # Mock the global secrets manager
        from slob.config import secrets
        original_manager = secrets._secrets_manager

        manager = SecretsManager(use_docker_secrets=False, use_local_secrets=True)
        manager.LOCAL_SECRETS_DIR = temp_secrets_dir
        secrets._secrets_manager = manager

        try:
            from slob.config.secrets import get_redis_password
            # Should return empty string default if not found
            password = get_redis_password()
            assert password == ''
        finally:
            secrets._secrets_manager = original_manager


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
