# Fly.io: secrets and configuration

What `.github/workflows/flyio.yml` needs, where each value lives, and why it lives there
(architecture-standards FLY-IO-DEPLOYMENT §9). Nothing here is set by hand on a Fly app:
the workflow sets everything it needs on every deploy, so an environment cannot drift from
this page.

| Name | Kind | Where | Needed | What it is |
|---|---|---|---|---|
| `FLY_API_TOKEN` | secret | GitHub environment `production` | yes | `fly tokens create org`. Without it the workflow deploys nothing and says so. |
| `SWARM_AUTH_AUTHORITY` | variable | GitHub repository variables | yes | Base URL of the `authservice` that signs tokens for this API, e.g. `https://<your-authservice>.fly.dev`. swarmsim-api refuses to start without it (`Auth__Required`, docs/adr/0011), and the gate job fails first. |
| `SWARM_AUTH_AUDIENCE` | variable | GitHub repository variables | no | The audience `authservice` issues tokens for (default `SwarmApi`). |
| `SWARM_AUTH_ISSUER` | variable | GitHub repository variables | no | Its issuer (default `AuthService`). |
| `FLY_ORG` | variable | GitHub repository variables | no | The Fly organisation a first deploy creates the app in (default `personal`). |

Everything else is non-secret and committed in `flyio/swarmsim-api.fly.toml` `[env]`:
`Auth__Required`, `ScenarioRuns__Directory`, the ASP.NET Core settings. The authority is a
URL, not a secret, but no `authservice` is deployed yet, so its address cannot be written
into the repository; it comes in as a variable and is set with `flyctl deploy --env`.

One-time setup, per repository:

1. `fly tokens create org` → `FLY_API_TOKEN` in a GitHub **environment** named
   `production` (an environment can be reviewed and restricted; a repository secret
   cannot).
2. `SWARM_AUTH_AUDIENCE`/`SWARM_AUTH_ISSUER` only if your `authservice` does not use the
   defaults; `SWARM_AUTH_AUTHORITY` always.
3. Push a `v*` tag. The first run creates the app and its volume (FLY-IO-DEPLOYMENT §11).

If the app name `swarmsim-api` is taken on Fly (names are global), change `app` in
`flyio/swarmsim-api.fly.toml` and `FLY_APP` in the workflow together.
