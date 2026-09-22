from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from media import build_timeline, export_video, parse_subtitles, probe_video

FFMPEG = shutil.which("ffmpeg")


class SubtitleAndTimelineTests(unittest.TestCase):
    def test_parse_srt_bom_crlf_multiline_and_overlap(self) -> None:
        source = (
            "\ufeff1\r\n"
            "00:00:00,500 --> 00:00:01,500\r\n"
            "first line\r\n"
            "second line\r\n\r\n"
            "2\r\n"
            "00:00:01,200 --> 00:00:02,000\r\n"
            "overlap\r\n"
        )
        cues = parse_subtitles(source)
        self.assertEqual(
            cues,
            [
                {
                    "id": "cue-0001",
                    "start": 0.5,
                    "end": 1.5,
                    "text": "first line\nsecond line",
                },
                {"id": "cue-0002", "start": 1.2, "end": 2.0, "text": "overlap"},
            ],
        )

    def test_parse_vtt_skips_metadata_and_retains_text_as_plain_text(self) -> None:
        source = (
            "WEBVTT - sample\n\n"
            "NOTE this is metadata\nnot a cue\n\n"
            "cue-name\n"
            "00:00.250 --> 00:01.000 position:10%\n"
            "<b>literal</b>\n"
        )
        cues = parse_subtitles(source)
        self.assertEqual(cues[0]["start"], 0.25)
        self.assertEqual(cues[0]["end"], 1.0)
        self.assertEqual(cues[0]["text"], "<b>literal</b>")

    def test_parse_rejects_backwards_invalid_and_too_many_cues(self) -> None:
        with self.assertRaises(ValueError):
            parse_subtitles(
                "1\n00:00:02,000 --> 00:00:03,000\nlater\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nearlier\n"
            )
        with self.assertRaises(ValueError):
            parse_subtitles("1\n00:00:00,000 --> 00:00:00,000\nempty interval\n")
        with self.assertRaises(ValueError):
            parse_subtitles("1\n00:00:NaN --> 00:00:01,000\nnot finite\n")

        blocks = []
        for index in range(1001):
            start = index
            blocks.append(
                f"{index + 1}\n00:{start // 60:02d}:{start % 60:02d},000 --> "
                f"00:{(start + 1) // 60:02d}:{(start + 1) % 60:02d},500\nline"
            )
        with self.assertRaises(ValueError):
            parse_subtitles("\n\n".join(blocks))

    def test_build_timeline_merges_padding_clamps_and_rebases(self) -> None:
        cues = [
            {"id": "cue-0001", "start": 0.5, "end": 1.1, "text": "one"},
            {"id": "cue-0002", "start": 1.05, "end": 1.4, "text": "two"},
            {"id": "cue-0003", "start": 3.5, "end": 3.6, "text": "three"},
        ]
        timeline = build_timeline(cues, ["cue-0001", "cue-0002", "cue-0003"], 4.0, 0.1)
        self.assertEqual(len(timeline), 2)
        self.assertAlmostEqual(timeline[0]["source_start"], 0.4)
        self.assertAlmostEqual(timeline[0]["source_end"], 1.5)
        self.assertEqual(timeline[0]["cue_ids"], ["cue-0001", "cue-0002"])
        self.assertAlmostEqual(timeline[1]["source_start"], 3.4)
        self.assertAlmostEqual(timeline[1]["source_end"], 3.7)
        self.assertAlmostEqual(timeline[1]["output_start"], 1.1)

        clamped = build_timeline(
            [{"id": "cue-0001", "start": 0.05, "end": 3.95, "text": "whole"}],
            ["cue-0001"],
            4.0,
            0.1,
        )
        self.assertEqual(clamped[0]["source_start"], 0.0)
        self.assertEqual(clamped[0]["source_end"], 4.0)

    def test_build_timeline_rejects_bad_selection_and_segment_count(self) -> None:
        cue = {"id": "cue-0001", "start": 0.0, "end": 0.1, "text": "x"}
        for selected, padding in (([], 0.1), (["missing"], 0.1), (["cue-0001"], 1.1)):
            with self.assertRaises(ValueError):
                build_timeline([cue], selected, 1.0, padding)
        with self.assertRaises(ValueError):
            build_timeline(
                [{"id": "cue-0001", "start": float("nan"), "end": 1.0, "text": "x"}],
                ["cue-0001"],
                1.0,
            )
        with self.assertRaises(ValueError):
            build_timeline([cue], ["cue-0001"], float("inf"))

        many = [
            {"id": f"cue-{index:04d}", "start": index * 2.0, "end": index * 2.0 + 0.5, "text": "x"}
            for index in range(61)
        ]
        with self.assertRaises(ValueError):
            build_timeline(many, [cue["id"] for cue in many], 121.0, 0.0)


