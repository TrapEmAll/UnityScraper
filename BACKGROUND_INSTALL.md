# Xbox-Inspired UnityScraper Background

This drop-in adds a custom dark-green, Xbox-inspired UnityScraper
background and displays it as a responsive banner across every page.

## Install

Copy the included files into the repository root and allow
`modern_gui.py` to be replaced.

```powershell
python -m pip install -r requirements-background.txt
python desktop_app.py
```

## PyInstaller

Include the assets folder in the build:

```powershell
python -m PyInstaller `
  --clean `
  --noconfirm `
  --name UnityScraper `
  --noconsole `
  --onefile `
  --add-data "JSON.txt;." `
  --add-data "assets;assets" `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageTk `
  desktop_app.py
```

The image is loaded through `resource_path(...)`, so it works from the
source checkout and from the packaged executable.
