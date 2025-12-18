"""
Enkel demonstration av 5/1 SLOB system

Skapar minimal, perfekt data som garanterat hittar en setup
"""

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, '/Users/erikaberg/Downloads/slobprototype')

from slob.backtest import SetupFinder, Backtester


def create_perfect_setup_data():
    """Skapa minimal perfekt data med exakt 1 setup"""

    print("Skapar perfekt setup data...")

    # 480 candles (8 hours: 09:00-17:00)
    dates = pd.date_range('2024-01-15 09:00', periods=480, freq='1min')

    # Initialize med flat baseline
    df = pd.DataFrame({
        'Open': 16000.0,
        'High': 16002.0,
        'Low': 15998.0,
        'Close': 16000.0,
        'Volume': 1000
    }, index=dates)

    # LSE SESSION (09:00-15:30): Range 15900-16100
    # Flat mellan 15950-16050 (undvik extremer)
    lse_end = pd.Timestamp('2024-01-15 15:30')
    lse_mask = df.index < lse_end

    for idx in df[lse_mask].index:
        df.loc[idx, 'Open'] = 16000
        df.loc[idx, 'High'] = 16050
        df.loc[idx, 'Low'] = 15950
        df.loc[idx, 'Close'] = 16000
        df.loc[idx, 'Volume'] = 1000

    # Set LSE High och Low explicit
    df.loc['2024-01-15 14:00', 'High'] = 16100  # LSE High
    df.loc['2024-01-15 10:00', 'Low'] = 15900   # LSE Low

    print(f"  LSE High: 16100, LSE Low: 15900")

    # LIQ #1 @ 15:31 (breaks LSE High 16100)
    df.loc['2024-01-15 15:31', 'Open'] = 16098
    df.loc['2024-01-15 15:31', 'High'] = 16110  # Breaks 16100
    df.loc['2024-01-15 15:31', 'Low'] = 16095
    df.loc['2024-01-15 15:31', 'Close'] = 16105
    df.loc['2024-01-15 15:31', 'Volume'] = 2500  # Volume spike

    print(f"  LIQ #1 @ 15:31: High 16110 (breaks LSE High)")

    # CONSOLIDATION (15:32-16:02, 30 min)
    # Perfect sideways 16100-16110
    for minute in range(32, 63):  # 15:32 to 16:02
        if minute < 60:
            time_str = f'2024-01-15 15:{minute}'
        else:
            time_str = f'2024-01-15 16:{minute-60:02d}'

        # Alternating between high and low
        if (minute - 32) % 2 == 0:
            price = 16108
        else:
            price = 16102

        df.loc[time_str, 'Open'] = price
        df.loc[time_str, 'High'] = price + 2
        df.loc[time_str, 'Low'] = price - 2
        df.loc[time_str, 'Close'] = price
        df.loc[time_str, 'Volume'] = 900

    print(f"  Consolidation (15:32-16:02): 16100-16110")

    # NO-WICK @ 15:50 (inside consolidation)
    # Bullish with minimal upper wick
    df.loc['2024-01-15 15:50', 'Open'] = 16102
    df.loc['2024-01-15 15:50', 'High'] = 16107  # Only 1 pip upper wick
    df.loc['2024-01-15 15:50', 'Low'] = 16100
    df.loc['2024-01-15 15:50', 'Close'] = 16106  # Bullish (Close > Open)
    df.loc['2024-01-15 15:50', 'Volume'] = 900

    print(f"  No-wick @ 15:50: Bullish (Close 16106 > Open 16102)")

    # LIQ #2 @ 16:03 (breaks consolidation high 16110)
    df.loc['2024-01-15 16:03', 'Open'] = 16108
    df.loc['2024-01-15 16:03', 'High'] = 16120  # Breaks 16110
    df.loc['2024-01-15 16:03', 'Low'] = 16106
    df.loc['2024-01-15 16:03', 'Close'] = 16115
    df.loc['2024-01-15 16:03', 'Volume'] = 2000

    print(f"  LIQ #2 @ 16:03: High 16120 (breaks consolidation)")

    # ENTRY TRIGGER @ 16:05 (close below no-wick low 16100)
    df.loc['2024-01-15 16:05', 'Open'] = 16112
    df.loc['2024-01-15 16:05', 'High'] = 16115
    df.loc['2024-01-15 16:05', 'Low'] = 16095
    df.loc['2024-01-15 16:05', 'Close'] = 16098  # Closes below no-wick low (16100)
    df.loc['2024-01-15 16:05', 'Volume'] = 1500

    print(f"  Entry trigger @ 16:05: Close 16098 < no-wick low 16100")

    # ENTRY @ 16:06 (next candle's OPEN)
    df.loc['2024-01-15 16:06', 'Open'] = 16097  # Entry price
    df.loc['2024-01-15 16:06', 'High'] = 16100
    df.loc['2024-01-15 16:06', 'Low'] = 16093
    df.loc['2024-01-15 16:06', 'Close'] = 16095

    print(f"  Entry @ 16:06: OPEN 16097 (SHORT)")

    # MOVE TO TP (16:07-16:30)
    # Gradual move from 16097 → 15900 (197 pips)
    for minute in range(7, 31):
        time_str = f'2024-01-15 16:{minute:02d}'
        progress = (minute - 7) / 24  # 0 to 1
        price = 16097 - (197 * progress)

        df.loc[time_str, 'Open'] = price
        df.loc[time_str, 'High'] = price + 3
        df.loc[time_str, 'Low'] = price - 3
        df.loc[time_str, 'Close'] = price - 1
        df.loc[time_str, 'Volume'] = 1000

    # TP HIT @ 16:30
    df.loc['2024-01-15 16:30', 'Low'] = 15899  # Hits TP (LSE Low 15900)

    print(f"  TP hit @ 16:30: Low 15899 (LSE Low 15900)")

    # Calculate wick columns
    df['Body_Pips'] = abs(df['Close'] - df['Open'])
    df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
    df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']
    df['Range_Pips'] = df['High'] - df['Low']

    print(f"\n  Total candles: {len(df)}")
    print(f"  Time range: {df.index[0]} to {df.index[-1]}\n")

    return df


