FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Шрифт (стикеры, мемы, PDF), cairo (рисунки из SVG), ffmpeg (видео)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core ca-certificates libcairo2 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# WITH_VOICE=false — собрать без голосовых (образ меньше на ~480 МБ)
ARG WITH_VOICE=true
COPY requirements.txt requirements-voice.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_VOICE" = "true" ]; then pip install -r requirements-voice.txt; fi
# меньше «пустой» памяти у моделей голоса
ENV MALLOC_ARENA_MAX=2

COPY bot ./bot
COPY panel ./panel

# Без root: агенту пишут посторонние люди
RUN useradd --create-home --uid 1000 stella && mkdir -p /app/data && chown -R stella:stella /app
USER stella

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
