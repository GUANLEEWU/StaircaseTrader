import os
import shutil

# List of files and directories to remove
remove_items = [
    "buy_orders.json",
    "grid_trader.log",
    "open_orders.json",
    "portfolio.json",
    "sell_orders.json",
    "trades_record.csv",
    "order_tracking.json",
]

# Remove the specified files and directories
for item in remove_items:
    if os.path.isfile(item):
        os.remove(item)
        print(f"Removed file: {item}")
    elif os.path.isdir(item):
        shutil.rmtree(item)
        print(f"Removed directory: {item}")
    else:
        print(f"Item not found: {item}")