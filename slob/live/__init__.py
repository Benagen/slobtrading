"""
Live trading module for 5/1 SLOB system.

Provides real-time trading capabilities with:
- Alpaca WebSocket data streaming
- Event-driven state machine for setup tracking
- Order execution and position management
- State persistence (Redis + SQLite)
"""

__version__ = "0.1.0"
