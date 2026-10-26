"""ffmpeg helpers for muxing generated audio into videos."""
import asyncio
import shutil
import tempfile
from pathlib import Path

HAS_FFMPEG = shutil.which("ffmpeg") is not None


async def _ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="ignore")[-300:])


async def mux(video: bytes, audio: bytes, mix_original: bool = False, audio_ext: str = "mp3") -> bytes | None:
    """Puts audio onto video: replaces the soundtrack, or mixes it under the original one."""
    if not HAS_FFMPEG:
        return None
    with tempfile.TemporaryDirectory() as d:
        v, a, out = Path(d, "in.mp4"), Path(d, f"in.{audio_ext}"), Path(d, "out.mp4")
        v.write_bytes(video)
        a.write_bytes(audio)
        if mix_original:
            args = [
                "-i", str(v), "-i", str(a),
                "-filter_complex", "[1:a]volume=0.8[m];[0:a][m]amix=inputs=2:duration=first[aout]",
                "-map", "0:v", "-map", "[aout]",
            ]
        else:
            args = ["-i", str(v), "-i", str(a), "-map", "0:v", "-map", "1:a", "-shortest"]
        try:
            await _ffmpeg(*args, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out))
        except RuntimeError:
            if not mix_original:
                return None
            # the source had no audio track to mix with — fall back to replacing it
            return await mux(video, audio, False, audio_ext)
        return out.read_bytes()


async def to_mp3(audio: bytes, ext: str) -> bytes | None:
    if not HAS_FFMPEG:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d, f"in.{ext}"), Path(d, "out.mp3")
        src.write_bytes(audio)
        try:
            await _ffmpeg("-i", str(src), "-b:a", "192k", str(out))
        except RuntimeError:
            return None
        return out.read_bytes()
