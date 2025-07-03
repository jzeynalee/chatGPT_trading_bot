import asyncio
import os
import pandas as pd
from datetime import datetime

from websocket_client_real_time import WebSocketClient
from core import get_multi_df
from indicator import IndicatorCalculator
from strategy import strategy_macd_ichimoku
from trade_planner import TradePlanner
from trader import Trader
from signal_checker import SignalChecker
from notifier import Notifier
from logger import get_logger

# === CONFIG ===
API_KEY = "your_api_key"
API_SECRET = "your_secret_key"
EQUITY = 10000
SIGNAL_FILE = "signals.csv"
SYMBOLS = ["btc_usdt", "eth_usdt"]
TIMEFRAMES = ["1min"]

# === LOGGING ===
logger = get_logger("app")

# === COMPONENTS ===
planner = TradePlanner(equity=EQUITY)
trader = Trader(api_key=API_KEY, secret_key=API_SECRET)
notifier = Notifier()
checker = SignalChecker(signal_file=SIGNAL_FILE, trader=trader, notifier=notifier)

# === INIT SIGNAL DB ===
if not os.path.exists(SIGNAL_FILE):
    pd.DataFrame(columns=["symbol", "entry", "direction", "sl", "tp", "position_size", "status"]).to_csv(SIGNAL_FILE, index=False)
    logger.info("Created new signal file: signals.csv")

# === SIGNAL HANDLER ===
def on_new_signal(signal: dict, atr: float):
    trade_plan = planner.plan_trade(signal, atr)
    logger.info(f"[TRADE PLAN] {trade_plan}")

    response = trader.place_order(
        symbol=trade_plan["symbol"],
        side=trade_plan["direction"],
        amount=trade_plan["position_size"],
        price=trade_plan["entry"],
        order_type="market"
    )
    logger.info(f"[ORDER SENT] {response}")

    df_log = pd.read_csv(SIGNAL_FILE)
    new_entry = {
        "symbol": trade_plan["symbol"],
        "entry": trade_plan["entry"],
        "direction": trade_plan["direction"],
        "sl": trade_plan["sl"],
        "tp": trade_plan["tp"],
        "position_size": trade_plan["position_size"],
        "status": "OPEN"
    }
    df_log = pd.concat([df_log, pd.DataFrame([new_entry])], ignore_index=True)
    df_log.to_csv(SIGNAL_FILE, index=False)
    logger.info(f"Logged new trade for {signal['symbol']} at {signal['entry']}")

# === TICK HANDLER ===
def on_tick():
    checker.check_signals()

# === HANDLE INCOMING MESSAGE FROM WS ===
async def handle_message(data, df_store, order_books):
    if 'ticker' in data.get('subscribe', ''):
        symbol = data['subscribe'].split('.')[-1]
        tf = "1min"  # You can make this dynamic if needed

        try:
            # Append new close price to df
            tick_price = float(data['tick']['latest'])
            ts = datetime.utcfromtimestamp(data['ts'] / 1000)

            df = df_store[symbol][tf]
            if df['timestamp'].iloc[-1] < ts:
                new_row = df.iloc[-1].copy()
                new_row['timestamp'] = ts
                new_row['close_price'] = tick_price
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                df = df.iloc[-100:]
                df_store[symbol][tf] = df

                calc = IndicatorCalculator(df)
                df = calc.calculate_macd().calculate_ichimoku().get_df()

                result = strategy_macd_ichimoku(df)
                if result:
                    signal = {
                        "symbol": symbol,
                        "entry": tick_price,
                        "direction": result
                    }
                    logger.info(f"[SIGNAL DETECTED] {signal}")
                    atr = df['high_price'].rolling(14).max().iloc[-1] - df['low_price'].rolling(14).min().iloc[-1]
                    on_new_signal(signal, atr)

            # Check signals after tick processed
            on_tick()

        except Exception as e:
            logger.error(f"[DATA HANDLER ERROR] {symbol}: {e}")

# === MAIN ===
if __name__ == "__main__":
    logger.info("🔄 Starting LBank Trading Bot...")
    ws_client = WebSocketClient(symbols=SYMBOLS, timeframes=TIMEFRAMES, on_message_callback=handle_message)
    asyncio.run(ws_client.connect())
