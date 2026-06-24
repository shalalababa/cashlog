# App icons

A default Cashlog icon set is committed here (`32x32.png`, `128x128.png`,
`128x128@2x.png`, `icon.icns`, `icon.ico`, plus the Windows Store / Android /
iOS variants), so the project builds out of the box. The source artwork is
`cashlog-source.png`.

To replace them, regenerate from a single square PNG (≥ 1024×1024):

```bash
cd frontend
npm run tauri icon path/to/new-logo.png
```

This overwrites every size in this folder (paths referenced by `tauri.conf.json`).
