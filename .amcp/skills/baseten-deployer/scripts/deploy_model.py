#!/usr/bin/env python3
"""
Baseten Model Deployment Script

This script handles deploying ML models to Baseten platform.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import baseten
    from baseten import baseten_api
except ImportError:
    print("Error: baseten package not installed. Install with: pip install baseten")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BasetenDeployer:
    """Handle Baseten model deployment operations."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize deployer with API key."""
        self.api_key = api_key or os.environ.get("BASETEN_API_KEY")
        if not self.api_key:
            raise ValueError("BASETEN_API_KEY environment variable must be set")
        
        # Initialize Baseten API
        baseten_api.init(api_key=self.api_key)
    
    def deploy_model(
        self,
        model_path: str,
        model_name: str,
        version: str = "1.0.0",
        framework: str = "sklearn"
    ) -> Dict[str, Any]:
        """Deploy a model to Baseten.
        
        Args:
            model_path: Path to the model file
            model_name: Name for the deployment
            version: Model version
            framework: ML framework used
            
        Returns:
            Deployment information
        """
        try:
            # Load model based on framework
            model = self._load_model(model_path, framework)
            
            # Deploy to Baseten
            logger.info(f"Deploying {model_name} to Baseten...")
            deployment_id = baseten_api.deploy_model(
                model=model,
                model_name=model_name,
                version=version
            )
            
            # Get deployment info
            deployment_info = baseten_api.get_deployment(deployment_id)
            
            return {
                "deployment_id": deployment_id,
                "status": "deployed",
                "endpoint": f"https://api.baseten.co/v1/models/{deployment_id}",
                "model_name": model_name,
                "version": version,
                "framework": framework
            }
            
        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }
    
    def _load_model(self, model_path: str, framework: str) -> Any:
        """Load model based on framework."""
        model_path = Path(model_path)
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        if framework == "sklearn":
            import joblib
            return joblib.load(model_path)
        elif framework == "pytorch":
            import torch
            return torch.load(model_path)
        elif framework == "tensorflow":
            import tensorflow as tf
            return tf.keras.models.load_model(model_path)
        elif framework == "xgboost":
            import xgboost as xgb
            return xgb.Booster().load_model(model_path)
        else:
            raise ValueError(f"Unsupported framework: {framework}")
    
    def test_deployment(self, deployment_id: str, test_data: Dict[str, Any]) -> Dict[str, Any]:
        """Test a deployed model."""
        try:
            result = baseten_api.invoke_model(
                deployment_id=deployment_id,
                input_data=test_data
            )
            
            return {
                "status": "success",
                "result": result,
                "deployment_id": deployment_id
            }
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "deployment_id": deployment_id
            }
    
    def get_deployment_status(self, deployment_id: str) -> Dict[str, Any]:
        """Get deployment status and metrics."""
        try:
            info = baseten_api.get_deployment(deployment_id)
            metrics = baseten_api.get_deployment_metrics(
                deployment_id=deployment_id,
                time_range="24h"
            )
            
            return {
                "deployment_id": deployment_id,
                "status": info.get("status"),
                "endpoint": info.get("endpoint"),
                "metrics": metrics,
                "created_at": info.get("created_at")
            }
            
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return {
                "deployment_id": deployment_id,
                "status": "error",
                "error": str(e)
            }
    
    def list_deployments(self) -> Dict[str, Any]:
        """List all deployments."""
        try:
            deployments = baseten_api.list_deployments()
            
            return {
                "status": "success",
                "deployments": deployments
            }
            
        except Exception as e:
            logger.error(f"Failed to list deployments: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }


def main():
    """CLI interface for the deployer."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Deploy models to Baseten")
    parser.add_argument("action", choices=["deploy", "test", "status", "list"])
    parser.add_argument("--model-path", help="Path to model file")
    parser.add_argument("--model-name", help="Model name for deployment")
    parser.add_argument("--version", default="1.0.0", help="Model version")
    parser.add_argument("--framework", default="sklearn", help="ML framework")
    parser.add_argument("--deployment-id", help="Deployment ID for testing/status")
    parser.add_argument("--test-data", help="JSON test data for testing")
    parser.add_argument("--api-key", help="Baseten API key")
    
    args = parser.parse_args()
    
    # Initialize deployer
    try:
        deployer = BasetenDeployer(api_key=args.api_key)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Execute action
    if args.action == "deploy":
        if not args.model_path or not args.model_name:
            print("Error: --model-path and --model-name required for deploy")
            sys.exit(1)
        
        result = deployer.deploy_model(
            model_path=args.model_path,
            model_name=args.model_name,
            version=args.version,
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