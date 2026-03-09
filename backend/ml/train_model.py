# -----------------------------
# IMPORT REQUIRED LIBRARIES
# -----------------------------
import os
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import accuracy_score, classification_report


# -----------------------------
# PATH CONFIGURATION
# -----------------------------
# Get the current directory of this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dataset path (30,000 records CSV)
DATASET_PATH = os.path.join(BASE_DIR, "complaints_55000.csv")

# Folder to save trained model & vectorizer
MODELS_DIR = os.path.join(BASE_DIR, "models")

MODEL_PATH = os.path.join(MODELS_DIR, "complaint_model.pkl")
VECTORIZER_PATH = os.path.join(MODELS_DIR, "vectorizer.pkl")


# -----------------------------
# CREATE MODELS DIRECTORY
# -----------------------------
os.makedirs(MODELS_DIR, exist_ok=True)


# -----------------------------
# LOAD DATASET
# -----------------------------
df = pd.read_csv(DATASET_PATH)

# Keep only required columns (safety check)
df = df[["Complaint_Text", "Category"]]

# Remove empty rows
df.dropna(inplace=True)

print(f"✅ Dataset Loaded: {df.shape[0]} records")


# -----------------------------
# INPUT (X) AND OUTPUT (y)
# -----------------------------
X = df["Complaint_Text"]   # Complaint description
y = df["Category"]         # Complaint category


# -----------------------------
# TRAIN / TEST SPLIT
# -----------------------------
# Stratify ensures all 10 categories are balanced in train & test
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.25,
    random_state=42,
    stratify=y
)


# -----------------------------
# TEXT VECTORIZATION (TF-IDF)
# -----------------------------
vectorizer = TfidfVectorizer(
    stop_words="english",     # Remove common words (is, the, and)
    max_features=8000,        # Higher features = better real-world learning
    ngram_range=(1, 2),       # Unigrams + Bigrams (very important)
    min_df=3                  # Ignore extremely rare words
)

# Convert text to numerical vectors
X_train_vec = vectorizer.fit_transform(X_train)
X_test_vec = vectorizer.transform(X_test)


# -----------------------------
# MODEL TRAINING
# -----------------------------
# Multinomial Naive Bayes works best for text classification
model = MultinomialNB(alpha=0.5)   # alpha tuning improves accuracy

model.fit(X_train_vec, y_train)


# -----------------------------
# MODEL EVALUATION
# -----------------------------
y_pred = model.predict(X_test_vec)

accuracy = accuracy_score(y_test, y_pred)

print("\n📊 Model Accuracy:")
print(f"{accuracy:.2f}")

print("\n📄 Classification Report:")
print(classification_report(y_test, y_pred))


# -----------------------------
# SAVE MODEL & VECTORIZER
# -----------------------------
joblib.dump(model, MODEL_PATH)
joblib.dump(vectorizer, VECTORIZER_PATH)

print("\n✅ Training Completed Successfully")
print(f"📁 Model saved at: {MODEL_PATH}")
print(f"📁 Vectorizer saved at: {VECTORIZER_PATH}")
