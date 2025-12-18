"""
Sample Backtest - Demonstrerar full 5/1 SLOB system execution

Skapar realistisk data och kör komplett backtest med:
- LSE session (09:00-15:30)
- LIQ #1 detection
- Consolidation
- No-wick candle
- LIQ #2 & Entry trigger
- Trade execution simulation
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, '/Users/erikaberg/Downloads/slobprototype')

from slob.backtest import SetupFinder, Backtester, RiskManager


def create_realistic_sample_data(date='2024-01-15'):
    """
    Skapa realistisk M1 data med:
    - LSE session (09:00-15:30) med range 15900-16100
    - LIQ #1 @ 15:31 (NYSE break av LSE High)
    - Consolidation 15:32-16:02 (30 min oscillation)
    - No-wick candle @ 15:55
    - LIQ #2 @ 16:03 (break consolidation high)
    - Entry trigger @ 16:07
    - Trade execution → TP hit
    """
    print("Skapar realistisk sample data...")

    # Generate M1 data (09:00 - 18:00)
    start = pd.Timestamp(f'{date} 09:00')
    periods = 9 * 60  # 9 hours
    dates = pd.date_range(start, periods=periods, freq='1min')

    # Initialize DataFrame
    df = pd.DataFrame({
        'Open': 16000.0,
        'High': 16005.0,
        'Low': 15995.0,
        'Close': 16000.0,
        'Volume': 1000
    }, index=dates)

    # ===== LSE SESSION (09:00-15:30) =====
    # Controlled range: EXACTLY 15900-16100 (no random spikes)
    lse_mask = (df.index.time >= pd.Timestamp('09:00').time()) & \
               (df.index.time < pd.Timestamp('15:30').time())
    lse_indices = df[lse_mask].index

    for i, idx in enumerate(lse_indices):
        # Controlled oscillation between 15950-16050 (smaller than max)
        phase = (i / 30) * 2 * np.pi  # 30-min cycles
        base_price = 16000
        oscillation = 50 * np.sin(phase)  # ±50 pips
        noise = np.random.uniform(-3, 3)  # Smaller noise

        price = base_price + oscillation + noise

        # Ensure we stay below 16100
        df.loc[idx, 'Open'] = min(price, 16090)
        df.loc[idx, 'High'] = min(price + abs(np.random.uniform(2, 5)), 16095)
        df.loc[idx, 'Low'] = max(price - abs(np.random.uniform(2, 5)), 15905)
        df.loc[idx, 'Close'] = min(price + np.random.uniform(-2, 2), 16090)
        df.loc[idx, 'Volume'] = np.random.randint(800, 1200)

    # LSE High EXACTLY at 16100
    lse_high_time = f'{date} 14:15'
    df.loc[lse_high_time, 'Open'] = 16095
    df.loc[lse_high_time, 'High'] = 16100  # EXACT LSE High
    df.loc[lse_high_time, 'Low'] = 16090
    df.loc[lse_high_time, 'Close'] = 16095

    # LSE Low EXACTLY at 15900
    lse_low_time = f'{date} 10:30'
    df.loc[lse_low_time, 'Open'] = 15905
    df.loc[lse_low_time, 'High'] = 15910
    df.loc[lse_low_time, 'Low'] = 15900  # EXACT LSE Low
    df.loc[lse_low_time, 'Close'] = 15905

    print(f"  LSE Session: High = {df[lse_mask]['High'].max():.1f}, Low = {df[lse_mask]['Low'].min():.1f}")

    # ===== LIQ #1 @ 15:31 (NYSE break LSE High) =====
    liq1_time = f'{date} 15:31'
    df.loc[liq1_time, 'Open'] = 16098
    df.loc[liq1_time, 'High'] = 16108  # Breaks LSE High (16100)
    df.loc[liq1_time, 'Low'] = 16095
    df.loc[liq1_time, 'Close'] = 16102
    df.loc[liq1_time, 'Volume'] = 2500  # Volume spike

    print(f"  LIQ #1 @ {liq1_time}: High = 16108 (breaks LSE High 16100)")

    # ===== CONSOLIDATION (15:32-16:02, 30 min) =====
    # Oscillates between 16096-16107 (tight ~11-pip range)
    # IMPORTANT: Sideways, not trending
    consol_start = pd.Timestamp(f'{date} 15:32')
    consol_end = pd.Timestamp(f'{date} 16:02')
    consol_mask = (df.index >= consol_start) & (df.index <= consol_end)
    consol_indices = df[consol_mask].index

    for i, idx in enumerate(consol_indices):
        # Controlled sideways oscillation (no trend)
        cycle_pos = (i % 6) / 6.0  # 6-minute cycles
        mid_price = 16101.5  # Midpoint
        oscillation = 5 * np.sin(cycle_pos * 2 * np.pi)  # ±5 pips

        price = mid_price + oscillation
        noise = np.random.uniform(-0.5, 0.5)  # Minimal noise
        price += noise

        df.loc[idx, 'Open'] = price
        df.loc[idx, 'High'] = price + abs(np.random.uniform(1.0, 2.5))
        df.loc[idx, 'Low'] = price - abs(np.random.uniform(1.0, 2.5))
        df.loc[idx, 'Close'] = price + np.random.uniform(-0.5, 0.5)
        df.loc[idx, 'Volume'] = np.random.randint(700, 1000)

    print(f"  Consolidation (15:32-16:02): Range = {df[consol_mask]['High'].max():.1f} - {df[consol_mask]['Low'].min():.1f}")

    # ===== NO-WICK CANDLE @ 15:55 =====
    # BULLISH candle (Close > Open) with minimal upper wick
    # Inside consolidation, 1-5 candles before LIQ #2
    nowick_time = f'{date} 15:55'
    df.loc[nowick_time, 'Open'] = 16098.5
    df.loc[nowick_time, 'High'] = 16102.0  # Minimal upper wick
    df.loc[nowick_time, 'Low'] = 16097.0
    df.loc[nowick_time, 'Close'] = 16101.5  # Bullish: Close > Open
    df.loc[nowick_time, 'Volume'] = 850

    print(f"  No-wick @ {nowick_time}: Bullish (Close 16101.5 > Open 16098.5), upper wick = 0.5 pip")

    # ===== LIQ #2 @ 16:03 (break consolidation high) =====
    # Should break consolidation high (~16107) after consolidation ends
    liq2_time = f'{date} 16:03'
    df.loc[liq2_time, 'Open'] = 16106
    df.loc[liq2_time, 'High'] = 16118  # Breaks consolidation high clearly
    df.loc[liq2_time, 'Low'] = 16104
    df.loc[liq2_time, 'Close'] = 16112
    df.loc[liq2_time, 'Volume'] = 2200  # Volume spike

    print(f"  LIQ #2 @ {liq2_time}: High = 16118 (breaks consolidation)")

    # ===== ENTRY TRIGGER @ 16:07 =====
    # Candle closes below no-wick low (16097.0)
    trigger_time = f'{date} 16:07'
    df.loc[trigger_time, 'Open'] = 16110
    df.loc[trigger_time, 'High'] = 16113
    df.loc[trigger_time, 'Low'] = 16092
    df.loc[trigger_time, 'Close'] = 16094  # Closes below no-wick low (16097.0)
    df.loc[trigger_time, 'Volume'] = 1600

    print(f"  Entry trigger @ {trigger_time}: Close 16094 < no-wick low 16097")

    # Entry @ 16:08 (next candle's OPEN)
    entry_time = f'{date} 16:08'
    df.loc[entry_time, 'Open'] = 16093  # Entry price
    df.loc[entry_time, 'High'] = 16096
    df.loc[entry_time, 'Low'] = 16089
    df.loc[entry_time, 'Close'] = 16091

    print(f"  Entry @ {entry_time}: OPEN = 16093 (SHORT)")

    # ===== TRADE MOVES TO TP =====
    # TP = LSE Low (15900)
    # Price gradually moves down from 16093 → 15900 (193 pips)
    trade_start = pd.Timestamp(f'{date} 16:09')
    trade_end = pd.Timestamp(f'{date} 17:30')
    trade_mask = (df.index >= trade_start) & (df.index <= trade_end)
    trade_indices = df[trade_mask].index

    for i, idx in enumerate(trade_indices):
        # Gradual downtrend from 16093 → 15900
        progress = i / len(trade_indices)
        price = 16093 - (193 * progress)  # 16093 → 15900
        noise = np.random.uniform(-3, 3)
        price += noise

        # Ensure we don't hit SL (which should be ~16120)
        df.loc[idx, 'Open'] = price
        df.loc[idx, 'High'] = min(price + abs(np.random.uniform(2, 5)), 16110)
        df.loc[idx, 'Low'] = price - abs(np.random.uniform(2, 5))
        df.loc[idx, 'Close'] = price + np.random.uniform(-2, 2)
        df.loc[idx, 'Volume'] = np.random.randint(800, 1200)

    # TP HIT @ 17:25
    tp_time = f'{date} 17:25'
    df.loc[tp_time, 'Open'] = 15903
    df.loc[tp_time, 'High'] = 15905
    df.loc[tp_time, 'Low'] = 15899  # Hits TP (LSE Low 15900)
    df.loc[tp_time, 'Close'] = 15901

    print(f"  TP hit @ {tp_time}: Low = 15899 (target 15900)")

    # Calculate wick columns (required by NoWickDetector)
    df['Body_Pips'] = abs(df['Close'] - df['Open'])
    df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
    df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']
    df['Range_Pips'] = df['High'] - df['Low']

    print(f"\nData created: {len(df)} candles, {df.index[0]} to {df.index[-1]}")

    return df


def run_sample_backtest():
    """Kör full sample backtest"""

    print("\n" + "="*80)
    print("5/1 SLOB SAMPLE BACKTEST")
    print("="*80 + "\n")

    # 1. Create sample data
    df = create_realistic_sample_data()

    # 2. Initialize SetupFinder
    print("\n" + "-"*80)
    print("SETUP DETECTION")
    print("-"*80 + "\n")

    finder = SetupFinder(
        consol_min_duration=15,
        consol_max_duration=40,
        atr_multiplier_min=0.3,
        atr_multiplier_max=2.5,
        nowick_percentile=90
    )

    # 3. Find setups (verbose)
    setups = finder.find_setups(df, verbose=True)

    print(f"\n{'='*80}")
    print(f"SETUPS FOUND: {len(setups)}")
    print(f"{'='*80}\n")

    if len(setups) == 0:
        print("⚠️  No setups found!")
        return

    # 4. Display setup details
    for i, setup in enumerate(setups):
        print(f"\n{'─'*80}")
        print(f"SETUP #{i+1}")
        print(f"{'─'*80}")
        print(f"  LSE High:          {setup['lse_high']:.2f}")
        print(f"  LSE Low:           {setup['lse_low']:.2f}")
        print(f"  LIQ #1 Time:       {setup['liq1_time']}")
        print(f"  LIQ #1 Price:      {setup['liq1_price']:.2f}")
        print(f"  Consolidation:     {setup['consol_start_idx']} to {setup['consol_end_idx']} ({setup['consol_end_idx'] - setup['consol_start_idx']} candles)")
        print(f"  Consol Range:      {setup['consol_high']:.2f} - {setup['consol_low']:.2f} ({setup['consol_range']:.1f} pips)")
        print(f"  No-wick Time:      {setup['nowick_time']}")
        print(f"  No-wick Low:       {setup['nowick_low']:.2f}")
        print(f"  LIQ #2 Time:       {setup['liq2_time']}")
        print(f"  LIQ #2 Price:      {setup['liq2_price']:.2f}")
        print(f"  Entry Time:        {setup['entry_time']}")
        print(f"  Entry Price:       {setup['entry_price']:.2f} (SHORT)")
        print(f"  SL Price:          {setup['sl_price']:.2f}")
        print(f"  TP Price:          {setup['tp_price']:.2f}")
        print(f"  Risk:              {setup['risk_pips']:.1f} pips")
        print(f"  Reward:            {setup['reward_pips']:.1f} pips")
        print(f"  R:R Ratio:         {setup['risk_reward_ratio']:.2f}")

    # 5. Run backtest
    print(f"\n\n{'='*80}")
    print("BACKTEST EXECUTION")
    print(f"{'='*80}\n")

    risk_manager = RiskManager(
        initial_capital=50000.0,
        max_risk_per_trade=0.02
    )

    backtester = Backtester(
        df=df,
        setup_finder=finder,
        initial_capital=50000.0,
        risk_manager=risk_manager,
        use_ml_filter=False,  # No ML for this sample
        use_news_filter=False  # No news for this sample
    )

    results = backtester.run(verbose=True)

    # 6. Display trade results
    print(f"\n\n{'='*80}")
    print("TRADE RESULTS")
    print(f"{'='*80}\n")

    if len(results['trades']) > 0:
        for i, trade in enumerate(results['trades']):
            print(f"\nTRADE #{i+1}:")
            print(f"  Direction:         {trade['direction']}")
            print(f"  Entry Time:        {trade['entry_time']}")
            print(f"  Entry Price:       {trade['entry_price']:.2f}")
            print(f"  Exit Time:         {trade['exit_time']}")
            print(f"  Exit Price:        {trade['exit_price']:.2f}")
            print(f"  Exit Type:         {trade['exit_type']}")
            print(f"  Duration:          {(trade['exit_time'] - trade['entry_time']).total_seconds() / 60:.0f} minutes")
            print(f"  Contracts:         {trade['contracts']:.2f}")
            print(f"  Position Size:     {trade['position_size']:,.0f} SEK")
            print(f"  Result:            {trade['result']}")
            print(f"  P&L (pips):        {trade['pnl_pips']:+.1f}")
            print(f"  P&L (SEK):         {trade['pnl']:+,.0f} SEK")
            print(f"  R:R Achieved:      {trade['rr_achieved']:.2f}")
    else:
        print("⚠️  No trades executed!")

    # 7. Display metrics
    print(f"\n\n{'='*80}")
    print("PERFORMANCE METRICS")
    print(f"{'='*80}\n")

    metrics = results['metrics']
    if metrics:
        print(f"  Total Setups:      {len(results['setups'])}")
        print(f"  Total Trades:      {metrics.get('total_trades', 0)}")
        print(f"  Wins:              {metrics.get('wins', 0)}")
        print(f"  Losses:            {metrics.get('losses', 0)}")
        print(f"  Win Rate:          {metrics.get('win_rate', 0):.1%}")
        print(f"  Total P&L:         {metrics.get('total_pnl', 0):+,.0f} SEK")
        print(f"  Avg Win:           {metrics.get('avg_win', 0):,.0f} SEK")
        print(f"  Avg Loss:          {metrics.get('avg_loss', 0):,.0f} SEK")
        print(f"  Profit Factor:     {metrics.get('profit_factor', 0):.2f}")
        print(f"  Final Capital:     {metrics.get('final_capital', 0):,.0f} SEK")
        print(f"  Total Return:      {metrics.get('total_return', 0):+.1%}")

    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    run_sample_backtest()
