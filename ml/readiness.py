"""Interview-readiness model starter.

Use only after enough labelled application outcomes exist. Until then the UI shows a readiness score,
not a claimed interview probability.
"""
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

def build_model():
    return Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(max_iter=1000))])
