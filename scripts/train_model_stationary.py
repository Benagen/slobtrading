"""
Train ML Model with Stationary Features

This script:
1. Fetches historical NQ futures data (or uses checkpoint data)
2. Runs backtest to find setups and label them (WIN/LOSS)
3. Extracts stationary features using FeatureEngineer
4. Trains XGBoost classifier
5. Saves model to models/setup_classifier_latest.joblib

Usage:
    python scripts/train_model_stationary.py --days 60 --verbose
"""

import sys
import os
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from slob.backtest import SetupFinder, Backtester, RiskManager
from slob.features.feature_engineer import FeatureEngineer
from slob.ml.setup_classifier import SetupClassifier


def fetch_historical_data(days=60, verbose=True):
    """
    Fetch historical NQ futures data from yfinance.

    Args:
        days: Number of days of historical data
        verbose: Print progress

    Returns:
        DataFrame with OHLCV data
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"FETCHING HISTORICAL DATA")
        print(f"{'='*80}\n")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    if verbose:
        print(f"Downloading NQ futures data from {start_date.date()} to {end_date.date()}...")

    try:
        # Fetch NQ=F (Nasdaq 100 futures) - 1 minute data
        ticker = yf.Ticker("NQ=F")

        # yfinance only provides last 7 days of 1-minute data
        # For longer periods, we'll use 5-minute data and resample
        if days <= 7:
            interval = "1m"
        elif days <= 30:
            interval = "5m"
        else:
            interval = "15m"

        df = ticker.history(
            start=start_date,
            end=end_date,
            interval=interval
        )

        if df.empty:
            raise ValueError(f"No data returned for NQ=F")

        # Ensure column names match expected format
        df = df.rename(columns={
            'Open': 'Open',
            'High': 'High',
            'Low': 'Low',
            'Close': 'Close',
            'Volume': 'Volume'
        })

        # Keep only OHLCV
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

        # Drop any NaN rows
        df = df.dropna()

        # Calculate wick columns (required by SetupFinder)
        df['Body_Pips'] = abs(df['Close'] - df['Open'])
        df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
        df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']
        df['Range_Pips'] = df['High'] - df['Low']

        if verbose:
            print(f"✅ Downloaded {len(df)} candles ({interval} interval)")
            print(f"   Date range: {df.index[0]} to {df.index[-1]}")
            print(f"   Price range: {df['Low'].min():.2f} - {df['High'].max():.2f}")

        return df

    except Exception as e:
        print(f"❌ Error fetching data from yfinance: {e}")
        print(f"\nℹ️  yfinance has limitations on minute-level data.")
        print(f"   Consider using a professional data provider for production.")
        raise


def run_backtest(df, relaxed_params=False, verbose=True):
    """
    Run backtest to find setups and label them with WIN/LOSS outcomes.

    Args:
        df: OHLCV DataFrame
        relaxed_params: Use relaxed parameters for more setups
        verbose: Print progress

    Returns:
        Tuple of (setups_list, trades_list)
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"RUNNING BACKTEST")
        print(f"{'='*80}\n")

    # Initialize SetupFinder with appropriate parameters
    if relaxed_params:
        if verbose:
            print("Using RELAXED parameters with WHITEPAPER-COMPLIANT CONSOLIDATION...")
        finder = SetupFinder(
            consol_min_duration=3,       # WHITEPAPER: 3-25 candles (flexible)
            consol_max_duration=25,      # WHITEPAPER: No strict upper limit
            atr_multiplier_min=0.2,      # Wide range for relaxed mode
            atr_multiplier_max=5.0,      # Allow wider ranges
            nowick_percentile=60         # Relaxed no-wick detection (NOTE: percentile param deprecated)
        )
    else:
        if verbose:
            print("Using STRICT parameters with WHITEPAPER-COMPLIANT CONSOLIDATION...")
        finder = SetupFinder(
            consol_min_duration=3,       # WHITEPAPER: 3-25 candles (flexible)
            consol_max_duration=20,      # WHITEPAPER: Slightly tighter than relaxed
            atr_multiplier_min=0.3,
            atr_multiplier_max=4.5,      # Stricter than relaxed but still wide
            nowick_percentile=70         # Stricter no-wick detection (NOTE: percentile param deprecated)
        )

    # Find setups
    if verbose:
        print("Finding setups...")

    setups = finder.find_setups(df, verbose=verbose)

    if verbose:
        print(f"✅ Found {len(setups)} setups")

    if len(setups) == 0:
        raise ValueError("No setups found! Try increasing the date range or adjusting parameters.")

    # Run backtest to get trade outcomes
    if verbose:
        print("\nExecuting trades...")

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

    trades = results['trades']

    if verbose:
        wins = sum(1 for t in trades if t['result'] == 'WIN')
        losses = sum(1 for t in trades if t['result'] == 'LOSS')
        win_rate = wins / len(trades) if len(trades) > 0 else 0

        print(f"\n✅ Backtest complete:")
        print(f"   Total trades: {len(trades)}")
        print(f"   Wins: {wins}")
        print(f"   Losses: {losses}")
        print(f"   Win rate: {win_rate:.1%}")

    return setups, trades


