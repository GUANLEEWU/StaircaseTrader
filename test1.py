import time
import sys, os, json
import napilib as na
from staircaseMain import GridTrader
from bybitTrader import BybitTrader
sys.path.append(os.path.expanduser('~/docus'))
import secret0 # type: ignore
# Assuming BybitTrader is already defined as per your code

def test_get_order_history(trader):
    # Define symbol and time range
    symbol = "BTCUSDT"
    category = "spot"
    
    # Define the start and end time (e.g., from 8/19 00:00 to now)
    # start_time = int(time.mktime(time.strptime("2024-08-19 00:00:00", "%Y-%m-%d %H:%M:%S")) * 1000)
    # start_time = 1724131749928
    start_time = int((time.time()-1) * 1000)
    end_time = int(time.time() * 1000)  # Current time in milliseconds
    print(start_time,end_time)
    # Fetch order history
    order_history = trader.get_order_history(symbol, start_time, end_time, category=category)

    # Print the fetched order history
    if order_history:
        # print(f"Order history for {symbol} from 8/19 00:00 to now:")
        for order in order_history:
            print(json.dumps(order, indent=2))
            # print(f"Order ID: {order['orderId']}, Status: {order['orderStatus']}, Price: {order.get('price')}, Quantity: {order.get('qty')}")
    else:
        print("No order history found or an error occurred.")
        print(order_history)

if __name__ == "__main__":
    
    api_key = secret0.apiKeyProf
    secret_key = secret0.apiSecretProf
    trader = BybitTrader(api_key, secret_key, testnet=False)
    test_get_order_history(trader)
    # trader.cancel_order(id='1756590931362218752',symbol='ETHUSDT',category='spot')
    
    
    # trader.create_order("spot", 'ETHUSDT', "Sell", "limit", 0.001, price=2500)
