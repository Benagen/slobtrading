"""
Interactive Brokers Configuration

Configuration for IB paper/live trading connection.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class IBConfig:
    """
    Interactive Brokers configuration.

    Connection settings for IB Gateway or TWS.

    Default Ports:
    - TWS Paper Trading: 7497
    - TWS Live Trading: 7496
    - IB Gateway Paper: 4002
    - IB Gateway Live: 4001
    """

    # Connection
    host: str = '127.0.0.1'
    port: int = 7497  # Default: TWS paper trading
    client_id: int = 1  # Unique ID (1-999)

    # Account
    account: Optional[str] = None  # Paper: DU123456, Live: U123456
    paper_trading: bool = True

    # Connection settings
    timeout: int = 10
    max_reconnect_attempts: int = 10
    reconnect_delay_seconds: int = 5

    # Market data
    data_type: str = 'realtime'  # 'realtime', 'delayed' (15min free), 'frozen'

    # Symbols
    symbols: list = None

    def __post_init__(self):
        """Initialize default symbols."""
        if self.symbols is None:
            self.symbols = ['NQ']  # Default to NQ futures

    @classmethod
    def paper_trading_config(cls, account: str, client_id: int = 1) -> 'IBConfig':
        """
        Create paper trading configuration.

        Args:
            account: Paper trading account (DU number)
            client_id: Unique client ID

        Returns:
            IBConfig for paper trading
        """
        return cls(
            host='127.0.0.1',
            port=7497,  # TWS paper
            client_id=client_id,
            account=account,
            paper_trading=True,
            symbols=['NQ']
        )

    @classmethod
    def live_trading_config(cls, account: str, client_id: int = 1) -> 'IBConfig':
        """
        Create live trading configuration.

        Args:
            account: Live trading account (U number)
            client_id: Unique client ID

        Returns:
            IBConfig for live trading
        """
        return cls(
            host='127.0.0.1',
            port=7496,  # TWS live
            client_id=client_id,
            account=account,
            paper_trading=False,
            symbols=['NQ']
        )

    @classmethod
    def gateway_paper_config(cls, account: str, client_id: int = 1) -> 'IBConfig':
        """
        Create IB Gateway paper trading configuration.

        Args:
            account: Paper trading account (DU number)
            client_id: Unique client ID

        Returns:
            IBConfig for IB Gateway paper trading
        """
        return cls(
            host=os.getenv('IB_GATEWAY_HOST', '127.0.0.1'),
            port=int(os.getenv('IB_GATEWAY_PORT', '4002')),  # Gateway paper
            client_id=client_id,
            account=account,
            paper_trading=True,
            symbols=['NQ']
        )

    @classmethod
    def gateway_live_config(cls, account: str, client_id: int = 1) -> 'IBConfig':
        """
        Create IB Gateway live trading configuration.

        Args:
            account: Live trading account (U number)
            client_id: Unique client ID

        Returns:
            IBConfig for IB Gateway live trading
        """
        return cls(
            host='127.0.0.1',
            port=4001,  # Gateway live
            client_id=client_id,
            account=account,
            paper_trading=False,
            symbols=['NQ']
        )

    def validate(self):
        """
        Validate configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        if self.port not in [7497, 7496, 4002, 4001]:
            raise ValueError(
                f"Invalid port {self.port}. Must be 7497 (TWS paper), "
                f"7496 (TWS live), 4002 (Gateway paper), or 4001 (Gateway live)"
            )

        if not 1 <= self.client_id <= 999:
            raise ValueError(f"client_id must be 1-999, got {self.client_id}")

        if self.paper_trading and self.account and not self.account.startswith('DU'):
            raise ValueError(
                f"Paper trading account should start with 'DU', got {self.account}"
            )

        if not self.paper_trading and self.account and not self.account.startswith('U'):
            raise ValueError(
                f"Live trading account should start with 'U', got {self.account}"
            )

    def __str__(self) -> str:
        """String representation."""
        mode = "PAPER" if self.paper_trading else "LIVE"
        return (
            f"IBConfig({mode} | {self.host}:{self.port} | "
            f"client_id={self.client_id} | account={self.account})"
        )


# Example configurations
EXAMPLE_PAPER_CONFIG = IBConfig(
    host='127.0.0.1',
    port=7497,
    client_id=1,
    account='DU123456',
    paper_trading=True,
    symbols=['NQ']
)

EXAMPLE_GATEWAY_PAPER_CONFIG = IBConfig(
    host='127.0.0.1',
    port=4002,
    client_id=1,
    account='DU123456',
    paper_trading=True,
    symbols=['NQ']
)
