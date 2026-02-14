#!/usr/bin/env python3
"""
Create a simple model for Baseten deployment testing.
"""

import pickle
import numpy as np
from pathlib import Path


def create_simple_model():
    """Create a very simple model for testing."""
    
    # Create a simple rule-based "model"
    class SimpleModel:
        def __init__(self):
            self.threshold = 0.5
            self.name = "simple-classifier"
        
        def predict(self, X):
            """Simple prediction based on feature sum."""
            if isinstance(X, list):
                X = np.array(X)
            
            # Reshape if needed
            if X.ndim == 1:
                X = X.reshape(1, -1)
            
            # Simple rule: if sum of features > threshold, predict 1
            predictions = []
            for row in X:
                feature_sum = np.sum(row)
                prediction = 1 if feature_sum > self.threshold else 0
                predictions.append(prediction)
            
            return np.array(predictions)
        
        def predict_proba(self, X):
            """Return probability-like scores."""
            predictions = self.predict(X)
            # Convert to probabilities
            probas = []
            for pred in predictions:
                if pred == 1:
                    probas.append([0.3, 0.7])  # [prob_class_0, prob_class_1]
                else:
                    probas.append([0.8, 0.2])
            return np.array(probas)
    
    # Create and save model
    model = SimpleModel()
    
    # Save to skill directory
    skill_dir = Path(__file__).parent.parent
    model_path = skill_dir / "examples" / "simple_classifier.pkl"
    
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    
    print(f"✅ Simple model created and saved to: {model_path}")
    
    # Test the model
    test_input = [[0.1, 0.2, 0.3], [1.0, 2.0, 3.0]]
    predictions = model.predict(test_input)
    print(f"✅ Model test - Input: {test_input}, Predictions: {predictions}")
    
    return model_path


if __name__ == "__main__":
    create_simple_model()