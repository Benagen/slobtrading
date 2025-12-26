#!/bin/bash
#
# Health Check Shell Wrapper
#
# Calls Python health check script and returns proper exit code.
# This wrapper is referenced by deploy.sh and monitoring scripts.
#
# Exit codes:
# - 0: All health checks passed
# - 1: One or more health checks failed

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Call the Python health check script
python3 "${SCRIPT_DIR}/health_check.py" "$@"

# Capture and return the exit code
exit $?
