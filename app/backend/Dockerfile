# -----------------------------

# Stage 1: Build dependencies

# -----------------------------

FROM python:3.11-slim AS builder

# Set environment variables

ENV PYTHONDONTWRITEBYTECODE=1

ENV PYTHONUNBUFFERED=1

# Set working directory

WORKDIR /mainapp

# Install system dependencies

#RUN apt-get update && apt-get install -y \
#
#    build-essential \
#
#    libpq-dev \
#&& rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies

COPY requirements.txt .

RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt


# -----------------------------

# Stage 2: Runtime image

# -----------------------------

FROM python:3.11-slim

WORKDIR /mainapp

# Environment vars

ENV PYTHONDONTWRITEBYTECODE=1

ENV PYTHONUNBUFFERED=1

# Copy installed packages from builder stage

COPY --from=builder /usr/local /usr/local

# Copy project files

COPY . .

# Collect static files

# RUN python manage.py collectstatic --noinput
# RUN find . -type d -name "migrations" -exec rm -rf {} +
# Expose port

EXPOSE 80

# Default command (Gunicorn for production)

# CMD ["/bin/sh", "-c", "python manage.py makemigrations --noinput && python manage.py migrate --noinput && gunicorn mainapp.wsgi:application --bind :80"]
CMD ["/bin/sh", "-c", "python manage.py migrate --noinput && gunicorn mainapp.wsgi:application --timeout 180 --workers 4  --bind :80"]