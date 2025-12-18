
import asyncio
import logging
import math # För att kolla efter NaN
from typing import List, Callable, Optional, Any
from datetime import datetime

# Importera biblioteket direkt
from ib_insync import IB, Stock, Future, Forex, Contract, Ticker

class Tick:
    """
    Enkel Tick-klass.
    Fixar buggen genom att ha både .volume och .size som synonymer.
    """
    def __init__(self, symbol: str, price: float, timestamp: datetime, volume: int = 0):
        self.symbol = symbol
        self.price = price
        self.timestamp = timestamp
        self.volume = volume
        self.size = volume # <-- FIX: CandleAggregator vill ha .size

class IBWSFetcher:
    """
    Hämtar data från Interactive Brokers.
    """
    def __init__(self, host='127.0.0.1', port=4002, client_id=1, account=''):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.account = account
        self.ib = None
        self.connected = False
        self.subscriptions = []
        self.on_tick: Optional[Callable[[Tick], Any]] = None
        self.logger = logging.getLogger(__name__)

    async def connect(self):
        """Connect to IB Gateway/TWS."""
        self.ib = IB()
        try:
            self.logger.info(f"Connecting to IB at {self.host}:{self.port}")
            await self.ib.connectAsync(self.host, self.port, self.client_id)
            self.connected = True
            
            # Request Delayed Data (Type 3)
            self.ib.reqMarketDataType(3) 
            self.logger.info("✅ Requested Market Data Type 3 (Delayed/Frozen)")
            
            self.logger.info(f"✅ Successfully connected to IB (clientId={self.client_id})")
        except Exception as e:
            self.logger.error(f"Failed to connect to IB: {e}")
            self.connected = False

    async def subscribe(self, symbols: List[str]):
        if not self.connected:
            return

        for symbol in symbols:
            try:
                contract = None
                if symbol == "NQ":
                    nq = Future(symbol='NQ', exchange='CME', currency='USD')
                    details = await self.ib.reqContractDetailsAsync(nq)
                    if not details: continue
                    details = sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)
                    contract = details[0].contract
                    await self.ib.qualifyContractsAsync(contract)
                    self.logger.info(f"Resolved NQ to {contract.localSymbol}")
                else:
                    contract = Stock(symbol, 'SMART', 'USD')
                    await self.ib.qualifyContractsAsync(contract)

                if contract:
                    self.ib.reqMktData(contract, '', False, False)
                    self.subscriptions.append(contract)
                    self.logger.info(f"✅ Subscribed to: {symbol}")

            except Exception as e:
                self.logger.error(f"Subscription failed for {symbol}: {e}")

        self.ib.pendingTickersEvent += self._on_ib_tick

    def _on_ib_tick(self, tickers):
        for ticker in tickers:
            try:
                # Hämta pris
                price = ticker.last if ticker.last and ticker.last > 0 else ticker.close
                
                if (price is None or price != price) and hasattr(ticker, 'delayedLast'):
                     price = ticker.delayedLast
                
                if (price is None or price != price): 
                     if ticker.bid and ticker.ask:
                         price = (ticker.bid + ticker.ask) / 2
                
                # FIX: Hantera volym som kan vara NaN
                vol = 0
                if ticker.volume and not math.isnan(ticker.volume):
                    vol = int(ticker.volume)
                
                if price and price == price: 
                    t = Tick(
                        symbol="NQ", 
                        price=float(price),
                        timestamp=ticker.time if ticker.time else datetime.now(),
                        volume=vol
                    )
                    if self.on_tick:
                        asyncio.create_task(self.on_tick(t))
            except Exception as e:
                # Logga felet men krascha inte hela loopen
                self.logger.error(f"Error processing tick: {e}")

    async def disconnect(self):
        if self.ib:
            self.ib.disconnect()
            self.connected = False
