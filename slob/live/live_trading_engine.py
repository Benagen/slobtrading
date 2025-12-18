
"""
Live Trading Engine
"""
import asyncio
import logging
from typing import List, Optional, Any
from datetime import datetime

from .alpaca_ws_fetcher import AlpacaWSFetcher, Tick
from .tick_buffer import TickBuffer
from .candle_aggregator import CandleAggregator, Candle
from .event_bus import EventBus, EventType
from .candle_store import CandleStore

# Week 2 components
from .setup_tracker import SetupTracker, SetupTrackerConfig
from .state_manager import StateManager, StateManagerConfig
from .order_executor import OrderExecutor, OrderExecutorConfig
from .setup_state import SetupCandidate, SetupState

# --- DIREKT IMPORT (INGEN TRY-EXCEPT SOM DÖLJER FEL) ---
from .ib_ws_fetcher import IBWSFetcher
IB_AVAILABLE = True
# -------------------------------------------------------

class LiveTradingEngineConfig:
    """Configuration that accepts ANYTHING via kwargs."""
    def __init__(self, **kwargs):
        # Defaults
        self.ib_host = "127.0.0.1"
        self.ib_port = 4002
        self.client_id = 1
        self.account = ""
        self.risk_per_trade = 0.01
        self.max_position_size = 5
        self.symbol = "NQ"
        
        # Strategy Defaults
        self.consol_max_range_pips = 20.0
        self.consol_min_duration_minutes = 15
        self.sl_buffer_pips = 1.0
        self.tp_risk_reward = 2.0
        self.bar_size = "1 min"
        
        # Apply overrides
        for key, value in kwargs.items():
            setattr(self, key, value)

class LiveTradingEngine:
    def __init__(self, config: LiveTradingEngineConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.tasks = []
        self.started_at = None
        
        # Initialize Components
        self.event_bus = EventBus()
        self.tick_buffer = TickBuffer()
        self.candle_aggregator = CandleAggregator(on_candle_complete=self._on_candle_complete)
        self.candle_store = CandleStore()
        self.state_manager = StateManager(StateManagerConfig(sqlite_path="data/trading_state.db"))
        
        # Setup Tracker
        tracker_config = SetupTrackerConfig(
            symbol=config.symbol,
            consol_max_range_pips=getattr(config, 'consol_max_range_pips', 20.0),
            consol_min_duration=getattr(config, 'consol_min_duration_minutes', 15),
            sl_buffer_pips=getattr(config, 'sl_buffer_pips', 1.0)
        )
        self.setup_tracker = SetupTracker(tracker_config)
        
        # Order Executor
        executor_config = OrderExecutorConfig(
            ib_host=config.ib_host,
            ib_port=config.ib_port,
            client_id=config.client_id,
            account=config.account,
            max_position_size=config.max_position_size
        )
        self.order_executor = OrderExecutor(executor_config)
        self.ws_fetcher = None
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        self.event_bus.subscribe(EventType.CANDLE_COMPLETED, self.candle_store.save_candle)

    async def _on_candle_complete(self, candle: Candle):
        await self.event_bus.emit(EventType.CANDLE_COMPLETED, candle)
        self.candle_store.save_candle(candle)
        
        candle_dict = {
            'timestamp': candle.timestamp,
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume
        }
        await self.setup_tracker.on_candle(candle_dict)
        
        for setup in self.setup_tracker.completed_setups:
            await self._handle_setup_found({'setup': setup})

    async def _handle_setup_found(self, data: dict):
        setup = data.get('setup')
        if not setup: return
        self.logger.info(f"⚡ SETUP FOUND: {setup.id} | Entry: {setup.entry_price}")

        # Calculate position size using RiskManager
        position_size = self.order_executor.calculate_position_size(
            entry_price=setup.entry_price,
            stop_loss_price=setup.sl_price,
            atr=getattr(setup, 'atr', None)  # Use ATR if available
        )

        self.logger.info(f"Position size: {position_size} contracts")
        await self.order_executor.place_bracket_order(setup, position_size)

    async def initialize(self):
        """Connects to IB and sets up fetcher."""
        self.started_at = datetime.now()
        self.logger.info(f"🚀 Initializing Engine for {self.config.symbol} on port {self.config.ib_port}")
        
        # DIRECT LOGIC - NO CHECKS
        self.ws_fetcher = IBWSFetcher(
            host=self.config.ib_host, 
            port=self.config.ib_port, 
            client_id=self.config.client_id + 1,
            account=self.config.account
        )
        
        async def on_tick_bridge(tick):
             await self.tick_buffer.enqueue(tick)
             await self.candle_aggregator.process_tick(tick)
        
        self.ws_fetcher.on_tick = on_tick_bridge
        
        # Connect
        await self.ws_fetcher.connect()
        await self.ws_fetcher.subscribe([self.config.symbol])
        
        # Initialize Executor too
        if hasattr(self.order_executor, 'initialize'):
             await self.order_executor.initialize()
              
        self.running = True

    async def run(self):
        """Main blocking loop."""
        if not self.running:
            await self.initialize()
            
        self.logger.info("🟢 Engine loop started. Waiting for market data...")
        
        # Health monitor loop
        while self.running:
            await asyncio.sleep(60) # Log status every minute
            self.logger.info("💓 Engine heartbeat - Running...")

    async def start(self):
        await self.run()

    async def shutdown(self):
        self.running = False
        self.logger.info("🛑 Shutting down Engine...")
        if self.ws_fetcher:
            await self.ws_fetcher.disconnect()
        if self.order_executor and hasattr(self.order_executor, 'close'):
            await self.order_executor.close()

    async def stop(self):
        await self.shutdown()