@unittest.skipUnless(FFMPEG, "ffmpeg is required for media export tests")
class VideoExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory(prefix="cutroom-media-tests-")
        root = Path(cls.tempdir.name)
        cls.audio_source = root / "odd-audio.mkv"
        cls.silent_source = root / "odd-silent.mkv"
        cls._make_fixture(
            cls.audio_source,
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=321x241:rate=25",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:sample_rate=48000",
                "-t",
                "3",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv444p",
                "-c:a",
                "pcm_s16le",
            ],
        )
        cls._make_fixture(
            cls.silent_source,
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=321x241:rate=25",
                "-t",
                "2",
                "-map",
                "0:v:0",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv444p",
            ],
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    @staticmethod
    def _make_fixture(destination: Path, input_args: list[str]) -> None:
        subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                *input_args,
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_probe_reports_odd_source_dimensions_and_audio(self) -> None:
        metadata = probe_video(self.audio_source)
        self.assertEqual(metadata["width"], 321)
        self.assertEqual(metadata["height"], 241)
        self.assertTrue(metadata["has_audio"])
        self.assertAlmostEqual(metadata["duration"], 3.0, delta=0.1)

    def test_export_audio_rebases_captions_and_writes_bundle(self) -> None:
        cues = parse_subtitles(
            "1\n00:00:00,400 --> 00:00:00,800\nfirst\n\n"
            "2\n00:00:01,600 --> 00:00:01,900\nsecond\n\n"
            "3\n00:00:02,400 --> 00:00:02,600\nnot selected\n"
        )
        output_dir = Path(self.tempdir.name) / "audio-output"
        sentinel = output_dir / "unrelated.txt"
        output_dir.mkdir()
        sentinel.write_text("keep", encoding="utf-8")
        result = export_video(self.audio_source, cues, ["cue-0001", "cue-0002"], output_dir, 0.1)

        self.assertAlmostEqual(result["requested_duration"], 1.1, delta=0.01)
        self.assertGreater(result["duration"], 0.8)
        self.assertLess(result["duration"], 1.4)
        self.assertTrue(result["has_audio"])
        output_metadata = probe_video(output_dir / "clip.mp4")
        self.assertTrue(output_metadata["has_audio"])
        self.assertEqual(output_metadata["width"] % 2, 0)
        self.assertEqual(output_metadata["height"] % 2, 0)

        rendered_cues = parse_subtitles((output_dir / "clip.srt").read_text(encoding="utf-8"))
        self.assertEqual([cue["text"] for cue in rendered_cues], ["first", "second"])
        self.assertAlmostEqual(rendered_cues[0]["start"], 0.1, delta=0.02)
        self.assertAlmostEqual(rendered_cues[1]["start"], 0.7, delta=0.02)
        timeline = json.loads((output_dir / "timeline.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(timeline["duration"], result["duration"], delta=0.01)
        self.assertEqual(timeline["segments"][0]["cue_ids"], ["cue-0001"])
        self.assertEqual(timeline["segments"][1]["cue_ids"], ["cue-0002"])
        self.assertEqual(timeline["captions"][0]["source_start"], 0.4)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

        with zipfile.ZipFile(output_dir / "cutroom.zip") as bundle:
            self.assertEqual(
                set(bundle.namelist()),
                {"clip.mp4", "clip.srt", "clip.vtt", "timeline.json"},
            )

    def test_export_silent_source_has_no_audio_and_keeps_video(self) -> None:
        cues = [{"id": "cue-0001", "start": 0.4, "end": 0.8, "text": "silent"}]
        output_dir = Path(self.tempdir.name) / "silent-output"
        result = export_video(self.silent_source, cues, ["cue-0001"], output_dir, 0.05)
        self.assertFalse(result["has_audio"])
        metadata = probe_video(output_dir / "clip.mp4")
        self.assertFalse(metadata["has_audio"])
        self.assertGreater(metadata["duration"], 0.4)
        self.assertLess(metadata["duration"], 0.6 + 0.5)

    def test_many_fractional_cuts_keep_captions_on_actual_frame_boundaries(self) -> None:
        cues = [
            {"id": str(i), "start": i * 0.22 + 0.017, "end": i * 0.22 + 0.147, "text": f"cue {i}"}
            for i in range(12)
        ]
        output = Path(self.tempdir.name) / "fractional-cuts"
        result = export_video(self.audio_source, cues, [cue["id"] for cue in cues], output, 0)
        timeline = json.loads((output / "timeline.json").read_text())
        self.assertAlmostEqual(result["duration"], 1.6, delta=0.02)
        self.assertAlmostEqual(
            timeline["segments"][-1]["output_end"], result["duration"], delta=0.02
        )
        for index, caption in enumerate(timeline["captions"]):
            self.assertAlmostEqual(caption["output_start"], index * 4 / 30, delta=0.001)
        self.assertTrue(all(0 <= item["tail_padding"] < 1 / 30 for item in result["segments"]))

    def test_subframe_cut_has_actionable_error_and_padding_recovers(self) -> None:
        cues = [{"id": "short", "start": 0.041, "end": 0.042, "text": "brief"}]
        output = Path(self.tempdir.name) / "short-cut"
        with self.assertRaisesRegex(ValueError, "Increase padding"):
            export_video(self.audio_source, cues, ["short"], output, 0)
        self.assertFalse((output / "clip.mp4").exists())
        result = export_video(self.audio_source, cues, ["short"], output, 0.12)
        self.assertGreater(result["duration"], 0.1)

    def test_probe_rejects_non_video_playlist_format(self) -> None:
        playlist = Path(self.tempdir.name) / "playlist.m3u8"
        playlist.write_text("#EXTM3U\n#EXTINF:1,\nsegment.ts\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            probe_video(playlist)


if __name__ == "__main__":
    unittest.main()
