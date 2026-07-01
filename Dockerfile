FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-dejavu-core \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/share/fonts/truetype/montserrat \
    && wget -q -O /usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf" \
    && wget -q -O /usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-ExtraBold.ttf" \
    && fc-cache -f

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

CMD ["python", "app.py"]
