"""
Secure Secrets Management

Handles reading secrets from multiple sources:
1. Docker secrets (/run/secrets/)
2. Local secrets files (./secrets/)
3. Environment variables (fallback)

Priority: Docker secrets > Local secrets > Environment variables
"""

import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class SecretsManager:
    """
    Centralized secrets management for SLOB system.

    Supports multiple secret sources with priority:
    1. Docker secrets (/run/secrets/)
    2. Local secrets files (./secrets/)
    3. Environment variables (development fallback)
    """

    # Docker secrets mount point
    DOCKER_SECRETS_DIR = Path("/run/secrets")

    # Local secrets directory (for development)
    LOCAL_SECRETS_DIR = Path("./secrets")

    def __init__(self, use_docker_secrets: bool = True, use_local_secrets: bool = True):
        """
        Initialize secrets manager.

        Args:
            use_docker_secrets: Enable reading from /run/secrets/ (production)
            use_local_secrets: Enable reading from ./secrets/ (development)
        """
        self.use_docker_secrets = use_docker_secrets
        self.use_local_secrets = use_local_secrets

        logger.info(f"Secrets manager initialized: docker={use_docker_secrets}, local={use_local_secrets}")

    def get_secret(self,
                   secret_name: str,
                   env_var: Optional[str] = None,
                   default: Optional[str] = None,
                   required: bool = False) -> Optional[str]:
        """
        Get secret value from multiple sources (in priority order).

        Priority:
        1. Docker secrets (/run/secrets/<secret_name>)
        2. Local secrets (./secrets/<secret_name>.txt)
        3. Environment variable (if env_var specified)
        4. Environment variable with _FILE suffix
        5. Default value

        Args:
            secret_name: Name of the secret (e.g., 'ib_account')
            env_var: Environment variable name (e.g., 'IB_ACCOUNT')
            default: Default value if secret not found
            required: Raise error if secret not found

        Returns:
            Secret value as string, or None if not found

        Raises:
            ValueError: If required=True and secret not found
        """

        # Try 1: Docker secrets
        if self.use_docker_secrets:
            docker_secret_path = self.DOCKER_SECRETS_DIR / secret_name
            if docker_secret_path.exists():
                try:
                    value = docker_secret_path.read_text().strip()
                    logger.debug(f"Secret '{secret_name}' loaded from Docker secrets")
                    return value
                except Exception as e:
                    logger.warning(f"Failed to read Docker secret '{secret_name}': {e}")

        # Try 2: Local secrets file
        if self.use_local_secrets:
            local_secret_path = self.LOCAL_SECRETS_DIR / f"{secret_name}.txt"
            if local_secret_path.exists():
                try:
                    value = local_secret_path.read_text().strip()
                    logger.debug(f"Secret '{secret_name}' loaded from local secrets")
                    return value
                except Exception as e:
                    logger.warning(f"Failed to read local secret '{secret_name}': {e}")

        # Try 3: Environment variable with _FILE suffix
        if env_var:
            env_file_var = f"{env_var}_FILE"
            env_file_path = os.getenv(env_file_var)
            if env_file_path:
                try:
                    value = Path(env_file_path).read_text().strip()
                    logger.debug(f"Secret '{secret_name}' loaded from {env_file_var}")
                    return value
                except Exception as e:
                    logger.warning(f"Failed to read secret from {env_file_var}={env_file_path}: {e}")

        # Try 4: Direct environment variable
        if env_var:
            value = os.getenv(env_var)
            if value:
                logger.debug(f"Secret '{secret_name}' loaded from environment variable {env_var}")
                return value

        # Try 5: Default value
        if default is not None:
            logger.debug(f"Secret '{secret_name}' using default value")
            return default

        # Not found
        if required:
            raise ValueError(
                f"Required secret '{secret_name}' not found. "
                f"Tried: Docker secrets, local secrets, {env_var or 'no env var'}"
            )

        logger.warning(f"Secret '{secret_name}' not found (not required)")
        return None

    def get_all_secrets(self) -> dict:
        """
        Get all secrets from all sources.

        Returns:
            Dict mapping secret names to values
        """
        secrets = {}

        # Load from Docker secrets
        if self.use_docker_secrets and self.DOCKER_SECRETS_DIR.exists():
            for secret_file in self.DOCKER_SECRETS_DIR.iterdir():
                if secret_file.is_file():
                    try:
                        secrets[secret_file.name] = secret_file.read_text().strip()
                    except Exception as e:
                        logger.warning(f"Failed to read Docker secret {secret_file.name}: {e}")

        # Load from local secrets
        if self.use_local_secrets and self.LOCAL_SECRETS_DIR.exists():
            for secret_file in self.LOCAL_SECRETS_DIR.glob("*.txt"):
                secret_name = secret_file.stem  # Remove .txt extension
                if secret_name not in secrets:  # Docker secrets take priority
                    try:
                        secrets[secret_name] = secret_file.read_text().strip()
                    except Exception as e:
                        logger.warning(f"Failed to read local secret {secret_name}: {e}")

        logger.info(f"Loaded {len(secrets)} secrets from all sources")
        return secrets

    def validate_secrets(self, required_secrets: list) -> tuple[bool, list]:
        """
        Validate that all required secrets are available.

        Args:
            required_secrets: List of secret names that must exist

        Returns:
            Tuple of (all_found: bool, missing_secrets: list)
        """
        missing = []

        for secret_name in required_secrets:
            try:
                self.get_secret(secret_name, required=True)
            except ValueError:
                missing.append(secret_name)

        all_found = len(missing) == 0

        if all_found:
            logger.info(f"✅ All {len(required_secrets)} required secrets found")
        else:
            logger.error(f"❌ Missing {len(missing)} required secrets: {missing}")

        return all_found, missing


