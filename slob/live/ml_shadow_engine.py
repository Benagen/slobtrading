"""
ML Shadow Mode Engine

Runs ML predictions in parallel with rule-based decisions.
Logs all predictions without affecting execution.
Collects data for ML validation.

Purpose:
- Validate ML model performance before enabling active filtering
- Compare ML decisions vs rule-based decisions
- Track agreement/disagreement rates
- Build confidence in ML predictions

Critical Design Principle: NEVER affects live trading execution
- All operations wrapped in try/except
- Runs asynchronously (non-blocking)
- Errors are logged but never propagated
- Trading continues normally even if shadow mode fails
"""

import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

import pandas as pd

from slob.ml.setup_classifier import SetupClassifier
from slob.features.feature_engineer import FeatureEngineer
from slob.live.event_bus import EventBus, EventType
from slob.live.candle_store import CandleStore
from slob.live.state_manager import StateManager
from slob.live.setup_state import SetupCandidate

logger = logging.getLogger(__name__)


class MLShadowEngine:
    """
    Shadow mode execution engine.

    Runs ML predictions alongside rule-based trading without affecting execution.
    All predictions and outcomes are logged for analysis.

    Responsibilities:
    - Subscribe to setup detection events
    - Extract features from live candle data
    - Run ML predictions
    - Log predictions + rule-based decisions
    - Track agreement/disagreement
    - Store results for analysis

    Critical: NEVER affects live trading execution
    """

    def __init__(
        self,
        model_path: str,
        event_bus: EventBus,
        candle_store: CandleStore,
        state_manager: StateManager,
        threshold: float = 0.55
    ):
        """
        Initialize shadow mode engine.

        Args:
            model_path: Path to trained model (.joblib)
            event_bus: Event bus for setup notifications
            candle_store: Access to historical candles
            state_manager: Persistence for shadow results
            threshold: ML probability threshold (default 0.55)
        """
        self.model_path = model_path
        self.event_bus = event_bus
        self.candle_store = candle_store
        self.state_manager = state_manager
        self.threshold = threshold

        # Load ML model
        try:
            self.model = SetupClassifier.load(model_path)
            self.feature_engineer = FeatureEngineer()
            logger.info(f"✅ ML model loaded: {model_path}")
        except Exception as e:
            logger.error(f"❌ Failed to load ML model: {e}")
            raise

        # Shadow mode statistics
        self.predictions_made = 0
        self.agreements = 0
        self.disagreements = 0
        self.errors = 0

        # Subscribe to setup events
        self.event_bus.subscribe(
            EventType.SETUP_DETECTED,
            self._on_setup_detected
        )
        logger.info("✅ Shadow mode subscribed to SETUP_DETECTED events")

    async def _on_setup_detected(self, event: dict):
        """
        Handle setup detection event.

        This runs in parallel with normal execution.
        Does NOT affect whether trade is taken.

        Args:
            event: Event dictionary containing setup
        """
        setup = event.get('setup')
        if not setup:
            logger.warning("Shadow mode received SETUP_DETECTED event without setup")
            return

        try:
            # Extract features from recent candles
            features = await self._extract_features(setup)
            if features is None:
                logger.error(f"Failed to extract features for setup {setup.id[:8]}")
                self.errors += 1
                return

            # Get ML prediction
            ml_probability = self.model.predict_probability(features)[0]
            ml_decision = 'TAKE' if ml_probability >= self.threshold else 'SKIP'

            # Rule-based decision (always TAKE in current system)
            rule_decision = 'TAKE'

            # Track agreement
            agreement = (ml_decision == rule_decision)
            if agreement:
                self.agreements += 1
            else:
                self.disagreements += 1
            self.predictions_made += 1

            # Create shadow result
            shadow_result = {
                'setup_id': setup.id,
                'timestamp': datetime.now(),
                'ml_probability': ml_probability,
                'ml_decision': ml_decision,
                'ml_threshold': self.threshold,
                'rule_decision': rule_decision,
                'agreement': agreement,
                'features': features.to_dict('records')[0] if isinstance(features, pd.DataFrame) else features,
                'model_version': getattr(self.model, 'model_version', 'unknown')
            }

            # Log to console
            self._log_prediction(shadow_result)

            # Save to database (non-blocking)
            try:
                await self.state_manager.save_shadow_result(shadow_result)
            except Exception as e:
                logger.error(f"Failed to save shadow result (non-fatal): {e}")
                # Continue - database write failure shouldn't stop shadow mode

            # Emit shadow event (for monitoring)
            try:
                await self.event_bus.emit(
                    EventType.ML_SHADOW_PREDICTION,
                    shadow_result
                )
            except Exception as e:
                logger.error(f"Failed to emit shadow event (non-fatal): {e}")

        except Exception as e:
            logger.error(f"Shadow mode error (non-fatal): {e}")
            self.errors += 1
            # Never crash - this is shadow mode

    async def _extract_features(self, setup: SetupCandidate) -> Optional[pd.DataFrame]:
        """
        Extract ML features from live candle data.

        Args:
            setup: Setup candidate to extract features for

        Returns:
            DataFrame with 37 features (single row), or None if extraction fails
        """
        try:
            # Get recent candles for feature calculation
            # Need enough candles for ATR (14-20 periods) and volume stats
            candles_df = await self.candle_store.get_recent_candles(
                symbol='NQ',
                limit=200  # Enough for all feature calculations
            )

            if candles_df is None or len(candles_df) < 50:
                logger.warning(f"Insufficient candle data for feature extraction: {len(candles_df) if candles_df is not None else 0} candles")
                return None

            # Convert setup to dict format expected by FeatureEngineer
            setup_dict = self._setup_to_dict(setup)

            # Extract features using FeatureEngineer
            features_dict = self.feature_engineer.extract_features(
                df=candles_df,
                setup=setup_dict
            )

            # Convert to DataFrame (model expects this format)
            return pd.DataFrame([features_dict])

        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            return None

    def _setup_to_dict(self, setup: SetupCandidate) -> Dict[str, Any]:
        """
        Convert SetupCandidate to dictionary format for FeatureEngineer.

        Args:
            setup: SetupCandidate object

        Returns:
            Dictionary with setup fields
        """
        return {
            'id': setup.id,
            'lse_high': setup.lse_high,
            'lse_low': setup.lse_low,
            'liq1_time': setup.liq1_time,
            'liq1_price': setup.liq1_price,
            'liq2_time': setup.liq2_time if setup.liq2_detected else None,
            'liq2_price': setup.liq2_price if setup.liq2_detected else None,
            'entry_time': setup.entry_trigger_time if setup.entry_triggered else None,
            'entry_price': setup.entry_price if setup.entry_triggered else None,
            'direction': 'short',  # SLOB is primarily short strategy
            # Add any other fields FeatureEngineer needs
        }

    def _log_prediction(self, result: dict):
        """
        Log shadow prediction to console.

        Args:
            result: Shadow result dictionary
        """
        setup_id = result['setup_id'][:8]
        ml_prob = result['ml_probability']
        ml_dec = result['ml_decision']
        rule_dec = result['rule_decision']
        agree = '✅' if result['agreement'] else '❌'

        logger.info(
            f"[SHADOW] Setup {setup_id}: "
            f"ML={ml_prob:.1%} → {ml_dec}, "
            f"Rule={rule_dec} {agree}"
        )

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get shadow mode statistics.

        Returns:
            Dictionary with prediction counts and agreement rate
        """
        total = self.predictions_made
        if total == 0:
            agreement_rate = 0.0
        else:
            agreement_rate = self.agreements / total

        return {
            'predictions_made': total,
            'agreements': self.agreements,
            'disagreements': self.disagreements,
            'errors': self.errors,
            'agreement_rate': agreement_rate,
            'threshold': self.threshold
        }

    def log_statistics(self):
        """Log current statistics to console."""
        stats = self.get_statistics()
        logger.info(
            f"[SHADOW STATS] Predictions: {stats['predictions_made']}, "
            f"Agreement: {stats['agreement_rate']:.1%}, "
            f"Errors: {stats['errors']}"
        )


# Singleton instance management
_shadow_engine_instance: Optional[MLShadowEngine] = None


def get_shadow_engine() -> Optional[MLShadowEngine]:
    """Get global shadow engine instance."""
    return _shadow_engine_instance


def set_shadow_engine(engine: MLShadowEngine):
    """Set global shadow engine instance."""
    global _shadow_engine_instance
    _shadow_engine_instance = engine
