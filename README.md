# MetroFuse Marketplace

Public JSON registries for MetroFuse plugins maintained by [956tris](https://github.com/956tris).

## Registry URLs

Paste one of these URLs into **MetroFuse → Settings → Plugins → Marketplace**:

- Complete marketplace, including preview releases: `https://raw.githubusercontent.com/956tris/MetroFuse-Marketplace/main/registry.json`
- Stable releases only: `https://raw.githubusercontent.com/956tris/MetroFuse-Marketplace/main/stable.json`
- JavaScript-preferred packages, with native-only plugins retained: `https://raw.githubusercontent.com/956tris/MetroFuse-Marketplace/main/javascript.json`

`sources.json` is a machine-readable inventory of the public plugin repositories and every package used to generate the registries. It also records the separate plugin documentation repository.

## Included repositories

- [Metrofuse-Deezer](https://github.com/956tris/Metrofuse-Deezer)
- [MetroFuse-JioSaavn](https://github.com/956tris/MetroFuse-JioSaavn)
- [MetroFuse-MetroFlow](https://github.com/956tris/MetroFuse-MetroFlow)
- [MetroFuse-Roselight](https://github.com/956tris/MetroFuse-Roselight)
- [MetroFuse-SoundCloud](https://github.com/956tris/MetroFuse-SoundCloud)
- [MetroFuse-Spotify](https://github.com/956tris/MetroFuse-Spotify)
- [MetroFuse-YouTube-Music](https://github.com/956tris/MetroFuse-YouTube-Music)
- [MetroFuse Plugin Docs](https://github.com/956tris/MetroFuse-Plugin-Docs)

Each marketplace entry is generated from the package's embedded `manifest.json`. Published release assets are downloaded and checked against both GitHub's SHA-256 digest and the metadata in the package before the JSON is written.

## Maintain the marketplace

Python 3.11 or newer is required. To rescan the owner's public repositories and regenerate every JSON file using the Git credentials already configured for GitHub:

```powershell
python tooling/marketplace.py refresh --git-auth
```

To validate the committed files and independently verify every package download:

```powershell
python tooling/marketplace.py validate --verify-downloads
```

GitHub Actions runs the full validation on every push and pull request.
