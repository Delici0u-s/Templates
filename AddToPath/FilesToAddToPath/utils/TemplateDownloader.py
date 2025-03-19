import os, sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote

def main():
    repo_url = "https://github.com/Delici0u-s/Templates/tree/main/AllTemplates"

    links = fetch_links(repo_url)
    available_Folders = getFolders(links)
    printNice(available_Folders)
    selected_Link = links[getSelection(available_Folders)]
    download_github_folder(selected_Link)

def download_github_folder(url: str, destination: str = os.getcwd()):
    parsed_url = urlparse(url)
    path_parts = parsed_url.path.strip('/').split('/')
    
    if len(path_parts) < 4 or path_parts[2] != 'tree':
        raise ValueError("Invalid GitHub folder URL format.")
    
    owner, repo, _, branch, *folder_path = path_parts
    folder_path = '/'.join(folder_path)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{folder_path}?ref={branch}"
    
    headers = {'Accept': 'application/vnd.github.v3+json'}
    response = requests.get(api_url, headers=headers)
    
    if response.status_code != 200:
        raise Exception(f"Failed to fetch folder contents: {response.status_code} - {response.text}")
    
    for item in response.json():
        if item['type'] == 'file':
            file_url = item['download_url']
            file_path = os.path.join(destination, item['name'])
            
            file_response = requests.get(file_url)
            if file_response.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(file_response.content)
            else:
                print(f"Failed to download {file_url}")
        elif item['type'] == 'dir':
            subfolder_path = os.path.join(destination, item['name'])
            os.makedirs(subfolder_path, exist_ok=True)
            download_github_folder(item['html_url'], subfolder_path)
    

def fetch_links(url):
    """Fetch links from the given URL, limited to the same directory."""
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        print(f"Failed to fetch {url}")
        exit()

    soup = BeautifulSoup(response.text, 'html.parser')
    base_path = urlparse(url).path.rstrip('/')

    links = set()
    for a_tag in soup.find_all('a', href=True):
        link = urljoin(url, a_tag['href'])
        parsed_link = urlparse(link)

        # Ensure the link is in the same directory
        if parsed_link.path.startswith(base_path):
            links.add(parsed_link.path)

    links = ["https://github.com" + i for i in links]

    return sorted(links)  # Sort for a cleaner tree structure

def getFolders(urls):
    out = []
    for path in urls:
        out.append(unquote(path.split("/")[-1]))
    return out

def printNice(List: list[str]):
    l = 0
    for idx, i in enumerate(List):
        if l > 100:
            print()
        l += len(i) + 4
        print(f"[{idx}] {i}", end='  ')
    print()

def getSelection(List : list[str]):
    try:
        inp = int(sys.argv[1])
        assert inp > 0 and inp < len(List)
        return inp
    except:
        try:
            return List.index(sys.argv[1])
        except:
            pass
    while True:
        inp = input("Select a valid name or number from the above selection (or q to quit): ")
        if inp == 'q': exit()
        try:
            inp = int(inp)    
            assert inp >= 0 and inp < len(List)
            return inp
        except:
            try:
                return List.index(inp)
            except:
                pass
    
if __name__ == "__main__":
    main()