def main():
    print("\n" + "="*80)
    print("5/1 SLOB SYSTEM - PERFEKT SETUP DEMONSTRATION")
    print("="*80 + "\n")

    # Create data
    df = create_perfect_setup_data()

    # Find setups
    print("-"*80)
    print("RUNNING SETUP FINDER...")
    print("-"*80 + "\n")

    finder = SetupFinder(
        consol_min_duration=15,
        consol_max_duration=40,
        atr_multiplier_min=0.2,  # Very relaxed for demo
        atr_multiplier_max=3.0,
        nowick_percentile=95  # Very strict for demo
    )

    setups = finder.find_setups(df, verbose=True)

    print(f"\n{'='*80}")
    print(f"RESULTS: {len(setups)} setups found")
    print(f"{'='*80}\n")

    if len(setups) > 0:
        setup = setups[0]
        print("SETUP DETAILS:")
        print(f"  LSE High:          {setup['lse_high']:.2f}")
        print(f"  LSE Low:           {setup['lse_low']:.2f}")
        print(f"  LIQ #1:            {setup['liq1_time']} @ {setup['liq1_price']:.2f}")
        print(f"  Consolidation:     {setup['consol_start_idx']} to {setup['consol_end_idx']}")
        print(f"  No-wick:           {setup['nowick_time']} (low: {setup['nowick_low']:.2f})")
        print(f"  LIQ #2:            {setup['liq2_time']} @ {setup['liq2_price']:.2f}")
        print(f"  Entry:             {setup['entry_time']} @ {setup['entry_price']:.2f}")
        print(f"  SL:                {setup['sl_price']:.2f}")
        print(f"  TP:                {setup['tp_price']:.2f}")
        print(f"  Risk:              {setup['risk_pips']:.1f} pips")
        print(f"  Reward:            {setup['reward_pips']:.1f} pips")
        print(f"  R:R:               {setup['risk_reward_ratio']:.2f}")

        # Run backtest
        print(f"\n{'-'*80}")
        print("RUNNING BACKTEST...")
        print(f"{'-'*80}\n")

        backtester = Backtester(
            df=df,
            setup_finder=finder,
            initial_capital=50000.0,
            use_ml_filter=False,
            use_news_filter=False
        )

        results = backtester.run(verbose=False)

        if len(results['trades']) > 0:
            trade = results['trades'][0]
            print("\nTRADE RESULT:")
            print(f"  Entry:    {trade['entry_time']} @ {trade['entry_price']:.2f}")
            print(f"  Exit:     {trade['exit_time']} @ {trade['exit_price']:.2f}")
            print(f"  Type:     {trade['exit_type']}")
            print(f"  Duration: {(trade['exit_time'] - trade['entry_time']).total_seconds() / 60:.0f} min")
            print(f"  Result:   {trade['result']}")
            print(f"  P&L:      {trade['pnl']:+,.0f} SEK ({trade['pnl_pips']:+.1f} pips)")
            print(f"  R:R:      {trade['rr_achieved']:.2f}")
            print(f"  Position: {trade['contracts']:.2f} contracts ({trade['position_size']:,.0f} SEK)")
    else:
        print("⚠️  No setups found - något är fel!")

    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    main()
