"""يلتقط المرجع الذهبي لتفريغ P1 (م18) — يُشغَّل قبل الـrefactor وبعده للمقارنة.

python scripts/capture_stt_reference.py [--out backend/tests/fixtures/streaming_reference.json]

المرجع = مخرج المسار القائم حرفياً على ملف صوت مُولَّد حتمياً، مع تقسيمه إلى
مقاطع تغذية (chunks) ليختبر التكافؤ المتدفق لاحقاً.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("STT_ENGINE", "mock")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://medify_app:medify_app@localhost:5544/postgres")

CHUNK_FRAMES = 16000  # ثانية واحدة لكل مقطع تغذية


def _build_audio(path: Path) -> bytes:
    """صوت PCM16 حتمي (نغمة متدرجة) — نفسه في كل تشغيل."""
    frames = bytes(
        b for i in range(16000 * 8)
        for b in int(6000 * ((i % 400) - 200) / 200).to_bytes(2, "little", signed=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(frames)
    return frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "tests" / "fixtures" / "streaming_reference.json"))
    args = parser.parse_args()

    audio_path = BACKEND / "var" / "reference" / "streaming_reference.wav"
    frames = _build_audio(audio_path)

    from app.pipelines.stt import get_stt

    segments = get_stt().transcribe_visit(str(audio_path))

    chunk_bytes = CHUNK_FRAMES * 2
    chunks = [
        {"index": index, "pcm_len": len(frames[offset:offset + chunk_bytes])}
        for index, offset in enumerate(range(0, len(frames), chunk_bytes))
    ]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "audio_path": str(audio_path),
        "segments": segments,
        "chunks": chunks,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"المرجع الذهبي: {out_path} — {len(segments)} مقطع تفريغ · {len(chunks)} مقطع تغذية")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
