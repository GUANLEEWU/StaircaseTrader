import json
import csv
import numpy as np
from bybitTrader import BybitTrader
import time
import os
import napilib as na
import signal
import sys
import random, socket
import logging, threading
import requests as requests
from logging.handlers import RotatingFileHandler
import traceback
import pytz
from datetime import datetime

sys.path.append(os.path.expanduser('~/docus'))
import secret0

grid_trader = None

tz_Taiwan = pytz.timezone('Asia/Taipei')
def time_in_taiwan(*args):
    return datetime.now(tz_Taiwan).timetuple()

logger = logging.getLogger()
logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler('grid_trader.log', maxBytes=5*1024*1024, backupCount=2)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)
logging.Formatter.converter = time_in_taiwan

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

def get_latest_logs(file_name, num_lines=30):
    try:
        with open(file_name, 'r') as f:
            lines = f.readlines()
            return lines[-num_lines:]  # Get the last num_lines entries
    except Exception as e:
        logging.error(f"Error reading log file {file_name}: {e}")
        return []

class StateManager:
    def __init__(self):
        pass

    def load_state(self, key, default_value):
        return self.load_json_file(key, default_value)

    def save_state(self, key, data):
        self.save_json_file(key, data)

    def load_json_file(self, file_name, default_value):
        if os.path.exists(file_name):
            try:
                with open(file_name, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
                    else:
                        logging.warning(f"Data in {file_name} is not a valid dictionary. Loading default value.")
                        return default_value
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON from {file_name}: {e}. Loading default value.")
                return default_value
        else:
            return default_value
    def save_json_file(self, file_name, data):
        try:
            with open(file_name, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.critical(f"Failed to save file {file_name}: {e}")
            raise

def retry_with_backoff(retries=8, backoff_in_seconds=1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            max_retries = retries
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.RequestException, ConnectionError, TimeoutError, socket.gaierror, socket.timeout) as e:
                    wait_time = backoff_in_seconds * (2 ** attempt) + random.uniform(0, 1)
                    logging.error(f"Connection error: {e}. Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                except Exception as e:
                    if "insufficient" in str(e).lower():
                        logging.error(f"Insufficient balance: {e}. Retrying in {wait_time:.2f} seconds...")
                        time.sleep(wait_time)
                    elif "nodename nor servname provided" in str(e).lower():
                        logging.error(f"DNS resolution error: {e}. Retrying in {wait_time:.2f} seconds...")
                        time.sleep(wait_time)
                    else:
                        logging.critical(f"Unhandled error: {e}. Aborting operation.")
                        if grid_trader:
                            grid_trader.graceful_shutdown()
                        raise
                time.sleep(3)
            logging.critical("Max retries exceeded. Could not complete the request.")
            if grid_trader:
                grid_trader.graceful_shutdown()
            raise
        return wrapper
    return decorator

class GridTrader:
    def __init__(self, api_key, secret_key,naDB,grid_size, buy_size, initial_price, symbol, polling_interval=5, testnet=True,session='not set'):
        self.trader = BybitTrader(api_key, secret_key, testnet=testnet)
        self.db = naDB
        self.logDB = na.db(naDB.secret,'36458b82ef9740b68eb401b732136476')
        self.ActionDB = na.db(naDB.secret,'18b3e4c0c19746e8b114702f6e310846')
        self.OpenOrderDB = na.db(naDB.secret,'06fd76415bf4441f81aeaeb1f8fd12b2')
        self.grid_size = grid_size
        self.buy_size = buy_size
        self.initial_price = initial_price
        self.symbol = symbol
        self.lock = threading.Lock()

        # Initialize state manager and load states
        self.state_manager = StateManager()
        self.buy_orders = self.state_manager.load_state(f'buy_orders_{self.symbol}.json', {})
        self.sell_orders = self.state_manager.load_state(f'sell_orders_{self.symbol}.json', {})
        self.order_tracking = self.state_manager.load_state(f'order_tracking_{self.symbol}.json', {})
        portfolio_data = self.state_manager.load_state(f'portfolio_{self.symbol}.json', {'cumulative_income': 0.0, 'balance': 0.0, 'crypto_holdings': 0.0})
        self.openOrders = self.state_manager.load_state(f'open_orders_{self.symbol}.json', {})
        
        self.cumulative_income = portfolio_data['cumulative_income']
        self.balance = portfolio_data['balance']
        self.crypto_holdings = portfolio_data['crypto_holdings']
        self.portfolio_value = self.get_portfolio_value()

        self.csv_file = f'trades_record_{self.symbol}.csv'
        self.batch_size = 5  # How often to batch save
        self.pending_updates = []
        self.polling_interval = polling_interval
        self.session = session
        
        # Initialize CSV if it doesn't exist
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Time','Buy Price', 'Sell Price', 'Quantity', 'Pair Profit', 'Cumulative Income', 'Portfolio Value', 'Balance', 'Crypto Holdings', 'session'])

        # Signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self.graceful_shutdown)
        signal.signal(signal.SIGTERM, self.graceful_shutdown)


    @retry_with_backoff(retries=8, backoff_in_seconds=1)
    def place_buy_order(self, price):
        try:
            if price not in self.buy_orders:
                order_id = self.trader.create_order("spot", self.symbol, "Buy", "limit", self.buy_size, price=price)
                if order_id:
                    self.buy_orders[price] = order_id
                    logging.info(f"Placed buy order at {price}, Order ID: {order_id}")
                else:
                    logging.warning(f"Failed to place buy order at {price}, no Order ID returned.")
            else:
                logging.info(f"{price} buy order already exists")
        except:
            logging.error(f"Exception occurred while placing buy order at {price}: {e}")
            logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
            raise

    @retry_with_backoff(retries=8, backoff_in_seconds=1)
    def place_sell_order(self, buy_price, qty):
        try:
            sell_price = round(buy_price + self.grid_size, 2)
            if sell_price not in self.sell_orders:
                sell_order_id = self.trader.create_order("spot", self.symbol, "Sell", "limit", qty, price=sell_price)
                if sell_order_id:
                    self.sell_orders[sell_price] = sell_order_id
                    # self.state_manager.save_state('sell_orders', self.sell_orders)
                    temp = na.row()
                    temp.set('Name', "open", 'title')
                    temp.set('side', 'Sell', 'select')
                    temp.set('session', self.session, 'select')
                    temp.set('price', sell_price, 'number')
                    temp.set('qty', qty, 'number')
                    temp.set('status','open','select')
                    self.openOrders.update({sell_order_id:self.OpenOrderDB.add(temp)})
                    logging.info(f"Placed sell order at {sell_price}")
                    return sell_order_id
                else:
                    logging.warning(f"Failed to place sell order at {sell_price}, no Order ID returned.")
            else:
                logging.info(f"Sell order at {sell_price} already exists.")
        except Exception as e:
            logging.error(f"Exception occurred while placing sell order at {sell_price}: {e}")
            logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
            raise
            # logging.error(f"Stack trace: {traceback.format_exc()}")

    def update_portfolio(self, price, qty, fee, side):
        if side == 'Buy':
            self.balance -= (price * qty) + fee
            self.crypto_holdings += qty
        elif side == 'Sell':
            self.balance += (price * qty) - fee
            self.crypto_holdings -= qty
        self.get_portfolio_value()
        # self.state_manager.save_state('portfolio', {
        #     'cumulative_income': self.cumulative_income,
        #     'balance': self.balance,
        #     'crypto_holdings': self.crypto_holdings
        # })

    def get_portfolio_value(self):
        current_eth_price = self.trader.get_index_price(self.symbol)
        portfolio_value = self.balance + (self.crypto_holdings * current_eth_price)
        self.portfolio_value = portfolio_value
        return portfolio_value

    def record_trade(self, buy_price, sell_price, qty, pair_profit):
        self.cumulative_income += pair_profit
        portfolio_value = self.get_portfolio_value()
        cur_time = datetime.now(pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d %H:%M:%S')
        self.pending_updates.append([cur_time,buy_price, sell_price, qty, pair_profit, self.cumulative_income, portfolio_value, self.balance, self.crypto_holdings, self.session])
        if len(self.pending_updates) >= self.batch_size:
            self.flush_updates()

    def flush_updates(self):
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(self.pending_updates)  # Write all pending updates at once
            self.pending_updates.clear()
            logging.info("Flushed pending updates to CSV.")
        except Exception as e:
            logging.error(f"Error flushing updates: {e}")

    def handle_filled_order_callback(self, message):
        with self.lock:
            if not message:
                return
            try:
                for order in message['data']:
                    print(json.dumps(order,indent=2))
                    order_status = order.get('orderStatus')
                    order_id = order.get('orderId')
                    logging.info(f"Processing order with ID: {order_id}, Status: {order_status}")

                    if order_status == 'Filled':
                        
                        filled_price = order.get('avgPrice','')
                        qty = float(order.get('cumExecQty',order['qty']))
                        if not filled_price:
                            value = order.get('cumExecValue','')
                            if value:
                                filled_price = float(value)/float(qty)
                            else:
                                filled_price = order['price']
                        filled_price = float(filled_price)
                        fee = float(order['cumExecFee'])
                        logging.info(f"Order filled - ID: {order_id}, Side: {order['side']}, Price: {filled_price}, Qty: {qty}")
                        
                        if order['side'] == 'Buy':
                            fee_in_usdt = fee * filled_price
                            contribution = - (filled_price * qty) - fee_in_usdt
                            sell_order_id = self.place_sell_order(float(order['price']), qty)
                            self.order_tracking[sell_order_id] = {
                                'filled_price': filled_price,
                                'buy-price': round(float(order['price']), 2),
                                'qty': qty,
                                'fee': fee_in_usdt,
                                'contribution': contribution
                            }
                            self.update_portfolio(filled_price, qty, fee_in_usdt, 'Buy')
                            logging.info(f"Placed corresponding sell order with ID: {sell_order_id}")
                            # self.state_manager.save_state('order_tracking', self.order_tracking)

                            temp = na.row()
                            temp.set('Name', "filled", 'title')
                            temp.set('side', order['side'], 'select')
                            temp.set('contribution', contribution, 'number')
                            temp.set('session', self.session, 'select')
                            temp.set('price', round(float(order['price']), 2), 'number')
                            temp.set('qty', qty, 'number')
                            temp.set('crypto_holding', self.crypto_holdings, 'number')
                            temp.set('portfolio_value',self.portfolio_value, 'number')
                            self.db.add(temp)
                            logging.info(f"Logged filled sell order to database")
                            
                        elif order['side'] == 'Sell':
                            contribution = filled_price * qty - fee
                            buy_order_details = self.order_tracking.pop(order_id, None)
                            if buy_order_details:
                                pair_profit = contribution + buy_order_details['contribution']
                                self.record_trade(
                                    buy_order_details['filled_price'], 
                                    filled_price, 
                                    qty, 
                                    pair_profit
                                )
                                self.update_portfolio(filled_price, qty, fee, 'Sell')
                                logging.info(f"Processed filled sell order - Pair Profit: {pair_profit}")
                                # self.state_manager.save_state('order_tracking', self.order_tracking)
                                
                                temp = na.row()
                                temp.set('Name', "filled", 'title')
                                temp.set('side', order['side'], 'select')
                                temp.set('contribution', contribution, 'number')
                                temp.set('pair_profit', pair_profit, 'number')
                                temp.set('price', round(float(order['price']), 2), 'number')
                                temp.set('session', self.session, 'select')
                                temp.set('pair', f"buy price: {buy_order_details['buy-price']}", 'rich_text')
                                temp.set('qty', qty, 'number')
                                temp.set('crypto_holding', self.crypto_holdings, 'number')
                                temp.set('portfolio_value',self.portfolio_value, 'number')
                                self.db.add(temp)
                                logging.info(f"Logged filled sell order to database")
                                
                                try:
                                    openRowID = self.openOrders[order_id]
                                    openSellOrder = na.row(id=openRowID,secret=self.OpenOrderDB.secret)
                                    openSellOrder.data_d['properties'] = {}
                                    openSellOrder.set('status','filled','select')
                                    openSellOrder.update()   
                                    logging.info(f'marked sell order {openRowID}')
                                except Exception as e:
                                    logging.error(f'Failed to mark sell order as closed: {e}')
                                    logging.error(f'Exception type: {type(e).__name__}')
                                    # logging.error(f'Traceback: {traceback.format_exc()}')
                                self.buy_orders.pop(buy_order_details["buy-price"], None)
                                self.sell_orders.pop(round(float(order["price"]), 2))
                            else:
                                logging.warning('Caught sell order with no matching buy pair.')

            except KeyError as e:
                logging.error(f"KeyError in filled order callback: {e}")
                logging.error(f'Error occurred on line {traceback.format_exc().splitlines()[-2]}')
                logging.error(f'Traceback: {traceback.format_exc()}')
                raise
            except TypeError as e:
                logging.error(f"TypeError occurred: {e}")
                logging.error(f'Error occurred on line {traceback.format_exc().splitlines()[-2]}')
                logging.error(f'Traceback: {traceback.format_exc()}')
                raise
            except Exception as e:
                logging.error(f"Unhandled error in filled order callback: {e}")
                logging.error(f'Error occurred on line {traceback.format_exc().splitlines()[-2]}')
                logging.error(f'Traceback: {traceback.format_exc()}')
                raise

    def checkpoint_state(self):
        try:
            self.state_manager.save_state(f'buy_orders_{self.symbol}.json', self.buy_orders)
            self.state_manager.save_state(f'sell_orders_{self.symbol}.json', self.sell_orders)
            self.state_manager.save_state(f'order_tracking_{self.symbol}.json', self.order_tracking)
            self.state_manager.save_state(f'open_orders_{self.symbol}.json', self.openOrders)
            self.state_manager.save_state(f'portfolio_{self.symbol}.json', {
                'cumulative_income': self.cumulative_income,
                'balance': self.balance,
                'crypto_holdings': self.crypto_holdings
            })
            logging.info("State checkpointed successfully.")
        except Exception as e:
            logging.error(f"Failed to checkpoint state: {e}")
            logging.error(f'Error occurred on line {traceback.format_exc().splitlines()[-2]}')
            self.upload_logs('checkpoint_state')
            
        
    def calculate_next_buy_level(self, current_price):
        n = np.floor((current_price - self.initial_price) / self.grid_size)
        next_level = self.initial_price + n * self.grid_size
        return round(next_level, 2)

    def get_param(self):
        try:
            self.ActionDB.grab()
            for x in self.ActionDB.lrows:
                if x.get('state') == 'adjusting':
                    if x.get('Name') == 'Buy Size':
                        value = x.get('value')
                        if value > 0.08:
                            logging.info('too large')
                            self.buy_size = 0.08
                        else:
                            self.buy_size = value
                        logging.info(f"Buy size changed to {str(self.buy_size)}")
                        try:
                            x.data_d['properties'] = {}
                            x.set('state','is set','select')
                            x.set('note',f"changed to {str(self.buy_size)}",'rich_text')
                            x.secret = secret0.NotionStaticSecret
                            x.update()
                            logging.info("param modification info updated")
                        except Exception as e:
                            logging.error(f"Failed to update modification info: {e}")
                            logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
                            raise
        except Exception as e:
            logging.error(f"Failed to get param: {e}")
            logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
            self.upload_logs('get_param')
    def subscribe_to_websocket(self):
        attempt = 0
        max_retries = 60
        steady_wait_time = 0.5  # Number of seconds to wait between retries

        while True:
            try:
                self.trader.websocket.subscribe_to_order_updates(self.symbol, self.handle_filled_order_callback)
                logging.info(f"Successfully subscribed to WebSocket updates for {self.symbol}")
                break
            except Exception as e:
                if attempt < max_retries:
                    wait_time = steady_wait_time * (attempt + 1)
                else:
                    wait_time = steady_wait_time * max_retries  # Stabilize wait time after max_retries
                logging.error(f"Error during WebSocket subscription: {e}. Retrying in {wait_time} seconds...")
                logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
                time.sleep(wait_time)
                attempt += 1
    def get_index_price(self):
        attempt = 0
        max_retries = 60
        steady_wait_time = 0.5  # Number of seconds to wait between retries

        while True:
            try:
                return self.trader.get_index_price(self.symbol)
            except Exception as e:
                if attempt < max_retries:
                    wait_time = steady_wait_time * (attempt + 1)
                else:
                    wait_time = max_retries * steady_wait_time  # Stabilize wait time after max_retries
                logging.error(f"Error getting index price for {self.symbol}: {e}. Retrying in {wait_time} seconds...")
                logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
                time.sleep(wait_time)
                attempt += 1                
                    
    
    @retry_with_backoff(retries=12, backoff_in_seconds=1)
    def run(self):
        count = 0
        # for i in range(30):
        #     try:
        #         self.trader.websocket.subscribe_to_order_updates(self.symbol, self.handle_filled_order_callback)
        #         break
        #     except Exception as e:
        #         logging.error(f"Failed to subscribe to WebSocket updates: {e}")
        #         logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
        #         if i == 29:
        #             logging.critical("Max retries reached. Could not subscribe to WebSocket updates.")
        #             raise
        #         else:
        #             time.sleep(5)
        self.subscribe_to_websocket()
        while True:
            if not self.trader.websocket.ws.is_connected():
                self.subscribe_to_websocket()
            current_price = self.get_index_price(self.symbol)
            try:
                next_buy_level = self.calculate_next_buy_level(current_price)
                if next_buy_level not in self.buy_orders:
                    self.place_buy_order(next_buy_level)
                if count >= 12:
                    self.checkpoint_state()
                    count = 0
                if count % 2 == 0:
                    self.get_param()
                count += 1
                time.sleep(self.polling_interval)
            except Exception as e:
                logging.error(f"Error occurred: {e}")
                logging.error(f"Error occurred on line {traceback.format_exc().splitlines()[-2]}")
                self.graceful_shutdown()
                

    def upload_logs(self,title='logging'):
        temp = na.row()
        temp.set('Name',title,'title')
        temp.set('detail','\n'.join(get_latest_logs('grid_trader.log',15)),'rich_text')
        self.logDB.add(temp)
    def graceful_shutdown(self, signum=None, frame=None):
        logging.info("Shutting down gracefully...")
        self.checkpoint_state()
        temp = na.row()
        self.upload_logs('graceful_shutdown')
        sys.exit(0)

# api_key = secret0.api_key_real
# secret_key = secret0.secret_key_real
api_key = secret0.apiKeySelf
secret_key = secret0.apiSecretSelf
grid_size = 1
buy_size = 0.001
initial_price = 3.7
symbol = "ETHUSDT"

targetDB = na.db(secret=secret0.NotionStaticSecret, id=secret0.OrderDBID)
grid_trader = GridTrader(api_key, secret_key, targetDB, grid_size, buy_size, initial_price, symbol, testnet=False,session='test0')
grid_trader.run()
#test update
