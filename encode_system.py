from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


PRESET_SPEED = {
    "ultrafast": 2.5,
    "superfast": 2.0,
    "veryfast": 1.6,
    "faster": 1.35,
    "fast": 1.2,
    "medium": 1.0,
    "slow": 0.75,
    "slower": 0.6,
}

RUNNER_BASE_FPS = {
    "public": 42.0,
    "private": 22.0,
}

RESOLUTION_SCALE = {
    "source": None,
    "1080p": "1920:1080",
    "720p": "1280:720",
    "480p": "854:480",
}


@dataclass
class EncodeConfig:
    input_source: str
    output_file: str
    duration_minutes: float
    runner_type: str = "public"
    preset: str = "medium"
    resolution: str = "1080p"
    mode: str = "crf"
    crf: int = 23
    maxrate_mbps: float = 5.0
    audio_bitrate_k: int = 128
    target_video_bitrate_mbps: float = 4.0
    custom_extra_args: str = ""


def estimate_encode_minutes(duration_minutes: float, runner_type: str, preset: str) -> float:
    base_fps = RUNNER_BASE_FPS.get(runner_type, RUNNER_BASE_FPS["private"])
    speed_multiplier = PRESET_SPEED.get(preset, PRESET_SPEED["medium"])
    encode_fps = base_fps * speed_multiplier
    total_frames = max(duration_minutes, 0.0) * 60 * 30
    seconds = total_frames / encode_fps if encode_fps else 0
    return round(seconds / 60, 2)


def expected_size_mb(
    duration_minutes: float,
    mode: str,
    target_video_bitrate_mbps: float,
    audio_bitrate_k: int,
    crf: int,
) -> float:
    if mode == "two_pass":
        video_mbps = max(target_video_bitrate_mbps, 0.1)
    elif mode == "crf_cap":
        video_mbps = 2.5
    else:
        # crude estimate for CRF mode to give users quick intuition.
        video_mbps = max(0.8, 5.0 - (crf - 18) * 0.3)
    total_mbps = video_mbps + (audio_bitrate_k / 1000.0)
    total_megabits = total_mbps * max(duration_minutes, 0.0) * 60
    return round(total_megabits / 8.0, 2)


def build_ffmpeg_command(config: EncodeConfig, pass_no: int | None = None, null_target: str = "/dev/null") -> List[str]:
    args: List[str] = ["ffmpeg", "-y", "-i", config.input_source, "-c:v", "libx264", "-preset", config.preset]

    if config.resolution in RESOLUTION_SCALE and RESOLUTION_SCALE[config.resolution]:
        args += ["-vf", f"scale={RESOLUTION_SCALE[config.resolution]}"]

    if config.mode == "two_pass":
        args += ["-b:v", f"{config.target_video_bitrate_mbps}M"]
        if pass_no is not None:
            args += ["-pass", str(pass_no)]
            if pass_no == 1:
                args += ["-an", "-f", "null", null_target]
                return args
    elif config.mode == "crf_cap":
        args += [
            "-crf",
            str(config.crf),
            "-maxrate",
            f"{config.maxrate_mbps}M",
            "-bufsize",
            f"{config.maxrate_mbps * 2}M",
        ]
    else:
        args += ["-crf", str(config.crf)]

    args += ["-c:a", "aac", "-b:a", f"{config.audio_bitrate_k}k"]

    if config.custom_extra_args.strip():
        args += config.custom_extra_args.split()

    args.append(config.output_file)
    return args


def safe_output_name(raw_name: str) -> str:
    base_name = Path(raw_name).name
    cleaned = "".join(ch for ch in base_name if ch.isalnum() or ch in ("-", "_", "."))
    cleaned = cleaned.lstrip(".")
    if not cleaned:
        cleaned = "encoded.mp4"
    if not cleaned.lower().endswith(".mp4"):
        cleaned += ".mp4"
    return Path(cleaned).name
