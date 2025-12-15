"""
5/1 SLOB Model Backtester
Trading Strategy: Liquidity-based reversal trading on US100

Author: Your trading team
Date: 2024
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import List, Dict, Tuple, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

class SLOBConfig:
    """Configuration for 5/1 SLOB strategy"""
    
    # Market & Instrument
    SYMBOL = "NQ=F"  # US100 futures (Nasdaq 100)
    
    # Time Configuration (UTC+2 Stockholm)
    TIMEZONE = pytz.timezone('Europe/Stockholm')
    ASIA_START = "02:00"
    ASIA_END = "09:00"
    LSE_START = "09:00"
    LSE_END = "15:30"
    NYSE_START = "15:30"
    NYSE_END = "22:00"
    
    # Strategy Parameters
    CONSOLIDATION_MIN_PIPS = 20
    CONSOLIDATION_MAX_PIPS = 150
    CONSOLIDATION_MIN_DURATION_MINUTES = 15
    CONSOLIDATION_MAX_DURATION_MINUTES = 30
    CONSOLIDATION_PERCENT_MIN = 0.002  # 0.2%
    CONSOLIDATION_PERCENT_MAX = 0.005  # 0.5%
    
    # No-wick candle criteria
    NO_WICK_MAX_PIPS = 8
    NO_WICK_MAX_PERCENT = 0.20  # Max 20% of candle range
    NO_WICK_MIN_BODY_PIPS = 15
    NO_WICK_MAX_BODY_PIPS = 60
    
    # Entry criteria
    MAX_RETRACEMENT_PIPS = 100  # Max pips price can go up after no-wick before invalidation
    
    # Risk Management
    INITIAL_CAPITAL = 50000  # SEK
    POSITION_SIZE_PERCENT = 0.50  # 50% of capital
    INITIAL_POSITION_PERCENT = 0.70  # 70% of position size
    ADD_ON_PERCENT = 0.30  # 30% add-on at 50% pullback
    MIN_SL_PIPS = 10
    MAX_SL_PIPS = 60
    MIN_RR = 1.5
    MAX_RR = 2.5
    MAX_TRADES_PER_DAY = 2
    
    # Optimal trading window
    OPTIMAL_START = "16:00"
    OPTIMAL_END = "17:30"
    
    # News filter times
    NEWS_BLACKOUT_START = "19:00"
    NEWS_BLACKOUT_END = "22:00"
    
    # Backtesting period
    BACKTEST_DAYS = 30


# ============================================================================
# DATA ACQUISITION
# ============================================================================

class DataFetcher:
    """Fetch and prepare market data"""
    
    @staticmethod
    def fetch_us100_data(days: int = 30) -> pd.DataFrame:
        """
        Fetch US100 M1 data from yfinance
        
        Note: yfinance has limitations on M1 data availability
        For production, consider using a proper data provider
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        print(f"Fetching US100 data from {start_date.date()} to {end_date.date()}...")
        
        # Fetch data - yfinance uses NQ=F for Nasdaq futures
        ticker = yf.Ticker(SLOBConfig.SYMBOL)
        
        # Try to get 1-minute data (limited availability)
        df = ticker.history(start=start_date, end=end_date, interval="1m")
        
        if df.empty:
            print("Warning: No M1 data available. Trying 5m data...")
            df = ticker.history(start=start_date, end=end_date, interval="5m")
        
        if df.empty:
            raise ValueError("Could not fetch data. Check symbol and date range.")
        
        # Convert to Stockholm timezone
        df.index = df.index.tz_convert(SLOBConfig.TIMEZONE)
        
        # Add pip calculation (for indices, 1 point = 1 pip typically)
        df['Range_Pips'] = df['High'] - df['Low']
        df['Body_Pips'] = abs(df['Close'] - df['Open'])
        df['Upper_Wick_Pips'] = df['High'] - df[['Open', 'Close']].max(axis=1)
        df['Lower_Wick_Pips'] = df[['Open', 'Close']].min(axis=1) - df['Low']
        
        # Add session markers
        df['Hour'] = df.index.hour
        df['Minute'] = df.index.minute
        df['Time'] = df.index.strftime('%H:%M')
        df['Date'] = df.index.date
        df['Weekday'] = df.index.dayofweek  # 0=Monday, 4=Friday
        
        # Mark sessions
        df['Session'] = df.apply(DataFetcher._mark_session, axis=1)
        
        # Filter only weekdays
        df = df[df['Weekday'] < 5]
        
        print(f"Loaded {len(df)} candles")
        return df
    
    @staticmethod
    def _mark_session(row) -> str:
        """Mark which session a candle belongs to"""
        time_str = row['Time']
        
        if "02:00" <= time_str < "09:00":
            return "ASIA"
        elif "09:00" <= time_str < "15:30":
            return "LSE"
        elif "15:30" <= time_str < "22:00":
            return "NYSE"
        else:
            return "CLOSED"


