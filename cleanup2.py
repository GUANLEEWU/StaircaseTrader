import os
import subprocess

def remove_json_files(directory):
    # List all files in the specified directory
    for file_name in os.listdir(directory):
        # Check if the file ends with .json
        if file_name.endswith('.json'):
            file_path = os.path.join(directory, file_name)
            try:
                # Check if the file is tracked by Git
                result = subprocess.run(['git', 'ls-files', '--error-unmatch', file_path],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                if result.returncode == 0:
                    # If the file is tracked, use git rm
                    subprocess.run(['git', 'rm','-f', file_path], check=True)
                    print(f"Removed tracked file with git: {file_path}")
                else:
                    # If the file is untracked, remove it normally
                    os.remove(file_path)
                    print(f"Removed untracked file: {file_path}")
            except subprocess.CalledProcessError as e:
                print(f"Error removing file {file_path} with git: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")

def commit_changes():
    try:
        # Commit the removal with a message
        subprocess.run(['git', 'commit', '-m', 'Removed .json files'], check=True)
        print("Changes committed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error committing changes: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    # Specify the directory where you want to remove .json files
    directory = '.'  # Current directory
    remove_json_files(directory)
    # Commit the removal
    commit_changes()