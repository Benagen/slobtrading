"""
Model Training Pipeline for Setup Classifier.

Handles data splitting, training, evaluation, and model persistence.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from pathlib import Path
import logging

from .setup_classifier import SetupClassifier
from ..features import FeatureEngineer

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Training pipeline for setup classifiers"""

    @staticmethod
    def train_pipeline(
        df: pd.DataFrame,
        setups: list,
        trades: list,
        test_size: float = 0.2,
        lookback: int = 100,
        save_path: Optional[str] = None,
        **classifier_kwargs
    ) -> Tuple[SetupClassifier, Dict]:
        """
        Complete training pipeline from setups to trained model.

        Args:
            df: OHLCV DataFrame
            setups: List of setup dicts
            trades: List of trade results
            test_size: Fraction of data for testing (0.2 = 20%)
            lookback: Lookback for feature extraction
            save_path: Path to save model (optional)
            **classifier_kwargs: Additional kwargs for SetupClassifier

        Returns:
            Tuple of (trained_classifier, metrics_dict)
        """
        logger.info("=" * 70)
        logger.info("SLOB SETUP CLASSIFIER - TRAINING PIPELINE")
        logger.info("=" * 70)

        # 1. Extract features
        logger.info(f"\nStep 1: Extracting features from {len(setups)} setups...")
        df_features = FeatureEngineer.create_feature_matrix(
            df, setups, trades, lookback=lookback
        )

        logger.info(f"Features extracted: {df_features.shape[1] - 1} features")  # -1 for label
        logger.info(f"Samples: {len(df_features)}")
        logger.info(f"WIN rate: {df_features['label'].mean():.2%}")

        # 2. Time-based train/test split
        logger.info(f"\nStep 2: Splitting data (test_size={test_size})...")
        X_train, X_test, y_train, y_test = ModelTrainer._time_based_split(
            df_features, test_size=test_size
        )

        logger.info(f"Train set: {len(X_train)} samples ({y_train.mean():.2%} WIN)")
        logger.info(f"Test set:  {len(X_test)} samples ({y_test.mean():.2%} WIN)")

        # 3. Train classifier
        logger.info(f"\nStep 3: Training XGBoost classifier...")
        classifier = SetupClassifier(**classifier_kwargs)
        train_metrics = classifier.train(X_train, y_train, verbose=True)

        # 4. Evaluate on test set
        logger.info(f"\nStep 4: Evaluating on test set...")
        test_metrics = classifier.evaluate(X_test, y_test, verbose=True)

        # 5. Save model
        if save_path:
            logger.info(f"\nStep 5: Saving model to {save_path}...")
            classifier.save(save_path)

        # Combine metrics
        metrics = {
            **train_metrics,
            'test_auc': test_metrics['auc'],
            'test_accuracy': test_metrics['accuracy'],
            'test_precision': test_metrics['precision'],
            'test_recall': test_metrics['recall'],
            'test_f1': test_metrics['f1'],
            'test_confusion_matrix': test_metrics['confusion_matrix'],
            'train_size': len(X_train),
            'test_size': len(X_test),
            'train_win_rate': y_train.mean(),
            'test_win_rate': y_test.mean()
        }

        logger.info("\n" + "=" * 70)
        logger.info("TRAINING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"CV AUC:       {train_metrics['mean_cv_auc']:.4f} (+/- {train_metrics['std_cv_auc']:.4f})")
        logger.info(f"Test AUC:     {test_metrics['auc']:.4f}")
        logger.info(f"Test F1:      {test_metrics['f1']:.4f}")
        logger.info("=" * 70 + "\n")

        return classifier, metrics

    @staticmethod
    def _time_based_split(
        df_features: pd.DataFrame,
        test_size: float = 0.2
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """
        Time-based train/test split (NO shuffling!).

        Args:
            df_features: Feature DataFrame with 'label' column
            test_size: Fraction for test set

        Returns:
            Tuple of (X_train, X_test, y_train, y_test)
        """
        # Time-based split: train on first 80%, test on last 20%
        split_idx = int(len(df_features) * (1 - test_size))

        train = df_features.iloc[:split_idx]
        test = df_features.iloc[split_idx:]

        X_train = train.drop('label', axis=1)
        y_train = train['label']
        X_test = test.drop('label', axis=1)
        y_test = test['label']

        return X_train, X_test, y_train, y_test

    @staticmethod
    def retrain_with_new_data(
        classifier: SetupClassifier,
        df: pd.DataFrame,
        new_setups: list,
        new_trades: list,
        lookback: int = 100,
        save_path: Optional[str] = None
    ) -> Dict:
        """
        Retrain existing classifier with new data.

        Args:
            classifier: Existing trained classifier
            df: OHLCV DataFrame
            new_setups: New setup dicts
            new_trades: New trade results
            lookback: Lookback for feature extraction
            save_path: Path to save updated model

        Returns:
            Dict with retrain metrics
        """
        logger.info(f"Retraining model with {len(new_setups)} new samples...")

        # Extract features from new data
        df_new = FeatureEngineer.create_feature_matrix(
            df, new_setups, new_trades, lookback=lookback
        )

        X_new = df_new.drop('label', axis=1)
        y_new = df_new['label']

        # Retrain (this will add to existing knowledge)
        train_metrics = classifier.train(X_new, y_new, verbose=False)

        if save_path:
            classifier.save(save_path)

        logger.info(f"Retrain complete. New CV AUC: {train_metrics['mean_cv_auc']:.4f}")

        return train_metrics

    @staticmethod
    def analyze_feature_importance(
        classifier: SetupClassifier,
        save_plot: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Analyze and optionally plot feature importances.

        Args:
            classifier: Trained classifier
            save_plot: Path to save importance plot (optional)

        Returns:
            DataFrame with feature importances
        """
        importance = classifier.get_feature_importance(top_n=20)

        print(f"\n{'='*70}")
        print(f"Feature Importance Analysis")
        print(f"{'='*70}")
        print(f"{'Feature':40s} {'Importance':>10s}")
        print(f"{'-'*70}")
        
        for i, row in importance.iterrows():
            print(f"{row['feature']:40s} {row['importance']:10.4f}")
        
        print(f"{'='*70}\n")

        # Optional plotting
        if save_plot:
            try:
                import matplotlib.pyplot as plt
                
                plt.figure(figsize=(12, 8))
                plt.barh(importance['feature'], importance['importance'])
                plt.xlabel('Importance')
                plt.ylabel('Feature')
                plt.title('Top 20 Feature Importances')
                plt.gca().invert_yaxis()
                plt.tight_layout()
                plt.savefig(save_plot, dpi=300, bbox_inches='tight')
                plt.close()
                
                logger.info(f"Feature importance plot saved to {save_plot}")
            except ImportError:
                logger.warning("matplotlib not available for plotting")

        return importance

    @staticmethod
    def compare_models(
        models: Dict[str, SetupClassifier],
        X_test: pd.DataFrame,
        y_test: pd.Series
    ) -> pd.DataFrame:
        """
        Compare multiple models on same test set.

        Args:
            models: Dict of {name: classifier}
            X_test: Test features
            y_test: Test labels

        Returns:
            DataFrame with comparison metrics
        """
        results = []

        for name, classifier in models.items():
            metrics = classifier.evaluate(X_test, y_test, verbose=False)
            
            results.append({
                'model': name,
                'auc': metrics['auc'],
                'accuracy': metrics['accuracy'],
                'precision': metrics['precision'],
                'recall': metrics['recall'],
                'f1': metrics['f1']
            })

        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values('auc', ascending=False)

        print(f"\n{'='*90}")
        print(f"Model Comparison")
        print(f"{'='*90}")
        print(df_results.to_string(index=False))
        print(f"{'='*90}\n")

        return df_results
