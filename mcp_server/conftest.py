"""Empty on purpose: its presence makes pytest add this directory (the package root, one
level above the `mcp_server/` package itself) to `sys.path`, so `test/*.py` can
`import mcp_server.swarm_client` without an editable install — mirrors
swarm_coordination/conftest.py.
"""
