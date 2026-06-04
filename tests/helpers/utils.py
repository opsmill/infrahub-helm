"""Reusable helpers for the e2e suite: HTTP polling, the Infrahub SDK,
Grafana's HTTP API, and small Kubernetes helpers (wait for Job) via kr8s.
"""

import asyncio
import time
import uuid

import httpx

# Default admin token baked into charts/infrahub/values.yaml
# (INFRAHUB_INITIAL_ADMIN_TOKEN). Tests use it to talk to the API.
INFRAHUB_ADMIN_TOKEN = "06438eb2-8019-4776-878c-0941b1f1d1ec"


# ---------------------------------------------------------------------------
# HTTP polling
# ---------------------------------------------------------------------------
async def wait_for_http(
    url: str,
    timeout: float = 120.0,
    interval: float = 2.0,
    expected_status: int = 200,
    auth: tuple[str, str] | None = None,
) -> None:
    """Poll an HTTP endpoint until it returns the expected status code."""
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(url, timeout=5, auth=auth)
                if resp.status_code == expected_status:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(interval)
    raise TimeoutError(f"{url} did not return {expected_status} after {timeout}s")


# ---------------------------------------------------------------------------
# Infrahub SDK helpers — a BuiltinTag is the simplest object to round-trip.
# ---------------------------------------------------------------------------
def _infrahub_client(url: str, token: str):
    from infrahub_sdk import Config, InfrahubClient

    # insert_tracker makes the SDK send an X-Infrahub-Tracker header (e.g.
    # "query-builtintag-page1"), which Infrahub records for observability.
    return InfrahubClient(config=Config(address=url, api_token=token, insert_tracker=True))


async def check_infrahub_healthy(url: str, token: str) -> dict:
    """Confirm the API is reachable and reports schema/branches via the SDK."""
    client = _infrahub_client(url, token)
    branches = await client.branch.all()
    assert "main" in branches, f"Expected a 'main' branch, got {list(branches)}"
    return {"branches": list(branches)}


async def seed_infrahub_data(url: str, token: str) -> dict:
    """Create a uniquely-named BuiltinTag; return data used for verification."""
    client = _infrahub_client(url, token)
    tag_name = f"e2e-{uuid.uuid4().hex[:8]}"
    tag = await client.create(kind="BuiltinTag", name=tag_name)
    await tag.save()
    return {"tag_name": tag_name}


async def verify_infrahub_data(url: str, token: str, expected: dict) -> None:
    """Assert the seeded tag exists."""
    client = _infrahub_client(url, token)
    tag = await client.get(kind="BuiltinTag", name__value=expected["tag_name"])
    assert tag.name.value == expected["tag_name"], (
        f"Expected tag '{expected['tag_name']}' but got '{tag.name.value}'"
    )


async def generate_infrahub_traffic(
    url: str, token: str, operation_name: str, rounds: int = 5
) -> None:
    """Drive API calls to produce server-side metrics and traces.

    Creates tags (metrics) and sends a BuiltinTag GraphQL query carrying an
    explicit operationName. Infrahub records that name on the `execute_graphql`
    span's `operation` attribute, so the trace can be located precisely in Tempo
    via `{ span.operation = "<operation_name>" }`.
    """
    client = _infrahub_client(url, token)
    for i in range(rounds):
        tag = await client.create(kind="BuiltinTag", name=f"obs-traffic-{i}-{uuid.uuid4().hex[:6]}")
        await tag.save()

    query = f"query {operation_name} {{ BuiltinTag {{ edges {{ node {{ id }} }} }} }}"
    payload = {"query": query, "operationName": operation_name}
    headers = {"X-INFRAHUB-KEY": token, "content-type": "application/json"}
    async with httpx.AsyncClient() as client_http:
        for _ in range(rounds):
            resp = await client_http.post(
                f"{url}/graphql/main", json=payload, headers=headers, timeout=30
            )
            resp.raise_for_status()


async def modify_infrahub_data(url: str, token: str, data: dict) -> None:
    """Delete the seeded tag so a restore can prove it reverted."""
    client = _infrahub_client(url, token)
    tag = await client.get(kind="BuiltinTag", name__value=data["tag_name"])
    await tag.delete()
    tags = await client.all(kind="BuiltinTag")
    assert all(t.name.value != data["tag_name"] for t in tags), (
        f"Tag '{data['tag_name']}' still exists after deletion"
    )


