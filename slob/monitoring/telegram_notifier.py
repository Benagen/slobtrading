"""
Telegram Notifier for SLOB Trading System

Sends real-time alerts to Telegram for:
- Setup detection
- Order placement
- Trade completion (P&L)
- Errors and warnings

Setup:
1. Create bot via @BotFather
2. Get bot token
3. Send message to bot, then get chat ID from:
   https://api.telegram.org/bot<TOKEN>/getUpdates

Environment variables:
- TELEGRAM_BOT_TOKEN: Bot token from @BotFather
- TELEGRAM_CHAT_ID: Your chat ID
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Send trading alerts to Telegram.

    Usage:
        notifier = TelegramNotifier()
        notifier.notify_setup_detected(setup_data)
        notifier.notify_order_placed(order_data)
    """

    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "Telegram notifications DISABLED - "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable"
            )
        else:
            logger.info(f"✅ Telegram notifications enabled (chat_id: {self.chat_id})")

    def send_alert(self, message: str, level: str = "INFO"):
        """
        Send generic alert to Telegram.

        Args:
            message: Alert message
            level: INFO, WARNING, ERROR, SUCCESS
        """
        if not self.enabled:
            return

        try:
            import requests

            emoji_map = {
                "INFO": "ℹ️",
                "WARNING": "⚠️",
                "ERROR": "🚨",
                "SUCCESS": "✅",
                "SETUP": "📊",
                "ORDER": "🎯",
                "TRADE": "💰"
            }

            emoji = emoji_map.get(level, "📢")
            formatted_message = f"{emoji} {message}"

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            response = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": formatted_message,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            response.raise_for_status()

            logger.debug(f"Telegram alert sent: {level}")

        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def notify_setup_detected(self, setup: Dict[str, Any]):
        """
        Alert when a setup is detected.

        Args:
            setup: Setup dictionary with entry, sl, tp, rr_ratio
        """
        try:
            direction = setup.get('direction', 'SHORT')
            entry = setup.get('entry_price', 0)
            sl = setup.get('sl_price', 0)
            tp = setup.get('tp_price', 0)
            rr = setup.get('risk_reward_ratio', 0)
            setup_id = setup.get('id', 'Unknown')[:8]

            message = (
                f"<b>🚨 SETUP DETECTED</b>\n\n"
                f"<b>ID:</b> {setup_id}\n"
                f"<b>Direction:</b> {direction}\n"
                f"<b>Entry:</b> {entry:.2f}\n"
                f"<b>Stop Loss:</b> {sl:.2f}\n"
                f"<b>Take Profit:</b> {tp:.2f}\n"
                f"<b>Risk/Reward:</b> {rr:.2f}\n\n"
                f"<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            )

            self.send_alert(message, "SETUP")

        except Exception as e:
            logger.error(f"Error formatting setup alert: {e}")

    def notify_order_placed(self, order: Dict[str, Any]):
        """
        Alert when an order is placed.

        Args:
            order: Order dictionary with type, symbol, quantity, price
        """
        try:
            order_type = order.get('type', 'UNKNOWN')
            symbol = order.get('symbol', 'NQ')
            quantity = order.get('quantity', 0)
            price = order.get('price', 'MARKET')
            order_id = order.get('order_id', 'Unknown')

            message = (
                f"<b>🎯 ORDER PLACED</b>\n\n"
                f"<b>Order ID:</b> {order_id}\n"
                f"<b>Type:</b> {order_type}\n"
                f"<b>Symbol:</b> {symbol}\n"
                f"<b>Quantity:</b> {quantity}\n"
                f"<b>Price:</b> {price}\n\n"
                f"<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            )

            self.send_alert(message, "ORDER")

        except Exception as e:
            logger.error(f"Error formatting order alert: {e}")

    def notify_trade_closed(self, trade: Dict[str, Any]):
        """
        Alert when a trade is closed with P&L.

        Args:
            trade: Trade dictionary with entry, exit, pnl, duration
        """
        try:
            setup_id = trade.get('setup_id', 'Unknown')[:8]
            entry = trade.get('entry_price', 0)
            exit_price = trade.get('exit_price', 0)
            pnl = trade.get('pnl', 0)
            pnl_pct = trade.get('pnl_percent', 0)
            duration = trade.get('duration_minutes', 0)
            outcome = trade.get('outcome', 'UNKNOWN')

            # Emoji based on outcome
            outcome_emoji = {
                'WIN': '🟢',
                'LOSS': '🔴',
                'BREAKEVEN': '🟡'
            }.get(outcome, '⚪')

            message = (
                f"<b>{outcome_emoji} TRADE CLOSED</b>\n\n"
                f"<b>Setup ID:</b> {setup_id}\n"
                f"<b>Entry:</b> {entry:.2f}\n"
                f"<b>Exit:</b> {exit_price:.2f}\n"
                f"<b>P&L:</b> ${pnl:.2f} ({pnl_pct:+.2f}%)\n"
                f"<b>Duration:</b> {duration} minutes\n"
                f"<b>Outcome:</b> {outcome}\n\n"
                f"<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            )

            self.send_alert(message, "TRADE")

        except Exception as e:
            logger.error(f"Error formatting trade close alert: {e}")

    def notify_error(self, error: str, context: Optional[str] = None):
        """
        Alert on critical errors.

        Args:
            error: Error message
            context: Optional context (e.g., function name)
        """
        try:
            message = f"<b>🚨 ERROR</b>\n\n"

            if context:
                message += f"<b>Context:</b> {context}\n"

            message += (
                f"<b>Error:</b> {error}\n\n"
                f"<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
            )

            self.send_alert(message, "ERROR")

        except Exception as e:
            logger.error(f"Error formatting error alert: {e}")

    def notify_system_status(self, status: str, details: Optional[Dict[str, Any]] = None):
        """
        Send system status update.

        Args:
            status: Status message (e.g., "System Started", "System Stopped")
            details: Optional status details
        """
        try:
            message = f"<b>📊 SYSTEM STATUS</b>\n\n<b>{status}</b>\n"

            if details:
                message += "\n"
                for key, value in details.items():
                    message += f"<b>{key}:</b> {value}\n"

            message += f"\n<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"

            self.send_alert(message, "INFO")

        except Exception as e:
            logger.error(f"Error formatting status alert: {e}")

    def notify_daily_summary(self, stats: Dict[str, Any]):
        """
        Send end-of-day trading summary.

        Args:
            stats: Daily statistics dictionary
        """
        try:
            message = (
                f"<b>📈 DAILY SUMMARY</b>\n\n"
                f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d')}\n\n"
                f"<b>Setups Detected:</b> {stats.get('setups_detected', 0)}\n"
                f"<b>Orders Placed:</b> {stats.get('orders_placed', 0)}\n"
                f"<b>Trades Closed:</b> {stats.get('trades_closed', 0)}\n\n"
                f"<b>Win Rate:</b> {stats.get('win_rate', 0):.1%}\n"
                f"<b>Total P&L:</b> ${stats.get('total_pnl', 0):.2f}\n"
                f"<b>Best Trade:</b> ${stats.get('best_trade', 0):.2f}\n"
                f"<b>Worst Trade:</b> ${stats.get('worst_trade', 0):.2f}\n\n"
                f"<b>Active Positions:</b> {stats.get('active_positions', 0)}"
            )

            self.send_alert(message, "INFO")

        except Exception as e:
            logger.error(f"Error formatting daily summary: {e}")


# Example usage
if __name__ == "__main__":
    # Test notification
    notifier = TelegramNotifier()

    if notifier.enabled:
        notifier.send_alert("🧪 Test alert from SLOB bot", "INFO")

        # Test setup alert
        test_setup = {
            'id': 'test-setup-001',
            'direction': 'SHORT',
            'entry_price': 15297.0,
            'sl_price': 15316.0,
            'tp_price': 15199.0,
            'risk_reward_ratio': 5.2
        }
        notifier.notify_setup_detected(test_setup)

        print("✅ Test alerts sent!")
    else:
        print("❌ Telegram not configured")
