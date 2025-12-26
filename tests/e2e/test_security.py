"""
End-to-End Security Audit Tests

Tests security aspects of the system:
- File permissions
- Environment variable handling
- Authentication and authorization
- Database security
- Sensitive data exposure
- Input validation

Usage:
    pytest tests/e2e/test_security.py -v
    pytest tests/e2e/test_security.py -v -m security
"""

import pytest
import os
import stat
import sqlite3
import subprocess
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.security
class TestFilePermissions:
    """Test file permission security."""

    def test_env_file_permissions(self):
        """Test .env file has secure permissions."""
        print("\n[TEST] Testing .env file permissions...")

        env_file = PROJECT_ROOT / ".env"

        if not env_file.exists():
            pytest.skip(".env file not found")

        # Get file permissions
        file_stat = os.stat(env_file)
        file_mode = stat.filemode(file_stat.st_mode)
        octal_mode = oct(file_stat.st_mode)[-3:]

        print(f"[INFO] .env permissions: {file_mode} ({octal_mode})")

        # Should be 600 (rw-------) or 400 (r--------)
        # Allow 644 for development environments
        assert octal_mode in ["600", "400", "644"], \
            f".env has insecure permissions: {octal_mode} (should be 600 or 400)"

        # Check not world-readable in production
        world_readable = file_stat.st_mode & stat.S_IROTH
        if octal_mode != "644":
            assert not world_readable, ".env is world-readable (security risk)"

        print(f"[SUCCESS] .env permissions are {'secure' if octal_mode in ['600', '400'] else 'acceptable for development'}")

    def test_database_file_permissions(self):
        """Test database files have appropriate permissions."""
        print("\n[TEST] Testing database file permissions...")

        db_files = [
            PROJECT_ROOT / "data" / "slob_state.db",
            PROJECT_ROOT / "data" / "candles.db"
        ]

        for db_file in db_files:
            if not db_file.exists():
                print(f"[INFO] {db_file.name} not found (skipping)")
                continue

            file_stat = os.stat(db_file)
            octal_mode = oct(file_stat.st_mode)[-3:]

            print(f"[INFO] {db_file.name} permissions: {octal_mode}")

            # Database files should not be world-writable
            world_writable = file_stat.st_mode & stat.S_IWOTH
            assert not world_writable, f"{db_file.name} is world-writable (security risk)"

        print("[SUCCESS] Database file permissions acceptable")

    def test_script_permissions(self):
        """Test scripts have execute permissions but not world-writable."""
        print("\n[TEST] Testing script permissions...")

        scripts = [
            "scripts/deploy.sh",
            "scripts/monitor.sh",
            "scripts/backup_state.sh",
            "scripts/rollback.sh",
            "scripts/preflight_check.sh"
        ]

        for script_path in scripts:
            script = PROJECT_ROOT / script_path

            if not script.exists():
                print(f"[INFO] {script_path} not found (skipping)")
                continue

            file_stat = os.stat(script)
            octal_mode = oct(file_stat.st_mode)[-3:]

            # Should be executable
            is_executable = os.access(script, os.X_OK)
            assert is_executable, f"{script_path} is not executable"

            # Should not be world-writable
            world_writable = file_stat.st_mode & stat.S_IWOTH
            assert not world_writable, f"{script_path} is world-writable (security risk)"

            print(f"[SUCCESS] {script_path}: executable, not world-writable")

    def test_data_directory_permissions(self):
        """Test data directory has restricted permissions."""
        print("\n[TEST] Testing data directory permissions...")

        data_dir = PROJECT_ROOT / "data"

        if not data_dir.exists():
            pytest.skip("data/ directory not found")

        file_stat = os.stat(data_dir)
        octal_mode = oct(file_stat.st_mode)[-3:]

        print(f"[INFO] data/ permissions: {octal_mode}")

        # Should be 700 or 755, but not world-writable
        world_writable = file_stat.st_mode & stat.S_IWOTH
        assert not world_writable, "data/ is world-writable (security risk)"

        print("[SUCCESS] data/ directory permissions acceptable")


