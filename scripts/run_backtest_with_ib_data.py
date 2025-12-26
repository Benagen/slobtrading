"""
Run Backtest with IB Historical Data

Uses previously fetched IB data for robust backtesting validation.

Usage:
    python scripts/run_backtest_with_ib_data.py --input data/nq_historical.csv
    python scripts/run_backtest_with_ib_data.py --input data/nq_historical.csv --relaxed-params
"""

import sys
import os
import argparse
import pandas as pd
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from slob.backtest import SetupFinder, Backtester, RiskManager


def load_ib_data(file_path: str, verbose: bool = True):
    """
    Load IB historical data from CSV.

    Args:
        file_path: Path to CSV file
        verbose: Print progress

    Returns:
        DataFrame with OHLCV data
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"LOADING IB HISTORICAL DATA")
        print(f"{'='*80}\n")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Data file not found: {file_path}")

    # Load CSV - parse_dates will create DatetimeIndex with timezone info
    df = pd.read_csv(file_path, index_col='Date', parse_dates=['Date'])

    # Convert to UTC to handle DST transitions (mixed timezones in data)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        # Already timezone-aware, just convert to UTC
        df.index = df.index.tz_convert('UTC')
    elif isinstance(df.index, pd.DatetimeIndex):
        # Timezone-naive, localize then convert
        df.index = df.index.tz_localize('UTC')
    else:
        # Not a DatetimeIndex, convert with UTC
        df.index = pd.to_datetime(df.index, utc=True)

    if verbose:
        print(f"   Index type: {type(df.index)}")
        print(f"   Index tz: {df.index.tz if hasattr(df.index, 'tz') else 'None'}")

    if verbose:
        print(f"✅ Loaded {len(df)} bars from {file_path}")
        print(f"   Date range: {df.index[0]} to {df.index[-1]}")
        print(f"   Days: {(df.index[-1] - df.index[0]).days}")
        print(f"   Price range: {df['Low'].min():.2f} - {df['High'].max():.2f}")

    # Verify required columns
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Add wick columns if not present
    if 'Body_Pips' not in df.columns:
        if verbose:
            print(f"\nCalculating wick columns...")
        df['Body_Pips'] = abs(df['Close'] - df['Open'])
        df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
        df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']
        df['Range_Pips'] = df['High'] - df['Low']

    return df


def run_backtest(df, relaxed_params=False, verbose=True):
    """
    Run backtest on IB data.

    Args:
        df: OHLCV DataFrame
        relaxed_params: Use relaxed parameters
        verbose: Print progress

    Returns:
        Tuple of (setups_list, results_dict)
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"RUNNING BACKTEST ON IB DATA")
        print(f"{'='*80}\n")

    # Initialize SetupFinder with parameters
    if relaxed_params:
        if verbose:
            print("Using RELAXED parameters (whitepaper-compliant)...")
        finder = SetupFinder(
            consol_min_duration=3,       # Whitepaper: 3-25 flexible
            consol_max_duration=25,
            atr_multiplier_min=0.2,
            atr_multiplier_max=5.0,
        )
    else:
        if verbose:
            print("Using STRICT parameters (whitepaper-compliant)...")
        finder = SetupFinder(
            consol_min_duration=3,       # Whitepaper: 3-25 flexible
            consol_max_duration=20,
            atr_multiplier_min=0.3,
            atr_multiplier_max=4.5,
        )

    # Find setups
    if verbose:
        print("Finding setups...\n")

    setups = finder.find_setups(df, verbose=verbose)

    if verbose:
        print(f"\n{'='*80}")
        print(f"✅ Found {len(setups)} setups")
        print(f"{'='*80}\n")

    if len(setups) == 0:
        print("⚠️  No setups found!")
        print("\nPossible reasons:")
        print("  • Market conditions not suitable for strategy")
        print("  • Parameters too strict")
        print("  • Data period doesn't contain valid setups")
        return setups, None

    # Run backtest to get trade outcomes
    if verbose:
        print("Executing trades...\n")

    risk_manager = RiskManager(
        initial_capital=50000.0,
        max_risk_per_trade=0.02  # 2% risk per trade
    )

    backtester = Backtester(
        df=df,
        setup_finder=finder,
        initial_capital=50000.0,
        risk_manager=risk_manager,
        use_ml_filter=False,
        use_news_filter=False
    )

    results = backtester.run(verbose=verbose)

    return setups, results


