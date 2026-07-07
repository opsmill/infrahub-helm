"""Reusable helpers for the e2e suite: HTTP polling, the Infrahub SDK,
Grafana's HTTP API, and small Kubernetes helpers (wait for Job) via kr8s.
"""

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

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
    headers: dict | None = None,
) -> None:
    """Poll an HTTP endpoint until it returns the expected status code.

    ``headers`` lets callers send e.g. a ``Host`` header so a request through a
    port-forwarded ingress controller is routed to the right virtual host.
    """
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(url, timeout=5, auth=auth, headers=headers)
                if resp.status_code == expected_status:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(interval)
    raise TimeoutError(f"{url} did not return {expected_status} after {timeout}s")


async def wait_for_infrahub_branch_ready(
    url: str,
    token: str,
    *,
    headers: dict | None = None,
    timeout: float = 180.0,
    interval: float = 5.0,
) -> None:
    """Poll (via the Infrahub SDK) until a branch can actually be created.

    An HTTP 200 on ``/api/config`` only means the web app is up — it does *not*
    mean the task-worker has finished registering its Prefect flow deployments.
    Branch creation runs the ``create-branch`` deployment, so until that is
    registered ``client.branch.create`` fails with a Prefect 404 surfaced as a
    GraphQL 500 ("Deployment not found"). Callers that create branches (e.g. the
    MCP session auto-branch) must wait for this, or they race the worker and
    flake.

    Creates a throwaway branch (retrying through the transient error) and deletes
    it best-effort. ``headers`` may carry a ``Host`` header to route through a
    name-based ingress; it is merged into the SDK client's request headers so the
    probe reaches Infrahub the same way the caller does.
    """
    from infrahub_sdk import Config, InfrahubClient
    from infrahub_sdk.exceptions import Error as InfrahubError

    client = InfrahubClient(config=Config(address=url, api_token=token))
    client.headers.update(headers or {})

    start = time.time()
    last = "no response"
    while time.time() - start < timeout:
        probe = f"e2e-branch-probe-{uuid.uuid4().hex[:8]}"
        try:
            await client.branch.create(branch_name=probe, sync_with_git=False)
        except (InfrahubError, httpx.HTTPError) as exc:
            last = str(exc) or type(exc).__name__
            await asyncio.sleep(interval)
            continue
        try:  # cleanup is best-effort — the cluster is throwaway
            await client.branch.delete(branch_name=probe)
        except (InfrahubError, httpx.HTTPError):
            pass
        return
    raise TimeoutError(f"Infrahub branch API not ready after {timeout}s ({last})")


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
# MCP client helpers (streamable-HTTP transport)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def mcp_session(
    mcp_url: str, headers: dict | None = None, timeout: float = 120.0
):
    """Open an initialized MCP session over the streamable-HTTP transport.

    ``headers`` may carry a ``Host`` header so the session is established
    through a name-based ingress. Yields an initialized ``ClientSession`` so a
    test can issue several tool calls on one session — e.g. a write tool then a
    read tool that share the auto-created session branch.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(mcp_url, headers=headers, timeout=timeout) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def mcp_result_text(result) -> str:
    """Serialize an MCP tool-call result to text (content blocks + structured).

    Folding both forms in lets callers assert on the payload without depending
    on whether a tool returns text content, structured output, or both.
    """
    parts = [
        block.text
        for block in result.content
        if getattr(block, "text", None) is not None
    ]
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        parts.append(json.dumps(structured, default=str))
    return "\n".join(parts)


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
# Grafana dashboards: provisioning API + dashboard-JSON inspection
# ---------------------------------------------------------------------------
async def grafana_search_dashboards(url: str, auth: tuple[str, str]) -> list[dict]:
    """Return Grafana's dashboard search results (type=dash-db)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/api/search", params={"type": "dash-db"}, auth=auth, timeout=30
        )
        resp.raise_for_status()
        return resp.json()


async def grafana_wait_for_dashboards(
    url: str, auth: tuple[str, str], expected_uids: set[str], timeout: float = 180.0
) -> list[dict]:
    """Poll search until every expected dashboard UID has been imported.

    Grafana's sidecar copies the dashboard ConfigMaps into the provisioning
    folder shortly after the pod is Ready, so the set appears a little after
    deploy — hence the poll rather than a single read.
    """
    start = time.time()
    found: list[dict] = []
    while time.time() - start < timeout:
        found = await grafana_search_dashboards(url, auth)
        if expected_uids <= {d.get("uid") for d in found}:
            return found
        await asyncio.sleep(5)
    missing = expected_uids - {d.get("uid") for d in found}
    raise TimeoutError(
        f"Dashboards {sorted(missing)} not imported by Grafana after {timeout}s"
    )


