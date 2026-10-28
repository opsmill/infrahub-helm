# RabbitMQ image for the infrahub chart's Bitnami rabbitmq sub-chart.
#
# Bitnami no longer updates bitnamilegacy/rabbitmq, so this image rebuilds it
# with the pending Debian 12 updates on top. The official rabbitmq image cannot replace
# it: the sub-chart runs Bitnami scripts and paths (/opt/bitnami/...) that only
# the Bitnami image ships.
#
# Published as registry.opsmill.io/opsmill/rabbitmq by
# .github/workflows/build-rabbitmq-image.yml, under the tag that
# charts/infrahub/values.yaml sets in rabbitmq.image.tag.
ARG BASE_IMAGE=docker.io/bitnamilegacy/rabbitmq:4.1.3-debian-12-r1
FROM ${BASE_IMAGE}

USER root

# Install every pending Debian 12 update. Only Debian packages are upgraded:
# Bitnami installs RabbitMQ and Erlang under /opt/bitnami outside of dpkg, so
# their versions stay those of the base image. Existing configuration files are
# kept, so the build never stops at a dpkg configuration prompt.
#
# The version check fails the build if libbrotli1 is still vulnerable to
# CVE-2026-111497 (buffer overflow in the Brotli decoder): the base image ships
# 1.0.9-2+b6 and Debian 12 fixes it in 1.0.9-2+deb12u1 (DLA-4855-1).
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --with-new-pkgs --no-install-recommends \
        -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    && apt-get clean && rm -rf /var/lib/apt/lists /var/cache/apt/archives \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libbrotli1)" ge 1.0.9-2+deb12u1

USER 1001