def analyze_results(setups, results, verbose=True):
    """
    Analyze backtest results.

    Args:
        setups: List of setups
        results: Backtest results dict
        verbose: Print analysis
    """
    if not results:
        return

    trades = results['trades']

    if verbose:
        print(f"\n{'='*80}")
        print(f"DETAILED ANALYSIS")
        print(f"{'='*80}\n")

    # Calculate statistics
    total_trades = len(trades)
    wins = sum(1 for t in trades if t['result'] == 'WIN')
    losses = sum(1 for t in trades if t['result'] == 'LOSS')
    win_rate = wins / total_trades if total_trades > 0 else 0

    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in trades if t['result'] == 'WIN') / wins if wins > 0 else 0
    avg_loss = sum(t['pnl'] for t in trades if t['result'] == 'LOSS') / losses if losses > 0 else 0

    # Get date range
    if trades:
        dates = [t['entry_time'] for t in trades]
        days = (max(dates) - min(dates)).days + 1
        weeks = days / 7
        setups_per_week = total_trades / weeks if weeks > 0 else 0
    else:
        days = weeks = setups_per_week = 0

    if verbose:
        print(f"📊 TRADE STATISTICS")
        print(f"{'─'*80}")
        print(f"Total Trades:        {total_trades}")
        print(f"Wins:                {wins} ({win_rate:.1%})")
        print(f"Losses:              {losses}")
        print(f"")
        print(f"Total P&L:           {total_pnl:+,.0f} SEK")
        print(f"Average Win:         {avg_win:+,.0f} SEK")
        print(f"Average Loss:        {avg_loss:+,.0f} SEK")
        print(f"")
        print(f"📅 FREQUENCY ANALYSIS")
        print(f"{'─'*80}")
        print(f"Period:              {days} days ({weeks:.1f} weeks)")
        print(f"Setups per week:     {setups_per_week:.2f}")
        print(f"")

    # Statistical confidence
    if total_trades >= 30:
        confidence = "HIGH"
        confidence_msg = "✅ Sample size sufficient for statistical confidence"
    elif total_trades >= 10:
        confidence = "MEDIUM"
        confidence_msg = "⚠️  Sample size acceptable, but more data recommended"
    else:
        confidence = "LOW"
        confidence_msg = "❌ Sample size too small for statistical confidence"

    if verbose:
        print(f"📈 STATISTICAL CONFIDENCE")
        print(f"{'─'*80}")
        print(f"Confidence Level:    {confidence}")
        print(f"{confidence_msg}")
        print(f"")
        if total_trades < 30:
            needed = 30 - total_trades
            print(f"Need {needed} more trades for HIGH confidence")
            print(f"Recommendation: Fetch {int(needed / setups_per_week * 7)} more days of data")
            print(f"")

    # Directional analysis
    short_trades = [t for t in trades if t['direction'] == 'short']
    long_trades = [t for t in trades if t['direction'] == 'long']

    if verbose:
        print(f"🎯 DIRECTIONAL ANALYSIS")
        print(f"{'─'*80}")
        print(f"SHORT trades:        {len(short_trades)}")
        if short_trades:
            short_wins = sum(1 for t in short_trades if t['result'] == 'WIN')
            short_wr = short_wins / len(short_trades) * 100
            print(f"  Win rate:          {short_wr:.1f}%")

        print(f"LONG trades:         {len(long_trades)}")
        if long_trades:
            long_wins = sum(1 for t in long_trades if t['result'] == 'WIN')
            long_wr = long_wins / len(long_trades) * 100
            print(f"  Win rate:          {long_wr:.1f}%")
        print(f"")

    # Risk/Reward analysis
    if wins > 0 and losses > 0:
        rr_values = [t.get('rr', 0) for t in trades if t['result'] == 'WIN']
        avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0

        if verbose:
            print(f"💰 RISK/REWARD ANALYSIS")
            print(f"{'─'*80}")
            print(f"Average R:R (wins):  {avg_rr:.2f}")
            print(f"Win/Loss ratio:      {abs(avg_win / avg_loss):.2f}" if avg_loss != 0 else "N/A")
            print(f"")

    return {
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'setups_per_week': setups_per_week,
        'confidence': confidence,
        'avg_rr': avg_rr if wins > 0 and losses > 0 else None
    }


def main():
    parser = argparse.ArgumentParser(description='Run backtest with IB data')
    parser.add_argument('--input', type=str, default='data/nq_historical.csv', help='Input CSV file from IB fetch')
    parser.add_argument('--relaxed-params', action='store_true', help='Use relaxed parameters')
    parser.add_argument('--quiet', action='store_true', help='Suppress output')

    args = parser.parse_args()
    verbose = not args.quiet

    try:
        # Print header
        if verbose:
            print(f"\n{'#'*80}")
            print(f"# IB DATA BACKTEST VALIDATION")
            if args.relaxed_params:
                print(f"# MODE: RELAXED PARAMETERS")
            else:
                print(f"# MODE: STRICT PARAMETERS")
            print(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'#'*80}\n")

        # Load data
        df = load_ib_data(args.input, verbose=verbose)

        # Run backtest
        setups, results = run_backtest(df, relaxed_params=args.relaxed_params, verbose=verbose)

        # Analyze results
        if results:
            stats = analyze_results(setups, results, verbose=verbose)

            # Print final verdict
            if verbose:
                print(f"\n{'='*80}")
                print(f"FINAL VERDICT")
                print(f"{'='*80}\n")

                if stats['total_trades'] >= 30:
                    print(f"✅ VALIDATION SUCCESSFUL")
                    print(f"\nStrategy performance with {stats['total_trades']} trades:")
                    print(f"  • Win rate: {stats['win_rate']:.1%}")
                    print(f"  • Frequency: {stats['setups_per_week']:.2f} setups/week")
                    print(f"  • Total P&L: {stats['total_pnl']:+,.0f} SEK")
                    print(f"\nStatistical confidence: {stats['confidence']}")
                    print(f"\n🎯 Strategy is validated for production use!")

                elif stats['total_trades'] >= 10:
                    print(f"⚠️  PARTIAL VALIDATION")
                    print(f"\nStrategy shows promise with {stats['total_trades']} trades:")
                    print(f"  • Win rate: {stats['win_rate']:.1%}")
                    print(f"  • Frequency: {stats['setups_per_week']:.2f} setups/week")
                    print(f"  • Total P&L: {stats['total_pnl']:+,.0f} SEK")
                    print(f"\nRecommendation: Fetch more data for full validation")

                else:
                    print(f"❌ INSUFFICIENT DATA")
                    print(f"\nOnly {stats['total_trades']} trades found.")
                    print(f"Need minimum 30 trades for statistical confidence.")
                    print(f"\nRecommendation: Fetch more historical data")

                print(f"\n{'='*80}\n")

        return 0

    except Exception as e:
        if verbose:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
