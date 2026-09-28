FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cortex_tts ./cortex_tts
RUN pip install --no-cache-dir .
RUN useradd --system --uid 10001 cortex
USER cortex
EXPOSE 10200 18080
CMD ["python", "-m", "cortex_tts.main"]
