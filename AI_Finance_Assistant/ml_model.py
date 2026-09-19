import pandas as pd

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


# Load dataset
data = pd.read_csv("finance_dataset.csv")

X = data["description"]
y = data["category"]


# Create ML pipeline
model = Pipeline([
    ("tfidf", TfidfVectorizer()),
    ("classifier", LogisticRegression(max_iter=1000))
])


# Train model
model.fit(X, y)


def predict_category(description):

    prediction = model.predict([description])[0]

    probabilities = model.predict_proba([description])[0]

    confidence = max(probabilities) * 100

    return prediction, round(confidence, 2)