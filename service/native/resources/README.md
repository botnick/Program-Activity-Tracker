# Icon resources

`tracker.svg` is the source design (an "eye + pulse line" on a dark rounded
square). `tracker.ico` and `../../../ui/public/favicon.ico` are derived
binaries and are **checked into git** so a fresh checkout doesn't need
ImageMagick / Pillow to build.

The `.ico` is embedded into `tracker_capture.exe` via `tracker_capture.rc`
(see the `if(WIN32)` block in `service/native/CMakeLists.txt`). Once
embedded, Windows Explorer, Task Manager, and Alt-Tab all show the icon,
and right-click → Properties → Details displays the version metadata.

## Files

| File                       | Sizes embedded            | Purpose                       |
| -------------------------- | ------------------------- | ----------------------------- |
| `tracker.svg`              | vector                    | source of truth                |
| `tracker.ico`              | 16, 32, 48, 64, 128, 256  | embedded into the .exe         |
| `../../../ui/public/favicon.ico` | 16, 32, 48          | served by Vite at site root    |
| `tracker_capture.rc`       | n/a                       | resource script (icon + verinfo) |
| `regenerate_icons.py`      | n/a                       | rebuild script (Pillow only)   |

## Regenerate (when you change tracker.svg)

The repo's regen path uses **Pillow only** (no cairosvg / ImageMagick
required) — the icon is drawn procedurally to mirror the SVG, so you'll
need to update `regenerate_icons.py` if you alter the SVG geometry.

```cmd
:: from this directory
pip install --user Pillow
python regenerate_icons.py
```

This rewrites `tracker.ico` and `../../../ui/public/favicon.ico`. Then
rebuild the native exe so the new icon is embedded:

```cmd
cmake --build ..\build --config Release
```

### Alternative: ImageMagick

If you have ImageMagick installed and want to rasterize the SVG directly
(rather than using the procedural Pillow path), this also works:

```cmd
magick convert -background none -density 300 tracker.svg ^
       -define icon:auto-resize=16,32,48,64,128,256 tracker.ico
copy /Y tracker.ico ..\..\..\ui\public\favicon.ico
```

## Verify after rebuild

```powershell
Get-ItemProperty service\native\build\tracker_capture.exe | Select VersionInfo | Format-List
```

Should print `CompanyName=Activity Tracker`, `FileDescription=Native ETW
capture engine`, etc. In Explorer, the .exe should now show the cyan-eye
icon instead of the generic Win32 console-app placeholder.
