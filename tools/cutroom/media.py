"""Local subtitle parsing, timeline construction, and video export for Cutroom.

The module intentionally has no web-server dependencies.  Its public functions
accept paths owned by the caller and use only local ffmpeg/ffprobe subprocesses.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

MAX_SOURCE_SECONDS = 2 * 60 * 60
MAX_CUES = 1000
MAX_SEGMENTS = 60
OUTPUT_FPS = 30
PROBE_TIMEOUT_SECONDS = 30
RENDER_TIMEOUT_SECONDS = 10 * 60
LOCAL_PROTOCOL_WHITELIST = "file,pipe"
LOCAL_FORMAT_WHITELIST = "mov,matroska,webm"


_TIMESTAMP_SECONDS_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_WEBVTT_HEADER_RE = re.compile(r"^WEBVTT(?:\s|$)", re.IGNORECASE)


def _error(message: str) -> ValueError:
    """Return the common public exception type without leaking subprocess data."""

    return ValueError(message)


def _parse_timestamp(value: str) -> float:
    """Parse the SRT/WebVTT timestamp forms into seconds."""

    candidate = value.strip()
    parts = candidate.split(":")
    if len(parts) not in (2, 3):
        raise _error(f"Invalid subtitle timestamp: {value!r}")

    if len(parts) == 3:
        hour_text, minute_text, second_text = parts
        if not hour_text.isdigit() or not minute_text.isdigit():
            raise _error(f"Invalid subtitle timestamp: {value!r}")
        hours = int(hour_text)
        minutes = int(minute_text)
        if minutes >= 60:
            raise _error(f"Invalid subtitle timestamp: {value!r}")
    else:
        minute_text, second_text = parts
        if not minute_text.isdigit():
            raise _error(f"Invalid subtitle timestamp: {value!r}")
        hours = 0
        minutes = int(minute_text)

    if not _TIMESTAMP_SECONDS_RE.fullmatch(second_text.strip()):
        raise _error(f"Invalid subtitle timestamp: {value!r}")
    seconds = float(second_text.replace(",", "."))
    if not math.isfinite(seconds) or seconds >= 60:
        raise _error(f"Invalid subtitle timestamp: {value!r}")

    timestamp = hours * 3600.0 + minutes * 60.0 + seconds
    if not math.isfinite(timestamp) or timestamp < 0:
        raise _error(f"Invalid subtitle timestamp: {value!r}")
    return timestamp


def _normalise_subtitle_input(text: str) -> list[str]:
    if not isinstance(text, str):
        raise _error("Subtitle input must be text")
    # A BOM is valid at the beginning of both SRT and WebVTT files.  Normalize
    # line endings before grouping cue blocks so CRLF input behaves identically.
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n")


def _cue_blocks(lines: list[str]) -> tuple[bool, list[list[str]]]:
    """Return whether the input is VTT and its non-empty cue blocks."""

    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        raise _error("Subtitle input contains no cues")

    is_vtt = bool(_WEBVTT_HEADER_RE.match(lines[first].strip()))
    if is_vtt:
        # WebVTT metadata is terminated by a blank line.  A malformed header
        # without that separator is rejected rather than treating metadata as a
        # cue.  The first line may contain a short header description.
        cursor = first + 1
        while cursor < len(lines) and lines[cursor].strip():
            cursor += 1
        lines = lines[cursor:]

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return is_vtt, blocks


def parse_subtitles(text: str) -> list[dict[str, Any]]:
    """Parse SRT or WebVTT text into deterministic cue dictionaries.

    Cue identifiers are generated so imported files with missing or duplicate
    native identifiers have the same API shape.  Cue markup is retained as
    text; it is never interpreted or executed.
    """

    lines = _normalise_subtitle_input(text)
    _is_vtt, blocks = _cue_blocks(lines)
    cues: list[dict[str, Any]] = []
    previous_start = -math.inf

    for block in blocks:
        first_line = block[0].strip()
        if first_line.upper().startswith(("NOTE", "STYLE", "REGION")):
            continue

        timing_index = next(
            (index for index, line in enumerate(block) if "-->" in line),
            None,
        )
        if timing_index is None:
            raise _error("Subtitle cue is missing a timing line")
        if timing_index > 1:
            raise _error("Subtitle cue has an invalid identifier section")

        timing = block[timing_index].split("-->", 1)
        if len(timing) != 2:
            raise _error("Subtitle cue has an invalid timing line")
        start = _parse_timestamp(timing[0])
        # WebVTT permits cue settings after the end timestamp.  SRT does not
        # need special handling, and taking the first token is harmless there.
        end_token = timing[1].strip().split(None, 1)[0] if timing[1].strip() else ""
        end = _parse_timestamp(end_token)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise _error("Subtitle cue must have a finite positive interval")
        if start < previous_start:
            raise _error("Subtitle cue start times must be chronological")
        previous_start = start

        cue_lines = block[timing_index + 1 :]
        cue_text = "\n".join(cue_lines)
        if not cue_text.strip():
            raise _error("Subtitle cue has no text")
        cues.append(
            {
                "id": f"cue-{len(cues) + 1:04d}",
                "start": float(start),
                "end": float(end),
                "text": cue_text,
            }
        )
        if len(cues) > MAX_CUES:
            raise _error(f"Subtitle input may contain at most {MAX_CUES} cues")

    if not cues:
        raise _error("Subtitle input contains no cues")
    return cues


def _validate_cues(cues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(cues, list):
        raise _error("Cues must be a list")

    by_id: dict[str, dict[str, Any]] = {}
    previous_start = -math.inf
    for cue in cues:
        if not isinstance(cue, dict):
            raise _error("Each cue must be an object")
        cue_id = cue.get("id")
        if not isinstance(cue_id, str) or not cue_id:
            raise _error("Each cue must have a non-empty id")
        if cue_id in by_id:
            raise _error(f"Duplicate cue id: {cue_id}")
        start = cue.get("start")
        end = cue.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            raise _error("Cue timestamps must be numbers")
        try:
            start_float = float(start)
            end_float = float(end)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _error("Cue timestamps must be finite numbers") from exc
        if (
            not math.isfinite(start_float)
            or not math.isfinite(end_float)
            or start_float < 0
            or end_float <= start_float
        ):
            raise _error("Cue timestamps must be finite positive intervals")
        if start_float < previous_start:
            raise _error("Cue start times must be chronological")
        text = cue.get("text")
        if not isinstance(text, str):
            raise _error("Cue text must be a string")
        normalized = dict(cue)
        normalized["start"] = start_float
        normalized["end"] = end_float
        by_id[cue_id] = normalized
        previous_start = start_float
    return by_id


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise _error(f"{name} must be a finite number")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _error(f"{name} must be a finite number") from exc
    if not math.isfinite(converted):
        raise _error(f"{name} must be a finite number")
    return converted


def build_timeline(
    cues: list[dict[str, Any]],
    selected_ids: list[str],
    duration: float,
    padding: float = 0.12,
) -> list[dict[str, Any]]:
    """Build merged source/output intervals for selected subtitle cues."""

    source_duration = _number(duration, "duration")
    if source_duration <= 0:
        raise _error("Video duration must be positive")
    pad = _number(padding, "padding")
    if pad < 0 or pad > 1:
        raise _error("Padding must be between 0 and 1 seconds")
    if not isinstance(selected_ids, list) or not selected_ids:
        raise _error("At least one subtitle cue must be selected")
    if any(not isinstance(cue_id, str) or not cue_id for cue_id in selected_ids):
        raise _error("Selected cue ids must be non-empty strings")
    if len(set(selected_ids)) != len(selected_ids):
        raise _error("Selected cue ids must be unique")

    by_id = _validate_cues(cues)
    missing = [cue_id for cue_id in selected_ids if cue_id not in by_id]
    if missing:
        raise _error(f"Unknown selected cue id: {missing[0]}")

    selected_set = set(selected_ids)
    expanded: list[dict[str, Any]] = []
    for cue in cues:
        cue_id = cue["id"]
        if cue_id not in selected_set:
            continue
        start = max(0.0, float(cue["start"]) - pad)
        end = min(source_duration, float(cue["end"]) + pad)
        if end <= start:
            raise _error(f"Selected cue is outside the video duration: {cue_id}")
        expanded.append({"start": start, "end": end, "cue_ids": [cue_id]})

    merged: list[dict[str, Any]] = []
    for item in expanded:
        if merged and item["start"] <= merged[-1]["source_end"] + 1e-9:
            merged[-1]["source_end"] = max(merged[-1]["source_end"], item["end"])
            merged[-1]["cue_ids"].extend(item["cue_ids"])
        else:
            merged.append(
                {
                    "source_start": item["start"],
                    "source_end": item["end"],
                    "cue_ids": list(item["cue_ids"]),
                }
            )
    if len(merged) > MAX_SEGMENTS:
        raise _error(f"Selection may contain at most {MAX_SEGMENTS} merged segments")

    output_cursor = 0.0
    timeline: list[dict[str, Any]] = []
    for segment in merged:
        source_start = float(segment["source_start"])
        source_end = float(segment["source_end"])
        output_start = output_cursor
        output_end = output_start + (source_end - source_start)
        timeline.append(
            {
                "source_start": source_start,
                "source_end": source_end,
                "output_start": output_start,
                "output_end": output_end,
                "cue_ids": list(segment["cue_ids"]),
            }
        )
        output_cursor = output_end
    return timeline


def _executable(name: str) -> str:
    candidates = (
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    resolved = shutil.which(name)
    if resolved:
        return resolved
    raise _error(f"{name} is not installed")


def _validated_source(path: Path) -> Path:
    try:
        source = Path(path)
    except (TypeError, ValueError) as exc:
        raise _error("Video source path is invalid") from exc
    if "\x00" in str(source):
        raise _error("Video source path is invalid")
    try:
        exists = source.exists()
        regular_file = source.is_file()
    except OSError as exc:
        raise _error("Video source cannot be accessed") from exc
    if not exists or not regular_file:
        raise _error("Video source does not exist")
    try:
        return source.resolve()
    except (OSError, RuntimeError) as exc:
        raise _error("Video source path cannot be resolved") from exc


def _run_capture(args: list[str], timeout: int, label: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _error(f"{label} timed out") from exc
    except FileNotFoundError as exc:
        raise _error(f"{label} dependency is unavailable") from exc
    except OSError as exc:
        raise _error(f"{label} could not start") from exc


def probe_video(path: Path) -> dict[str, Any]:
    """Read duration, dimensions, and audio presence using local ffprobe."""

    source = _validated_source(path)
    ffprobe = _executable("ffprobe")
    result = _run_capture(
        [
            ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            LOCAL_PROTOCOL_WHITELIST,
            "-format_whitelist",
            LOCAL_FORMAT_WHITELIST,
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(source),
        ],
        PROBE_TIMEOUT_SECONDS,
        "ffprobe",
    )
    if result.returncode != 0:
        raise _error("ffprobe could not read the video")
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _error("ffprobe returned invalid metadata") from exc

    try:
        duration = float(metadata["format"]["duration"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _error("Video duration is unavailable") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise _error("Video duration is invalid")

    streams = metadata.get("streams")
    if not isinstance(streams, list):
        raise _error("Video streams are unavailable")
    video_stream = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "video"
        ),
        None,
    )
    if video_stream is None:
        raise _error("Video stream is unavailable")
    try:
        width = int(video_stream["width"])
        height = int(video_stream["height"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _error("Video dimensions are unavailable") from exc
    if width <= 0 or height <= 0:
        raise _error("Video dimensions are invalid")

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": any(
            isinstance(stream, dict) and stream.get("codec_type") == "audio" for stream in streams
        ),
    }


def _filter_number(value: float) -> str:
    # Timeline numbers are generated locally, so a fixed decimal representation
    # is sufficient and avoids locale-dependent filter expressions.
    return f"{value:.6f}"


def _render_video(
    source: Path,
    destination: Path,
    segments: list[dict[str, Any]],
    has_audio: bool,
) -> None:
    ffmpeg = _executable("ffmpeg")
    filter_parts: list[str] = []
    concat_labels: list[str] = []
    for index, segment in enumerate(segments):
        start = _filter_number(float(segment["source_start"]))
        end = _filter_number(float(segment["source_end"]))
        video_label = f"v{index}"
        filter_parts.append(
            f"[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
            f"fps={OUTPUT_FPS}:start_time=0,"
            f"scale=ceil(iw/2)*2:ceil(ih/2)*2,setsar=1,"
            "tpad=stop_mode=clone:stop_duration=1,"
            f"trim=end_frame={segment['output_frames']},"
            f"setpts=N/({OUTPUT_FPS}*TB)[{video_label}]"
        )
        concat_labels.append(f"[{video_label}]")
        if has_audio:
            audio_label = f"a{index}"
            segment_duration = _filter_number(
                float(segment["output_end"]) - float(segment["output_start"])
            )
            filter_parts.append(
                f"[0:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                f"apad=whole_dur={segment_duration},atrim=duration={segment_duration}[{audio_label}]"
            )
            concat_labels.append(f"[{audio_label}]")

    concat_inputs = "".join(concat_labels)
    if has_audio:
        filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=1:a=1[outv][outa]")
    else:
        filter_parts.append(f"{concat_inputs}concat=n={len(segments)}:v=1:a=0[outv]")

    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-protocol_whitelist",
        LOCAL_PROTOCOL_WHITELIST,
        "-format_whitelist",
        LOCAL_FORMAT_WHITELIST,
        "-i",
        str(source),
        "-filter_complex",
        ";".join(filter_parts),
        "-filter_complex_threads",
        "2",
        "-map",
        "[outv]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-threads",
        "2",
        "-pix_fmt",
        "yuv420p",
    ]
    if has_audio:
        args.extend(["-map", "[outa]", "-c:a", "aac"])
    else:
        args.append("-an")
    args.extend(["-movflags", "+faststart", str(destination)])
    result = _run_capture(args, RENDER_TIMEOUT_SECONDS, "ffmpeg")
    if result.returncode != 0:
        raise _error("ffmpeg could not render the selected video")


def _format_caption_timestamp(seconds: float, separator: str) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{millis:03d}"


def _rebased_captions(
    cues: list[dict[str, Any]],
    selected_ids: list[str],
    segments: list[dict[str, Any]],
    duration: float,
) -> list[dict[str, Any]]:
    by_id = _validate_cues(cues)
    captions: list[dict[str, Any]] = []
    for cue_id in selected_ids:
        cue = by_id[cue_id]
        for segment in segments:
            source_start = max(float(cue["start"]), float(segment["source_start"]))
            source_end = min(float(cue["end"]), float(segment["source_end"]))
            if source_end <= source_start:
                continue
            output_start = float(segment["output_start"]) + (
                source_start - float(segment["source_start"])
            )
            output_end = float(segment["output_start"]) + (
                source_end - float(segment["source_start"])
            )
            if output_end <= output_start or output_start >= duration:
                continue
            captions.append(
                {
                    "id": cue_id,
                    "source_start": source_start,
                    "source_end": source_end,
                    "output_start": max(0.0, output_start),
                    "output_end": min(duration, output_end),
                    "text": cue["text"],
                }
            )
            break
    captions.sort(key=lambda caption: (caption["output_start"], caption["id"]))
    return captions


def _write_caption_files(
    captions: list[dict[str, Any]],
    srt_path: Path,
    vtt_path: Path,
) -> None:
    srt_blocks: list[str] = []
    vtt_blocks: list[str] = []
    for index, caption in enumerate(captions, start=1):
        srt_start = _format_caption_timestamp(float(caption["output_start"]), ",")
        srt_end = _format_caption_timestamp(float(caption["output_end"]), ",")
        vtt_start = _format_caption_timestamp(float(caption["output_start"]), ".")
        vtt_end = _format_caption_timestamp(float(caption["output_end"]), ".")
        text = str(caption["text"])
        srt_blocks.append(f"{index}\n{srt_start} --> {srt_end}\n{text}")
        vtt_blocks.append(f"{vtt_start} --> {vtt_end}\n{text}")
    srt_path.write_text("\n\n".join(srt_blocks) + ("\n" if srt_blocks else ""), encoding="utf-8")
    vtt_path.write_text(
        "WEBVTT\n\n" + "\n\n".join(vtt_blocks) + ("\n" if vtt_blocks else ""),
        encoding="utf-8",
    )


def _write_timeline(
    path: Path,
    source_duration: float,
    duration: float,
    requested_duration: float,
    has_audio: bool,
    segments: list[dict[str, Any]],
    captions: list[dict[str, Any]],
) -> None:
    payload = {
        "source_duration": source_duration,
        "duration": duration,
        "requested_duration": requested_duration,
        "has_audio": has_audio,
        "segments": segments,
        "captions": captions,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_video(
    source: Path,
    cues: list[dict[str, Any]],
    selected_ids: list[str],
    output_dir: Path,
    padding: float = 0.12,
) -> dict[str, Any]:
    """Render selected subtitle intervals and write the Cutroom artifact set."""

    source_path = _validated_source(source)
    try:
        output_path = Path(output_dir)
    except (TypeError, ValueError) as exc:
        raise _error("Output directory path is invalid") from exc
    try:
        output_exists = output_path.exists()
        output_is_dir = output_path.is_dir()
    except OSError as exc:
        raise _error("Output directory cannot be accessed") from exc
    if output_exists and not output_is_dir:
        raise _error("Output directory is not a directory")
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _error("Output directory cannot be created") from exc
    own_video = output_path / "clip.mp4"
    try:
        if source_path.resolve() == own_video.resolve():
            raise _error("Source video cannot be the output clip")
    except (OSError, RuntimeError) as exc:
        raise _error("Video paths could not be resolved") from exc

    metadata = probe_video(source_path)
    source_duration = float(metadata["duration"])
    if source_duration > MAX_SOURCE_SECONDS:
        raise _error(f"Video source may be at most {MAX_SOURCE_SECONDS // 3600} hours")
    segments = build_timeline(cues, selected_ids, source_duration, padding)
    if any(segment["source_end"] - segment["source_start"] < 0.1 - 1e-9 for segment in segments):
        raise _error(
            "Each cut must span at least 0.10 seconds. Increase padding or choose a longer cue."
        )
    requested_duration = float(segments[-1]["output_end"])
    # Concat uses actual frame boundaries. Account for each rounded segment,
    # otherwise many short cuts accumulate drift between captions and audio.
    output_frames = 0
    for segment in segments:
        source_length = segment["source_end"] - segment["source_start"]
        frames = max(1, math.ceil(source_length * OUTPUT_FPS - 1e-7))
        segment["output_frames"] = frames
        segment["output_start"] = output_frames / OUTPUT_FPS
        output_frames += frames
        segment["output_end"] = output_frames / OUTPUT_FPS
        segment["tail_padding"] = frames / OUTPUT_FPS - source_length

    filenames = {
        "video": "clip.mp4",
        "srt": "clip.srt",
        "vtt": "clip.vtt",
        "timeline": "timeline.json",
        "bundle": "cutroom.zip",
    }
    with tempfile.TemporaryDirectory(prefix=".cutroom-", dir=str(output_path)) as temporary:
        temporary_path = Path(temporary)
        video_path = temporary_path / filenames["video"]
        srt_path = temporary_path / filenames["srt"]
        vtt_path = temporary_path / filenames["vtt"]
        timeline_path = temporary_path / filenames["timeline"]
        bundle_path = temporary_path / filenames["bundle"]

        _render_video(source_path, video_path, segments, bool(metadata["has_audio"]))
        actual = probe_video(video_path)
        captions = _rebased_captions(
            cues,
            selected_ids,
            segments,
            float(actual["duration"]),
        )
        _write_caption_files(captions, srt_path, vtt_path)
        _write_timeline(
            timeline_path,
            source_duration,
            float(actual["duration"]),
            requested_duration,
            bool(actual["has_audio"]),
            segments,
            captions,
        )
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for filename in (
                filenames["video"],
                filenames["srt"],
                filenames["vtt"],
                filenames["timeline"],
            ):
                bundle.write(temporary_path / filename, arcname=filename)

        for filename in (
            filenames["video"],
            filenames["srt"],
            filenames["vtt"],
            filenames["timeline"],
            filenames["bundle"],
        ):
            os.replace(temporary_path / filename, output_path / filename)

    return {
        "duration": float(actual["duration"]),
        "requested_duration": requested_duration,
        "has_audio": bool(actual["has_audio"]),
        "segments": segments,
        "filenames": filenames,
    }
