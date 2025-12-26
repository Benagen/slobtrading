"""
Analyze ML Shadow Mode Performance

Compares ML predictions vs actual outcomes to determine if ML improves results.

Usage:
    python scripts/analyze_shadow_mode.py
    python scripts/analyze_shadow_mode.py --days 60
    python scripts/analyze_shadow_mode.py --db data/slob_state.db
"""

import argparse
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path


def analyze_shadow_performance(db_path: str, days: int = 30):
    """
    Analyze shadow mode performance.

    Compares:
    - Rule-based performance (all trades taken)
    - ML-filtered performance (only trades ML approved)
    - Agreement analysis (when do they disagree?)

    Args:
        db_path: Path to state database
        days: Number of days to analyze
    """

    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        print("\n💡 Make sure shadow mode is running and collecting data.")
        return

    conn = sqlite3.connect(db_path)

    # Check if shadow_predictions table exists
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='shadow_predictions'
    """)
    if not cursor.fetchone():
        print("❌ Shadow predictions table not found")
        print("\n💡 Shadow mode has not been initialized yet.")
        print("   Enable shadow mode in LiveTradingEngine configuration.")
        conn.close()
        return

    # Load shadow predictions with outcomes
    query = f"""
        SELECT
            s.setup_id,
            s.timestamp,
            s.ml_probability,
            s.ml_decision,
            s.rule_decision,
            s.agreement,
            s.actual_outcome,
            s.actual_pnl
        FROM shadow_predictions s
        WHERE s.timestamp > datetime('now', '-{days} days')
        ORDER BY s.timestamp DESC
    """

    df = pd.read_sql(query, conn)
    conn.close()

    if len(df) == 0:
        print(f"❌ No shadow mode data found in last {days} days")
        print("\n💡 Shadow mode is collecting data but no predictions yet.")
        print("   Wait for setups to be detected during live trading.")
        return

    # Count predictions with outcomes
    df_with_outcomes = df[df['actual_outcome'].notna()]

    print("=" * 70)
    print("ML SHADOW MODE ANALYSIS")
    print("=" * 70)
    print(f"Period: Last {days} days")
    print(f"Total Predictions: {len(df)}")
    print(f"Predictions with Outcomes: {len(df_with_outcomes)}")
    print()

    if len(df_with_outcomes) == 0:
        print("⏳ No completed trades yet - still collecting data")
        print("\nCurrent Predictions (no outcomes yet):")
        print(f"  Total predictions: {len(df)}")
        print(f"  ML approved: {(df['ml_decision'] == 'TAKE').sum()}")
        print(f"  ML rejected: {(df['ml_decision'] == 'SKIP').sum()}")
        print(f"  Agreement rate: {df['agreement'].mean():.1%}")
        print()
        print("💡 Run this script again after trades complete to see performance comparison.")
        return

    # Analyze rule-based performance (all trades)
    rule_wins = (df_with_outcomes['actual_outcome'] == 'WIN').sum()
    rule_total = len(df_with_outcomes)
    rule_win_rate = rule_wins / rule_total if rule_total > 0 else 0
    rule_total_pnl = df_with_outcomes['actual_pnl'].sum()
    rule_avg_pnl = df_with_outcomes['actual_pnl'].mean()

    # Analyze ML-filtered performance (only ML approved)
    ml_approved = df_with_outcomes[df_with_outcomes['ml_decision'] == 'TAKE']
    ml_wins = (ml_approved['actual_outcome'] == 'WIN').sum()
    ml_total = len(ml_approved)
    ml_win_rate = ml_wins / ml_total if ml_total > 0 else 0
    ml_total_pnl = ml_approved['actual_pnl'].sum()
    ml_avg_pnl = ml_approved['actual_pnl'].mean() if ml_total > 0 else 0

    # ML rejected trades (would have been skipped)
    ml_rejected = df_with_outcomes[df_with_outcomes['ml_decision'] == 'SKIP']
    rejected_total = len(ml_rejected)
    rejected_pnl = ml_rejected['actual_pnl'].sum()
    rejected_avg_pnl = ml_rejected['actual_pnl'].mean() if rejected_total > 0 else 0

    # Print comparison
    print("RULE-BASED PERFORMANCE (All Trades):")
    print(f"  Trades: {rule_total}")
    print(f"  Wins: {rule_wins} ({rule_win_rate:.1%})")
    print(f"  Total P&L: ${rule_total_pnl:.2f}")
    print(f"  Avg P&L per trade: ${rule_avg_pnl:.2f}")
    print()

    print("ML-FILTERED PERFORMANCE (Only ML Approved):")
    print(f"  Trades: {ml_total} (filtered {rejected_total} setups)")
    print(f"  Wins: {ml_wins} ({ml_win_rate:.1%})")
    print(f"  Total P&L: ${ml_total_pnl:.2f}")
    print(f"  Avg P&L per trade: ${ml_avg_pnl:.2f}")
    print()

    print("ML REJECTED TRADES (Would Have Been Skipped):")
    print(f"  Trades: {rejected_total}")
    print(f"  Total P&L: ${rejected_pnl:.2f}")
    print(f"  Avg P&L per trade: ${rejected_avg_pnl:.2f}")
    print()

    # Calculate improvement
    print("IMPROVEMENT:")
    win_rate_improvement = ml_win_rate - rule_win_rate
    pnl_improvement = ml_total_pnl - rule_total_pnl
    avg_pnl_improvement = ml_avg_pnl - rule_avg_pnl

    print(f"  Win Rate: {win_rate_improvement:+.1%}")
    print(f"  Total P&L: ${pnl_improvement:+.2f}")
    print(f"  Avg P&L per trade: ${avg_pnl_improvement:+.2f}")
    print()

    # Agreement analysis
    agreement_rate = df_with_outcomes['agreement'].mean()
    print(f"Agreement Rate: {agreement_rate:.1%}")
    print()

    # Statistical significance check
    if rule_total < 20:
        print("⚠️  WARNING: Sample size too small for statistical significance")
        print(f"   Current: {rule_total} trades | Recommended: 20+ trades")
        print()

    # Decision recommendation
    print("RECOMMENDATION:")
    if ml_total < 10:
        print("  ⏳ KEEP COLLECTING DATA")
        print(f"     Need at least 10 ML-approved trades (current: {ml_total})")
    elif win_rate_improvement >= 0.05 and avg_pnl_improvement > 0:
        print("  ✅ ENABLE ML FILTERING")
        print("     ML shows significant improvement in both win rate and P&L")
        print("     Consider enabling ML filtering in production")
    elif win_rate_improvement >= 0.03:
        print("  ⚡ PROMISING - COLLECT MORE DATA")
        print("     ML shows improvement but needs more validation")
        print(f"     Target: 30+ trades (current: {rule_total})")
    elif win_rate_improvement < -0.05:
        print("  ❌ DO NOT ENABLE ML FILTERING")
        print("     ML underperforms rule-based system")
        print("     Consider retraining model with more data")
    else:
        print("  ⏸️  NEUTRAL - KEEP MONITORING")
        print("     ML performance similar to rules")
        print("     Continue shadow mode and reassess later")

    print()

    # Disagreement analysis
    disagreements = df_with_outcomes[df_with_outcomes['agreement'] == False]
    if len(disagreements) > 0:
        print("DISAGREEMENTS (ML rejected, Rules approved):")
        print()
        for _, row in disagreements.head(10).iterrows():
            outcome_emoji = '✅' if row['actual_outcome'] == 'WIN' else '❌'
            print(f"  {outcome_emoji} Setup {row['setup_id'][:8]}: "
                  f"ML={row['ml_probability']:.1%}, "
                  f"Outcome={row['actual_outcome']}, "
                  f"P&L=${row['actual_pnl']:.2f}")

        if len(disagreements) > 10:
            print(f"  ... and {len(disagreements) - 10} more disagreements")
        print()

        # Analyze if ML was right to reject
        ml_rejection_wins = (disagreements['actual_outcome'] == 'WIN').sum()
        ml_rejection_loss_pnl = disagreements[disagreements['actual_outcome'] == 'LOSS']['actual_pnl'].sum()
        print(f"ML Rejection Analysis:")
        print(f"  ML rejected {len(disagreements)} trades")
        print(f"  {ml_rejection_wins} would have won")
        print(f"  {len(disagreements) - ml_rejection_wins} would have lost")
        print(f"  Saved from losses: ${abs(ml_rejection_loss_pnl):.2f}")
        print()

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze ML shadow mode performance"
    )
    parser.add_argument(
        '--db',
        default='data/slob_state.db',
        help='Path to state database (default: data/slob_state.db)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days to analyze (default: 30)'
    )

    args = parser.parse_args()

    analyze_shadow_performance(args.db, args.days)


if __name__ == "__main__":
    main()