# ============================================================================
# PATTERN DETECTION
# ============================================================================

class PatternDetector:
    """Detect trading patterns and setups"""
    
    @staticmethod
    def identify_session_highs_lows(df: pd.DataFrame, session: str, date) -> Dict:
        """Get session high/low for a specific date"""
        session_data = df[(df['Date'] == date) & (df['Session'] == session)]
        
        if session_data.empty:
            return {'high': None, 'low': None}
        
        return {
            'high': session_data['High'].max(),
            'low': session_data['Low'].min(),
            'high_time': session_data['High'].idxmax(),
            'low_time': session_data['Low'].idxmin()
        }
    
    @staticmethod
    def detect_liquidity_grab(df: pd.DataFrame, idx: int, level: float, 
                            direction: str = 'up') -> bool:
        """
        Detect if a liquidity grab occurred
        
        Args:
            df: DataFrame with OHLCV data
            idx: Current candle index
            level: Liquidity level to check
            direction: 'up' for breaking above, 'down' for breaking below
            
        Returns:
            True if LIQ occurred with volume confirmation
        """
        if idx < 1:
            return False
        
        current = df.iloc[idx]
        previous = df.iloc[idx - 1]
        
        # Check if price broke the level
        if direction == 'up':
            level_broken = current['High'] > level
        else:
            level_broken = current['Low'] < level
        
        # Volume confirmation: current volume > previous volume
        volume_confirm = current['Volume'] > previous['Volume']
        
        return level_broken and volume_confirm
    
    @staticmethod
    def find_consolidation(df: pd.DataFrame, start_idx: int, 
                          max_candles: int = 30) -> Optional[Dict]:
        """
        Find consolidation pattern after LIQ
        
        Returns dict with consolidation info or None
        """
        end_idx = min(start_idx + max_candles, len(df))
        window = df.iloc[start_idx:end_idx]
        
        if len(window) < 15:  # Minimum 15 minutes
            return None
        
        # Calculate range
        high = window['High'].max()
        low = window['Low'].min()
        range_pips = high - low
        
        # Check if within consolidation range
        if not (SLOBConfig.CONSOLIDATION_MIN_PIPS <= range_pips <= 
                SLOBConfig.CONSOLIDATION_MAX_PIPS):
            return None
        
        # Check duration (15-30 minutes)
        duration_minutes = len(window)
        if not (SLOBConfig.CONSOLIDATION_MIN_DURATION_MINUTES <= duration_minutes <= 
                SLOBConfig.CONSOLIDATION_MAX_DURATION_MINUTES):
            return None
        
        return {
            'start_idx': start_idx,
            'end_idx': start_idx + len(window),
            'high': high,
            'low': low,
            'range_pips': range_pips,
            'duration': duration_minutes
        }
    
    @staticmethod
    def is_no_wick_candle(candle: pd.Series, direction: str = 'bullish') -> bool:
        """
        Check if candle qualifies as "no-wick candle"
        
        For SHORT setup: needs bullish (white) candle with minimal upper wick
        For LONG setup: needs bearish (red) candle with minimal lower wick
        """
        # Check if bullish/bearish
        is_bullish = candle['Close'] > candle['Open']
        is_bearish = candle['Close'] < candle['Open']
        
        if direction == 'bullish' and not is_bullish:
            return False
        if direction == 'bearish' and not is_bearish:
            return False
        
        # Check body size (15-60 pips)
        body_pips = candle['Body_Pips']
        if not (SLOBConfig.NO_WICK_MIN_BODY_PIPS <= body_pips <= 
                SLOBConfig.NO_WICK_MAX_BODY_PIPS):
            return False
        
        # Check wick size
        if direction == 'bullish':
            wick_pips = candle['Upper_Wick_Pips']
        else:
            wick_pips = candle['Lower_Wick_Pips']
        
        # Absolute wick limit
        if wick_pips > SLOBConfig.NO_WICK_MAX_PIPS:
            return False
        
        # Relative wick limit (max 20% of candle range)
        if wick_pips > (candle['Range_Pips'] * SLOBConfig.NO_WICK_MAX_PERCENT):
            return False
        
        return True


# ============================================================================
# SETUP IDENTIFICATION
# ============================================================================

