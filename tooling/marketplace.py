"""Build and verify MetroFuse registries from public GitHub release packages."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OWNER = "956tris"
API = "https://api.github.com"
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
FORMATS = {".jar": "desktop", ".apk": "android", ".mfp": "universal"}
TOKEN = None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def request(url, maximum):
    require(urllib.parse.urlsplit(url).scheme == "https", "HTTPS is required")
    headers = {"User-Agent": "MetroFuse-Marketplace", "Accept": "application/vnd.github+json"}
    if TOKEN and urllib.parse.urlsplit(url).netloc == "api.github.com":
        headers["Authorization"] = "Bearer " + TOKEN
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        require(urllib.parse.urlsplit(response.url).scheme == "https", "HTTPS redirect required")
        data = response.read(maximum + 1)
    require(len(data) <= maximum, "Response exceeds MetroFuse size limit")
    return data


def api_pages(path):
    result = []
    for page in range(1, 101):
        separator = "&" if "?" in path else "?"
        items = json.loads(request(f"{API}{path}{separator}per_page=100&page={page}", 16 * 1024 * 1024))
        result.extend(items)
        if len(items) < 100:
            return result
    raise ValueError("GitHub pagination limit reached")


def package(url, expected=None):
    cache = ROOT / ".cache" / (hashlib.sha256(url.encode()).hexdigest() + ".zip")
    data = cache.read_bytes() if cache.exists() else request(url, 64 * 1024 * 1024)
    require(len(data) <= 64 * 1024 * 1024, "Artifact exceeds 64 MiB")
    digest = hashlib.sha256(data).hexdigest()
    if expected:
        require(digest == expected.lower(), f"SHA-256 mismatch: {url}")
    extension = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    manifest_path = "assets/metrofuse/manifest.json" if extension == ".apk" else "manifest.json"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(archive.getinfo(manifest_path).file_size <= 128 * 1024, "Manifest exceeds 128 KiB")
        manifest = json.loads(archive.read(manifest_path))
    require(SEMVER.fullmatch(manifest["version"]), f"Unsupported manifest version: {url}")
    require(SEMVER.fullmatch(manifest["api"]), f"Unsupported API version: {url}")
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(data)
    return manifest, digest


def inspect_asset(item):
    asset, release, repo = item
    expected = asset.get("digest") or ""
    require(not expected or expected.startswith("sha256:"), "Unknown GitHub digest algorithm")
    manifest, digest = package(asset["browser_download_url"], expected.removeprefix("sha256:"))
    extension = Path(asset["name"]).suffix.lower()
    platform = FORMATS[extension]
    require(manifest["runtime"] == ("javascript" if platform == "universal" else "kotlin"), "Runtime mismatch")
    require(manifest.get("platforms"), "Missing manifest platforms")
    if platform != "universal":
        require(platform in manifest["platforms"], "Platform mismatch")
    else:
        require(set(manifest["platforms"]) >= {"android", "desktop"}, "Universal platform mismatch")
    return {
        "manifest": manifest, "platform": platform, "repository": repo["html_url"],
        "releaseTag": release["tag_name"], "releaseChannel": "preview" if release["prerelease"] else "stable",
        "download": {"url": asset["browser_download_url"], "sha256": digest, "fileName": asset["name"]},
    }


def entry(records, javascript=False):
    ordered = sorted(records, key=lambda r: (r["platform"] == "universal") != javascript)
    first = ordered[0]
    manifest = first["manifest"]
    matching = [r for r in ordered if (r["manifest"]["version"], r["manifest"]["api"]) == (manifest["version"], manifest["api"])]
    if javascript and first["platform"] == "universal":
        matching = [first]
    capabilities = sorted({cap for r in matching for cap in r["manifest"].get("capabilities", [])})
    return {
        "id": manifest["id"], "name": manifest["name"], "author": manifest["author"],
        "description": manifest.get("description") or ("MetroFuse JavaScript interface." if "metroflow" in manifest["id"] else "MetroFuse plugin."),
        "version": manifest["version"], "pluginApiVersion": manifest["api"],
        "capabilities": capabilities, "categories": ["Interface" if "ui" in capabilities or "metroflow" in manifest["id"] else "Music"],
        "sourceRepository": first["repository"], "releaseChannel": first["releaseChannel"],
        "downloads": {r["platform"]: r["download"] for r in matching},
    }


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def refresh():
    repos = api_pages(f"/users/{OWNER}/repos?type=owner")
    repos = sorted((r for r in repos if not r["private"] and r["name"].lower().startswith("metrofuse-")), key=lambda r: r["name"].lower())
    inventory, records = [], []
    for repo in repos:
        documentation = repo["name"].lower() == "metrofuse-plugin-docs"
        source = {"repository": repo["html_url"], "name": repo["name"], "description": repo["description"], "kind": "documentation" if documentation else "plugin", "artifacts": []}
        if not documentation:
            releases = api_pages(f"/repos/{OWNER}/{repo['name']}/releases")
            releases = sorted((r for r in releases if not r["draft"]), key=lambda r: (r["prerelease"], -(int(re.sub(r"\D", "", r["published_at"])))) )
            selected = {}
            for release in releases:
                for asset in release["assets"]:
                    extension = Path(asset["name"]).suffix.lower()
                    if extension in FORMATS and extension not in selected:
                        selected[extension] = (asset, release, repo)
            require(selected, f"No published plugin packages: {repo['name']}")
            with ThreadPoolExecutor(max_workers=3) as pool:
                inspected = list(pool.map(inspect_asset, selected.values()))
            records.extend(inspected)
            source["artifacts"] = [{"pluginId": r["manifest"]["id"], "version": r["manifest"]["version"], "runtime": r["manifest"]["runtime"], "platform": r["platform"], "releaseTag": r["releaseTag"], "releaseChannel": r["releaseChannel"], **r["download"]} for r in inspected]
            print(f"Verified {repo['name']}: {len(inspected)} packages", flush=True)
        inventory.append(source)
    groups = {}
    for record in records:
        groups.setdefault(record["manifest"]["id"], []).append(record)
    default = sorted((entry(group) for group in groups.values()), key=lambda e: e["name"].lower())
    javascript = sorted((entry(group, javascript=True) for group in groups.values()), key=lambda e: e["name"].lower())
    for name, plugins in [("registry.json", default), ("stable.json", [e for e in default if e["releaseChannel"] == "stable"]), ("javascript.json", javascript)]:
        write_json(name, {"schemaVersion": 1, "plugins": plugins})
    write_json("sources.json", {"owner": OWNER, "repositories": inventory})
    validate(False)


def validate(downloads):
    required = {"id", "name", "author", "description", "version", "pluginApiVersion", "downloads"}
    optional = {"capabilities", "icon", "sourceRepository", "releaseChannel", "categories"}
    inspected = {}
    for filename in ("registry.json", "stable.json", "javascript.json"):
        raw = (ROOT / filename).read_bytes()
        require(len(raw) <= 2 * 1024 * 1024, "Registry exceeds 2 MiB")
        catalog = json.loads(raw)
        require(set(catalog) == {"schemaVersion", "plugins"} and catalog["schemaVersion"] == 1, "Invalid registry schema")
        require(0 < len(catalog["plugins"]) <= 1000, "Invalid entry count")
        ids = set()
        for plugin in catalog["plugins"]:
            require(required <= set(plugin) <= required | optional, "Invalid entry fields")
            require(plugin["id"] not in ids, "Duplicate plugin ID")
            ids.add(plugin["id"])
            require(all(isinstance(plugin[key], str) and plugin[key] for key in required - {"downloads"}), "Invalid metadata")
            require(SEMVER.fullmatch(plugin["version"]) and SEMVER.fullmatch(plugin["pluginApiVersion"]), "Invalid version")
            require(urllib.parse.urlsplit(plugin["sourceRepository"]).scheme == "https", "Invalid source URL")
            require(plugin["releaseChannel"] in {"stable", "preview"}, "Invalid channel")
            require(filename != "stable.json" or plugin["releaseChannel"] == "stable", "Preview in stable registry")
            require(plugin["downloads"] and set(plugin["downloads"]) <= set(FORMATS.values()), "Invalid downloads")
            for platform, artifact in plugin["downloads"].items():
                require(set(artifact) == {"url", "sha256", "fileName"}, "Invalid artifact fields")
                file = artifact["fileName"]
                require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(jar|apk|mfp)", file), "Invalid filename")
                require(file.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}, "Reserved filename")
                require(FORMATS[Path(file).suffix] == platform, "Incorrect platform format")
                require(re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]), "Invalid checksum")
                require(urllib.parse.urlsplit(artifact["url"]).scheme == "https", "Invalid download URL")
                if downloads:
                    key = (artifact["url"], artifact["sha256"])
                    if key not in inspected:
                        inspected[key] = package(*key)[0]
                    manifest = inspected[key]
                    require((manifest["id"], manifest["version"], manifest["api"]) == (plugin["id"], plugin["version"], plugin["pluginApiVersion"]), "Listing differs from package manifest")
        print(f"Validated {filename}: {len(ids)} entries", flush=True)
    if downloads:
        print(f"Verified SHA-256 and embedded metadata for {len(inspected)} distinct packages", flush=True)


def main():
    global TOKEN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh", "validate"))
    parser.add_argument("--verify-downloads", action="store_true")
    parser.add_argument("--git-auth", action="store_true", help="Use the existing Git credential manager for GitHub API requests")
    args = parser.parse_args()
    TOKEN = os.environ.get("GITHUB_TOKEN")
    if args.git_auth:
        credential = subprocess.run(["git", "credential", "fill"], input=f"protocol=https\nhost=github.com\nusername={OWNER}\n\n", text=True, capture_output=True, check=True)
        TOKEN = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)["password"]
    if args.command == "refresh":
        refresh()
    else:
        validate(args.verify_downloads)


if __name__ == "__main__":
    main()
