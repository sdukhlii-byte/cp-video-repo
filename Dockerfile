FROM python:3.11-slim

# ffmpeg с libass — субтитры прожигаются фильтром subtitles, без libass не соберётся
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python3", "cli.py", "doctor"]
