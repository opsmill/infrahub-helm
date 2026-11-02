The install notes print the MCP client URL as `<host>/mcp`. They printed `<host>/mcp/mcp`, which returns 404 because the ingress and the HTTPRoute pass the path to the server without rewriting it.
