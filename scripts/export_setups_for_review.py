"""
Export Found Setups to CSV for Manual Review

Instead of debugging backtest infrastructure, export the 17 setups
found during the scan for manual validation.
"""

import sys
from pathlib import Path
import pandas as pd
from datetime import datetime

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from slob.backtest import SetupFinder


def main():
    print("="*80)
    print("SETUP EXPORT FOR MANUAL REVIEW")
    print("="*80)
    print()

    # Load IB data
    print("Loading data from data/nq_6mo.csv...")
    df = pd.read_csv('data/nq_6mo.csv', index_col='Date', parse_dates=['Date'])

    # Convert to UTC (handle timezone)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_convert('UTC')
    else:
        df.index = pd.to_datetime(df.index, utc=True)

    print(f"✅ Loaded {len(df)} bars")
    print(f"   Range: {df.index[0]} to {df.index[-1]}")
    print()

    # Find setups
    print("Finding setups (this may take a moment)...")
    finder = SetupFinder(
        consol_min_duration=3,
        consol_max_duration=20,
        atr_multiplier_min=0.3,
        atr_multiplier_max=4.5,
    )

    setups = finder.find_setups(df, verbose=False)

    print(f"✅ Found {len(setups)} setups")
    print()

    if len(setups) == 0:
        print("⚠️  No setups found to export!")
        return

    # Convert setups to export format
    print("Converting setups to CSV format...")
    setups_data = []

    for i, setup in enumerate(setups, 1):
        # Extract data from setup dict
        entry_idx = setup['entry_idx']
        entry_time = df.index[entry_idx]
        entry_price = setup['entry_price']
        sl_price = setup['sl_price']
        tp_price = setup['tp_price']
        direction = setup['direction']

        # Calculate RR ratio
        if direction == 'short':
            risk = sl_price - entry_price
            reward = entry_price - tp_price
        else:  # long
            risk = entry_price - sl_price
            reward = tp_price - entry_price

        rr_ratio = reward / risk if risk > 0 else 0

        # Get additional info
        liq1_level = setup.get('liq1_sweep_level', 0)
        consol_duration = setup.get('consolidation_duration', 0)

        setups_data.append({
            'Setup_ID': i,
            'Date': entry_time.strftime('%Y-%m-%d'),
            'Time': entry_time.strftime('%H:%M'),
            'Weekday': entry_time.strftime('%A'),
            'Direction': direction.upper(),
            'Entry_Price': f"{entry_price:.2f}",
            'Stop_Loss': f"{sl_price:.2f}",
            'Take_Profit': f"{tp_price:.2f}",
            'Risk_Points': f"{abs(risk):.2f}",
            'Reward_Points': f"{abs(reward):.2f}",
            'RR_Ratio': f"{rr_ratio:.2f}",
            'LIQ1_Level': f"{liq1_level:.2f}",
            'Consol_Duration': consol_duration,
            'Entry_Index': entry_idx
        })

    # Create DataFrame
    df_export = pd.DataFrame(setups_data)

    # Export to CSV
    output_file = 'data/setups_for_review.csv'
    df_export.to_csv(output_file, index=False)

    print(f"✅ Exported to {output_file}")
    print()

    # Print summary statistics
    print("="*80)
    print("SETUP SUMMARY")
    print("="*80)
    print()

    print(f"Total Setups:       {len(df_export)}")
    print(f"Date Range:         {df_export['Date'].min()} to {df_export['Date'].max()}")
    print()

    # Direction breakdown
    short_setups = df_export[df_export['Direction'] == 'SHORT']
    long_setups = df_export[df_export['Direction'] == 'LONG']

    print(f"Direction Breakdown:")
    print(f"  SHORT trades:     {len(short_setups)} ({len(short_setups)/len(df_export)*100:.1f}%)")
    print(f"  LONG trades:      {len(long_setups)} ({len(long_setups)/len(df_export)*100:.1f}%)")
    print()

    # RR statistics
    rr_values = df_export['RR_Ratio'].astype(float)
    print(f"Risk/Reward Statistics:")
    print(f"  Average RR:       {rr_values.mean():.2f}")
    print(f"  Min RR:           {rr_values.min():.2f}")
    print(f"  Max RR:           {rr_values.max():.2f}")
    print()

    # Frequency analysis
    dates = pd.to_datetime(df_export['Date'])
    days_span = (dates.max() - dates.min()).days + 1
    weeks_span = days_span / 7

    print(f"Frequency Analysis:")
    print(f"  Trading days:     {days_span}")
    print(f"  Weeks:            {weeks_span:.1f}")
    print(f"  Setups/week:      {len(df_export) / weeks_span:.2f}")
    print()

    # Show first few setups
    print("="*80)
    print("FIRST 5 SETUPS")
    print("="*80)
    print()

    # Select key columns for display
    display_cols = ['Setup_ID', 'Date', 'Time', 'Direction', 'Entry_Price',
                    'Stop_Loss', 'Take_Profit', 'RR_Ratio']
    print(df_export[display_cols].head(5).to_string(index=False))
    print()

    print("="*80)
    print(f"✅ SUCCESS: Review setups in {output_file}")
    print("="*80)
    print()
    print("NEXT STEPS:")
    print("  1. Open data/setups_for_review.csv in Excel/Sheets")
    print("  2. Verify dates span multiple months (not all same day)")
    print("  3. Spot-check 2-3 setups manually on TradingView")
    print("  4. Validate setup quality and RR ratios")
    print()


if __name__ == '__main__':
    main()
