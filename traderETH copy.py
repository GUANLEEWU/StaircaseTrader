### testing

import sys, os
import napilib as na
from staircaseMain import GridTrader
sys.path.append(os.path.expanduser('~/docus'))
import secret0 # type: ignore

api_key = secret0.api_key_real
secret_key = secret0.secret_key_real
grid_size = 15
buy_size = 0.00005
initial_price = 0
symbol = "BTCUSDT"

targetDB = na.db(secret=secret0.NotionStaticSecret, id=secret0.OrderDBID)
grid_trader = GridTrader(api_key, secret_key, targetDB, grid_size, buy_size, initial_price, symbol, testnet=False, session='test1')
grid_trader.run()
