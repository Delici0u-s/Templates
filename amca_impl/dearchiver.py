import os
import sys
import json

def create_from_blueprint(data, root_path):
    """
    Recursively reconstructs files and directories from the JSON blueprint.
    """
    for name, details in data.items():
        path = os.path.join(root_path, name)
        
        if details["type"] == "directory":
            os.makedirs(path, exist_ok=True)
            create_from_blueprint(details["content"], path)
        
        elif details["type"] == "text_file":
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(details.get("content", ""))
            except Exception as e:
                print(f"Error writing text file {path}: {e}")

        elif details["type"] == "binary_file":
            try:
                with open(path, 'wb') as f:
                    f.write(b"")
            except Exception as e:
                print(f"Error creating binary file {path}: {e}")

def main():
    if len(sys.argv) != 3:
        print("Usage: python decoder.py <blueprint.json> <target_directory>")
        sys.exit(1)

    blueprint_file = sys.argv[1]
    target_dir = sys.argv[2]

    try:
        with open(blueprint_file, 'r', encoding='utf-8') as f:
            blueprint = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        sys.exit(1)

    root_name, root_content = next(iter(blueprint.items()))
    root_path = os.path.join(target_dir, root_name)
    os.makedirs(root_path, exist_ok=True)

    create_from_blueprint(root_content["content"], root_path)
    print(f"Files restored to: {root_path}")

if __name__ == '__main__':
    print("dearchiver [version:0.0.1]")
    main()
