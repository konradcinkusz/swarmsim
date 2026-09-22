# End-to-end tests

The dashboard in a real browser (Playwright, Chromium) against a running `SwarmApi.Api`
with the simulated swarm: a person approving an agent's plan and dispatching it with the
approval code, a conflicted plan that cannot be approved, the code shown once, and land-all.

```bash
pip install playwright pytest
python -m playwright install chromium
pytest e2e -v                       # starts the API with `dotnet run`, stops it after
SWARMSIM_E2E_URL=http://localhost:5000 pytest e2e -v   # or use one that is running
```

CI runs them on every push and pull request (`.github/workflows/ci.yml`, job `e2e`).
