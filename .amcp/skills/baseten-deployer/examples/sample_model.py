#!/usr/bin/env python3
"""
Create a sample model for Baseten deployment testing.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib
import os


def create_sample_model():
    """Create and save a sample classification model."""
    
    # Generate sample data
    np.random.seed(42)
    n_samples = 1000
    
    # Create features
    X = np.random.randn(n_samples, 5)
    
    # Create binary target based on feature combination
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Train model
    model = RandomForestClassifier(
        n_estimators=100,
        random_state=42,
        max_depth=5
    )
    
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    
    print(f"Model trained with accuracy: {accuracy:.3f}")
    
    # Save model
    model_dir = os.path.dirname(__file__)
    model_path = os.path.join(model_dir, "sample_classifier.pkl")
    
    joblib.dump(model, model_path)
    print(f"Model saved to: {model_path}")
    
    # Save sample test data
    test_data_path = os.path.join(model_dir, "test_data.json")
    sample_input = X_test[0].tolist()
    
    import json
    with open(test_data_path, "w") as f:
        json.dump({"features": sample_input}, f, indent=2)
    
    print(f"Test data saved to: {test_data_path}")
    
    return model_path, test_data_path


if __name__ == "__main__":
    create_sample_model()