# Global instance (singleton pattern)
_secrets_manager = None


def get_secrets_manager() -> SecretsManager:
    """Get global secrets manager instance (singleton)."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager


def get_secret(secret_name: str,
               env_var: Optional[str] = None,
               default: Optional[str] = None,
               required: bool = False) -> Optional[str]:
    """
    Convenience function to get a secret using global manager.

    See SecretsManager.get_secret() for full documentation.
    """
    return get_secrets_manager().get_secret(secret_name, env_var, default, required)


# Commonly used secrets with standardized names
def get_ib_account() -> str:
    """Get Interactive Brokers account ID."""
    return get_secret('ib_account', 'IB_ACCOUNT', required=True)


def get_alpaca_api_key() -> str:
    """Get Alpaca API key."""
    return get_secret('alpaca_api_key', 'ALPACA_API_KEY', required=True)


def get_alpaca_api_secret() -> str:
    """Get Alpaca API secret."""
    return get_secret('alpaca_api_secret', 'ALPACA_API_SECRET', required=True)


def get_telegram_bot_token() -> Optional[str]:
    """Get Telegram bot token (optional)."""
    return get_secret('telegram_bot_token', 'TELEGRAM_BOT_TOKEN', required=False)


def get_telegram_chat_id() -> Optional[str]:
    """Get Telegram chat ID (optional)."""
    return get_secret('telegram_chat_id', 'TELEGRAM_CHAT_ID', required=False)


def get_smtp_password() -> Optional[str]:
    """Get SMTP password (optional)."""
    return get_secret('smtp_password', 'SMTP_PASSWORD', required=False)


def get_redis_password() -> Optional[str]:
    """Get Redis password (optional but recommended)."""
    return get_secret('redis_password', 'REDIS_PASSWORD', default='')


def get_dashboard_secret_key() -> str:
    """Get dashboard Flask secret key."""
    return get_secret('dashboard_secret_key', 'DASHBOARD_SECRET_KEY', required=True)


def get_dashboard_password_hash() -> Optional[str]:
    """Get dashboard password hash (optional - falls back to plaintext if not set)."""
    return get_secret('dashboard_password_hash', 'DASHBOARD_PASSWORD_HASH', required=False)


if __name__ == "__main__":
    # Test secrets manager
    logging.basicConfig(level=logging.DEBUG)

    print("Testing SecretsManager...")
    print("=" * 60)

    manager = get_secrets_manager()

    # Test individual secrets
    print("\nTesting individual secret retrieval:")
    print(f"IB Account: {get_ib_account() or 'NOT FOUND'}")
    print(f"Alpaca Key: {get_alpaca_api_key()[:10] or 'NOT FOUND'}... (truncated)")
    print(f"Telegram Token: {get_telegram_bot_token() or 'NOT CONFIGURED (optional)'}")

    # Test validation
    print("\nValidating required secrets:")
    required = ['ib_account', 'alpaca_api_key', 'alpaca_api_secret']
    all_found, missing = manager.validate_secrets(required)

    if all_found:
        print("✅ All required secrets found!")
    else:
        print(f"❌ Missing secrets: {missing}")

    print("\n" + "=" * 60)