# ---------------------------------------------------------------------------
# Grafana HTTP API helpers
# ---------------------------------------------------------------------------
async def grafana_list_datasources(url: str, auth: tuple[str, str]) -> list[dict]:
    """Return the list of provisioned Grafana datasources."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{url}/api/datasources", auth=auth, timeout=30)
        resp.raise_for_status()
        return resp.json()


async def grafana_proxy_get(
    url: str,
    auth: tuple[str, str],
    uid: str,
    path: str,
    params: dict | None = None,
    timeout: float = 120.0,
):
    """GET through Grafana's datasource proxy, polling until HTTP 200.

    /api/datasources/proxy/uid/{uid}{path} forwards the request to the datasource
    backend, so a 200 proves Grafana can reach and query that datasource. Returns
    the parsed JSON body (or text if not JSON).
    """
    start = time.time()
    last: httpx.Response | None = None
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(
                    f"{url}/api/datasources/proxy/uid/{uid}{path}",
                    params=params,
                    auth=auth,
                    timeout=30,
                )
                last = resp
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        return resp.text
            except httpx.HTTPError:
                pass
            await asyncio.sleep(5)
    detail = "" if last is None else f" (last={last.status_code}: {last.text[:200]})"
    raise TimeoutError(f"proxy GET {path} on {uid} not 200 after {timeout}s{detail}")


async def grafana_query_prometheus(
    url: str, auth: tuple[str, str], datasource_uid: str, expr: str, timeout: float = 120.0
) -> list:
    """Run an instant PromQL query through Grafana's datasource proxy.

    Polls until the query returns at least one series, proving Grafana can query
    metrics end-to-end (Grafana -> Prometheus -> data).
    """
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            resp = await client.get(
                f"{url}/api/datasources/proxy/uid/{datasource_uid}/api/v1/query",
                params={"query": expr},
                auth=auth,
                timeout=30,
            )
            if resp.status_code == 200:
                payload = resp.json()
                result = payload.get("data", {}).get("result", [])
                if result:
                    return result
            await asyncio.sleep(5)
    raise TimeoutError(f"PromQL '{expr}' returned no data after {timeout}s")


async def grafana_tempo_traceql(
    url: str,
    auth: tuple[str, str],
    datasource_uid: str,
    query: str,
    timeout: float = 180.0,
) -> list:
    """Run a TraceQL search through Grafana's Tempo proxy until it matches.

    Lets Tempo filter server-side (so unrelated background traces don't crowd
    out the result), and returns the matching trace summaries.
    """
    proxy = f"{url}/api/datasources/proxy/uid/{datasource_uid}"
    start = time.time()
    last = ""
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            resp = await client.get(
                f"{proxy}/api/search",
                params={
                    "q": query,
                    "start": str(int(start) - 3600),
                    "end": str(int(time.time()) + 60),
                    "limit": "20",
                },
                auth=auth,
                timeout=30,
            )
            if resp.status_code == 200:
                traces = resp.json().get("traces") or []
                if traces:
                    return traces
            else:
                last = f"{resp.status_code}: {resp.text[:200]}"
            await asyncio.sleep(5)
    raise TimeoutError(f"TraceQL {query!r} matched no traces after {timeout}s ({last})")


# ---------------------------------------------------------------------------
# Kubernetes helpers (kr8s)
# ---------------------------------------------------------------------------
async def _job_pod_logs(api, namespace: str, job_name: str, tail: int = 200) -> str:
    """Collect recent logs from a Job's pods (for failure diagnostics)."""
    from kr8s.asyncio.objects import Pod

    chunks: list[str] = []
    async for pod in Pod.list(
        namespace=namespace, label_selector=f"job-name={job_name}", api=api
    ):
        lines = [line async for line in pod.logs(tail_lines=tail)]
        chunks.append(f"--- {pod.name} ---\n" + "\n".join(lines))
    return "\n".join(chunks) or "(no job pods/logs)"


async def wait_for_job(
    kubeconfig: str, namespace: str, job_name: str, timeout: int = 600
) -> None:
    """Block until a Job reports Complete, or raise on failure/timeout."""
    import kr8s.asyncio
    from kr8s.asyncio.objects import Job

    api = await kr8s.asyncio.api(kubeconfig=kubeconfig)
    job = await Job.get(job_name, namespace=namespace, api=api)
    try:
        await job.wait(["condition=Complete", "condition=Failed"], timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        logs = await _job_pod_logs(api, namespace, job_name)
        raise AssertionError(
            f"Job '{job_name}' did not finish within {timeout}s\n{logs}"
        )

    await job.refresh()
    conditions = (job.raw.get("status") or {}).get("conditions") or []
    if any(c.get("type") == "Failed" and str(c.get("status")) == "True" for c in conditions):
        logs = await _job_pod_logs(api, namespace, job_name)
        raise AssertionError(f"Job '{job_name}' failed\n{logs}")
