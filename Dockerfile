FROM python:3.11-slim as base
RUN apt-get update && \
    apt-get upgrade -y



FROM base as build
COPY . /src/
WORKDIR /src
RUN pip install -U pip && \
    python -m venv /venv --without-pip && \
    pip --python=/venv/bin/python install -c constraints.txt .




FROM base
ENV PYPI_SERVER_FILES_DIR="/pypi"

RUN apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=build /venv /venv
ENV PATH="/venv/bin:$PATH"

RUN mkdir -p $PYPI_SERVER_FILES_DIR && \
    chown -R www-data:www-data $PYPI_SERVER_FILES_DIR
VOLUME $PYPI_SERVER_FILES_DIR

USER www-data

ENV FORWARDED_ALLOW_IPS="*"
ENV UVICORN_HOST="0.0.0.0"
ENV UVICORN_PORT="80"
ENV PYPI_SERVER_ROOT_PATH="/pypi"
ENTRYPOINT ["uvicorn", "simple_python_package_index.main:app"]

HEALTHCHECK CMD curl --fail http://localhost/ping || exit 1
