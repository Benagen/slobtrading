"""
Quick IB Connection Test

Tests basic IB connectivity before running full checkpoint test.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ib_insync import IB, util


async def test_connection():
    """Test IB connection."""
    print("=" * 60)
    print("IB CONNECTION TEST")
    print("=" * 60)

    ib = IB()

    try:
        print("\n1. Attempting to connect to IB...")
        print("   Host: 127.0.0.1")
        print("   Port: 4002 (IB Gateway paper trading)")
        print("   Client ID: 999")

        await ib.connectAsync('127.0.0.1', 4002, clientId=999, timeout=10)

        if ib.isConnected():
            print("   ✅ Connected successfully!")

            # Get account info
            print("\n2. Account information:")
            accounts = ib.managedAccounts()
            print(f"   Accounts: {accounts}")

            if accounts:
                account = accounts[0]
                print(f"   Using account: {account}")

                # Test NQ contract resolution
                print("\n3. Testing NQ futures contract resolution...")
                from ib_insync import Future

                nq = Future('NQ', exchange='CME')
                details = await ib.reqContractDetailsAsync(nq)

                if details:
                    contract = details[0].contract
                    print(f"   ✅ NQ contract found!")
                    print(f"   Symbol: {contract.localSymbol}")
                    print(f"   Expiry: {contract.lastTradeDateOrContractMonth}")
                    print(f"   Exchange: {contract.exchange}")
                    print(f"   Contract ID: {contract.conId}")

                    # Test market data subscription
                    print("\n4. Testing market data subscription...")
                    ticker = ib.reqMktData(contract, '', False, False)

                    print("   Waiting for tick data (5 seconds)...")
                    await asyncio.sleep(5)

                    if ticker.last and ticker.last > 0:
                        print(f"   ✅ Receiving market data!")
                        print(f"   Last price: {ticker.last}")
                        print(f"   Last size: {ticker.lastSize}")
                        print(f"   Time: {ticker.time}")
                    else:
                        print("   ⚠️  No tick data received yet")
                        print("   (This is normal if market is closed)")
                        print("   Or check CME market data subscription")

                    ib.cancelMktData(contract)

                else:
                    print("   ❌ NQ contract not found")
                    print("   Check futures permissions")

            print("\n" + "=" * 60)
            print("✅ CONNECTION TEST PASSED")
            print("=" * 60)
            print("\nReady to run full checkpoint test:")
            print(f"  python scripts/ib_checkpoint_test.py 60 {accounts[0] if accounts else 'DU123456'}")
            print("")

        else:
            print("   ❌ Connection failed")
            return False

    except asyncio.TimeoutError:
        print("\n❌ CONNECTION TIMEOUT")
        print("\nPossible issues:")
        print("  1. TWS or IB Gateway not running")
        print("  2. Wrong port (7497 for TWS paper, 4002 for Gateway paper)")
        print("  3. API not enabled in TWS settings")
        print("\nPlease check:")
        print("  • TWS/Gateway is running")
        print("  • Logged in with paper trading account (DU)")
        print("  • API enabled: File → Global Configuration → API → Settings")
        return False

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print("\nCommon solutions:")
        print("  • Restart TWS/Gateway")
        print("  • Check port number (7497 vs 4002)")
        print("  • Verify API settings enabled")
        return False

    finally:
        if ib.isConnected():
            ib.disconnect()
            print("Disconnected from IB")

    return True


if __name__ == "__main__":
    print("\n⚠️  Before running this test:")
    print("  1. Start TWS or IB Gateway")
    print("  2. Login with paper trading account (DU number)")
    print("  3. Enable API in settings (if not already)")
    print("\nPress Enter to continue...")
    input()

    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)
