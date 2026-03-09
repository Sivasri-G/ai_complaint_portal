import speech_recognition as sr
from pydub import AudioSegment
import os

def convert_voice_to_text(audio_path):
    try:
        # 🔹 Convert ANY format → PCM WAV
        sound = AudioSegment.from_file(audio_path)
        sound = sound.set_channels(1)
        sound = sound.set_frame_rate(16000)

        pcm_path = audio_path + "_pcm.wav"
        sound.export(pcm_path, format="wav")

        recognizer = sr.Recognizer()

        with sr.AudioFile(pcm_path) as source:
            audio_data = recognizer.record(source)

        # 🔹 FORCE Tamil language
        text = recognizer.recognize_google(audio_data, language="ta-IN")

        print("✅ Tamil Speech Recognized:", text)
        return text.strip()

    except sr.UnknownValueError:
        print("❌ Speech not understood")
        return ""

    except Exception as e:
        print("❌ Speech error:", e)
        return ""
