FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade setuptools
RUN pip install --no-cache-dir --no-deps -r requirements.txt

COPY . .

EXPOSE 3000

CMD ["gunicorn", "simple_app:app", "--bind", "0.0.0.0:3000"]
