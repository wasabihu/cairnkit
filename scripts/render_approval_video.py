"""Assemble five full-page replay screenshots into the launch walkthrough.

Requires an existing ffmpeg installation; this script does not install anything.
Capture the five numbered stages in examples/approval-demo at one desktop viewport,
as frame-01.png through frame-05.png. These are state replays, not a live LLM recording.
"""

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/assets"))
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg is required to render media; the Python demo does not need it.")
    frames = [args.frames / f"frame-{i:02}.png" for i in range(1, 6)]
    for frame in frames:
        if not frame.is_file():
            parser.error(f"Missing screenshot: {frame}")
    args.output.mkdir(parents=True, exist_ok=True)
    video = args.output / "cairnkit-approval-demo.mp4"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for i, frame in enumerate(frames):
        command.extend(["-loop", "1", "-framerate", "30", "-t", "7.4" if i < 4 else "7"])
        command.extend(["-i", str(frame)])
    filters = [f"[{i}:v]format=yuv420p,setsar=1,settb=AVTB[v{i}]" for i in range(5)]
    previous = "v0"
    for i in range(1, 5):
        filters.append(f"[{previous}][v{i}]xfade=transition=fade:duration=0.4:offset={i * 7}[m{i}]")
        previous = f"m{i}"
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{previous}]",
            "-t",
            "35",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ]
    )
    subprocess.run(command, check=True)
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-filter_complex",
            "fps=4,scale=960:-1:flags=lanczos,split[a][b];"
            "[a]palettegen=max_colors=96:stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=5",
            "-loop",
            "0",
            str(args.output / "approval-demo.gif"),
        ],
        check=True,
    )
    shutil.copyfile(frames[2], args.output / "approval-poster.png")
    print(f"Rendered {video} and approval-demo.gif; copied approval-poster.png.")


if __name__ == "__main__":
    main()
