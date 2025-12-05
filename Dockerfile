FROM node:18.20.4-alpine3.20 AS build-stage

RUN apk add git
RUN set -eux \
    && mkdir -p /app \
    && mkdir -p /api

COPY frontend/ /app
COPY entrypoint.sh /api/entrypoint.sh

WORKDIR /app
RUN rm -r src/components/Stacks-Editor
RUN git clone https://github.com/BaldissaraMatheus/Stacks-Editor src/components/Stacks-Editor
RUN cd src/components/Stacks-Editor && npm ci --no-audit
RUN set -eux && npm ci --no-audit --omit=dev

COPY backend/ /api/

WORKDIR /api
RUN set -eux && npm ci --no-audit

FROM alpine:3.20 AS final
USER root
RUN set -eux && apk add --no-cache nodejs npm python3 py3-pip gcc musl-dev python3-dev
RUN mkdir /stylesheets

# Autoschedule setup
COPY autoschedule/requirements.txt /autoschedule/requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /autoschedule/requirements.txt
COPY autoschedule/src/ /autoschedule/src/
COPY autoschedule/pyproject.toml /autoschedule/pyproject.toml
WORKDIR /autoschedule
RUN pip3 install --break-system-packages -e .
COPY --from=build-stage /app /app
COPY --from=build-stage /api/ /api/

VOLUME /tasks
VOLUME /config
WORKDIR /api
EXPOSE 8080

ENTRYPOINT sh entrypoint.sh
