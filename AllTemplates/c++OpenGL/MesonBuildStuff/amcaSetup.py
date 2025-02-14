import os, sys, re, json


################ Bloat ######################
def getNameMesonVarDecl(filepath, variablename):
    regex = re.compile(rf'^{variablename}\s*=')
    out = 'NOT_FOUND'

    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            for line in file:
                if regex.match(line):
                    out = line
                    break
            else:
                print(f"No {variablename} found in {filepath}.")
    except FileNotFoundError:
        print(f"{filepath} not found.")
    except Exception as e:
        print(f"An error occurred Looking for {variablename}: {e}")
    return out

def update_launch_json(output_full):
    vscode_folder = os.path.join(os.getcwd(), ".vscode")
    launch_json_path = os.path.join(vscode_folder, "launch.json")

    if not os.path.exists(launch_json_path):
        print("launch.json not found. Skipping modification.")
        return

    try:
        with open(launch_json_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        for config in data.get("configurations", []):
            config["program"] = "${workspaceFolder}/" + output_full.replace("\\", "/")

        with open(launch_json_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        print("Updated launch.json successfully.")
    except Exception as e:
        print(f"Failed to update launch.json: {e}")

target_file = "meson.build"
basedir = os.path.realpath(os.path.join(__file__, "..\\.."))
meson_file_path = os.path.join(basedir, target_file)

output_dir = getNameMesonVarDecl(meson_file_path, "output_dir").split("'")[1].replace('/', '\\').removeprefix('\\')
output_name = getNameMesonVarDecl(meson_file_path, "output_name").split("'")[1].replace('/', '\\').removeprefix('\\')
build_dir_name = getNameMesonVarDecl(meson_file_path, "build_dir_where").split("'")[1].replace('/', '\\').removeprefix('\\')
output_full = os.path.join(build_dir_name, output_dir, output_name)
################# end bloat ##################

update_launch_json(output_full)

args = ' '.join([sys.argv[x] for x in range(1, len(sys.argv))])

os.chdir(os.path.realpath(os.path.join(__file__, '../..')))
print(''.join(["meson setup ", build_dir_name,  " --wipe ", args]))
sys.exit(os.system(''.join(["meson setup ", build_dir_name,  " --wipe ", args])))