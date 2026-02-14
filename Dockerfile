FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for graphviz
RUN apt-get update && apt-get install -y \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY satisfactory_data.py .
COPY satisfactory_optimizer.py .
COPY satisfactory_flowchart.py .
COPY data_raw.json .
COPY webapp/ ./webapp/

# Create directories for uploads and watched files
RUN mkdir -p /app/uploads /app/watch

# Expose Flask port
EXPOSE 5000

# Set environment for Flask
ENV FLASK_APP=webapp/app.py
ENV PYTHONUNBUFFERED=1

# Default command runs the Flask app with file watcher
CMD ["python", "-u", "webapp/app.py"]
