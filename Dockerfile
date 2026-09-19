FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY data ./data
COPY docs ./docs
COPY .env.example ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src.runner", "--list-scenarios"]
