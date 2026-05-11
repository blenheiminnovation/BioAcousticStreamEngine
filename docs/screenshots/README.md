# Screenshots

Drop PNG files into this folder using the filenames below — the main README
will render them automatically.

| Filename | What it shows |
|---|---|
| `dashboard.png` | Live detection feed, VU meter, per-device controls |
| `schedule.png` | Listening windows, classifier-to-device assignment |
| `clips.png` | Audio clip library, in-browser playback |
| `reports.png` | Species filtering, daily summary table, CSV download |
| `settings.png` | Location, MQTT broker config, classifier device assignment |

## Guidelines

- **Format**: PNG (lossless) for screenshots; JPG only if reducing a photo.
- **Width**: 1280 px or smaller — GitHub READMEs cap usable width around 800 px.
- **Size**: under ~500 KB each. Run through `pngquant` before committing:

  ```bash
  pngquant --quality=70-90 --strip --skip-if-larger --output dashboard.png dashboard.png
  ```

- **Dark mode**: if you have both, save as `dashboard-light.png` /
  `dashboard-dark.png` and the README uses a `<picture>` tag to switch.
