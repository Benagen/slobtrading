"""
Continual Learning for Setup Filtering.

Uses River library for online learning - model updates after each trade.
Useful for future live trading where model adapts to new market conditions.
"""

from river import linear_model, preprocessing, metrics, ensemble
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class ContinualLearner:
    """Online learning classifier that updates after each trade"""

    def __init__(self, model_type: str = 'logistic'):
        """
        Initialize Continual Learner.

        Args:
            model_type: Type of online model
                - 'logistic': Logistic Regression
                - 'passive_aggressive': Passive Aggressive Classifier
                - 'adaboost': Adaptive Boosting
        """
        self.model_type = model_type
        
        # Create pipeline with scaler + model
        if model_type == 'logistic':
            model = linear_model.LogisticRegression()
        elif model_type == 'passive_aggressive':
            model = linear_model.PAClassifier()
        elif model_type == 'adaboost':
            model = ensemble.AdaBoostClassifier(
                model=linear_model.LogisticRegression(),
                n_models=10
            )
        else:
            raise ValueError(f"Unknown model type: {model_type}")

        self.model = preprocessing.StandardScaler() | model
        
        # Metrics tracking
        self.metric_accuracy = metrics.Accuracy()
        self.metric_rocauc = metrics.ROCAUC()
        self.metric_precision = metrics.Precision()
        self.metric_recall = metrics.Recall()
        
        self.n_updates = 0
        self.feature_names = None

    def update(self, features: Dict[str, float], outcome: bool):
        """
        Update model with single trade result (online learning).

        Args:
            features: Dict of feature_name -> value
            outcome: True if WIN, False if LOSS
        """
        # Store feature names on first update
        if self.feature_names is None:
            self.feature_names = list(features.keys())

        # Predict first (for metric tracking)
        try:
            y_pred = self.model.predict_proba_one(features)
            win_prob = y_pred.get(True, 0.5)
            
            # Update metrics
            self.metric_accuracy.update(outcome, win_prob > 0.5)
            self.metric_rocauc.update(outcome, win_prob)
            self.metric_precision.update(outcome, win_prob > 0.5)
            self.metric_recall.update(outcome, win_prob > 0.5)
        except:
            # Model not yet initialized
            pass

        # Update model with new observation
        self.model.learn_one(features, outcome)
        self.n_updates += 1

        logger.debug(f"Model updated (n={self.n_updates}). "
                    f"Accuracy: {self.metric_accuracy.get():.3f}, "
                    f"AUC: {self.metric_rocauc.get():.3f}")

    def predict_probability(self, features: Dict[str, float]) -> float:
        """
        Predict win probability for a setup.

        Args:
            features: Dict of feature_name -> value

        Returns:
            Win probability (0-1)
        """
        try:
            proba = self.model.predict_proba_one(features)
            return proba.get(True, 0.5)
        except:
            # Model not yet trained
            return 0.5

    def predict(self, features: Dict[str, float], threshold: float = 0.5) -> bool:
        """
        Predict binary outcome.

        Args:
            features: Dict of feature_name -> value
            threshold: Probability threshold

        Returns:
            True if WIN predicted, False if LOSS
        """
        prob = self.predict_probability(features)
        return prob >= threshold

    def get_metrics(self) -> Dict[str, float]:
        """
        Get current online metrics.

        Returns:
            Dict with accuracy, AUC, precision, recall
        """
        return {
            'accuracy': self.metric_accuracy.get(),
            'auc': self.metric_rocauc.get(),
            'precision': self.metric_precision.get(),
            'recall': self.metric_recall.get(),
            'n_updates': self.n_updates
        }

    def reset_metrics(self):
        """Reset metric trackers (but keep model)"""
        self.metric_accuracy = metrics.Accuracy()
        self.metric_rocauc = metrics.ROCAUC()
        self.metric_precision = metrics.Precision()
        self.metric_recall = metrics.Recall()

    def simulate_online_learning(
        self,
        features_list: list,
        outcomes_list: list,
        test_every: int = 10,
        verbose: bool = True
    ) -> Dict:
        """
        Simulate online learning on historical data.

        Args:
            features_list: List of feature dicts
            outcomes_list: List of outcomes (True/False)
            test_every: Test performance every N samples
            verbose: Print progress

        Returns:
            Dict with simulation results
        """
        if len(features_list) != len(outcomes_list):
            raise ValueError("features_list and outcomes_list must have same length")

        logger.info(f"Simulating online learning on {len(features_list)} samples...")

        metrics_history = []
        
        for i, (features, outcome) in enumerate(zip(features_list, outcomes_list)):
            # Update model
            self.update(features, outcome)

            # Track metrics periodically
            if (i + 1) % test_every == 0:
                current_metrics = self.get_metrics()
                current_metrics['sample'] = i + 1
                metrics_history.append(current_metrics)

                if verbose and (i + 1) % (test_every * 5) == 0:
                    print(f"Sample {i+1}/{len(features_list)}: "
                          f"Accuracy={current_metrics['accuracy']:.3f}, "
                          f"AUC={current_metrics['auc']:.3f}")

        final_metrics = self.get_metrics()

        if verbose:
            print(f"\n{'='*70}")
            print(f"Online Learning Simulation Complete:")
            print(f"{'='*70}")
            print(f"Total samples:   {len(features_list)}")
            print(f"Final Accuracy:  {final_metrics['accuracy']:.3f}")
            print(f"Final AUC:       {final_metrics['auc']:.3f}")
            print(f"Final Precision: {final_metrics['precision']:.3f}")
            print(f"Final Recall:    {final_metrics['recall']:.3f}")
            print(f"{'='*70}\n")

        return {
            'final_metrics': final_metrics,
            'metrics_history': metrics_history
        }

    def __repr__(self) -> str:
        return f"ContinualLearner(model={self.model_type}, updates={self.n_updates}, auc={self.metric_rocauc.get():.3f})"


class HybridLearner:
    """Hybrid approach: XGBoost for initial predictions + River for adaptation"""

    def __init__(self, xgboost_classifier, continual_learner: ContinualLearner):
        """
        Initialize Hybrid Learner.

        Args:
            xgboost_classifier: Trained SetupClassifier (XGBoost)
            continual_learner: ContinualLearner instance
        """
        self.xgb = xgboost_classifier
        self.river = continual_learner
        self.blend_weight = 0.7  # 70% XGBoost, 30% River initially

    def predict_probability(self, features: Dict[str, float]) -> float:
        """
        Blended prediction from both models.

        Args:
            features: Feature dict

        Returns:
            Blended win probability
        """
        # XGBoost prediction (requires DataFrame)
        import pandas as pd
        df_features = pd.DataFrame([features])
        xgb_prob = self.xgb.predict_probability(df_features)[0]

        # River prediction
        river_prob = self.river.predict_probability(features)

        # Blend (weighted average)
        blended_prob = (self.blend_weight * xgb_prob + 
                       (1 - self.blend_weight) * river_prob)

        return blended_prob

    def update(self, features: Dict[str, float], outcome: bool):
        """
        Update River model (XGBoost stays fixed).

        Args:
            features: Feature dict
            outcome: True if WIN
        """
        self.river.update(features, outcome)

        # Gradually increase River weight as it learns
        if self.river.n_updates > 100:
            self.blend_weight = max(0.5, 0.7 - (self.river.n_updates - 100) * 0.001)

    def get_blend_weight(self) -> float:
        """Get current blend weight (for XGBoost)"""
        return self.blend_weight

    def __repr__(self) -> str:
        return (f"HybridLearner(xgb_weight={self.blend_weight:.2f}, "
                f"river_updates={self.river.n_updates})")
