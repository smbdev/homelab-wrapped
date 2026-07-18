# Homelab Wrapped — one image, one volume (/data), near-zero idle.
FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE config.example.yaml ./
COPY wrapped ./wrapped
RUN pip install --no-cache-dir .

# Everything the app touches lives under /data: config.yaml, events.db, stories/.
WORKDIR /data
VOLUME /data
EXPOSE 8000

ENTRYPOINT ["wrapped"]
# Serves the UI; also runs the scheduler when jobs are enabled in config.yaml.
CMD ["serve", "--host", "0.0.0.0"]
