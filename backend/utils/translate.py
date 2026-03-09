from deep_translator import GoogleTranslator
from langdetect import detect

def translate_to_english(text):
    try:
        lang = detect(text)
        if lang != "en":
            translated = GoogleTranslator(source='auto', target='en').translate(text)
            return translated
        return text
    except Exception as e:
        print("⚠️ Translation failed:", e)
        return text
