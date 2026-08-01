---
inclusion: auto
---
# Coding Standards

## Python
- Python 3.12+
- Type hints on all function signatures
- Docstrings on all public functions/classes
- Use Pydantic for data models and validation
- Use `logging` module, never `print()`
- Import order: stdlib → third-party → local (enforced by isort)

## Naming
- snake_case for functions, variables, modules
- PascalCase for classes
- UPPER_CASE for constants
- Prefix private methods with underscore

## Error Handling
- Use custom exception classes per module
- Always log errors before raising
- Lambda handlers must catch all exceptions and notify via WebSocket

## AWS
- Always specify region explicitly
- Use SSE-KMS for all S3 uploads
- Never hardcode credentials — use IAM roles and environment variables
- Bedrock calls must go through BedrockRateLimiter

## Testing
- Unit tests in tests/unit/
- Integration tests in tests/integration/
- Use pytest fixtures for AWS mocking (moto)
