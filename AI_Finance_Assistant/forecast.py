import numpy as np
from sklearn.linear_model import LinearRegression


def predict_next_month(expenses):

    if len(expenses) < 2:
        return None

    X = np.arange(1, len(expenses) + 1).reshape(-1, 1)
    y = np.array(expenses)

    model = LinearRegression()
    model.fit(X, y)

    next_month = np.array([[len(expenses) + 1]])

    prediction = model.predict(next_month)[0]

    return round(max(0, prediction), 2)