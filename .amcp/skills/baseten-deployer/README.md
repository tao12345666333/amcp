# Baseten Model Deployment Skill

这个技能提供了将机器学习模型部署到 Baseten 平台的专业知识和工具。

## 功能特性

- 🚀 **模型部署**: 支持多种 ML 框架的模型部署
- 📊 **监控告警**: 实时监控模型性能和健康状态
- 🔧 **配置管理**: 灵活的部署配置选项
- 🧪 **测试验证**: 部署后自动测试和验证
- 📈 **性能优化**: 自动扩缩容和资源管理

## 支持的框架

- Scikit-learn
- PyTorch
- TensorFlow/Keras
- XGBoost
- Hugging Face Transformers

## 快速开始

### 1. 设置 API Key

```bash
export BASETEN_API_KEY="your_api_key_here"
```

### 2. 准备模型

```python
# 使用示例脚本创建测试模型
cd examples
python sample_model.py
```

### 3. 部署模型

```bash
# 使用部署脚本
cd scripts
python deploy_model.py deploy \
  --model-path ../examples/sample_classifier.pkl \
  --model-name "my-classifier" \
  --framework sklearn
```

### 4. 测试部署

```bash
python deploy_model.py test \
  --deployment-id <deployment_id> \
  --test-data '{"features": [1.0, 2.0, 3.0, 4.0, 5.0]}'
```

## 配置文件

在 `config.toml` 中配置部署参数：

```toml
[baseten]
api_key = "${BASETEN_API_KEY}"
base_url = "https://api.baseten.co"

[baseten.deployment]
auto_deploy = true
monitoring = true
scaling = "auto"
```

## AMCP 集成

这个技能可以与 AMCP 的其他工具集成：

### 模型部署工具

```python
from amcp.tools import deploy_to_baseten

# 部署模型
result = deploy_to_baseten(
    model_path="model.pkl",
    model_name="my-model"
)
```

### 健康检查工具

```python
from amcp.tools import check_baseten_health

# 检查部署状态
status = check_baseten_health(deployment_id="xxx")
```

## 最佳实践

### 模型版本管理
- 使用语义化版本号 (1.0.0, 1.1.0, 2.0.0)
- 记录模型指标和性能数据
- 保持回滚能力

### 监控和告警
- 设置延迟阈值告警
- 监控错误率
- 配置资源使用告警

### 安全考虑
- 使用环境变量存储 API Key
- 定期轮换密钥
- 遵循最小权限原则

## 故障排除

### 常见问题

1. **认证错误**: 检查 API Key 是否有效
2. **模型格式**: 确保模型格式兼容
3. **内存限制**: 监控资源使用情况
4. **延迟问题**: 优化模型大小和批处理

### 调试命令

```bash
# 检查部署状态
baseten-cli get deployment <deployment_id>

# 查看日志
baseten-cli logs <deployment_id>

# 测试部署
baseten-cli test <deployment_id> --input-file test.json
```

## 脚本说明

### `deploy_model.py`
主要的部署脚本，支持：
- 模型部署
- 部署测试
- 状态查询
- 部署列表

### `sample_model.py`
创建示例模型用于测试

### `config.toml`
部署配置文件

## 扩展功能

### 自定义模型支持

可以通过修改 `_load_model` 方法来支持自定义模型格式：

```python
def _load_model(self, model_path: str, framework: str) -> Any:
    if framework == "custom":
        # 自定义加载逻辑
        return load_custom_model(model_path)
    # ... 其他框架
```

### 批量部署

可以扩展脚本来支持批量部署多个模型：

```python
def batch_deploy(config_file: str):
    configs = load_config(config_file)
    for config in configs:
        deploy_model(config)
```

## 相关资源

- [Baseten 官方文档](https://docs.baseten.co/)
- [Baseten API 参考](https://docs.baseten.co/reference)
- [AMCP 技能文档](../README.md)