async def grafana_get_dashboard(url: str, auth: tuple[str, str], uid: str) -> dict:
    """Fetch a dashboard by UID; returns the {'dashboard', 'meta'} envelope.

    A 200 proves Grafana parsed and loaded the stored dashboard model.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{url}/api/dashboards/uid/{uid}", auth=auth, timeout=30)
        resp.raise_for_status()
        return resp.json()


async def grafana_promql_is_valid(
    url: str, auth: tuple[str, str], datasource_uid: str, expr: str, timeout: float = 60.0
) -> dict:
    """Execute an instant PromQL query through the proxy and return the raw
    Prometheus response, *without* requiring it to return data.

    Prometheus answers `{"status": "success", ...}` for a query it can parse
    and run, and `{"status": "error", ...}` (HTTP 400) for a malformed one — so
    this checks a shipped dashboard query is *valid*, independent of whether
    series happen to exist yet. A genuine Prometheus error is returned at once;
    only transient transport/proxy hiccups (non-JSON, e.g. a brief 502) are
    retried, so they don't masquerade as an invalid query.
    """
    proxy = f"{url}/api/datasources/proxy/uid/{datasource_uid}/api/v1/query"
    start = time.time()
    last = "no response"
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(
                    proxy, params={"query": expr}, auth=auth, timeout=30
                )
                return resp.json()
            except httpx.HTTPError as exc:
                last = str(exc)
            except ValueError:
                last = f"{resp.status_code}: {resp.text[:200]}"
            await asyncio.sleep(3)
    return {"status": "error", "error": f"no JSON response after {timeout}s ({last})"}


def load_vendored_dashboards(dashboards_dir) -> list[dict]:
    """Read the dashboard JSONs the chart ships from ``dashboards_dir``.

    Returns one entry per file: ``{"file", "uid", "title", "model"}``. This is
    the source of truth the e2e test checks Grafana against, so adding or
    removing a dashboard in the chart automatically widens/narrows the checks.
    """
    dashboards = []
    for path in sorted(Path(dashboards_dir).glob("*.json")):
        model = json.loads(path.read_text())
        dashboards.append(
            {
                "file": path.name,
                "uid": model.get("uid"),
                "title": model.get("title"),
                "model": model,
            }
        )
    return dashboards


def _walk_dicts(obj, visit) -> None:
    """Depth-first walk that calls ``visit`` on every dict node."""
    if isinstance(obj, dict):
        visit(obj)
        for value in obj.values():
            _walk_dicts(value, visit)
    elif isinstance(obj, list):
        for value in obj:
            _walk_dicts(value, visit)


def _iter_panels(model: dict):
    """Yield every panel, descending one level into row panels."""
    for panel in model.get("panels", []) or []:
        yield panel
        for sub in panel.get("panels", []) or []:
            yield sub


def _datasource_type(datasource) -> str | None:
    """Normalize a panel/target ``datasource`` (dict, str, or None) to its type."""
    if isinstance(datasource, dict):
        return datasource.get("type")
    return datasource if isinstance(datasource, str) else None


def dashboard_concrete_datasource_uids(model: dict) -> set[str]:
    """Hard-coded datasource UIDs referenced anywhere in the dashboard.

    Excludes template-variable references (``${...}``), the builtin ``grafana``
    datasource, and special sentinels (``-- Mixed --``, ``-- Dashboard --``).
    Whatever remains must resolve to a real datasource or the dashboard breaks.
    """
    uids: set[str] = set()

    def visit(node: dict) -> None:
        datasource = node.get("datasource")
        if isinstance(datasource, dict):
            uid = datasource.get("uid")
            if (
                isinstance(uid, str)
                and uid
                and not uid.startswith("$")
                and uid != "grafana"
                and not uid.startswith("-- ")
            ):
                uids.add(uid)

    _walk_dicts(model, visit)
    return uids


def dashboard_datasource_variable_types(model: dict) -> set[str]:
    """Datasource types selected by the dashboard's ``datasource`` template vars.

    A datasource picker that matches no datasource of its type renders empty,
    so every type here must exist among Grafana's datasources.
    """
    types: set[str] = set()
    for var in (model.get("templating") or {}).get("list", []) or []:
        if var.get("type") == "datasource":
            type_filter = var.get("query")
            if isinstance(type_filter, str) and type_filter:
                types.add(type_filter)
    return types


def dashboard_templatefree_prometheus_exprs(model: dict) -> list[str]:
    """Prometheus panel expressions that use no template variables.

    These run as-is against Prometheus (no Grafana-side interpolation), so they
    are exactly the shipped queries — ideal for asserting the dashboard's panels
    issue valid PromQL. Targets whose datasource isn't Prometheus, or whose
    expression contains a ``$`` variable, are skipped.
    """
    exprs: list[str] = []
    seen: set[str] = set()
    for panel in _iter_panels(model):
        panel_ds = panel.get("datasource")
        for target in panel.get("targets", []) or []:
            if _datasource_type(target.get("datasource") or panel_ds) != "prometheus":
                continue
            expr = target.get("expr")
            if not expr or "$" in expr or expr in seen:
                continue
            seen.add(expr)
            exprs.append(expr)
    return exprs


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
