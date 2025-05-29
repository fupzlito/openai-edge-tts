# tts_handler.py

import edge_tts
import asyncio
import tempfile
import subprocess
import os
from pathlib import Path

from langdetect import detect, LangDetectException

from utils import DETAILED_ERROR_LOGGING
from config import DEFAULT_CONFIGS

# Language default (environment variable)
DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', DEFAULT_CONFIGS["DEFAULT_LANGUAGE"])

# OpenAI voice names mapped to edge-tts equivalents
voice_mapping = {
    'alloy': 'en-US-AvaNeural',
    'echo': 'en-US-AndrewNeural',
    'fable': 'en-GB-SoniaNeural',
    'onyx': 'en-US-EricNeural',
    'nova': 'en-US-SteffanNeural',
    'shimmer': 'en-US-EmmaNeural'
}

# Language fallback voices
MULTILINGUAL_VOICE = "en-US-AndrewMultilingualNeural"
LANGUAGE_VOICE_OVERRIDES = {
    "ru": "ru-RU-DmitryNeural"
}

def is_ffmpeg_installed():
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

async def _generate_audio(text, voice, response_format, speed):
    temp_mp3_file_obj = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    temp_mp3_path = temp_mp3_file_obj.name

    try:
        speed_rate = speed_to_rate(speed)
    except Exception as e:
        print(f"Error converting speed: {e}. Defaulting to +0%.")
        speed_rate = "+0%"

    communicator = edge_tts.Communicate(text=text, voice=voice, rate=speed_rate)
    await communicator.save(temp_mp3_path)
    temp_mp3_file_obj.close()

    if response_format == "mp3":
        return temp_mp3_path

    if not is_ffmpeg_installed():
        print("FFmpeg is not available. Returning unmodified mp3 file.")
        return temp_mp3_path

    converted_file_obj = tempfile.NamedTemporaryFile(delete=False, suffix=f".{response_format}")
    converted_path = converted_file_obj.name
    converted_file_obj.close()

    ffmpeg_command = [
        "ffmpeg", "-i", temp_mp3_path,
        "-c:a", {
            "aac": "aac",
            "mp3": "libmp3lame",
            "wav": "pcm_s16le",
            "opus": "libopus",
            "flac": "flac"
        }.get(response_format, "aac")
    ]

    if response_format != "wav":
        ffmpeg_command.extend(["-b:a", "192k"])

    ffmpeg_command.extend([
        "-f", {
            "aac": "mp4",
            "mp3": "mp3",
            "wav": "wav",
            "opus": "ogg",
            "flac": "flac"
        }.get(response_format, response_format),
        "-y", converted_path
    ])

    try:
        subprocess.run(ffmpeg_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        Path(converted_path).unlink(missing_ok=True)
        Path(temp_mp3_path).unlink(missing_ok=True)

        error_message = (
            f"FFmpeg error during audio conversion. Command: '{' '.join(e.cmd)}'. "
            f"Stderr: {e.stderr.decode('utf-8', 'ignore')}" if DETAILED_ERROR_LOGGING
            else f"FFmpeg error during audio conversion: {e}"
        )
        print(error_message)
        raise RuntimeError(error_message)

    Path(temp_mp3_path).unlink(missing_ok=True)
    return converted_path

def generate_speech(text, voice, response_format, speed=1.0):
    try:
        detected_lang = detect(text)
    except LangDetectException:
        detected_lang = "en"

    mapped_voice = voice_mapping.get(voice, voice)

    if mapped_voice.startswith("en-") and "Multilingual" not in mapped_voice:
        if detected_lang in LANGUAGE_VOICE_OVERRIDES:
            print(f"[TTS] Detected {detected_lang} — using {LANGUAGE_VOICE_OVERRIDES[detected_lang]}")
            mapped_voice = LANGUAGE_VOICE_OVERRIDES[detected_lang]
        elif detected_lang != "en":
            print(f"[TTS] Detected non-English ({detected_lang}) — using multilingual voice")
            mapped_voice = MULTILINGUAL_VOICE

    return asyncio.run(_generate_audio(text, mapped_voice, response_format, speed))

def get_models():
    return [
        {"id": "tts-1", "name": "Text-to-speech v1"},
        {"id": "tts-1-hd", "name": "Text-to-speech v1 HD"}
    ]

async def _get_voices(language=None):
    all_voices = await edge_tts.list_voices()
    language = language or DEFAULT_LANGUAGE
    return [
        {"name": v['ShortName'], "gender": v['Gender'], "language": v['Locale']}
        for v in all_voices if language == 'all' or language is None or v['Locale'] == language
    ]

def get_voices(language=None):
    return asyncio.run(_get_voices(language))

def speed_to_rate(speed: float) -> str:
    if speed < 0 or speed > 2:
        raise ValueError("Speed must be between 0 and 2 (inclusive).")
    percentage_change = (speed - 1) * 100
    return f"{percentage_change:+.0f}%"
