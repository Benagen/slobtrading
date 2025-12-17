#!/bin/bash

# Test Runner Script for SLOB Trading System
# Usage: ./scripts/run_tests.sh [options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================="
echo "SLOB Trading System - Test Runner"
echo "=================================="
echo ""

# Parse command line arguments
TEST_TYPE="${1:-all}"
COVERAGE="${2:-no}"

# Function to run tests
run_tests() {
    local test_path=$1
    local test_name=$2

    echo -e "${YELLOW}Running $test_name...${NC}"

    if [ "$COVERAGE" = "coverage" ]; then
        pytest "$test_path" --cov=slob --cov-report=html --cov-report=term-missing -v
    else
        pytest "$test_path" -v
    fi

    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✓ $test_name PASSED${NC}"
    else
        echo -e "${RED}✗ $test_name FAILED${NC}"
        return $exit_code
    fi

    echo ""
}

# Main test execution
case $TEST_TYPE in
    "unit")
        echo "Running unit tests only..."
        run_tests "tests/live/" "Unit Tests"
        ;;

    "integration")
        echo "Running integration tests only..."
        run_tests "tests/integration/" "Integration Tests"
        ;;

    "alpaca")
        echo "Running AlpacaWSFetcher tests..."
        run_tests "tests/live/test_alpaca_ws_fetcher.py" "AlpacaWSFetcher Tests"
        ;;

    "buffer")
        echo "Running TickBuffer tests..."
        run_tests "tests/live/test_tick_buffer.py" "TickBuffer Tests"
        ;;

    "aggregator")
        echo "Running CandleAggregator tests..."
        run_tests "tests/live/test_candle_aggregator.py" "CandleAggregator Tests"
        ;;

    "eventbus")
        echo "Running EventBus tests..."
        run_tests "tests/live/test_event_bus.py" "EventBus Tests"
        ;;

    "store")
        echo "Running CandleStore tests..."
        run_tests "tests/live/test_candle_store.py" "CandleStore Tests"
        ;;

    "all"|*)
        echo "Running all tests..."
        run_tests "tests/" "All Tests"
        ;;
esac

# Show coverage report if requested
if [ "$COVERAGE" = "coverage" ]; then
    echo ""
    echo -e "${YELLOW}Coverage report generated in htmlcov/index.html${NC}"
    echo "Open it with: open htmlcov/index.html (macOS) or xdg-open htmlcov/index.html (Linux)"
fi

echo ""
echo "=================================="
echo -e "${GREEN}Tests completed successfully!${NC}"
echo "=================================="
