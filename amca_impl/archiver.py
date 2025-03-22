import os
import sys
import json

def is_text_file(filepath, blocksize=512):
    """
    Attempt to read a block of the file as UTF-8.
    Returns True if successful, otherwise False.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            f.read(blocksize)
        return True
    except UnicodeDecodeError:
        return False
    except Exception:
        return False

def process_directory(path):
    """
    Recursively process a directory and return its structure as a dictionary.
    """
    tree = {"type": "directory", "content": {}}
    try:
        entries = os.listdir(path)
    except Exception as e:
        tree["error"] = str(e)
        return tree

    for entry in entries:
        full_path = os.path.join(path, entry)
        if os.path.isdir(full_path):
            tree["content"][entry] = process_directory(full_path)
        elif os.path.isfile(full_path):
            if is_text_file(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    tree["content"][entry] = {
                        "type": "text_file",
                        "content": content
                    }
                except Exception as e:
                    tree["content"][entry] = {
                        "type": "text_file",
                        "error": str(e)
                    }
            else:
                tree["content"][entry] = {
                    "type": "binary_file",
                    "content": None
                }
        else:
            tree["content"][entry] = {
                "type": "unknown"
            }
    return tree

def main():
    if len(sys.argv) != 3:
        print("Usage: python archiver.py <directory> <output_directory>")
        sys.exit(1)

    root_dir = sys.argv[1]
    root_dir = root_dir.rstrip(os.sep)
    base_name = os.path.basename(root_dir)

    tree = {base_name: process_directory(root_dir)}
    output_filename = f".{os.path.join(sys.argv[2], base_name)}_blueprint.json"
    try:
        with open(output_filename, 'w', encoding='utf-8') as outfile:
            json.dump(tree, outfile, indent=2, ensure_ascii=False)
        print(f"Blueprint saved to {output_filename}")
    except Exception as e:
        print(f"Error writing JSON file: {e}")

if __name__ == '__main__':
    main()