def extract_features(df, setups, trades, verbose=True):
    """
    Extract stationary features from setups.

    Args:
        df: OHLCV DataFrame
        setups: List of setup dicts
        trades: List of trade dicts (with WIN/LOSS labels)
        verbose: Print progress

    Returns:
        DataFrame with features and labels
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"EXTRACTING FEATURES (STATIONARY)")
        print(f"{'='*80}\n")

    # Extract features using FeatureEngineer (automatically uses stationary names)
    df_features = FeatureEngineer.create_feature_matrix(df, setups, trades)

    if verbose:
        print(f"✅ Extracted features:")
        print(f"   Shape: {df_features.shape}")
        print(f"   Features: {len(df_features.columns) - 1} (+ 1 label)")

        # Verify stationary features are present
        stationary_features = [
            'atr_relative', 'entry_to_lse_high_pct', 'entry_to_lse_low_pct',
            'lse_range_pct', 'nowick_body_pct', 'liq2_sweep_pct', 'price_volatility_cv'
        ]

        present = [f for f in stationary_features if f in df_features.columns]
        print(f"   Stationary features: {len(present)}/{len(stationary_features)}")

        if len(present) == len(stationary_features):
            print(f"   ✅ All stationary features confirmed!")
        else:
            missing = set(stationary_features) - set(present)
            print(f"   ⚠️  Missing: {missing}")

        # Show label distribution
        if 'label' in df_features.columns:
            win_rate = df_features['label'].mean()
            print(f"   Win rate: {win_rate:.1%}")

    return df_features


def train_model(df_features, verbose=True):
    """
    Train XGBoost classifier on features.

    Args:
        df_features: DataFrame with features and labels
        verbose: Print progress

    Returns:
        Trained SetupClassifier
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"TRAINING ML MODEL")
        print(f"{'='*80}\n")

    # Separate features and labels
    X = df_features.drop('label', axis=1)
    y = df_features['label']

    if verbose:
        print(f"Training samples: {len(X)}")
        print(f"Win rate: {y.mean():.1%}")

    # Check if we have enough data
    if len(X) < 30:
        print(f"\n⚠️  WARNING: Only {len(X)} samples. Recommend 100+ for reliable training.")
        print(f"   Consider increasing --days parameter or using more data sources.")

    # Time-based split (80/20 train/test)
    split_idx = int(len(X) * 0.8)
    X_train = X.iloc[:split_idx]
    y_train = y.iloc[:split_idx]
    X_test = X.iloc[split_idx:]
    y_test = y.iloc[split_idx:]

    if verbose:
        print(f"\nTrain set: {len(X_train)} samples ({y_train.mean():.1%} win rate)")
        print(f"Test set:  {len(X_test)} samples ({y_test.mean():.1%} win rate)")

    # Initialize classifier
    classifier = SetupClassifier(
        n_estimators=100,      # Number of trees
        max_depth=5,           # Limit depth to prevent overfitting
        learning_rate=0.1,
        subsample=0.8,         # Use 80% of data per tree
        colsample_bytree=0.8,  # Use 80% of features per tree
        random_state=42
    )

    # Train with cross-validation
    if verbose:
        print("\nTraining with 5-fold cross-validation...\n")

    train_metrics = classifier.train(
        X_train,
        y_train,
        cv_splits=5,
        verbose=verbose
    )

    # Evaluate on test set
    if verbose:
        print(f"\nEvaluating on test set...\n")

    test_metrics = classifier.evaluate(
        X_test,
        y_test,
        threshold=0.5,
        verbose=verbose
    )

    # Store metrics for later
    classifier.train_metrics = train_metrics
    classifier.test_metrics = test_metrics

    return classifier