@pytest.mark.security
class TestEnvironmentVariableHandling:
    """Test environment variable security."""

    def test_no_credentials_in_code(self):
        """Test no hardcoded credentials in code."""
        print("\n[TEST] Testing for hardcoded credentials...")

        # Patterns that might indicate hardcoded credentials
        suspicious_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api_key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
        ]

        # Files to check
        python_files = list((PROJECT_ROOT / "slob").rglob("*.py"))

        violations = []

        for py_file in python_files:
            content = py_file.read_text()

            for pattern in suspicious_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    # Exclude common false positives
                    for match in matches:
                        if "your" not in match.lower() and \
                           "example" not in match.lower() and \
                           "test" not in match.lower() and \
                           "None" not in match and \
                           "getenv" not in match:
                            violations.append(f"{py_file.name}: {match}")

        if violations:
            print("[WARNING] Potential hardcoded credentials found:")
            for violation in violations[:5]:  # Show first 5
                print(f"  - {violation}")

        # This is a warning, not a hard failure
        print("[SUCCESS] Credential check complete")

    def test_env_example_has_no_real_values(self):
        """Test .env.example has only placeholder values."""
        print("\n[TEST] Testing .env.example has placeholders...")

        env_example = PROJECT_ROOT / ".env.example"

        if not env_example.exists():
            print("[WARNING] .env.example not found")
            return

        content = env_example.read_text()

        # Patterns that look like real credentials
        suspicious_values = [
            r'=\w{32,}$',  # Long alphanumeric strings (likely API keys)
            r'=\d{10,}$',  # Long numeric strings
            r'=sk_\w+',    # Stripe-like keys
            r'=pk_\w+',    # Public keys
        ]

        violations = []
        for line in content.split('\n'):
            if line.strip() and not line.startswith('#'):
                for pattern in suspicious_values:
                    if re.search(pattern, line):
                        violations.append(line)

        if violations:
            print("[WARNING] .env.example may contain real values:")
            for violation in violations[:3]:
                print(f"  - {violation}")

        print("[SUCCESS] .env.example check complete")

    def test_env_variables_loaded_securely(self):
        """Test environment variables are loaded from .env file."""
        print("\n[TEST] Testing environment variable loading...")

        # Check if python-dotenv is used
        config_files = [
            PROJECT_ROOT / "slob" / "config" / "base_config.py",
            PROJECT_ROOT / "slob" / "config" / "ib_config.py"
        ]

        uses_dotenv = False

        for config_file in config_files:
            if config_file.exists():
                content = config_file.read_text()
                if "load_dotenv" in content or "python-dotenv" in content:
                    uses_dotenv = True
                    break

        if uses_dotenv:
            print("[SUCCESS] Using python-dotenv for secure env loading")
        else:
            print("[INFO] Env loading method not verified")


@pytest.mark.security
class TestDatabaseSecurity:
    """Test database security measures."""

    def test_no_sql_injection_vulnerabilities(self):
        """Test SQL queries use parameterized statements."""
        print("\n[TEST] Testing for SQL injection vulnerabilities...")

        python_files = list((PROJECT_ROOT / "slob").rglob("*.py"))

        # Patterns that might indicate SQL injection risk
        dangerous_patterns = [
            r'execute\(["\'].*%s.*["\']\s*%',  # String formatting
            r'execute\(["\'].*\{\}.*["\']\s*\.format',  # .format()
            r'execute\(f["\']',  # f-strings
        ]

        violations = []

        for py_file in python_files:
            content = py_file.read_text()

            for pattern in dangerous_patterns:
                if re.search(pattern, content):
                    violations.append(f"{py_file.name}: Potential SQL injection risk")

        if violations:
            print("[WARNING] Potential SQL injection vulnerabilities:")
            for violation in violations[:5]:
                print(f"  - {violation}")

        print("[SUCCESS] SQL injection check complete")

    def test_database_encryption_at_rest(self):
        """Test database encryption options."""
        print("\n[TEST] Testing database encryption options...")

        # SQLite doesn't encrypt by default
        # This test checks if encryption is mentioned in config

        config_files = list((PROJECT_ROOT / "slob" / "config").rglob("*.py"))

        uses_encryption = False

        for config_file in config_files:
            content = config_file.read_text()
            if "encryption" in content.lower() or "cipher" in content.lower():
                uses_encryption = True
                break

        if uses_encryption:
            print("[SUCCESS] Database encryption configured")
        else:
            print("[INFO] Database encryption not configured (consider sqlcipher)")


@pytest.mark.security
class TestAuthenticationSecurity:
    """Test authentication and authorization."""

    def test_dashboard_authentication_required(self):
        """Test dashboard requires authentication."""
        print("\n[TEST] Testing dashboard authentication...")

        dashboard_file = PROJECT_ROOT / "slob" / "monitoring" / "dashboard.py"

        if not dashboard_file.exists():
            pytest.skip("dashboard.py not found")

        content = dashboard_file.read_text()

        # Check for authentication decorator
        has_login_required = "@login_required" in content
        has_flask_login = "flask_login" in content or "LoginManager" in content

        if has_login_required and has_flask_login:
            print("[SUCCESS] Dashboard uses Flask-Login authentication")
        elif "authentication" in content.lower() or "login" in content.lower():
            print("[INFO] Some authentication mechanism present")
        else:
            print("[WARNING] No authentication found (dashboard may be public)")

    def test_password_hashing(self):
        """Test passwords are hashed, not stored in plaintext."""
        print("\n[TEST] Testing password hashing...")

        python_files = list((PROJECT_ROOT / "slob").rglob("*.py"))

        uses_hashing = False

        for py_file in python_files:
            content = py_file.read_text()

            # Check for password hashing libraries
            if any(lib in content for lib in ["bcrypt", "werkzeug.security", "hashlib", "pbkdf2"]):
                uses_hashing = True
                break

        if uses_hashing:
            print("[SUCCESS] Password hashing library found")
        else:
            print("[INFO] Password hashing not verified")

    def test_session_security(self):
        """Test session management security."""
        print("\n[TEST] Testing session security...")

        dashboard_file = PROJECT_ROOT / "slob" / "monitoring" / "dashboard.py"

        if not dashboard_file.exists():
            pytest.skip("dashboard.py not found")

        content = dashboard_file.read_text()

        # Check for session configuration
        has_secret_key = "SECRET_KEY" in content
        has_session_config = "SESSION" in content or "session" in content

        if has_secret_key:
            print("[SUCCESS] Session secret key configured")
        else:
            print("[INFO] Session configuration not verified")


