"""
XGBoost-based Setup Classifier for ML-filtered trading.

Filters trading setups based on ML-predicted win probability.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix
from typing import Dict, Tuple, Optional, List
import joblib
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class SetupClassifier:
    """XGBoost classifier for filtering trading setups"""

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        learning_rate: float = 0.1,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42
    ):
        """
        Initialize Setup Classifier.

        Args:
            n_estimators: Number of boosting rounds
            max_depth: Maximum tree depth (limit to prevent overfitting)
            learning_rate: Learning rate
            subsample: Subsample ratio of training instances
            colsample_bytree: Subsample ratio of columns per tree
            random_state: Random seed
        """
        self.model = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            eval_metric='logloss',
            random_state=random_state,
            use_label_encoder=False
        )
        
        self.scaler = StandardScaler()
        self.feature_names = None
        self.feature_importance = None
        self.cv_scores = None
        self.is_trained = False

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        cv_splits: int = 5,
        verbose: bool = True
    ) -> Dict:
        """
        Train classifier with time-series cross-validation.

        Args:
            X: Feature matrix
            y: Labels (1=WIN, 0=LOSS)
            cv_splits: Number of CV splits
            verbose: Print training info

        Returns:
            Dict with training metrics:
                - cv_scores: Cross-validation AUC scores
                - mean_cv_auc: Mean CV AUC
                - std_cv_auc: Std dev of CV AUC
                - feature_importance: DataFrame with feature importances
        """
        logger.info(f"Training XGBoost classifier on {len(X)} samples...")

        # Store feature names
        self.feature_names = X.columns.tolist()

        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        X_scaled = pd.DataFrame(X_scaled, columns=self.feature_names)

        # Time-series cross-validation (CRITICAL for time-series data!)
        tscv = TimeSeriesSplit(n_splits=cv_splits)

        # Cross-validation
        logger.info(f"Running {cv_splits}-fold time-series cross-validation...")
        self.cv_scores = cross_val_score(
            self.model, X_scaled, y,
            cv=tscv, scoring='roc_auc', n_jobs=-1
        )

        mean_auc = self.cv_scores.mean()
        std_auc = self.cv_scores.std()

        if verbose:
            print(f"\n{'='*60}")
            print(f"Cross-Validation Results:")
            print(f"{'='*60}")
            print(f"CV AUC: {mean_auc:.4f} (+/- {std_auc:.4f})")
            print(f"Individual fold AUCs: {[f'{score:.4f}' for score in self.cv_scores]}")
            print(f"{'='*60}\n")

        # Train on full dataset
        logger.info("Training final model on full dataset...")
        self.model.fit(X_scaled, y)

        # Calculate feature importances
        self.feature_importance = pd.DataFrame({
            'feature': self.feature_names,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)

        if verbose:
            print(f"Top 10 Most Important Features:")
            print(f"{'-'*60}")
            for i, row in self.feature_importance.head(10).iterrows():
                print(f"{row['feature']:30s} {row['importance']:.4f}")
            print(f"{'='*60}\n")

        self.is_trained = True

        return {
            'cv_scores': self.cv_scores,
            'mean_cv_auc': mean_auc,
            'std_cv_auc': std_auc,
            'feature_importance': self.feature_importance
        }

    def predict_probability(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict win probability for setups.

        Args:
            X: Feature matrix

        Returns:
            Array of win probabilities (0-1)
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")

        # Ensure feature order matches training
        X = X[self.feature_names]

        # Scale
        X_scaled = self.scaler.transform(X)

        # Predict probabilities for class 1 (WIN)
        probabilities = self.model.predict_proba(X_scaled)[:, 1]

        return probabilities

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """
        Predict binary class (WIN/LOSS).

        Args:
            X: Feature matrix
            threshold: Probability threshold for WIN

        Returns:
            Array of predictions (1=WIN, 0=LOSS)
        """
        probabilities = self.predict_probability(X)
        return (probabilities >= threshold).astype(int)

    def evaluate(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        threshold: float = 0.5,
        verbose: bool = True
    ) -> Dict:
        """
        Evaluate model on test set.

        Args:
            X_test: Test features
            y_test: Test labels
            threshold: Probability threshold
            verbose: Print evaluation metrics

        Returns:
            Dict with evaluation metrics:
                - auc: ROC AUC score
                - accuracy: Accuracy
                - precision: Precision
                - recall: Recall
                - f1: F1 score
                - confusion_matrix: Confusion matrix
        """
        y_prob = self.predict_probability(X_test)
        y_pred = (y_prob >= threshold).astype(int)

        auc = roc_auc_score(y_test, y_prob)

        # Classification metrics
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
        
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        
        cm = confusion_matrix(y_test, y_pred)

        if verbose:
            print(f"\n{'='*60}")
            print(f"Test Set Evaluation:")
            print(f"{'='*60}")
            print(f"AUC:        {auc:.4f}")
            print(f"Accuracy:   {accuracy:.4f}")
            print(f"Precision:  {precision:.4f}")
            print(f"Recall:     {recall:.4f}")
            print(f"F1 Score:   {f1:.4f}")
            print(f"\nConfusion Matrix:")
            print(f"              Predicted")
            print(f"              0    1")
            print(f"Actual  0    {cm[0,0]:3d}  {cm[0,1]:3d}")
            print(f"        1    {cm[1,0]:3d}  {cm[1,1]:3d}")
            print(f"{'='*60}\n")

        return {
            'auc': auc,
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'confusion_matrix': cm
        }

    def save(self, path: str):
        """
        Save model to disk.

        Args:
            path: Path to save model (without extension)
        """
        if not self.is_trained:
            raise ValueError("Cannot save untrained model")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save model
        model_path = path.with_suffix('.joblib')
        joblib.dump({
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importance,
            'cv_scores': self.cv_scores
        }, model_path)

        logger.info(f"Model saved to {model_path}")

    @classmethod
    def load(cls, path: str) -> 'SetupClassifier':
        """
        Load model from disk.

        Args:
            path: Path to saved model

        Returns:
            Loaded SetupClassifier instance
        """
        path = Path(path).with_suffix('.joblib')
        
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        data = joblib.load(path)

        # Create instance with default params (will be overwritten)
        classifier = cls()
        classifier.model = data['model']
        classifier.scaler = data['scaler']
        classifier.feature_names = data['feature_names']
        classifier.feature_importance = data['feature_importance']
        classifier.cv_scores = data['cv_scores']
        classifier.is_trained = True

        logger.info(f"Model loaded from {path}")

        return classifier

    def get_feature_importance(self, top_n: int = 10) -> pd.DataFrame:
        """
        Get top N most important features.

        Args:
            top_n: Number of features to return

        Returns:
            DataFrame with top features
        """
        if not self.is_trained:
            raise ValueError("Model must be trained first")

        return self.feature_importance.head(top_n)

    def __repr__(self) -> str:
        status = "trained" if self.is_trained else "untrained"
        return f"SetupClassifier(status={status}, features={len(self.feature_names) if self.feature_names else 0})"
