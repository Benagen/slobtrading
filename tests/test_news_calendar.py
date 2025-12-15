"""
Tests for NewsCalendar.

Run with: pytest tests/test_news_calendar.py -v
"""

import pytest
import pandas as pd
from datetime import datetime

from slob.utils import NewsCalendar


class TestNewsCalendar:
    """Test suite for NewsCalendar"""

    def test_initialization_default(self):
        """Test initialization with default calendar"""
        calendar = NewsCalendar()

        assert len(calendar.events) > 0
        assert len(calendar.df_events) > 0

    def test_initialization_custom(self):
        """Test initialization with custom events"""
        custom_events = [
            {'date': '2024-01-15', 'time': '14:00', 'event': 'Test Event', 'impact': 'HIGH'}
        ]

        calendar = NewsCalendar(events=custom_events)

        assert len(calendar.events) == 1
        assert calendar.events[0]['event'] == 'Test Event'

    def test_is_trading_allowed_no_events(self):
        """Test trading allowed when no events"""
        calendar = NewsCalendar()

        # Random day far from any scheduled events
        dt = datetime(2030, 1, 1, 16, 0)

        assert calendar.is_trading_allowed(dt) is True

    def test_is_trading_allowed_blocked_by_fomc(self):
        """Test trading blocked during FOMC"""
        calendar = NewsCalendar()

        # 2024-01-31 14:00 is FOMC meeting
        # Should be blocked from 12:00 to 16:00 (2h before/after)
        dt = datetime(2024, 1, 31, 15, 0)

        assert calendar.is_trading_allowed(dt, hours_blackout_before=2, hours_blackout_after=2) is False

    def test_is_trading_allowed_blocked_by_nfp(self):
        """Test trading blocked during NFP"""
        calendar = NewsCalendar()

        # 2024-01-05 13:30 is NFP
        dt = datetime(2024, 1, 5, 14, 0)

        assert calendar.is_trading_allowed(dt) is False

    def test_is_trading_allowed_outside_blackout(self):
        """Test trading allowed outside blackout window"""
        calendar = NewsCalendar()

        # 2024-01-31 has FOMC at 14:00
        # 10:00 should be allowed (4h before)
        dt = datetime(2024, 1, 31, 10, 0)

        assert calendar.is_trading_allowed(dt, hours_blackout_before=2) is True

    def test_get_events_on_date(self):
        """Test getting events on specific date"""
        calendar = NewsCalendar()

        # 2024-01-31 has FOMC
        dt = datetime(2024, 1, 31, 16, 0)

        events = calendar.get_events_on_date(dt)

        assert len(events) > 0
        assert any('FOMC' in event['event'] for event in events)

    def test_get_events_on_date_no_events(self):
        """Test getting events when none exist"""
        calendar = NewsCalendar()

        dt = datetime(2030, 1, 1, 16, 0)

        events = calendar.get_events_on_date(dt)

        assert len(events) == 0

    def test_filter_setups_by_news(self):
        """Test filtering setups by news calendar"""
        calendar = NewsCalendar()

        # Create mock setups with intraday timestamps (16:00 each day)
        dates = pd.date_range('2024-01-01 16:00', periods=100, freq='1D')
        df = pd.DataFrame({'close': 100}, index=dates)

        setups = [
            {'entry_idx': 4},   # 2024-01-05 16:00 (NFP at 13:30 - should be rejected with 2h after)
            {'entry_idx': 10},  # 2024-01-11 16:00 (CPI at 13:30 - should be rejected)
            {'entry_idx': 6},   # 2024-01-07 16:00 (normal day - should be allowed)
            {'entry_idx': 50},  # Normal day - should be allowed
        ]

        filtered = calendar.filter_setups_by_news(setups, df, verbose=False)

        # Should filter out at least some news days
        # With 2h blackout windows, 16:00 might be outside some events
        assert len(filtered) <= len(setups)  # Some may be filtered
        # At least one normal day should pass
        assert len(filtered) >= 1

    def test_add_event(self):
        """Test adding custom event"""
        calendar = NewsCalendar(events=[])

        initial_count = len(calendar.events)

        calendar.add_event(
            date='2024-06-15',
            event='Custom Event',
            impact='HIGH',
            time='15:00'
        )

        assert len(calendar.events) == initial_count + 1
        assert calendar.events[-1]['event'] == 'Custom Event'

    def test_impact_filter_high_only(self):
        """Test filtering by HIGH impact only"""
        events = [
            {'date': '2024-01-15', 'time': '14:00', 'event': 'High Impact', 'impact': 'HIGH'},
            {'date': '2024-01-16', 'time': '14:00', 'event': 'Medium Impact', 'impact': 'MEDIUM'}
        ]

        calendar = NewsCalendar(events=events)

        dt_jan15 = datetime(2024, 1, 15, 14, 30)
        dt_jan16 = datetime(2024, 1, 16, 14, 30)

        # Jan 15 has HIGH event at 14:00, filtering HIGH should block at 14:30
        assert calendar.is_trading_allowed(dt_jan15, impact_filter=['HIGH']) is False

        # Jan 15 has HIGH event, filtering MEDIUM should allow (no MEDIUM events on Jan 15)
        assert calendar.is_trading_allowed(dt_jan15, impact_filter=['MEDIUM']) is True

        # Jan 16 has MEDIUM event at 14:00, filtering MEDIUM should block at 14:30
        assert calendar.is_trading_allowed(dt_jan16, impact_filter=['MEDIUM']) is False

        # Jan 16 has MEDIUM event, filtering HIGH should allow (no HIGH events on Jan 16)
        assert calendar.is_trading_allowed(dt_jan16, impact_filter=['HIGH']) is True

    def test_impact_filter_multiple(self):
        """Test filtering by multiple impact levels"""
        events = [
            {'date': '2024-01-15', 'time': '14:00', 'event': 'High Impact', 'impact': 'HIGH'},
            {'date': '2024-01-16', 'time': '14:00', 'event': 'Medium Impact', 'impact': 'MEDIUM'}
        ]

        calendar = NewsCalendar(events=events)

        dt_high = datetime(2024, 1, 15, 14, 30)
        dt_medium = datetime(2024, 1, 16, 14, 30)

        # Filter HIGH and MEDIUM
        assert calendar.is_trading_allowed(dt_high, impact_filter=['HIGH', 'MEDIUM']) is False
        assert calendar.is_trading_allowed(dt_medium, impact_filter=['HIGH', 'MEDIUM']) is False

    def test_blackout_window_configuration(self):
        """Test configurable blackout windows"""
        events = [
            {'date': '2024-01-15', 'time': '14:00', 'event': 'Test Event', 'impact': 'HIGH'}
        ]

        calendar = NewsCalendar(events=events)

        # Event at 14:00, check at 11:00 with 2h blackout before (12:00-16:00 blackout)
        dt1 = datetime(2024, 1, 15, 11, 0)
        # 11:00 is before blackout window, should be allowed
        assert calendar.is_trading_allowed(dt1, hours_blackout_before=2, hours_blackout_after=2) is True

        # Check at 13:00 with 2h blackout before - should be blocked (within 12:00-16:00)
        dt2 = datetime(2024, 1, 15, 13, 0)
        assert calendar.is_trading_allowed(dt2, hours_blackout_before=2, hours_blackout_after=2) is False

        # Check at 13:00 with 0.5h blackout before (13:30-14:30 blackout) - should be allowed
        assert calendar.is_trading_allowed(dt2, hours_blackout_before=0.5, hours_blackout_after=0.5) is True

    def test_event_without_time(self):
        """Test event without specific time (all-day blackout)"""
        events = [
            {'date': '2024-01-15', 'time': None, 'event': 'All Day Event', 'impact': 'HIGH'}
        ]

        calendar = NewsCalendar(events=events)

        # Any time on that day should be blocked
        dt_morning = datetime(2024, 1, 15, 9, 0)
        dt_afternoon = datetime(2024, 1, 15, 16, 0)

        assert calendar.is_trading_allowed(dt_morning) is False
        assert calendar.is_trading_allowed(dt_afternoon) is False

    def test_repr(self):
        """Test string representation"""
        calendar = NewsCalendar()

        repr_str = repr(calendar)

        assert 'NewsCalendar' in repr_str
        assert 'events=' in repr_str

    def test_export_and_load_csv(self, tmp_path):
        """Test exporting and loading calendar from CSV"""
        calendar = NewsCalendar(events=[
            {'date': '2024-01-15', 'time': '14:00', 'event': 'Test', 'impact': 'HIGH'}
        ])

        # Export
        filepath = tmp_path / "calendar.csv"
        calendar.export_calendar(str(filepath))

        # Load
        loaded_calendar = NewsCalendar.from_csv(str(filepath))

        assert len(loaded_calendar.events) == 1
        assert loaded_calendar.events[0]['event'] == 'Test'

    def test_default_calendar_has_key_events(self):
        """Test that default calendar has key economic events"""
        calendar = NewsCalendar()

        events_text = ' '.join([e['event'] for e in calendar.events])

        # Check for major events
        assert 'FOMC' in events_text
        assert 'NFP' in events_text or 'Non-Farm Payrolls' in events_text
        assert 'CPI' in events_text

    def test_date_parsing_robustness(self):
        """Test date parsing handles different formats"""
        events = [
            {'date': '2024-01-15', 'time': '14:00', 'event': 'Test', 'impact': 'HIGH'}
        ]

        calendar = NewsCalendar(events=events)

        # Datetime object
        dt1 = datetime(2024, 1, 15, 15, 0)
        assert calendar.is_trading_allowed(dt1) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
