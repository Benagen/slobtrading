"""
Live trading module for 5/1 SLOB system.

Provides real-time trading capabilities with:
- Interactive Brokers WebSocket data streaming (via ib_insync)
- Event-driven state machine for setup tracking
- Order execution and position management
- State persistence (Redis + SQLite)
"""

__version__ = "0.1.0"