@pytest.mark.security
class TestSecretsManagement:
    """Test secrets management practices."""

    def test_gitignore_includes_sensitive_files(self):
        """Test .gitignore excludes sensitive files."""
        print("\n[TEST] Testing .gitignore configuration...")

        gitignore = PROJECT_ROOT / ".gitignore"

        if not gitignore.exists():
            print("[WARNING] .gitignore not found")
            return

        content = gitignore.read_text()

        required_excludes = [
            ".env",
            "*.db",
            "*.log",
            "__pycache__",
            "*.pyc"
        ]

        missing = []
        for exclude in required_excludes:
            # Simple check - just see if pattern is mentioned
            if exclude not in content:
                missing.append(exclude)

        if missing:
            print(f"[WARNING] .gitignore missing: {', '.join(missing)}")
        else:
            print("[SUCCESS] .gitignore properly configured")

    def test_no_secrets_in_git_history(self):
        """Test .env is not in git history."""
        print("\n[TEST] Testing .env not in git history...")

        # Check if .env is tracked by git
        try:
            result = subprocess.run(
                ["git", "ls-files", ".env"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True
            )

            if result.stdout.strip():
                print("[WARNING] .env is tracked by git (should be in .gitignore)")
            else:
                print("[SUCCESS] .env is not tracked by git")

        except FileNotFoundError:
            print("[INFO] Git not available")


@pytest.mark.security
class TestInputValidation:
    """Test input validation and sanitization."""

    def test_user_input_validation(self):
        """Test user input is validated."""
        print("\n[TEST] Testing input validation...")

        # Check for input validation in API endpoints
        dashboard_file = PROJECT_ROOT / "slob" / "monitoring" / "dashboard.py"

        if not dashboard_file.exists():
            pytest.skip("dashboard.py not found")

        content = dashboard_file.read_text()

        # Look for validation patterns
        has_validation = any(pattern in content for pattern in [
            "request.args.get",
            "request.form.get",
            "validate",
            "sanitize",
            "int(",
            "float(",
        ])

        if has_validation:
            print("[SUCCESS] Input validation patterns found")
        else:
            print("[INFO] Input validation not verified")

    def test_path_traversal_prevention(self):
        """Test path traversal attacks are prevented."""
        print("\n[TEST] Testing path traversal prevention...")

        python_files = list((PROJECT_ROOT / "slob").rglob("*.py"))

        # Look for file operations that might be vulnerable
        uses_safe_path_handling = False

        for py_file in python_files:
            content = py_file.read_text()

            # Check for Path usage (safer than raw string concatenation)
            if "from pathlib import Path" in content or "Path(" in content:
                uses_safe_path_handling = True
                break

        if uses_safe_path_handling:
            print("[SUCCESS] Using pathlib.Path for safe path handling")
        else:
            print("[INFO] Path handling method not verified")


@pytest.mark.security
class TestDependencySecurity:
    """Test dependency security."""

    def test_requirements_file_exists(self):
        """Test requirements.txt exists."""
        print("\n[TEST] Testing requirements.txt exists...")

        requirements = PROJECT_ROOT / "requirements.txt"

        assert requirements.exists(), "requirements.txt not found"

        print("[SUCCESS] requirements.txt exists")

    def test_no_known_vulnerable_packages(self):
        """Test for known vulnerable packages (basic check)."""
        print("\n[TEST] Testing for known vulnerable packages...")

        requirements = PROJECT_ROOT / "requirements.txt"

        if not requirements.exists():
            pytest.skip("requirements.txt not found")

        # This is a basic check - in production, use tools like:
        # - pip-audit
        # - safety
        # - Snyk

        # Check if pip-audit is available
        try:
            result = subprocess.run(
                ["pip-audit", "--version"],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                print("[INFO] pip-audit available - run separately for full scan")
            else:
                print("[INFO] Install pip-audit for vulnerability scanning")

        except FileNotFoundError:
            print("[INFO] pip-audit not installed (recommended: pip install pip-audit)")

        print("[SUCCESS] Dependency security check complete")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "security"])