class SetupFinder:
    """Find complete 5/1 SLOB setups"""
    
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.setups = []
    
    def find_all_setups(self) -> List[Dict]:
        """
        Scan through data and find all valid 5/1 SLOB setups
        """
        print("\n" + "="*80)
        print("SCANNING FOR 5/1 SLOB SETUPS")
        print("="*80)
        
        dates = self.df['Date'].unique()
        
        for date in dates:
            # Skip weekends
            date_obj = pd.to_datetime(date)
            if date_obj.weekday() >= 5:
                continue
            
            print(f"\nAnalyzing {date}...")
            
            # Get LSE session high/low
            lse_levels = PatternDetector.identify_session_highs_lows(
                self.df, 'LSE', date)
            
            if lse_levels['high'] is None:
                continue
            
            # Look for NYSE liquidation of LSE high (for SHORT setups)
            nyse_data = self.df[(self.df['Date'] == date) & 
                               (self.df['Session'] == 'NYSE')]
            
            if nyse_data.empty:
                continue
            
            self._find_short_setups(nyse_data, lse_levels, date)
        
        print(f"\n{'='*80}")
        print(f"FOUND {len(self.setups)} POTENTIAL SETUPS")
        print(f"{'='*80}\n")
        
        return self.setups
    
    def _find_short_setups(self, nyse_data: pd.DataFrame, 
                           lse_levels: Dict, date) -> None:
        """Find SHORT setups (NYSE liq LSE high)"""
        
        for idx in range(len(nyse_data)):
            global_idx = nyse_data.index[idx]
            df_idx = self.df.index.get_loc(global_idx)
            
            # Check for LIQ #1 (NYSE breaks LSE high)
            if not PatternDetector.detect_liquidity_grab(
                self.df, df_idx, lse_levels['high'], 'up'):
                continue
            
            print(f"  → LIQ #1 detected at {global_idx}")
            
            # Look for consolidation
            consol = PatternDetector.find_consolidation(self.df, df_idx + 1)
            if consol is None:
                continue
            
            print(f"    → Consolidation found: {consol['range_pips']:.1f} pips, "
                  f"{consol['duration']} min")
            
            # Look for no-wick candle (1-5 candles before LIQ #2)
            no_wick_candle = None
            no_wick_idx = None
            
            # Search in consolidation for no-wick candle
            search_start = consol['start_idx']
            search_end = consol['end_idx']
            
            for i in range(search_start, search_end):
                if PatternDetector.is_no_wick_candle(
                    self.df.iloc[i], 'bullish'):
                    no_wick_candle = self.df.iloc[i]
                    no_wick_idx = i
                    print(f"    → No-wick candle at {self.df.index[i]}")
                    break
            
            if no_wick_candle is None:
                continue
            
            # Look for LIQ #2 (sweep of consolidation high)
            liq2_detected = False
            liq2_idx = None
            
            for i in range(no_wick_idx + 1, min(no_wick_idx + 10, len(self.df))):
                if self.df.iloc[i]['High'] > consol['high']:
                    liq2_detected = True
                    liq2_idx = i
                    print(f"    → LIQ #2 at {self.df.index[i]}")
                    break
            
            if not liq2_detected:
                continue
            
            # Look for entry trigger (close below no-wick low)
            entry_idx = None
            no_wick_low = no_wick_candle['Low']
            
            for i in range(liq2_idx, min(liq2_idx + 20, len(self.df))):
                # Check if price went too far (invalidation)
                if self.df.iloc[i]['High'] > (no_wick_candle['High'] + 
                                              SLOBConfig.MAX_RETRACEMENT_PIPS):
                    print(f"    → Setup invalidated: price went too high")
                    break
                
                if self.df.iloc[i]['Close'] < no_wick_low:
                    entry_idx = i + 1  # Enter at next candle open
                    print(f"    → Entry trigger at {self.df.index[i]}")
                    break
            
            if entry_idx is None or entry_idx >= len(self.df):
                continue
            
            # Valid setup found!
            setup = {
                'date': date,
                'type': 'SHORT',
                'liq1_idx': df_idx,
                'liq1_level': lse_levels['high'],
                'consolidation': consol,
                'no_wick_idx': no_wick_idx,
                'no_wick_low': no_wick_low,
                'liq2_idx': liq2_idx,
                'liq2_high': self.df.iloc[liq2_idx]['High'],
                'entry_idx': entry_idx,
                'entry_price': self.df.iloc[entry_idx]['Open'],
                'entry_time': self.df.index[entry_idx],
                'sl_level': self.df.iloc[liq2_idx]['High'],
                'lse_low': lse_levels['low']  # Potential TP
            }
            
            self.setups.append(setup)
            print(f"    ✓ VALID SETUP FOUND!")


