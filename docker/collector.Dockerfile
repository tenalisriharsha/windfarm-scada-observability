FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 9200

ENTRYPOINT ["python", "-m", "windfarm.collector.cli"]
CMD ["--turbines", "10", "--modbus-host", "simulator", "--modbus-port", "5020", "--metrics-host", "0.0.0.0", "--metrics-port", "9200"]
