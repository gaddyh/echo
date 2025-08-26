import os
import tempfile
import ffmpeg
from google.cloud import speech_v1p1beta1 as speech
from google.oauth2 import service_account

GOOGLE_TTS_PHRASE_HINTS_LIMIT = 10

# NEW: config + helper import
import os

STT_PRICE_PER_MIN_USD = float(os.getenv("STT_PRICE_PER_MIN_USD", "0.024"))  # set in prod

def media_duration_seconds(path: str) -> float:
    """Return media duration in seconds using ffprobe."""
    try:
        meta = ffmpeg.probe(path)
        # prefer first audio stream, fallback to format
        for s in meta.get("streams", []):
            if s.get("codec_type") == "audio" and "duration" in s:
                return float(s["duration"])
        return float(meta["format"]["duration"])
    except Exception:
        return 0.0

def transcribe_opus_file(input_path: str, phrase_hints: list[str] = None) -> str:
    # Create a temporary .wav file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
        wav_path = wav_file.name

    # Convert .opus/.mp3/.ogg to .wav
    ffmpeg.input(input_path).output(
        wav_path, ac=1, ar=16000, format='wav', acodec='pcm_s16le'
    ).run(overwrite_output=True)

    try:
        with open(wav_path, "rb") as audio_file:
            content = audio_file.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            language_code="he-IL",
            speech_contexts=[speech.SpeechContext(phrases=phrase_hints[:GOOGLE_TTS_PHRASE_HINTS_LIMIT])] if phrase_hints else []
        )
        
        speech_creds = service_account.Credentials.from_service_account_file(
            os.path.join(os.getenv("SECRETS_DIR", ".secrets"), "tami-463501-a8053925ce03.json")
        )
        client = speech.SpeechClient(credentials=speech_creds)
        response = client.recognize(config=config, audio=audio)
        return " ".join(
            result.alternatives[0].transcript for result in response.results
        )
    finally:
        os.remove(wav_path)

if __name__ == "__main__":
    print(transcribe_opus_file("heVoice1.opus"))