# ============================================================================
# BACKTESTING ENGINE
# ============================================================================

class Backtester:
    """Execute and analyze trades based on setups"""
    
    def __init__(self, df: pd.DataFrame, setups: List[Dict]):
        self.df = df
        self.setups = setups
        self.trades = []
        self.capital = SLOBConfig.INITIAL_CAPITAL
    
    def run_backtest(self) -> List[Dict]:
        """Execute all trades and track performance"""
        
        print("\n" + "="*80)
        print("RUNNING BACKTEST")
        print("="*80)
        
        for i, setup in enumerate(self.setups, 1):
            print(f"\nTrade #{i} - {setup['date']} {setup['entry_time']}")
            
            trade = self._execute_trade(setup)
            self.trades.append(trade)
            
            # Update capital
            self.capital += trade['pnl_sek']
            
            print(f"  Entry: {trade['entry_price']:.2f}")
            print(f"  Exit: {trade['exit_price']:.2f}")
            print(f"  P&L: {trade['pnl_sek']:,.2f} SEK ({trade['pnl_percent']:.2f}%)")
            print(f"  Result: {trade['result']}")
            print(f"  Capital: {self.capital:,.2f} SEK")
        
        return self.trades
    
    def _execute_trade(self, setup: Dict) -> Dict:
        """Simulate trade execution and outcome"""
        
        entry_price = setup['entry_price']
        sl_price = setup['sl_level']
        tp_price = setup['lse_low']  # Using LSE low as TP
        
        # Position sizing
        position_value = self.capital * SLOBConfig.POSITION_SIZE_PERCENT
        initial_position = position_value * SLOBConfig.INITIAL_POSITION_PERCENT
        
        # Calculate position size (simplified - assume 1 point = 1 SEK for demo)
        contracts = initial_position / entry_price
        
        # Find exit
        exit_idx = setup['entry_idx']
        exit_price = entry_price
        exit_reason = "TIMEOUT"
        
        # Scan forward for SL or TP hit
        max_scan = min(setup['entry_idx'] + 200, len(self.df))  # Max 200 candles
        
        for i in range(setup['entry_idx'], max_scan):
            candle = self.df.iloc[i]
            
            # Check stop loss (price goes up for SHORT)
            if candle['High'] >= sl_price:
                exit_idx = i
                exit_price = sl_price
                exit_reason = "STOP_LOSS"
                break
            
            # Check take profit (price goes down for SHORT)
            if candle['Low'] <= tp_price:
                exit_idx = i
                exit_price = tp_price
                exit_reason = "TAKE_PROFIT"
                break
        
        # Calculate P&L (SHORT: profit when price goes down)
        pnl_points = entry_price - exit_price
        pnl_sek = pnl_points * contracts
        pnl_percent = (pnl_sek / position_value) * 100
        
        # Determine result
        if pnl_sek > 0:
            result = "WIN"
        elif pnl_sek < 0:
            result = "LOSS"
        else:
            result = "BREAKEVEN"
        
        return {
            'setup': setup,
            'entry_idx': setup['entry_idx'],
            'entry_price': entry_price,
            'entry_time': setup['entry_time'],
            'exit_idx': exit_idx,
            'exit_price': exit_price,
            'exit_time': self.df.index[exit_idx],
            'exit_reason': exit_reason,
            'sl_price': sl_price,
            'tp_price': tp_price,
            'position_value': position_value,
            'contracts': contracts,
            'pnl_points': pnl_points,
            'pnl_sek': pnl_sek,
            'pnl_percent': pnl_percent,
            'result': result
        }


# ============================================================================
# PERFORMANCE ANALYSIS
# ============================================================================

