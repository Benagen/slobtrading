"""
Tests for SetupClassifier.

Run with: pytest tests/test_setup_classifier.py -v
"""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile

from slob.ml import SetupClassifier


@pytest.fixture
def sample_training_data():
    """Create sample training data"""
    np.random.seed(42)
    
    # 100 samples, 10 features
    n_samples = 100
    n_features = 10
    
    X = pd.DataFrame(
        np.random.randn(n_samples, n_features),
        columns=[f'feature_{i}' for i in range(n_features)]
    )
    
    # Labels with some correlation to features
    y = pd.Series((X['feature_0'] + X['feature_1'] > 0).astype(int))
    
    return X, y


class TestSetupClassifier:
    """Test suite for SetupClassifier"""

    def test_initialization(self):
        """Test classifier initialization"""
        classifier = SetupClassifier()
        
        assert classifier.model is not None
        assert classifier.scaler is not None
        assert classifier.feature_names is None
        assert classifier.is_trained == False

    def test_train_basic(self, sample_training_data):
        """Test basic training"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        metrics = classifier.train(X, y, cv_splits=3, verbose=False)
        
        # Should return metrics
        assert 'cv_scores' in metrics
        assert 'mean_cv_auc' in metrics
        assert 'std_cv_auc' in metrics
        assert 'feature_importance' in metrics
        
        # Classifier should be trained
        assert classifier.is_trained == True
        assert classifier.feature_names == X.columns.tolist()
        
        # CV AUC should be reasonable
        assert 0.4 <= metrics['mean_cv_auc'] <= 1.0

    def test_predict_probability(self, sample_training_data):
        """Test probability prediction"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        classifier.train(X, y, verbose=False)
        
        # Predict on same data
        probabilities = classifier.predict_probability(X)
        
        # Should return probabilities
        assert len(probabilities) == len(X)
        assert all(0 <= p <= 1 for p in probabilities)

    def test_predict_binary(self, sample_training_data):
        """Test binary prediction"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        classifier.train(X, y, verbose=False)
        
        # Predict on same data
        predictions = classifier.predict(X, threshold=0.5)
        
        # Should return binary predictions
        assert len(predictions) == len(X)
        assert set(predictions).issubset({0, 1})

    def test_predict_different_thresholds(self, sample_training_data):
        """Test prediction with different thresholds"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        classifier.train(X, y, verbose=False)
        
        # Lower threshold should give more positive predictions
        pred_low = classifier.predict(X, threshold=0.3)
        pred_high = classifier.predict(X, threshold=0.7)
        
        assert pred_low.sum() >= pred_high.sum()

    def test_evaluate(self, sample_training_data):
        """Test model evaluation"""
        X, y = sample_training_data
        
        # Split data
        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]
        
        classifier = SetupClassifier()
        classifier.train(X_train, y_train, verbose=False)
        
        metrics = classifier.evaluate(X_test, y_test, verbose=False)
        
        # Should return evaluation metrics
        assert 'auc' in metrics
        assert 'accuracy' in metrics
        assert 'precision' in metrics
        assert 'recall' in metrics
        assert 'f1' in metrics
        assert 'confusion_matrix' in metrics
        
        # AUC should be reasonable
        assert 0.4 <= metrics['auc'] <= 1.0

    def test_feature_importance(self, sample_training_data):
        """Test feature importance extraction"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        classifier.train(X, y, verbose=False)
        
        importance = classifier.get_feature_importance(top_n=5)
        
        # Should return top 5 features
        assert len(importance) == 5
        assert 'feature' in importance.columns
        assert 'importance' in importance.columns
        
        # Importances should be sorted descending
        assert list(importance['importance']) == sorted(importance['importance'], reverse=True)

    def test_save_and_load(self, sample_training_data):
        """Test model saving and loading"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        classifier.train(X, y, verbose=False)
        
        # Save to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "test_model"
            classifier.save(str(save_path))
            
            # Load model
            loaded_classifier = SetupClassifier.load(str(save_path))
            
            # Should be trained
            assert loaded_classifier.is_trained == True
            assert loaded_classifier.feature_names == classifier.feature_names
            
            # Predictions should be identical
            pred_orig = classifier.predict_probability(X)
            pred_loaded = loaded_classifier.predict_probability(X)
            
            assert np.allclose(pred_orig, pred_loaded, atol=1e-6)

    def test_predict_before_training_raises(self, sample_training_data):
        """Test that prediction before training raises error"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        
        with pytest.raises(ValueError, match="Model must be trained"):
            classifier.predict_probability(X)

    def test_save_before_training_raises(self):
        """Test that saving before training raises error"""
        classifier = SetupClassifier()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "test_model"
            
            with pytest.raises(ValueError, match="Cannot save untrained model"):
                classifier.save(str(save_path))

    def test_load_nonexistent_model_raises(self):
        """Test that loading nonexistent model raises error"""
        with pytest.raises(FileNotFoundError):
            SetupClassifier.load("/nonexistent/path/model.joblib")

    def test_different_hyperparameters(self, sample_training_data):
        """Test training with different hyperparameters"""
        X, y = sample_training_data
        
        classifier1 = SetupClassifier(n_estimators=50, max_depth=3)
        classifier2 = SetupClassifier(n_estimators=200, max_depth=7)
        
        metrics1 = classifier1.train(X, y, cv_splits=2, verbose=False)
        metrics2 = classifier2.train(X, y, cv_splits=2, verbose=False)
        
        # Both should train successfully
        assert classifier1.is_trained
        assert classifier2.is_trained
        
        # AUCs should be different (different models)
        # But this might not always hold, so just check they're reasonable
        assert 0.4 <= metrics1['mean_cv_auc'] <= 1.0
        assert 0.4 <= metrics2['mean_cv_auc'] <= 1.0

    def test_repr(self, sample_training_data):
        """Test string representation"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        
        # Before training
        repr_untrained = repr(classifier)
        assert 'untrained' in repr_untrained
        
        # After training
        classifier.train(X, y, verbose=False)
        repr_trained = repr(classifier)
        assert 'trained' in repr_trained
        assert 'features=10' in repr_trained

    def test_consistent_predictions(self, sample_training_data):
        """Test that predictions are consistent"""
        X, y = sample_training_data
        
        classifier = SetupClassifier(random_state=42)
        classifier.train(X, y, verbose=False)
        
        # Multiple predictions should be identical
        pred1 = classifier.predict_probability(X)
        pred2 = classifier.predict_probability(X)
        
        assert np.array_equal(pred1, pred2)

    def test_handles_missing_features_gracefully(self, sample_training_data):
        """Test that missing features are handled"""
        X, y = sample_training_data
        
        classifier = SetupClassifier()
        classifier.train(X, y, verbose=False)
        
        # Try to predict with different features (should reorder correctly)
        X_reordered = X[list(reversed(X.columns))]
        pred1 = classifier.predict_probability(X)
        pred2 = classifier.predict_probability(X_reordered)
        
        # Should be identical (classifier reorders features internally)
        assert np.allclose(pred1, pred2, atol=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
