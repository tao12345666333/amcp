#!/usr/bin/env python3
"""
Test Baseten deployment functionality without actual API calls.
"""

import json
import os
import sys
from pathlib import Path


def mock_deploy_model(model_path: str, model_name: str, framework: str = "sklearn"):
    """Mock deployment for testing purposes."""
    
    # Check if model file exists
    if not Path(model_path).exists():
        return {
            "status": "failed",
            "error": f"Model file not found: {model_path}"
        }
    
    # Mock deployment response
    deployment_id = f"deploy_{model_name.replace('-', '_')}_12345"
    
    return {
        "deployment_id": deployment_id,
        "status": "deployed",
        "endpoint": f"https://api.baseten.co/v1/models/{deployment_id}",
        "model_name": model_name,
        "framework": framework,
        "version": "1.0.0",
        "message": "Mock deployment successful"
    }


def test_deployment_setup():
    """Test the deployment setup."""
    
    skill_dir = Path(__file__).parent.parent
    examples_dir = skill_dir / "examples"
    
    # Test files
    model_file = examples_dir / "sample_classifier.pkl"
    test_data_file = examples_dir / "test_data.json"
    
    print("Testing Baseten deployment setup...")
    print(f"Skill directory: {skill_dir}")
    print(f"Model file: {model_file}")
    print(f"Test data file: {test_data_file}")
    
    # Check if files exist
    if not model_file.exists():
        print(f"❌ Model file not found: {model_file}")
        return False
    
    if not test_data_file.exists():
        print(f"❌ Test data file not found: {test_data_file}")
        return False
    
    print("✅ All required files exist")
    
    # Test mock deployment
    result = mock_deploy_model(
        model_path=str(model_file),
        model_name="test-classifier",
        framework="sklearn"
    )
    
    print(f"Mock deployment result: {json.dumps(result, indent=2)}")
    
    if result["status"] == "deployed":
        print("✅ Mock deployment successful")
        
        # Test deployment status
        deployment_id = result["deployment_id"]
        print(f"Deployment ID: {deployment_id}")
        print(f"Endpoint: {result['endpoint']}")
        
        return True
    else:
        print("❌ Mock deployment failed")
        return False


def check_environment():
    """Check environment setup."""
    
    print("\nChecking environment...")
    
    # Check for required environment variables
    api_key = os.environ.get("BASETEN_API_KEY")
    if api_key:
        print("✅ BASETEN_API_KEY is set")
    else:
        print("⚠️  BASETEN_API_KEY not set (using mock mode)")
    
    # Check Python version
    python_version = sys.version_info
    print(f"✅ Python version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # Check for required packages (in mock mode, we don't need them)
    required_packages = ["json", "pathlib", "os", "sys"]
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package} available")
        except ImportError:
            print(f"❌ {package} not available")
            return False
    
    return True


def main():
    """Main test function."""
    
    print("=" * 50)
    print("Baseten Deployment Skill Test")
    print("=" * 50)
    
    # Check environment
    if not check_environment():
        print("\n❌ Environment check failed")
        sys.exit(1)
    
    # Test deployment setup
    if not test_deployment_setup():
        print("\n❌ Deployment setup test failed")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("✅ All tests passed!")
    print("=" * 50)
    
    print("\nNext steps:")
    print("1. Set BASETEN_API_KEY environment variable")
    print("2. Install baseten package: pip install baseten")
    print("3. Use deploy_model.py for actual deployment")
    print("4. Monitor deployment via Baseten dashboard")


if __name__ == "__main__":
    main()