FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

#system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    mpv \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

#python packages
RUN pip install --no-cache-dir \
	psycopg2-binary \
	bcrypt \
	yt-dlp

#source code
COPY server.py .
COPY schema.sql .

RUN mkdir -p music backups transcoded_cache

#tcp port
EXPOSE 9000

#Command to run when the container starts
CMD ["python3", "server.py"]
