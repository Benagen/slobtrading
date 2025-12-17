"""Debug IB ticker to see what data we're actually receiving."""

import asyncio
from ib_insync import IB, Future, util

async def main():
    ib = IB()

    try:
        print("Connecting to IB...")
        await ib.connectAsync('127.0.0.1', 4002, clientId=998, readonly=True, timeout=5)
        print("✅ Connected")

        # Resolve NQ
        print("\nResolving NQ contract...")
        nq = Future('NQ', exchange='CME')
        details = await ib.reqContractDetailsAsync(nq)
        contract = details[0].contract
        print(f"✅ Contract: {contract.localSymbol}")

        # Request delayed data
        print("\nRequesting delayed market data...")
        ib.reqMarketDataType(3)  # Delayed

        ticker = ib.reqMktData(contract, '', False, False)

        print(f"\nWaiting for tick updates (30 seconds)...")
        print(f"Initial ticker state:")
        print(f"  bid: {ticker.bid}")
        print(f"  ask: {ticker.ask}")
        print(f"  last: {ticker.last}")
        print(f"  time: {ticker.time}")

        # Monitor for 30 seconds
        for i in range(30):
            await asyncio.sleep(1)

            # Check if anything changed
            if ticker.bid or ticker.ask or ticker.last:
                print(f"\n[{i+1}s] Ticker update:")
                print(f"  bid: {ticker.bid}")
                print(f"  ask: {ticker.ask}")
                print(f"  last: {ticker.last}")
                print(f"  lastSize: {ticker.lastSize}")
                print(f"  time: {ticker.time}")

        print(f"\nFinal ticker state:")
        print(f"  bid: {ticker.bid}")
        print(f"  ask: {ticker.ask}")
        print(f"  last: {ticker.last}")
        print(f"  time: {ticker.time}")

    finally:
        ib.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
