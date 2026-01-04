---
name: ai-engineer
description: Expert knowledge in AI/ML development, model deployment, and MLOps practices
---

# AI Engineer Skill

## Machine Learning Development

### Model Development Lifecycle
1. **Problem Definition**: Business objective framing
2. **Data Collection**: Gathering relevant datasets
3. **Data Preprocessing**: Cleaning, transformation, feature engineering
4. **Model Selection**: Algorithm choice and evaluation
5. **Training**: Model fitting and hyperparameter tuning
6. **Evaluation**: Metrics validation and testing
7. **Deployment**: Production integration
8. **Monitoring**: Performance tracking and drift detection

### Deep Learning Frameworks
- **TensorFlow/Keras**: Production-ready deep learning
- **PyTorch**: Research-friendly dynamic graphs
- **JAX**: Functional programming and auto-diff
- **FastAI**: High-level deep learning API

### Classical Machine Learning
- **Scikit-learn**: Traditional ML algorithms
- **XGBoost/LightGBM**: Gradient boosting frameworks
- **Pandas/NumPy**: Data manipulation and computation

### MLOps and Model Deployment

#### Model Serving Options
- **REST APIs**: Flask, FastAPI, Django
- **gRPC**: High-performance RPC
- **Serverless**: AWS Lambda, Google Cloud Functions
- **Containerized**: Docker, Kubernetes
- **Edge Deployment**: ONNX, TensorFlow Lite

#### Model Versioning
- **MLflow**: Experiment tracking and model registry
- **DVC**: Data version control
- **Git LFS**: Large file storage
- **Weights & Biases**: Experiment tracking

#### Monitoring and Observability
- **Prometheus/Grafana**: Metrics collection and visualization
- **ELK Stack**: Logging and search
- **Model Drift Detection**: Data and concept drift monitoring
- **A/B Testing**: Model performance comparison

### Data Engineering for AI

#### Data Pipeline Architecture
- **Batch Processing**: Airflow, Luigi, Prefect
- **Stream Processing**: Kafka, Apache Flink
- **ETL/ELT**: Data transformation patterns
- **Data Lakes**: Storage strategies for unstructured data

#### Feature Engineering
- **Feature Stores**: Feast, Hopsworks
- **Real-time Features**: Streaming feature computation
- **Feature Monitoring**: Data quality and validation

### Model Optimization

#### Performance Optimization
- **Quantization**: Reducing model precision (INT8, FP16)
- **Pruning**: Removing unnecessary model parameters
- **Knowledge Distillation**: Teacher-student model training
- **Model Compression**: Size reduction techniques

#### Inference Optimization
- **Batch Inference**: Processing multiple requests
- **Model Caching**: Reducing repeated computations
- **Hardware Acceleration**: GPUs, TPUs, specialized chips

### AI Ethics and Responsible AI

#### Fairness and Bias
- **Bias Detection**: Identifying systematic biases
- **Fairness Metrics**: Demographic parity, equal opportunity
- **Bias Mitigation**: Algorithmic and data-based approaches

#### Explainability and Interpretability
- **SHAP Values**: Feature importance explanation
- **LIME**: Local interpretable model explanations
- **Attention Visualization**: Understanding model focus

#### Privacy and Security
- **Federated Learning**: Privacy-preserving training
- **Differential Privacy**: Adding noise for privacy
- **Model Security**: Adversarial attack prevention

### AI Framework Integration

#### Cloud AI Services
- **AWS SageMaker**: End-to-end ML platform
- **Google Cloud AI**: Vertex AI, AutoML
- **Azure ML**: Microsoft's ML platform
- **IBM Watson**: Enterprise AI services

#### AutoML Platforms
- **Google AutoML**: Automated model training
- **H2O.ai**: AutoML and machine learning platform
- **DataRobot**: Enterprise AI platform

### Code Examples

#### Model Deployment with FastAPI
```python
from fastapi import FastAPI
import joblib
import numpy as np
from pydantic import BaseModel

app = FastAPI()

class PredictionRequest(BaseModel):
    features: list[float]

# Load model
model = joblib.load("model.pkl")

@app.post("/predict")
async def predict(request: PredictionRequest):
    features = np.array(request.features).reshape(1, -1)
    prediction = model.predict(features)
    return {"prediction": prediction[0]}

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

#### MLflow Experiment Tracking
```python
import mlflow
import mlflow.sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

with mlflow.start_run():
    # Train model
    model = RandomForestClassifier(n_estimators=100)
    model.fit(X_train, y_train)
    
    # Make predictions
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    
    # Log metrics and model
    mlflow.log_metric("accuracy", accuracy)
    mlflow.log_param("n_estimators", 100)
    mlflow.sklearn.log_model(model, "model")
```

#### Feature Engineering Pipeline
```python
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.pipeline import Pipeline

numeric_features = ["age", "income"]
categorical_features = ["gender", "city"]

preprocessor = ColumnTransformer(
    transformers=[
        ("num", StandardScaler(), numeric_features),
        ("cat", OneHotEncoder(), categorical_features)
    ]
)

model_pipeline = Pipeline([
    ("preprocessor", preprocessor),
    ("classifier", RandomForestClassifier())
])
```

### Best Practices

#### Model Development
1. **Reproducibility**: Seed setting, environment management
2. **Experiment Tracking**: Document all experiments
3. **Data Validation**: Quality checks and monitoring
4. **Cross-validation**: Robust performance evaluation

#### Production Deployment
1. **Model Versioning**: Track all model iterations
2. **A/B Testing**: Gradual rollout and comparison
3. **Monitoring**: Track performance and data drift
4. **Rollback Strategy**: Quick reversion capabilities

#### Security and Compliance
1. **Data Privacy**: GDPR, CCPA compliance
2. **Model Security**: Protect against adversarial attacks
3. **Access Control**: Proper authentication and authorization
4. **Audit Trails**: Complete logging of model operations

When working on AI projects, always consider:
- Ethical implications and bias
- Data privacy and security
- Model interpretability requirements
- Production monitoring needs
- Regulatory compliance
- Scalability and performance requirements