def save_model(classifier, verbose=True):
    """
    Save trained model to disk.

    Args:
        classifier: Trained SetupClassifier
        verbose: Print progress
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"SAVING MODEL")
        print(f"{'='*80}\n")

    # Create models directory
    os.makedirs('models', exist_ok=True)

    # Save with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_path = f'models/setup_classifier_stationary_{timestamp}'

    classifier.save(model_path)

    if verbose:
        print(f"✅ Model saved to {model_path}.joblib")

    # Also save as 'latest'
    classifier.save('models/setup_classifier_latest')

    if verbose:
        print(f"✅ Model saved to models/setup_classifier_latest.joblib")


def verify_model(verbose=True):
    """
    Load and verify saved model works.

    Args:
        verbose: Print progress
    """
    if verbose:
        print(f"\n{'='*80}")
        print(f"VERIFYING MODEL")
        print(f"{'='*80}\n")

    # Load model
    classifier = SetupClassifier.load('models/setup_classifier_latest')

    if verbose:
        print(f"✅ Model loaded successfully:")
        print(f"   Status: {classifier}")
        print(f"   Features: {len(classifier.feature_names)}")
        print(f"   Top 5 important features:")

        for i, row in classifier.feature_importance.head(5).iterrows():
            print(f"      {i+1}. {row['feature']:30s} {row['importance']:.4f}")


def main():
    parser = argparse.ArgumentParser(description='Train ML model with stationary features')
    parser.add_argument('--days', type=int, default=60, help='Days of historical data (default: 60)')
    parser.add_argument('--relaxed-params', action='store_true', help='Use relaxed parameters for more setups')
    parser.add_argument('--verbose', action='store_true', default=True, help='Print verbose output')
    parser.add_argument('--quiet', action='store_true', help='Suppress output')

    args = parser.parse_args()
    verbose = args.verbose and not args.quiet

    try:
        # Print header
        if verbose:
            print(f"\n{'#'*80}")
            print(f"# ML MODEL TRAINING - STATIONARY FEATURES")
            if args.relaxed_params:
                print(f"# MODE: RELAXED PARAMETERS (more setups)")
            else:
                print(f"# MODE: STRICT PARAMETERS (default)")
            print(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'#'*80}\n")

        # Step 1: Fetch data
        df = fetch_historical_data(days=args.days, verbose=verbose)

        # Step 2: Run backtest with parameter mode
        setups, trades = run_backtest(df, relaxed_params=args.relaxed_params, verbose=verbose)

        # Step 3: Extract features
        df_features = extract_features(df, setups, trades, verbose=verbose)

        # Step 4: Train model
        classifier = train_model(df_features, verbose=verbose)

        # Step 5: Save model
        save_model(classifier, verbose=verbose)

        # Step 6: Verify
        verify_model(verbose=verbose)

        # Print summary
        if verbose:
            print(f"\n{'='*80}")
            print(f"✅ TRAINING COMPLETE!")
            print(f"{'='*80}\n")
            print(f"Summary:")
            print(f"  Training samples: {len(df_features)}")
            print(f"  CV AUC: {classifier.train_metrics['mean_cv_auc']:.4f} (+/- {classifier.train_metrics['std_cv_auc']:.4f})")
            print(f"  Test AUC: {classifier.test_metrics['auc']:.4f}")
            print(f"  Test Accuracy: {classifier.test_metrics['accuracy']:.4f}")
            print(f"  Test Precision: {classifier.test_metrics['precision']:.4f}")
            print(f"  Test Recall: {classifier.test_metrics['recall']:.4f}")
            print(f"\nModel saved to: models/setup_classifier_latest.joblib")
            print(f"\nNext steps:")
            print(f"  1. Review model performance metrics above")
            print(f"  2. Run backtest with ML filter to test (see ML_RETRAINING_GUIDE.md)")
            print(f"  3. Integrate into live trading (optional, see Step 8 in guide)")
            print(f"\n{'='*80}\n")

        return 0

    except Exception as e:
        if verbose:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
