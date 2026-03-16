import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
import os

print("Starting model training...")

# --- 1. TOXICITY MODEL (ML) ---
# In a real project, this would be a huge dataset.
# For now, this is enough to prove the concept.
X_train_toxic = [
    "This professor is an idiot and a moron.",
    "This class is stupid as hell.",
    "This is a useless class, what a joke.",
    "He's a terrible teacher and is very rude.",
    "I love this course!",
    "The TA was very helpful and nice.",
    "Great class, learned a lot."
]
# 1 = Toxic, 0 = Clean
y_train_toxic = [1, 1, 1, 1, 0, 0, 0]

# We create a Scikit-learn Pipeline to bundle the
# text vectorizer and the classifier together.
toxicity_model_pipeline = Pipeline([
    ('tfidf', TfidfVectorizer()),
    ('clf', LogisticRegression())
])

print("Training toxicity model...")
toxicity_model_pipeline.fit(X_train_toxic, y_train_toxic)

# Save the trained model to the 'ml' folder
model_filename = 'ml/toxicity_model.joblib'
joblib.dump(toxicity_model_pipeline, model_filename)

print(f"Toxicity model trained and saved to {model_filename}")
print("\n--- Model Training Complete ---")
