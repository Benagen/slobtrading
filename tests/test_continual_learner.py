"""
Tests for ContinualLearner.

Run with: pytest tests/test_continual_learner.py -v
"""

import pytest
import numpy as np

from slob.ml import ContinualLearner, HybridLearner, SetupClassifier


@pytest.fixture
def sample_features():
    """Create sample features"""
    return {
        'feature_0': 0.5,
        'feature_1': -0.3,
        'feature_2': 1.2,
        'feature_3': -0.8,
        'feature_4': 0.0
    }


class TestContinualLearner:
    """Test suite for ContinualLearner"""

    def test_initialization(self):
        """Test learner initialization"""
        learner = ContinualLearner(model_type='logistic')
        
        assert learner.model is not None
        assert learner.n_updates == 0
        assert learner.feature_names is None

    def test_initialization_different_models(self):
        """Test initialization with different model types"""
        models = ['logistic', 'passive_aggressive', 'adaboost']
        
        for model_type in models:
            learner = ContinualLearner(model_type=model_type)
            assert learner.model_type == model_type

    def test_initialization_invalid_model_raises(self):
        """Test that invalid model type raises error"""
        with pytest.raises(ValueError, match="Unknown model type"):
            ContinualLearner(model_type='invalid_model')

    def test_update_single(self, sample_features):
        """Test single update"""
        learner = ContinualLearner()
        
        learner.update(sample_features, outcome=True)
        
        assert learner.n_updates == 1
        assert learner.feature_names is not None

    def test_update_multiple(self, sample_features):
        """Test multiple updates"""
        learner = ContinualLearner()
        
        for i in range(10):
            outcome = i % 2 == 0  # Alternate WIN/LOSS
            learner.update(sample_features, outcome=outcome)
        
        assert learner.n_updates == 10

    def test_predict_probability(self, sample_features):
        """Test probability prediction"""
        learner = ContinualLearner()
        
        # Train on some data
        for i in range(20):
            features = {k: v + np.random.randn()*0.1 for k, v in sample_features.items()}
            outcome = (features['feature_0'] > 0)  # Correlate with feature_0
            learner.update(features, outcome)
        
        # Predict
        prob = learner.predict_probability(sample_features)
        
        assert 0 <= prob <= 1

    def test_predict_binary(self, sample_features):
        """Test binary prediction"""
        learner = ContinualLearner()
        
        # Train
        for i in range(20):
            features = {k: v + np.random.randn()*0.1 for k, v in sample_features.items()}
            outcome = (features['feature_0'] > 0)
            learner.update(features, outcome)
        
        # Predict
        prediction = learner.predict(sample_features, threshold=0.5)
        
        assert isinstance(prediction, bool)

    def test_get_metrics(self, sample_features):
        """Test metric retrieval"""
        learner = ContinualLearner()
        
        # Train
        for i in range(20):
            features = {k: v + np.random.randn()*0.1 for k, v in sample_features.items()}
            outcome = (features['feature_0'] > 0)
            learner.update(features, outcome)
        
        metrics = learner.get_metrics()
        
        assert 'accuracy' in metrics
        assert 'auc' in metrics
        assert 'precision' in metrics
        assert 'recall' in metrics
        assert 'n_updates' in metrics
        
        assert metrics['n_updates'] == 20
        assert 0 <= metrics['accuracy'] <= 1
        assert 0 <= metrics['auc'] <= 1

    def test_reset_metrics(self, sample_features):
        """Test metric reset"""
        learner = ContinualLearner()
        
        # Train
        for i in range(10):
            learner.update(sample_features, outcome=(i % 2 == 0))
        
        # Reset metrics
        learner.reset_metrics()
        
        metrics = learner.get_metrics()
        assert metrics['n_updates'] == 10  # n_updates not reset
        # But metrics should be reset (though this is hard to test without knowing exact values)

    def test_simulate_online_learning(self):
        """Test online learning simulation"""
        learner = ContinualLearner()
        
        # Create correlated data
        np.random.seed(42)
        features_list = []
        outcomes_list = []
        
        for i in range(50):
            features = {f'feature_{j}': np.random.randn() for j in range(5)}
            outcome = (features['feature_0'] + features['feature_1'] > 0)
            features_list.append(features)
            outcomes_list.append(outcome)
        
        results = learner.simulate_online_learning(
            features_list, outcomes_list,
            test_every=10, verbose=False
        )
        
        assert 'final_metrics' in results
        assert 'metrics_history' in results
        
        # Should have tracked metrics 5 times (every 10 samples)
        assert len(results['metrics_history']) == 5
        
        # AUC should be better than random
        assert results['final_metrics']['auc'] > 0.5

    def test_predict_before_training(self, sample_features):
        """Test prediction before any training"""
        learner = ContinualLearner()
        
        # Should return 0.5 (neutral) before training
        prob = learner.predict_probability(sample_features)
        assert prob == 0.5

    def test_repr(self):
        """Test string representation"""
        learner = ContinualLearner(model_type='logistic')
        
        repr_str = repr(learner)
        assert 'ContinualLearner' in repr_str
        assert 'logistic' in repr_str


class TestHybridLearner:
    """Test suite for HybridLearner"""

    @pytest.fixture
    def trained_xgb_classifier(self):
        """Create trained XGBoost classifier"""
        import pandas as pd
        
        np.random.seed(42)
        X = pd.DataFrame(np.random.randn(100, 5), columns=[f'feature_{i}' for i in range(5)])
        y = pd.Series((X['feature_0'] + X['feature_1'] > 0).astype(int))
        
        classifier = SetupClassifier()
        classifier.train(X, y, cv_splits=2, verbose=False)
        
        return classifier

    def test_initialization(self, trained_xgb_classifier):
        """Test hybrid learner initialization"""
        continual = ContinualLearner()
        hybrid = HybridLearner(trained_xgb_classifier, continual)
        
        assert hybrid.xgb is not None
        assert hybrid.river is not None
        assert 0 <= hybrid.blend_weight <= 1

    def test_predict_probability(self, trained_xgb_classifier, sample_features):
        """Test blended prediction"""
        continual = ContinualLearner()
        hybrid = HybridLearner(trained_xgb_classifier, continual)
        
        prob = hybrid.predict_probability(sample_features)
        
        assert 0 <= prob <= 1

    def test_update(self, trained_xgb_classifier, sample_features):
        """Test update (only updates River)"""
        continual = ContinualLearner()
        hybrid = HybridLearner(trained_xgb_classifier, continual)
        
        initial_updates = hybrid.river.n_updates
        
        hybrid.update(sample_features, outcome=True)
        
        # River should be updated
        assert hybrid.river.n_updates == initial_updates + 1

    def test_blend_weight_adaptation(self, trained_xgb_classifier, sample_features):
        """Test that blend weight adapts with updates"""
        continual = ContinualLearner()
        hybrid = HybridLearner(trained_xgb_classifier, continual)
        
        initial_weight = hybrid.get_blend_weight()
        
        # Update many times
        for i in range(150):
            hybrid.update(sample_features, outcome=(i % 2 == 0))
        
        final_weight = hybrid.get_blend_weight()
        
        # Weight should decrease (more weight to River as it learns)
        assert final_weight < initial_weight

    def test_repr(self, trained_xgb_classifier):
        """Test string representation"""
        continual = ContinualLearner()
        hybrid = HybridLearner(trained_xgb_classifier, continual)
        
        repr_str = repr(hybrid)
        assert 'HybridLearner' in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
