#!/usr/bin/env python3
"""
Baseten deployment demonstration script.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime


# Global deployments storage (in a real implementation, this would be a database)
DEPLOYMENTS_FILE = Path(__file__).parent / "deployments.json"


def load_deployments():
    """Load deployments from file."""
    if DEPLOYMENTS_FILE.exists():
        with open(DEPLOYMENTS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_deployments(deployments):
    """Save deployments to file."""
    with open(DEPLOYMENTS_FILE, 'w') as f:
        json.dump(deployments, f, indent=2)


def deploy_model(model_path: str, model_name: str, framework: str = "sklearn"):
    """Deploy a model to Baseten (demo implementation)."""
    
    # Check if model file exists
    if not Path(model_path).exists():
        return {
            "status": "failed",
            "error": f"Model file not found: {model_path}"
        }
    
    # Load existing deployments
    deployments = load_deployments()
    
    # Generate deployment ID
    deployment_id = f"deploy_{model_name.replace('-', '_')}_{int(datetime.now().timestamp())}"
    
    # Create deployment record
    deployment = {
        "deployment_id": deployment_id,
        "model_name": model_name,
        "framework": framework,
        "status": "deployed",
        "endpoint": f"https://api.baseten.co/v1/models/{deployment_id}",
        "created_at": datetime.now().isoformat(),
        "model_path": model_path,
        "api_key": os.environ.get("BASETEN_API_KEY", "demo_key")
    }
    
    # Store deployment
    deployments[deployment_id] = deployment
    save_deployments(deployments)
    
    return deployment


def test_deployment(deployment_id: str, test_data: dict):
    """Test a deployed model."""
    
    # Load deployments
    deployments = load_deployments()
    
    if deployment_id not in deployments:
        return {
            "status": "failed",
            "error": f"Deployment not found: {deployment_id}"
        }
    
    deployment = deployments[deployment_id]
    
    # Mock inference based on test data
    if "features" in test_data:
        features = test_data["features"]
        if isinstance(features, list) and len(features) > 0:
            # Simple rule: if sum > threshold, predict 1
            feature_sum = sum(features)
            prediction = 1 if feature_sum > 5.0 else 0
            confidence = 0.8 if prediction == 1 else 0.7
            
            # Add some model-specific logic
            if deployment["framework"] == "sklearn":
                confidence *= 0.9
            elif deployment["framework"] == "pytorch":
                confidence *= 0.95
        else:
            prediction = 0
            confidence = 0.5
    else:
        prediction = 0
        confidence = 0.5
    
    result = {
        "prediction": prediction,
        "confidence": confidence,
        "deployment_id": deployment_id,
        "model_name": deployment["model_name"],
        "framework": deployment["framework"],
        "status": "success",
        "timestamp": datetime.now().isoformat()
    }
    
    return result


def get_deployment_status(deployment_id: str):
    """Get deployment status and metrics."""
    
    # Load deployments
    deployments = load_deployments()
    
    if deployment_id not in deployments:
        return {
            "status": "failed",
            "error": f"Deployment not found: {deployment_id}"
        }
    
    deployment = deployments[deployment_id]
    
    # Add mock metrics
    deployment["metrics"] = {
        "requests_per_minute": 15,
        "average_latency_ms": 120,
        "error_rate": 0.005,
        "uptime_percentage": 99.95,
        "memory_usage_mb": 256,
        "cpu_usage_percent": 45
    }
    
    deployment["health"] = "healthy"
    deployment["last_checked"] = datetime.now().isoformat()
    
    return deployment


def list_deployments():
    """List all deployments."""
    
    deployments = load_deployments()
    
    return {
        "status": "success",
        "deployments": list(deployments.values()),
        "total_count": len(deployments),
        "timestamp": datetime.now().isoformat()
    }


def delete_deployment(deployment_id: str):
    """Delete a deployment."""
    
    deployments = load_deployments()
    
    if deployment_id not in deployments:
        return {
            "status": "failed",
            "error": f"Deployment not found: {deployment_id}"
        }
    
    # Remove deployment
    del deployments[deployment_id]
    save_deployments(deployments)
    
    return {
        "status": "success",
        "message": f"Deployment {deployment_id} deleted successfully",
        "timestamp": datetime.now().isoformat()
    }


def main():
    """Main CLI interface."""
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Baseten deployment demonstration")
    parser.add_argument("action", choices=["deploy", "test", "status", "list", "delete"])
    parser.add_argument("--model-path", help="Path to model file")
    parser.add_argument("--model-name", help="Model name")
    parser.add_argument("--framework", default="sklearn", help="ML framework")
    parser.add_argument("--deployment-id", help="Deployment ID")
    parser.add_argument("--test-data", help="JSON test data")
    
    args = parser.parse_args()
    
    # Execute action
    if args.action == "deploy":
        if not args.model_path or not args.model_name:
            print("Error: --model-path and --model-name required for deploy")
            sys.exit(1)
        
        result = deploy_model(
            model_path=args.model_path,
            model_name=args.model_name,
            framework=args.framework
        )
    
    elif args.action == "test":
        if not args.deployment_id or not args.test_data:
            print("Error: --deployment-id and --test-data required for test")
            sys.exit(1)
        
        test_data = json.loads(args.test_data)
        result = test_deployment(
            deployment_id=args.deployment_id,
            test_data=test_data
        )
    
    elif args.action == "status":
        if not args.deployment_id:
            print("Error: --deployment-id required for status")
            sys.exit(1)
        
        result = get_deployment_status(args.deployment_id)
    
    elif args.action == "list":
        result = list_deployments()
    
    elif args.action == "delete":
        if not args.deployment_id:
            print("Error: --deployment-id required for delete")
            sys.exit(1)
        
        result = delete_deployment(args.deployment_id)
    
    # Print result
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()