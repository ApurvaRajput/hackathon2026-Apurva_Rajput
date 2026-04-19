# Use lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Environment variables (optional)
ENV PYTHONUNBUFFERED=1

# Default command
CMD ["python", "-m", "app.test_agent"]