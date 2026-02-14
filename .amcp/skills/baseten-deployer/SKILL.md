---
name: baseten-deployer
description: Expert knowledge in Baseten model deployment, MLOps, and production ML workflows
---

# Baseten Model Deployment Skill

## Baseten Platform Overview

Baseten is a production ML platform that enables:
- **Model Deployment**: Deploy ML models as production APIs
- **Infrastructure Management**: Automatic scaling and monitoring
- **Model Registry**: Version control for models
- **A/B Testing**: Compare model performance
- **Monitoring**: Track model health and performance

## Baseten API Integration

### Authentication
```python
import os
from baseten import baseten_api

# Set API key
os.environ["BASETEN_API_KEY"] = "your_api_key_here"

# Initialize client
baseten_api.init()
```

### Model Deployment
```python
from baseten import baseten_api
import joblib
import pandas as pd

# Deploy a scikit-learn model
model = joblib.load("model.pkl")
deployment_id = baseten_api.deploy_model(
    model=model,
    model_name="my-classifier",
    version="1.0.0"
)
```

### Model Inference
```python
from baseten import baseten_api

# Make predictions
result = baseten_api.invoke_model(
    deployment_id="deployment_id",
    input_data={"features": [1.0, 2.0, 3.0]}
)
```

## AMCP + Baseten Integration

### Configuration
```toml
[baseten]
api_key = "your_api_key"
base_url = "https://api.baseten.co"
default_model = "zai-org/GLM-4.6"

[baseten.deployment]
auto_deploy = true
monitoring = true
scaling = "auto"
```

### Deployment Workflow
1. **Model Preparation**: Format model for Baseten
2. **API Integration**: Configure authentication and endpoints
3. **Deployment**: Upload and deploy model
4. **Testing**: Validate deployment with test requests
5. **Monitoring**: Set up health checks and alerts

## Model Types Support

### Supported Frameworks
- **Scikit-learn**: Traditional ML models
- **TensorFlow/Keras**: Deep learning models
- **PyTorch**: Research models
- **XGBoost**: Gradient boosting models
- **Hugging Face**: Transformer models

### Custom Models
```python
from baseten import baseten_api
import torch
import torch.nn as nn

class CustomModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = nn.Linear(10, 1)
    
    def forward(self, x):
        return self.linear(x)

# Deploy custom PyTorch model
model = CustomModel()
deployment_id = baseten_api.deploy_model(
    model=model,
    model_name="custom-pytorch",
    framework="pytorch"
)
```

## Production Best Practices

### Model Versioning
- Use semantic versioning (1.0.0, 1.1.0, 2.0.0)
- Track model metrics and performance
- Maintain rollback capabilities

### Monitoring and Alerting
```python
from baseten import baseten_api

# Get deployment metrics
metrics = baseten_api.get_deployment_metrics(
    deployment_id="deployment_id",
    time_range="24h"
)

# Set up alerts
baseten_api.create_alert(
    deployment_id="deployment_id",
    metric="latency",
    threshold=1000,  # ms
    action="notify"
)
```

### Scaling Configuration
```python
# Configure auto-scaling
baseten_api.configure_scaling(
    deployment_id="deployment_id",
    min_instances=1,
    max_instances=10,
    target_cpu_utilization=70
)
```

## Troubleshooting

### Common Issues
1. **Authentication Errors**: Check API key validity
2. **Model Format**: Ensure model is compatible
3. **Memory Limits**: Monitor resource usage
4. **Latency**: Optimize model size and batching

### Debug Commands
```bash
# Check deployment status
baseten-cli get deployment <deployment_id>

# View logs
baseten-cli logs <deployment_id>

# Test deployment
baseten-cli test <deployment_id> --input-file test.json
```

## Integration with AMCP Tools

### Model Deployment Tool
```python
def deploy_to_baseten(model_path: str, model_name: str):
    """Deploy model to Baseten."""
    import joblib
    from baseten import baseten_api
    
    # Load model
    model = joblib.load(model_path)
    
    # Deploy
    deployment_id = baseten_api.deploy_model(
        model=model,
        model_name=model_name
    )
    
    return {
        "deployment_id": deployment_id,
        "status": "deployed",
        "endpoint": f"https://api.baseten.co/v1/models/{deployment_id}"
    }
```

### Health Check Tool
```python
def check_baseten_health(deployment_id: str):
    """Check Baseten deployment health."""
    from baseten import baseten_api
    
    try:
        # Test with sample data
        result = baseten_api.invoke_model(
            deployment_id=deployment_id,
            input_data={"test": True}
        )
        return {"healthy": True, "response": result}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
```

## Security Considerations

### API Key Management
- Store API keys in environment variables
- Rotate keys regularly
- Use least privilege access

### Data Privacy
- Encrypt sensitive data
- Use secure connections (HTTPS)
- Comply with data protection regulations

## Cost Optimization

### Resource Management
- Monitor usage patterns
- Optimize model size
- Use spot instances when possible
- Implement caching strategies

### Performance Tuning
- Batch inference requests
- Optimize model architecture
- Use appropriate instance types
- Implement request queuing