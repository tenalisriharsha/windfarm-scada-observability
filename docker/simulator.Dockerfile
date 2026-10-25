FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 5020 8080

ENTRYPOINT ["python", "-m", "windfarm.simulator.cli"]
CMD ["--turbines", "10", "--modbus-host", "0.0.0.0", "--modbus-port", "5020", "--control-host", "0.0.0.0", "--control-port", "8080"]
