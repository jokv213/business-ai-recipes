# Cutroom

**Turn a recording into a focused clip by selecting its transcript.**

Bring an MP4/MOV/WebM/MKV and its SRT or WebVTT file. Click the lines you want to keep, preview the cut, and export a continuous MP4 with audio, retimed subtitles, and a source-to-output timeline. No Python packages, account, or API key required for editing.

## Try it

Requirements: Python 3.11+, `ffmpeg` and `ffprobe` on PATH. The FFmpeg build must include H.264 encoding (`libx264`) and AAC. On macOS these can be installed with `brew install ffmpeg`; on Debian/Ubuntu with `sudo apt install ffmpeg`.

From the repository root:

```bash
python3 tools/cutroom/server.py
```

Open **http://127.0.0.1:8771/** and click **Try the sample**. The sample has generated narration and an illustrated, synthetic incident walkthrough. It is not footage from a real business.

1. Click **Jev suggestion** to replay recorded selections for the sample goal. This makes no API call.
2. Toggle any transcript line. Use **Undo**, or click its time to hear it in context.
3. Enable **Play selected only** to preview the selected sections continuously.
4. Click **Export selected moments**, then download the MP4, subtitles, or complete ZIP.

For your own material: **Import video → Add SRT / VTT → select lines → export**. Literal keyword selection works offline. Your video is copied to the local workspace; the source file is never edited. Browser playback depends on its codec support; H.264/AAC MP4 is the recommended input. MOV, WebM, and MKV may render in FFmpeg even when your browser cannot preview them.

## What you get

| File | Use |
|---|---|
| `clip.mp4` | A re-encoded H.264 video, with AAC audio if the input has audio |
| `clip.srt`, `clip.vtt` | Only selected subtitles, retimed to the exported clip |
| `timeline.json` | Exact source intervals, output intervals, and caption mapping |
| `cutroom.zip` | All four files in one download |

Overlapping or touching selections are merged so footage is not repeated. Adjustable 0–1 second padding adds context around cuts. Output is 30 fps; each cut is rounded up to a full frame, adding less than 1/30 second of still-frame/silent tail. The timeline and captions use those actual output boundaries so rounding does not accumulate into subtitle drift. Captions are separate files, not burned into the picture. Subtitle boundaries may need manual adjustment to avoid cutting words; Cutroom does not transcribe audio or infer sentence boundaries.

## Optional live Jev

[Jev](https://docs.typesafe.ai/introduction) selects from typed options. Here it proposes keep/skip for each subtitle, with neighboring lines for context. Python owns the timeline and FFmpeg owns the render. You can override every proposal.

To use your own TypeSafe key, set `TYPESAFE_API_KEY` in your shell and explicitly enable the integration:

```bash
python3 tools/cutroom/server.py --enable-jev
```

For a custom goal, check the in-app consent box before requesting a suggestion. **Your goal and subtitle text are sent to TypeSafe; the video is not.** The key stays in the server process and is never requested by the web UI. Standard startup ignores the key and makes no network calls. The bundled goal always replays its recorded answers, even when live is enabled.

This release allows up to 30 subtitle cues for Jev and 30 new requests per server launch. `--api-budget 12` lowers that limit. The full operation is reserved before sending; a failed operation does not retry or refund its reservation. Identical successful requests in the same launch are cached. Restarting resets that local cap; it is not an account-wide spending limit. Manual editing supports up to 1,000 cues regardless of API availability.

## Measured, not promised

On 2026-09-22, six previously unused synthetic subtitles were tested against a goal and expected selection fixed before the calls. Jev selected the two expected recovery/verification lines. A literal search for `restore check` found none: those lines use “loaded the last healthy snapshot” and “row counts matched.” This illustrates semantic matching on **one authored example**, not a general accuracy benchmark or comparison with other language models.

The six calls used 2,878 input tokens and 3,844.11 ms summed request time. Cost was not measured. [Recorded answers](demo/recorded.json) include the choices, probabilities, confidence, time, and observation timestamps. Low-confidence or confident-but-wrong suggestions remain possible. The UI labels recorded and cached answers separately from new calls.

## Limits and local files

- Up to 512 MB input, two hours of video, 1,000 subtitle cues, and 60 merged cut regions. Rendering has a ten-minute timeout; long videos have not been benchmarked.
- Each merged cut must span at least 0.10 seconds. Increase padding for extremely short subtitle cues.
- Runs on `127.0.0.1` only. There is no hosted upload service, shared workspace, analytics, or CDN.
- Local copies and exports stay in `.cutroom/` under the directory where you launch it. Use `--output PATH` to choose another workspace. Delete that workspace yourself when no longer needed.
- No speech recognition, burned-in captions, vertical reframing, or project save/restore UI in this release. Keep your original subtitle file and exported timeline.
- Local FFmpeg and your operating system process uploaded files. This is a single-user development tool, not a hardened multi-user media service.

## Verify

```bash
python3 -B -m unittest discover -s tools/cutroom -p 'test_*.py' -v
```

Tests are offline and use generated videos. Media integration tests require FFmpeg. The HTTP tests cover importing a non-demo file with custom Japanese WebVTT, selection, export, range playback, host/origin checks, and rejecting invalid uploads. See the repository license for the source and authored sample assets.
