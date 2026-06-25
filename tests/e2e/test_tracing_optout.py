"""Special e2e test for the tracing env-var opt-out behaviour.

NOT part of CI. CI's e2e jobs only ever select the per-chart markers
(``-m infrahub`` / ``enterprise`` / ``backup`` / ``observability`` / ``mcp``);
this module carries only the ``manual`` marker, so no automated job collects it.
Run it on demand against a local Docker + vcluster setup with::

    uv run pytest -v -m manual tests/e2e/test_tracing_optout.py

It proves the fix in ``charts/infrahub/templates/_env.tpl``: enabling
``infrahub-observability`` for only the Prefect exporter (bundled Tempo
disabled) must NOT inject ``INFRAHUB_TRACE_*`` / ``OTEL_EXPORTER_OTLP_*`` env
vars into the server and task-worker pods, while the bundled-Tempo and the
external-collector (``global.tracing``) paths still do.

The deploys disable the data backends and wait for nothing — only the rendered
Deployment objects are inspected, so the suite is fast and needs no running
pods.
"""

import subprocess
from pathlib import Path

import kr8s.asyncio
import pytest
from kr8s.asyncio.objects import Deployment

from tests.e2e.conftest import _register_namespace

pytestmark = pytest.mark.manual

RELEASE = "infrahub"
TRACE_ENV_PREFIXES = ("INFRAHUB_TRACE_", "OTEL_EXPORTER_OTLP_")

# Trim the stack to just what we inspect: backends off so each install is fast
# and creates no PVCs/StatefulSets. The server/task-worker Deployments still
# render — their backend env vars are guarded on the respective `*.enabled`.
BASE_SETS = {
    "neo4j.enabled": "false",
    "rabbitmq.enabled": "false",
    "redis.enabled": "false",
    "nats.enabled": "false",
    "prefect-server.enabled": "false",
}

# observability on, but only the Prefect exporter — every collector disabled.
# This is exactly the "enable observability for just the Prefect exporter" case.
OBS_ONLY_PREFECT = {
    "infrahub-observability.enabled": "true",
    "infrahub-observability.alloy.enabled": "false",
    "infrahub-observability.loki.enabled": "false",
    "infrahub-observability.grafana.enabled": "false",
    "infrahub-observability.prometheus.enabled": "false",
    "infrahub-observability.prometheus-node-exporter.enabled": "false",
    "infrahub-observability.prefectExporter.enabled": "true",
}


def _helm_install_nowait(
    release: str, chart_path: Path, namespace: str, kubeconfig: str, sets: dict
) -> None:
    """`helm upgrade --install` without --wait (we only read rendered specs)."""
    cmd = [
        "helm", "upgrade", "--install", release, str(chart_path),
        "--create-namespace", "-n", namespace, "--kubeconfig", kubeconfig,
    ]
    for key, value in sets.items():
        cmd.extend(["--set", f"{key}={value}"])
    subprocess.run(cmd, check=True, timeout=300)


async def _trace_env(api, namespace: str, service: str) -> dict[str, str]:
    """Return the tracing env (name->value) on the Deployment labelled
    `service=<service>`, restricted to the INFRAHUB_TRACE_*/OTEL_* names."""
    deps = [
        d
        async for d in Deployment.list(
            namespace=namespace, label_selector=f"service={service}", api=api
        )
    ]
    assert deps, f"no Deployment with service={service!r} in namespace {namespace!r}"
    env: dict[str, str] = {}
    for container in deps[0].raw["spec"]["template"]["spec"]["containers"]:
        for item in container.get("env") or []:
            if "value" in item:
                env[item["name"]] = item["value"]
    return {k: v for k, v in env.items() if k.startswith(TRACE_ENV_PREFIXES)}


async def _deployment_exists(api, namespace: str, service: str) -> bool:
    deps = [
        d
        async for d in Deployment.list(
            namespace=namespace, label_selector=f"service={service}", api=api
        )
    ]
    return bool(deps)


async def test_no_tracing_env_when_observability_on_but_tempo_off(
    vcluster, staged_charts, request
):
    """The bug/fix: obs on (Prefect exporter only), Tempo off, tracing off ->
    server and task-worker get NO tracing env vars, yet the Prefect exporter is
    deployed (so observability really is enabled)."""
    namespace = "trace-optout"
    _register_namespace(request, namespace)
    kubeconfig = vcluster["kubeconfig_path"]
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)

    _helm_install_nowait(
        RELEASE, staged_charts["infrahub"], namespace, kubeconfig,
        {
            **BASE_SETS,
            **OBS_ONLY_PREFECT,
            "infrahub-observability.tempo.enabled": "false",
            "global.tracing.enabled": "false",
        },
    )

    for service in ("infrahub-server", "infrahub-task-worker"):
        env = await _trace_env(api, namespace, service)
        assert env == {}, f"{service}: expected no tracing env, got {env}"

    # Observability is genuinely enabled — the Prefect exporter is deployed.
    assert await _deployment_exists(api, namespace, "prefect-exporter"), (
        "Prefect exporter Deployment missing — observability was not enabled"
    )


async def test_tracing_env_points_at_bundled_tempo_when_enabled(
    vcluster, staged_charts, request
):
    """Control: obs on with the bundled Tempo enabled, tracing off -> the env
    vars are injected and default to <release>-tempo:4317."""
    namespace = "trace-bundled"
    _register_namespace(request, namespace)
    kubeconfig = vcluster["kubeconfig_path"]
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)

    _helm_install_nowait(
        RELEASE, staged_charts["infrahub"], namespace, kubeconfig,
        {
            **BASE_SETS,
            **OBS_ONLY_PREFECT,
            "infrahub-observability.tempo.enabled": "true",
            "global.tracing.enabled": "false",
        },
    )

    for service in ("infrahub-server", "infrahub-task-worker"):
        env = await _trace_env(api, namespace, service)
        assert env.get("INFRAHUB_TRACE_ENABLE") == "true", f"{service}: {env}"
        assert env.get("INFRAHUB_TRACE_EXPORTER_ENDPOINT") == f"{RELEASE}-tempo:4317", (
            f"{service}: endpoint not defaulted to bundled Tempo; got {env}"
        )


async def test_tracing_env_uses_external_endpoint_without_tempo(
    vcluster, staged_charts, request
):
    """Control: Tempo/observability off but global.tracing on with an external
    endpoint -> the env vars are injected and point at that endpoint (the
    external-APM path), never at a bundled Tempo."""
    namespace = "trace-external"
    _register_namespace(request, namespace)
    kubeconfig = vcluster["kubeconfig_path"]
    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    endpoint = "my-otlp-collector.example:4317"

    _helm_install_nowait(
        RELEASE, staged_charts["infrahub"], namespace, kubeconfig,
        {
            **BASE_SETS,
            "infrahub-observability.enabled": "false",
            "global.tracing.enabled": "true",
            "global.tracing.endpoint": endpoint,
            "global.tracing.protocol": "grpc",
            "global.tracing.insecure": "true",
        },
    )

    for service in ("infrahub-server", "infrahub-task-worker"):
        env = await _trace_env(api, namespace, service)
        assert env.get("INFRAHUB_TRACE_ENABLE") == "true", f"{service}: {env}"
        assert env.get("INFRAHUB_TRACE_EXPORTER_ENDPOINT") == endpoint, (
            f"{service}: endpoint not the external collector; got {env}"
        )
