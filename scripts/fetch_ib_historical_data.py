"""
Fetch Historical Data from Interactive Brokers

Fetches NQ futures 5-minute bars for backtesting validation.

Usage:
    python scripts/fetch_ib_historical_data.py --months 6
    python scripts/fetch_ib_historical_data.py --months 12 --output data/nq_12mo.csv
"""

import asyncio
import sys
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from ib_insync import IB, Future, util

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def fetch_historical_data(
    months: int = 6,
    bar_size: str = '5 mins',
    host: str = '127.0.0.1',
    port: int = 4002,
    output_file: str = None,
    verbose: bool = True
):
    """
    Fetch historical NQ futures data from IB.

    Args:
        months: Number of months of historical data
        bar_size: Bar size ('5 mins', '1 min', '15 mins', etc.)
        host: IB Gateway host
        port: IB Gateway port (4002 for paper, 4001 for live)
        output_file: Optional output CSV file
        verbose: Print progress

    Returns:
        DataFrame with OHLCV data
    """
    ib = IB()

    try:
        if verbose:
            print(f"\n{'='*80}")
            print(f"FETCHING IB HISTORICAL DATA")
            print(f"{'='*80}\n")
            print(f"Connecting to IB at {host}:{port}...")

        # Connect to IB
        await ib.connectAsync(host, port, clientId=999, timeout=20)

        if not ib.isConnected():
            raise ConnectionError("Failed to connect to IB")

        if verbose:
            print(f"✅ Connected successfully")
            accounts = ib.managedAccounts()
            print(f"   Accounts: {accounts}")

        # Request delayed market data (Type 3 - free)
        ib.reqMarketDataType(3)

        # Resolve NQ front month contract
        if verbose:
            print(f"\nResolving NQ futures contract...")

        nq = Future('NQ', exchange='CME')
        details = await ib.reqContractDetailsAsync(nq)

        if not details:
            raise ValueError("No NQ contract found. Check futures permissions.")

        # Sort by expiry and get front month
        details = sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)
        contract = details[0].contract

        if verbose:
            print(f"✅ Contract resolved: {contract.localSymbol}")
            print(f"   Expiry: {contract.lastTradeDateOrContractMonth}")
            print(f"   Exchange: {contract.exchange}")

        # Calculate date ranges
        end_date = datetime.now()

        # IB limitation: Can't request more than 365 days at once for intraday
        # So we'll chunk the requests if needed
        chunk_days = min(60, months * 30)  # Request in 60-day chunks max
        total_days = months * 30

        all_bars = []
        current_end = end_date

        chunks_needed = (total_days + chunk_days - 1) // chunk_days

        if verbose:
            print(f"\nFetching {months} months ({total_days} days) of {bar_size} bars...")
            print(f"Using {chunks_needed} chunk(s) of ~{chunk_days} days each\n")

        for chunk in range(chunks_needed):
            chunk_start = current_end - timedelta(days=chunk_days)

            # For last chunk, adjust to get exact months
            if chunk == chunks_needed - 1:
                chunk_start = end_date - timedelta(days=total_days)

            if verbose:
                print(f"  Chunk {chunk + 1}/{chunks_needed}: {chunk_start.date()} to {current_end.date()}")

            try:
                # Request historical bars
                bars = await ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime=current_end,
                    durationStr=f'{chunk_days} D',
                    barSizeSetting=bar_size,
                    whatToShow='TRADES',
                    useRTH=False,  # Include extended hours
                    formatDate=1,
                    keepUpToDate=False
                )

                if bars:
                    all_bars.extend(bars)
                    if verbose:
                        print(f"    ✅ Received {len(bars)} bars")
                else:
                    if verbose:
                        print(f"    ⚠️  No bars received")

                # Move to next chunk
                current_end = chunk_start

                # Rate limiting - IB has request limits
                if chunk < chunks_needed - 1:
                    await asyncio.sleep(2)  # 2 second pause between chunks

            except Exception as e:
                print(f"    ❌ Error fetching chunk: {e}")
                if "No market data permissions" in str(e):
                    print("\n⚠️  Market data permissions issue!")
                    print("   Solution: IB Gateway → Configure → Settings → Market Data → Subscribe to delayed data")
                    raise
                continue

        if not all_bars:
            raise ValueError("No historical data received from IB")

        # Convert to DataFrame
        if verbose:
            print(f"\n{'='*80}")
            print(f"Processing {len(all_bars)} total bars...")

        df = util.df(all_bars)

        # Rename columns to match our format
        df = df.rename(columns={
            'date': 'Date',
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        })

        # Set index
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')

        # Keep only OHLCV
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

        # Drop duplicates and sort
        df = df[~df.index.duplicated(keep='first')]
        df = df.sort_index()

        # Remove any NaN rows
        df = df.dropna()

        # Calculate wick columns (required by SetupFinder)
        df['Body_Pips'] = abs(df['Close'] - df['Open'])
        df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
        df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']
        df['Range_Pips'] = df['High'] - df['Low']

        if verbose:
            print(f"✅ Data processed successfully")
            print(f"\n{'='*80}")
            print(f"HISTORICAL DATA SUMMARY")
            print(f"{'='*80}\n")
            print(f"Total bars:     {len(df)}")
            print(f"Date range:     {df.index[0]} to {df.index[-1]}")
            print(f"Actual days:    {(df.index[-1] - df.index[0]).days}")
            print(f"Price range:    {df['Low'].min():.2f} - {df['High'].max():.2f}")
            print(f"Average volume: {df['Volume'].mean():.0f}")
            print(f"\nFirst 5 bars:")
            print(df.head())
            print(f"\nLast 5 bars:")
            print(df.tail())

        # Save to file if specified
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path)
            if verbose:
                print(f"\n✅ Data saved to: {output_path}")

        return df

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

    finally:
        if ib.isConnected():
            ib.disconnect()
            if verbose:
                print(f"\nDisconnected from IB")


