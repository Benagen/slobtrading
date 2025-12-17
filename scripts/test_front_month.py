"""Test front month resolution."""

import asyncio
from ib_insync import IB, Future

async def main():
    ib = IB()
    await ib.connectAsync('127.0.0.1', 4002, clientId=997, readonly=True)

    # Get all NQ contracts
    nq = Future('NQ', exchange='CME')
    details = await ib.reqContractDetailsAsync(nq)

    print(f"Found {len(details)} NQ contracts:")
    print()

    # Sort by expiry
    details = sorted(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)

    for i, d in enumerate(details[:10]):  # Show first 10
        c = d.contract
        print(f"{i+1}. {c.localSymbol:10} Expiry: {c.lastTradeDateOrContractMonth}  ConId: {c.conId}")

    print()
    print(f"✅ Front month (closest expiry): {details[0].contract.localSymbol}")
    print(f"   Expiry: {details[0].contract.lastTradeDateOrContractMonth}")

    ib.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
