import os
import joblib


import nltk
from nltk.stem import WordNetLemmatizer
import re

# Download required datasets for first-time use
nltk.download("wordnet")
nltk.download("omw-1.4")

lemmatizer = WordNetLemmatizer()

def clean_text(text):
    text = text.lower()  # lowercase everything
    text = re.sub(r"[^a-z0-9\s]", "", text)  # remove special chars
    text = " ".join([lemmatizer.lemmatize(word) for word in text.split()])
    return text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH = os.path.join(BASE_DIR, "models", "complaint_model.pkl")
VECTORIZER_PATH = os.path.join(BASE_DIR, "models", "vectorizer.pkl")

# Load model & vectorizer
model = joblib.load(MODEL_PATH)
vectorizer = joblib.load(VECTORIZER_PATH)

def predict_category(text):
    text_vector = vectorizer.transform([text])
    prediction = model.predict(text_vector)[0]
    confidence = max(model.predict_proba(text_vector)[0])

    # 🔹 LOW CONFIDENCE FALLBACK
    if confidence < 0.3:
        return "Needs Review", round(confidence, 2)

    return prediction, round(confidence, 2)