def main():
    parser = argparse.ArgumentParser(description='Fetch historical data from IB')
    parser.add_argument('--months', type=int, default=6, help='Months of historical data (default: 6)')
    parser.add_argument('--bar-size', type=str, default='5 mins', help='Bar size (default: 5 mins)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='IB Gateway host')
    parser.add_argument('--port', type=int, default=4002, help='IB Gateway port (4002=paper, 4001=live)')
    parser.add_argument('--output', type=str, default='data/nq_historical.csv', help='Output CSV file')
    parser.add_argument('--quiet', action='store_true', help='Suppress output')

    args = parser.parse_args()

    print("\n⚠️  REQUIREMENTS:")
    print("  1. IB Gateway or TWS must be running")
    print("  2. Logged in (paper trading account recommended)")
    print("  3. API enabled in settings")
    print("  4. Market data subscription (delayed data is free)")
    print("\nPress Enter to continue...")
    input()

    try:
        df = asyncio.run(fetch_historical_data(
            months=args.months,
            bar_size=args.bar_size,
            host=args.host,
            port=args.port,
            output_file=args.output,
            verbose=not args.quiet
        ))

        print(f"\n{'='*80}")
        print(f"✅ SUCCESS! Historical data fetched")
        print(f"{'='*80}")
        print(f"\nNext steps:")
        print(f"  1. Run backtest with IB data:")
        print(f"     python scripts/run_backtest_with_ib_data.py --input {args.output}")
        print(f"\n  2. Or train model:")
        print(f"     python scripts/train_model_with_ib_data.py --input {args.output}")
        print(f"\n")

        return 0

    except Exception as e:
        print(f"\n{'='*80}")
        print(f"❌ FAILED to fetch historical data")
        print(f"{'='*80}")
        print(f"\nError: {e}")
        print(f"\nTroubleshooting:")
        print(f"  • Verify IB Gateway is running")
        print(f"  • Check port (4002 for paper, 4001 for live)")
        print(f"  • Enable API in Global Configuration → API → Settings")
        print(f"  • Subscribe to delayed market data (free)")
        print(f"\n")
        return 1


if __name__ == '__main__':
    sys.exit(main())
