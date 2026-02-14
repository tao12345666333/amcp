#!/usr/bin/env python3
"""
Simple Baseten deployment script for demonstration.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime


class SimpleBasetenDeployer:
    """Simplified Baseten deployer for demonstration."""
    
    def __init__(self):
        self.api_key = os.environ.get("BASETEN_API_KEY", "demo_key")
        self.deployments = {}
    
    def deploy_model(self, model_path: str, model_name: str, framework: str = "sklearn"):
        """Deploy a model (mock implementation)."""
        
        # Check if model file exists
        if not Path(model_path).exists():
            return {
                "status": "failed",
                "error": f"Model file not found: {model_path}"
            }
        
        # Generate deployment ID
        deployment_id = f"deploy_{model_name.replace('-', '_')}_{int(datetime.now().timestamp())}"
        
        # Store deployment info
        self.deployments[deployment_id] = {
            "deployment_id": deployment_id,
            "model_name": model_name,
            "framework": framework,
            "status": "deployed",
            "endpoint": f"https://api.baseten.co/v1/models/{deployment_id}",
            "created_at": datetime.now().isoformat(),
            "model_path": model_path
        }
        
        return self.deployments[deployment_id]
    
    def test_deployment(self, deployment_id: str, test_data: dict):
        """Test a deployment."""
        
        if deployment_id not in self.deployments:
            return {
                "status": "failed",
                "error": f"Deployment not found: {deployment_id}"
            }
        
        # Mock inference
        deployment = self.deployments[deployment_id]
        
        # Simple mock prediction
        if "features" in test_data:
            features = test_data["features"]
            if isinstance(features, list) and len(features) > 0:
                # Simple rule: if sum > threshold, predict 1
                feature_sum = sum(features)
                prediction = 1 if feature_sum > 5.0 else 0
                confidence = 0.8 if prediction == 1 else 0.7
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
            "status": "success"
        }
        
        return result
    
    def get_deployment_status(self, deployment_id: str):
        """Get deployment status."""
        
        if deployment_id not in self.deployments:
            return {
                "status": "failed",
                "error": f"Deployment not found: {deployment_id}"
            }
        
        deployment = self.deployments[deployment_id]
        
        # Add mock metrics
        deployment["metrics"] = {
            "requests_per_minute": 10,
            "average_latency_ms": 150,
            "error_rate": 0.01,
            "uptime_percentage": 99.9
        }
        
        return deployment
    
    def list_deployments(self):
        """List all deployments."""
        
        return {
            "status": "success",
            "deployments": list(self.deployments.values()),
            "total_count": len(self.deployments)
        }


def main():
    """Main CLI interface."""
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Simple Baseten deployment demo")
    parser.add_argument("action", choices=["deploy", "test", "status", "list"])
    parser.add_argument("--model-path", help="Path to model file")
    parser.add_argument("--model-name", help="Model name")
    parser.add_argument("--framework", default="sklearn", help="ML framework")
    parser.add_argument("--deployment-id", help="Deployment ID")
    parser.add_argument("--test-data", help="JSON test data")
    
    args = parser.parse_args()
    
    # Initialize deployer
    deployer = SimpleBasetenDeployer()
    
    # Execute action
    if args.action == "deploy":
        if not args.model_path or not args.model_name:
            print("Error: --model-path and --model-name required for deploy")
            sys.exit(1)
        
        result = deployer.deploy_model(
            model_path=args.model_path,
            model_name=args.model_name,
            framework=args.framework
        )
    
    elif args.action == "test":
        if not args.deployment_id or not args.test_data:
            print("Error: --deployment-id and --test-data required for test")
            sys.exit(1)
        
        test_data = json.loads(args.test_data)
        result = deployer.test_deployment(
            deployment_id=args.deployment_id,
            test_data=test_data
        )
    
    elif args.action == "status":
        if not args.deployment_id:
            print("Error: --deployment-id required for status")
            sys.exit(1)
        
        result = deployer.get_deployment_status(args.deployment_id)
    
    elif args.action == "list":
        result = deployer.list_deployments()
    
    # Print result
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()