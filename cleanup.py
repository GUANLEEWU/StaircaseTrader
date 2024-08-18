import os

def remove_json_files(directory):
    # List all files in the specified directory
    for file_name in os.listdir(directory):
        # Check if the file ends with .json
        if file_name.endswith('.json'):
            file_path = os.path.join(directory, file_name)
            try:
                # Remove the file
                os.remove(file_path)
                print(f"Removed file: {file_path}")
            except Exception as e:
                print(f"Error removing file {file_path}: {e}")

if __name__ == "__main__":
    # Specify the directory where you want to remove .json files
    directory = '.'  # Current directory
    remove_json_files(directory)
