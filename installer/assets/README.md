# installer/assets/

This folder holds assets used by the installer build process.

## Required before building

### sanjinsight.ico (REQUIRED)
The application icon used by:
- The `.exe` file (visible in Windows Explorer, taskbar, alt-tab)
- The Start menu shortcut
- The installer wizard header

**How to create it:**

Option A — Convert your SVG logo (recommended):
1. Open `assets/microsanj-logo.svg` in Inkscape (free, inkscape.org)
2. Export as PNG at these sizes: 16×16, 32×32, 48×48, 64×64, 256×256
3. Use IcoFX (free trial) or https://icoconvert.com to combine into a single `.ico`
4. Save as `installer/assets/sanjinsight.ico`

Option B — Online converter:
1. Go to https://convertio.co/svg-ico/
2. Upload `assets/microsanj-logo.svg`
3. Download the `.ico` file
4. Save as `installer/assets/sanjinsight.ico`

The `.ico` file must contain at minimum the 32×32 and 256×256 sizes.

---

### Optional: installer banner images
Inno Setup supports custom header images for a more branded installer.
Uncomment the relevant lines in `sanjinsight.iss` if you add these:

- `installer_banner.bmp` — 493×58 pixels, shown at the top of wizard pages
- `installer_icon.bmp` — 55×55 pixels, small image top-right of wizard
