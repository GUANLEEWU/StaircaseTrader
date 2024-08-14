import os
import shutil

# Define the files and directories to keep
keep_files = {
    "Staircase 1.0.py", 
    "bybitTrader.py", 
    "napilib.py", 
    "secret0.py"
}
keep_dirs = {"__pycache__"}

# List all files and directories in the current directory
for item in os.listdir():
    if item not in keep_files and item not in keep_dirs:
        if os.path.isfile(item):
            # Remove file
            os.remove(item)
            print(f"Removed file: {item}")
        elif os.path.isdir(item):
            # Remove directory and its contents
            shutil.rmtree(item)
            print(f"Removed directory: {item}")