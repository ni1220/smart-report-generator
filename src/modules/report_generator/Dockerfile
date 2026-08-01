FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY prompts/ ./prompts/
COPY templates/ ./templates/

ENV PYTHONPATH=/app

# Run the report generator as ECS Fargate task
CMD ["python", "-m", "src.modules.report_generator.main"]
