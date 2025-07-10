import asyncio
import os
import json
import pandas as pd
from datetime import datetime
import logging

from my_modules.websocket_client_real_time import WebSocketClient
#from core import get_multi_df
from my_modules.indicator import IndicatorCalculator
from my_modules.strategy import IchimokuDayStrategy
from my_modules.strategy import TradePlanner
from my_modules.trader import Trader
from my_modules.signalChecker import SignalChecker
from my_modules.notifier.SignalDispatcher import SignalDispatcher
from my_modules.logger import setup_logger

# === Load JSON data from CONFIG file
EQUITY = 10000
with open('config.json', 'r', encoding='utf-8') as file:
    config_data = json.load(file)

SYMBOLS                   = config_data["SYMBOLS"]
TIMEFRAMES                = config_data["TIMEFRAMES"]
WEBSOCKET_TIMEFRAME_CODES = config_data["WEBSOCKET_TIMEFRAME_CODES"]
REST_TIMEFRAME_CODES      = config_data["REST_TIMEFRAME_CODES"]

TELEGRAM_chat_id      = config_data["TELEGRAM"]["chat_id"]
TELEGRAM_token        = config_data["TELEGRAM"]["token"]

TWITTER_api_key       = config_data["TWITTER"]["api_key"]
TWITTER_api_secret    = config_data["TWITTER"]["api_secret"]
TWITTER_access_token  = config_data["TWITTER"]["access_token"]
TWITTER_access_secret = config_data["TWITTER"]["access_secret"]

LINKEDIN_user_name    = config_data["LINKEDIN"]["username"]
TWITTER_password      = config_data["TWITTER"]["password"]

LBANK_api_key         = config_data["LBANK"]["api_key"]
LBANK_api_secret      = config_data["LBANK"]["api_secret"]

SIGNAL_FILE = "signals.csv"

# === LOGGING ===
logger = setup_logger(name="lbank_ws_logger", level=logging.INFO)

# === COMPONENTS ===
planner = TradePlanner(equity=EQUITY)
trader = Trader(api_key=LBANK_api_key, secret_key=LBANK_api_secret)
notifier = SignalDispatcher()
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

                result = IchimokuDayStrategy(df)
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
def main() -> None:
    """Main entry point for the LBank Trading Bot."""
    logger.info("🔄 Starting LBank Trading Bot...")
    ws_client = WebSocketClient(
        symbols=SYMBOLS,
        timeframes=TIMEFRAMES,
        on_message_callback=handle_message
    )
    asyncio.run(ws_client.connect())

if __name__ == "__main__":
    main()

    


    
