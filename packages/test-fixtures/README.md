# test-fixtures

Synthetic media inputs for the Phase 3 pipeline. **Nothing here is committed as a
binary** — real user media never enters the repository, and a checked-in blob
cannot be reviewed.

`societe_media_fixtures.py` generates the inputs on demand. Tests import it
directly (it is on the pytest `pythonpath`) and write into `tmp_path`, so each
test gets a private copy.

## Generate for manual inspection

```bash
uv run python -m societe_media_fixtures --out packages/test-fixtures/output
```

Output lands in `packages/test-fixtures/output/`, which is gitignored.

## What each fixture is for

| Fixture | Exercises |
| --- | --- |
| `sample_exif_gps.jpg` | EXIF orientation is baked into pixels, then orientation **and** GPS tags are dropped |
| `sample.png` | Non-JPEG image path and WebP derivative encoding |
| `sample.webp` | Signature sniffing when the container matches the target format |
| oversized PNG (helper) | Decompression-bomb rejection via the decoded-pixel budget |
| `sample.mp4` | ffmpeg probe, duration cap, progressive MP4 and poster output |

The MP4 requires `ffmpeg` on `PATH`. It is present in the API container image;
locally, video tests skip when it is missing rather than failing.

The malware branch uses the standard EICAR test string, which the tests build in
memory from a constant in `app.modules.media.malware` — it is deliberately not
written to disk here, because on-disk EICAR trips developer antivirus software.