class PerformanceAnalyzer:
    """Analyze backtest results"""
    
    def __init__(self, trades: List[Dict], initial_capital: float):
        self.trades = trades
        self.initial_capital = initial_capital
    
    def generate_report(self) -> None:
        """Generate comprehensive performance report"""
        
        if not self.trades:
            print("\nNo trades to analyze.")
            return
        
        print("\n" + "="*80)
        print("PERFORMANCE REPORT")
        print("="*80)
        
        # Basic stats
        total_trades = len(self.trades)
        wins = [t for t in self.trades if t['result'] == 'WIN']
        losses = [t for t in self.trades if t['result'] == 'LOSS']
        
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
        
        # P&L stats
        total_pnl = sum(t['pnl_sek'] for t in self.trades)
        avg_win = np.mean([t['pnl_sek'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_sek'] for t in losses]) if losses else 0
        
        # Risk/Reward
        avg_rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        # Equity curve
        final_capital = self.initial_capital + total_pnl
        total_return = (total_pnl / self.initial_capital) * 100
        
        print(f"\nTOTAL TRADES: {total_trades}")
        print(f"WINS: {len(wins)} | LOSSES: {len(losses)}")
        print(f"WIN RATE: {win_rate:.1f}%")
        print(f"\nTOTAL P&L: {total_pnl:,.2f} SEK")
        print(f"AVERAGE WIN: {avg_win:,.2f} SEK")
        print(f"AVERAGE LOSS: {avg_loss:,.2f} SEK")
        print(f"AVG RISK/REWARD: 1:{avg_rr:.2f}")
        print(f"\nINITIAL CAPITAL: {self.initial_capital:,.2f} SEK")
        print(f"FINAL CAPITAL: {final_capital:,.2f} SEK")
        print(f"TOTAL RETURN: {total_return:.2f}%")
        
        # Additional metrics
        if self.trades:
            max_win = max(t['pnl_sek'] for t in self.trades)
            max_loss = min(t['pnl_sek'] for t in self.trades)
            print(f"\nMAX WIN: {max_win:,.2f} SEK")
            print(f"MAX LOSS: {max_loss:,.2f} SEK")
        
        print("\n" + "="*80)
    
    def plot_equity_curve(self) -> None:
        """Plot equity curve over time"""
        
        if not self.trades:
            return
        
        equity = [self.initial_capital]
        dates = [self.trades[0]['entry_time']]
        
        for trade in self.trades:
            equity.append(equity[-1] + trade['pnl_sek'])
            dates.append(trade['exit_time'])
        
        plt.figure(figsize=(12, 6))
        plt.plot(dates, equity, linewidth=2, color='#2E86AB')
        plt.fill_between(dates, self.initial_capital, equity, alpha=0.3, color='#2E86AB')
        plt.axhline(y=self.initial_capital, color='gray', linestyle='--', alpha=0.5)
        plt.title('5/1 SLOB Strategy - Equity Curve', fontsize=16, fontweight='bold')
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Capital (SEK)', fontsize=12)
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig('/home/claude/equity_curve.png', dpi=150)
        print("\nEquity curve saved to: equity_curve.png")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main backtesting workflow"""
    
    print("="*80)
    print("5/1 SLOB MODEL BACKTESTER")
    print("="*80)
    print(f"\nSymbol: {SLOBConfig.SYMBOL}")
    print(f"Backtest Period: {SLOBConfig.BACKTEST_DAYS} days")
    print(f"Initial Capital: {SLOBConfig.INITIAL_CAPITAL:,} SEK")
    
    # Step 1: Fetch data
    print("\n[1/5] Fetching market data...")
    df = DataFetcher.fetch_us100_data(SLOBConfig.BACKTEST_DAYS)
    
    # Step 2: Find setups
    print("\n[2/5] Scanning for setups...")
    finder = SetupFinder(df)
    setups = finder.find_all_setups()
    
    if not setups:
        print("\nNo setups found in this period. Try adjusting parameters or extending backtest period.")
        return
    
    # Step 3: Run backtest
    print("\n[3/5] Running backtest...")
    backtester = Backtester(df, setups)
    trades = backtester.run_backtest()
    
    # Step 4: Analyze performance
    print("\n[4/5] Analyzing performance...")
    analyzer = PerformanceAnalyzer(trades, SLOBConfig.INITIAL_CAPITAL)
    analyzer.generate_report()
    
    # Step 5: Generate visualizations
    print("\n[5/5] Generating visualizations...")
    analyzer.plot_equity_curve()
    
    print("\n" + "="*80)
    print("BACKTESTING COMPLETE!")
    print("="*80)
    
    return df, setups, trades


if __name__ == "__main__":
    # Run the backtester
    df, setups, trades = main()
    
    # Optional: Save results to CSV
    if trades:
        trades_df = pd.DataFrame([
            {
                'Date': t['entry_time'].date(),
                'Entry Time': t['entry_time'],
                'Entry Price': t['entry_price'],
                'Exit Time': t['exit_time'],
                'Exit Price': t['exit_price'],
                'Exit Reason': t['exit_reason'],
                'P&L (SEK)': t['pnl_sek'],
                'P&L (%)': t['pnl_percent'],
                'Result': t['result']
            }
            for t in trades
        ])
        trades_df.to_csv('/home/claude/trades_log.csv', index=False)
        print("\nTrades log saved to: trades_log.csv")
