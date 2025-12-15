"""
News Calendar Integration.

Filters trades on high-impact economic news days to avoid excessive volatility.

Major events filtered:
- FOMC Meetings (Federal Open Market Committee)
- NFP (Non-Farm Payrolls)
- CPI Releases (Consumer Price Index)
- Fed Chair Speeches
- GDP Releases
- Interest Rate Decisions

Example:
    calendar = NewsCalendar()
    is_safe = calendar.is_trading_allowed(datetime(2024, 1, 15, 16, 30))
"""

import pandas as pd
from datetime import datetime, date, time
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class NewsCalendar:
    """Economic news calendar for filtering high-impact trading days"""

    def __init__(self, events: Optional[List[Dict]] = None):
        """
        Initialize News Calendar.

        Args:
            events: List of event dicts with 'date', 'event', 'impact'
                    If None, uses default 2024-2025 calendar
        """
        if events is None:
            self.events = self._load_default_calendar()
        else:
            self.events = events

        # Convert to DataFrame for easy filtering
        self.df_events = pd.DataFrame(self.events)

        if len(self.df_events) > 0:
            self.df_events['date'] = pd.to_datetime(self.df_events['date']).dt.date

        logger.info(f"News calendar loaded with {len(self.events)} events")

    def is_trading_allowed(
        self,
        dt: datetime,
        impact_filter: List[str] = ['HIGH'],
        hours_blackout_before: int = 2,
        hours_blackout_after: int = 2
    ) -> bool:
        """
        Check if trading is allowed at given datetime.

        Args:
            dt: Datetime to check
            impact_filter: List of impact levels to filter ['HIGH', 'MEDIUM']
            hours_blackout_before: Hours before event to stop trading
            hours_blackout_after: Hours after event to stop trading

        Returns:
            True if trading is allowed, False if news event blocks it
        """
        if len(self.df_events) == 0:
            return True  # No calendar, allow all trading

        check_date = dt.date()

        # Get events on this date
        events_today = self.df_events[
            (self.df_events['date'] == check_date) &
            (self.df_events['impact'].isin(impact_filter))
        ]

        if len(events_today) == 0:
            return True  # No high-impact events today

        # Check if within blackout window
        for _, event in events_today.iterrows():
            event_time = event.get('time')

            if event_time is None:
                # No specific time, blackout entire day
                logger.debug(f"Trading blocked: {event['event']} on {check_date}")
                return False

            # Parse event time
            if isinstance(event_time, str):
                try:
                    event_time = datetime.strptime(event_time, "%H:%M").time()
                except:
                    # Invalid time format, blackout entire day
                    logger.debug(f"Trading blocked: {event['event']} (invalid time)")
                    return False

            # Create event datetime
            event_dt = datetime.combine(check_date, event_time)

            # Calculate blackout window
            blackout_start = event_dt - pd.Timedelta(hours=hours_blackout_before)
            blackout_end = event_dt + pd.Timedelta(hours=hours_blackout_after)

            if blackout_start <= dt <= blackout_end:
                logger.debug(f"Trading blocked: {event['event']} at {event_time} "
                           f"(within {hours_blackout_before}h blackout)")
                return False

        return True

    def get_events_on_date(self, dt: datetime) -> List[Dict]:
        """Get all events on a specific date"""
        check_date = dt.date()

        events = self.df_events[self.df_events['date'] == check_date]

        return events.to_dict('records')

    def filter_setups_by_news(
        self,
        setups: List[Dict],
        df: pd.DataFrame,
        impact_filter: List[str] = ['HIGH'],
        verbose: bool = True
    ) -> List[Dict]:
        """
        Filter out setups that occur during high-impact news.

        Args:
            setups: List of setup dicts (must have 'entry_idx')
            df: OHLCV dataframe (with datetime index)
            impact_filter: Impact levels to filter
            verbose: Print filtering stats

        Returns:
            Filtered list of setups
        """
        filtered = []
        rejected = []

        for setup in setups:
            entry_idx = setup.get('entry_idx')

            if entry_idx is None:
                continue

            entry_time = df.index[entry_idx]

            if self.is_trading_allowed(entry_time, impact_filter=impact_filter):
                filtered.append(setup)
            else:
                rejected.append(setup)

        if verbose:
            print(f"\nNews Calendar Filtering:")
            print(f"  Total setups:      {len(setups)}")
            print(f"  Allowed:           {len(filtered)}")
            print(f"  Rejected (news):   {len(rejected)}")
            print(f"  Filter rate:       {len(rejected)/len(setups)*100:.1f}%")

        return filtered

    def _load_default_calendar(self) -> List[Dict]:
        """
        Load default economic calendar for 2024-2025.

        Note: This is a simplified calendar. For production, scrape from:
        - Forex Factory (https://www.forexfactory.com/calendar)
        - Investing.com Economic Calendar
        - CME Group Event Calendar
        """
        events = [
            # === 2024 FOMC Meetings ===
            {'date': '2024-01-31', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-03-20', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-05-01', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-06-12', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-07-31', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-09-18', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-11-07', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2024-12-18', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},

            # === 2024 NFP (Non-Farm Payrolls) - First Friday of month ===
            {'date': '2024-01-05', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-02-02', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-03-08', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-04-05', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-05-03', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-06-07', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-07-05', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-08-02', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-09-06', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-10-04', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-11-01', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2024-12-06', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},

            # === 2024 CPI (Consumer Price Index) ===
            {'date': '2024-01-11', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-02-13', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-03-12', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-04-10', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-05-15', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-06-12', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-07-11', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-08-14', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-09-11', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-10-10', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-11-13', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},
            {'date': '2024-12-11', 'time': '13:30', 'event': 'CPI - Consumer Price Index', 'impact': 'HIGH'},

            # === 2024 GDP Releases (Quarterly) ===
            {'date': '2024-01-25', 'time': '13:30', 'event': 'GDP Q4 2023', 'impact': 'HIGH'},
            {'date': '2024-04-25', 'time': '13:30', 'event': 'GDP Q1 2024', 'impact': 'HIGH'},
            {'date': '2024-07-25', 'time': '13:30', 'event': 'GDP Q2 2024', 'impact': 'HIGH'},
            {'date': '2024-10-30', 'time': '13:30', 'event': 'GDP Q3 2024', 'impact': 'HIGH'},

            # === 2025 FOMC Meetings ===
            {'date': '2025-01-29', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-03-19', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-05-07', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-06-18', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-07-30', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-09-17', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-11-05', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},
            {'date': '2025-12-17', 'time': '14:00', 'event': 'FOMC Rate Decision', 'impact': 'HIGH'},

            # === 2025 NFP (estimated dates) ===
            {'date': '2025-01-10', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-02-07', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-03-07', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-04-04', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-05-02', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-06-06', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-07-03', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-08-01', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-09-05', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-10-03', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-11-07', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},
            {'date': '2025-12-05', 'time': '13:30', 'event': 'NFP - Non-Farm Payrolls', 'impact': 'HIGH'},

            # === Notable Fed Speeches (examples) ===
            {'date': '2024-08-23', 'time': '10:00', 'event': 'Fed Chair Powell - Jackson Hole Symposium', 'impact': 'HIGH'},
            {'date': '2025-08-22', 'time': '10:00', 'event': 'Fed Chair Powell - Jackson Hole Symposium', 'impact': 'HIGH'},

            # === MEDIUM Impact Events (can be included optionally) ===
            # Retail Sales, Housing Starts, etc. (not included by default)
        ]

        return events

    def add_event(
        self,
        date: str,
        event: str,
        impact: str = 'HIGH',
        time: Optional[str] = None
    ):
        """
        Add custom event to calendar.

        Args:
            date: Date string 'YYYY-MM-DD'
            event: Event name
            impact: 'HIGH', 'MEDIUM', or 'LOW'
            time: Time string 'HH:MM' (optional)
        """
        new_event = {
            'date': date,
            'event': event,
            'impact': impact,
            'time': time
        }

        self.events.append(new_event)

        # Rebuild DataFrame
        self.df_events = pd.DataFrame(self.events)
        self.df_events['date'] = pd.to_datetime(self.df_events['date']).dt.date

        logger.info(f"Added event: {event} on {date}")

    def export_calendar(self, filepath: str):
        """Export calendar to CSV"""
        self.df_events.to_csv(filepath, index=False)
        logger.info(f"Calendar exported to {filepath}")

    @staticmethod
    def from_csv(filepath: str) -> 'NewsCalendar':
        """Load calendar from CSV file"""
        df = pd.read_csv(filepath)
        events = df.to_dict('records')
        return NewsCalendar(events=events)

    def __repr__(self) -> str:
        return f"NewsCalendar(events={len(self.events)})"


if __name__ == "__main__":
    # Example usage
    print("News Calendar Example:\n")

    calendar = NewsCalendar()

    print(f"Loaded {len(calendar.events)} economic events\n")

    # Check specific dates
    test_dates = [
        datetime(2024, 1, 5, 16, 0),   # NFP day
        datetime(2024, 1, 6, 16, 0),   # Day after NFP
        datetime(2024, 1, 31, 15, 0),  # 1h before FOMC
        datetime(2024, 2, 1, 16, 0),   # Normal trading day
    ]

    for dt in test_dates:
        allowed = calendar.is_trading_allowed(dt)
        events = calendar.get_events_on_date(dt)

        print(f"{dt.strftime('%Y-%m-%d %H:%M')}: {'✓ ALLOWED' if allowed else '✗ BLOCKED'}")

        if events:
            for event in events:
                print(f"  → {event['event']} at {event.get('time', 'N/A')}")

        print()

    # Example: Filter setups
    print("\nExample: Filtering setups by news")
    print("(Would filter out setups on FOMC/NFP days)")
