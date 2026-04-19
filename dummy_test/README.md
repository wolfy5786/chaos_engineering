# dummy_test — FastAPI playground (Kubernetes)

Minimal **four-service** stack for load and chaos experiments: **gateway**, **svc-a**, **svc-b**, and **auth** (email/password via [Supabase Auth](https://supabase.com/docs/guides/auth/passwords) backed by your Supabase project database). **External** traffic should use the **gateway** only. **Internal** endpoints are for east-west calls inside the cluster (or debugging).

**Credential logging:** The **gateway** and **auth** services log **email and password on purpose** at multiple steps (proxy + Supabase calls). This is for this playground only; it is **unsafe** for production and must not be copied into real systems.

---

## Endpoints

### External (entrypoint for tests / orchestrator)

Use these when pointing a workload generator or browser at the system under test. Reachable from your machine after **port-forward** (see [Run](#run)), or from inside the cluster as `http://gateway:8000`.

| Method | Path | Service | Description |
|--------|------|---------|-------------|
| `GET` | `/health` | gateway | Liveness-style JSON (`status`, `service`). |
| `GET` | `/chain` | gateway | Calls **svc-a** → **svc-b**; returns multi-hop JSON (`path`, `hop`, `downstream`). |
| `POST` | `/auth/signup` | gateway → auth | Email/password signup; JSON body `{"email":"...","password":"..."}`. Proxied to **auth** `POST /signup`. |
| `POST` | `/auth/login` | gateway → auth | Email/password login; same JSON body. Proxied to **auth** `POST /login`. |

Example (port-forward to localhost):

- `http://localhost:8000/health`
- `http://localhost:8000/chain`
- Signup: `curl -s -X POST http://localhost:8000/auth/signup -H "Content-Type: application/json" -d "{\"email\":\"user@example.com\",\"password\":\"secret\"}"`
- Login: `curl -s -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"user@example.com\",\"password\":\"secret\"}"`

Successful responses are JSON with keys such as `ok`, `user`, and `session` (when Supabase returns a session). Exact fields follow the [Supabase Python client](https://supabase.com/docs/reference/python/introduction) `AuthResponse` shape (for example, `session` may be `null` until email is confirmed if your project requires confirmation).

### Internal (cluster DNS — not the primary external API)

These are used by other pods or for troubleshooting. Default Kubernetes short names assume namespace **`dummy-test`**.

| Method | Path | Service | Full in-cluster base (short DNS) | Description |
|--------|------|---------|-----------------------------------|-------------|
| `GET` | `/health` | gateway | `http://gateway:8000` | Same as external when called from another pod. |
| `GET` | `/chain` | gateway | `http://gateway:8000` | Same as external. |
| `POST` | `/auth/signup` | gateway | `http://gateway:8000` | Same as external (prefer gateway for consistency). |
| `POST` | `/auth/login` | gateway | `http://gateway:8000` | Same as external. |
| `GET` | `/health` | svc-a | `http://svc-a:8000` | Health JSON. |
| `GET` | `/forward` | svc-a | `http://svc-a:8000` | Calls **svc-b** `GET /leaf`; returns `downstream` payload. |
| `GET` | `/health` | svc-b | `http://svc-b:8000` | Health JSON. |
| `GET` | `/leaf` | svc-b | `http://svc-b:8000` | Leaf JSON (`service`, `role`). |
| `GET` | `/health` | auth | `http://auth:8000` | Health JSON (`status`, `service`). |
| `POST` | `/signup` | auth | `http://auth:8000` | Direct signup (same body as gateway); use for debugging. |
| `POST` | `/login` | auth | `http://auth:8000` | Direct login (same body as gateway). |

Fully qualified names (same ports):

- `http://gateway.dummy-test.svc.cluster.local:8000`
- `http://svc-a.dummy-test.svc.cluster.local:8000`
- `http://svc-b.dummy-test.svc.cluster.local:8000`
- `http://auth.dummy-test.svc.cluster.local:8000`

Environment wiring in the cluster: **gateway** uses `SVC_A_URL=http://svc-a:8000` and `AUTH_SERVICE_URL=http://auth:8000`; **svc-a** uses `SVC_B_URL=http://svc-b:8000`; **auth** reads `SUPABASE_URL` and `SUPABASE_KEY` from [`services/auth/.env`](services/auth/.env) when you run locally (copy from [`services/auth/.env.example`](services/auth/.env.example)). In the cluster, the same variables are injected from the Kubernetes `Secret` `supabase-auth`, which you should create **from that `.env` file** (see [Run](#run)) so keys stay in one place (see [`k8s/deployment-auth.yaml`](k8s/deployment-auth.yaml)).

---

## Supabase prerequisites

1. Create a project in the [Supabase dashboard](https://supabase.com/dashboard).
2. Open **Project Settings → API** and copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon public** (publishable) key → `SUPABASE_KEY`  
   Use the **anon** key for this service (do **not** put the `service_role` secret key in Kubernetes manifests or images).
3. Under **Authentication → Providers**, ensure **Email** is enabled (default).
4. Optional: **Authentication → Providers → Email** — if **Confirm email** is on, new users get a `user` but `session` may be `null` until they confirm; [password sign-in](https://supabase.com/docs/guides/auth/passwords) may require confirmation depending on settings. Adjust or test accordingly.

### Local Supabase (CLI)

Instead of a hosted project, you can run Postgres + Auth locally with the [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started) and Docker.

1. From the `dummy_test` directory: `supabase start` (first run downloads images; keep Docker running).
2. Copy **API URL** (typically `http://127.0.0.1:54321`) and the **anon** `anon key` from the command output into [`services/auth/.env`](services/auth/.env) as `SUPABASE_URL` and `SUPABASE_KEY` (see [`.env.example`](services/auth/.env.example)).
3. SQL migrations live under [`supabase/migrations/`](supabase/migrations/). After editing them, apply with `supabase db reset` (recreates the local DB and runs migrations + [`seed.sql`](supabase/seed.sql)).
4. Local Auth is configured in [`supabase/config.toml`](supabase/config.toml) with email confirmations off for this playground so signup can return a session without using the [Inbucket](https://github.com/inbucket/inbucket) mail UI (see [Studio](http://127.0.0.1:54323) and mail at `http://127.0.0.1:54324` if you enable confirmations later).

---

## Environment variables

| Variable | Consumed by | Description |
|----------|-------------|-------------|
| `SUPABASE_URL` | auth | Supabase API URL: hosted `https://<ref>.supabase.co`, or local `http://127.0.0.1:54321` from `supabase start`. Set in `services/auth/.env` (see `.env.example`). |
| `SUPABASE_KEY` | auth | Supabase **anon** / publishable API key (hosted Project Settings → API, or anon key from `supabase start` output). Set in `services/auth/.env`. |
| `AUTH_SERVICE_URL` | gateway | Base URL of the auth service (`http://auth:8000` in cluster; local default `http://127.0.0.1:8003`). |
| `SVC_A_URL` | gateway | **svc-a** base URL (see deployments). |
| `SVC_B_URL` | svc-a | **svc-b** base URL (see deployments). |

---

## Prerequisites

- Docker (for images; also required for [local Supabase](#local-supabase-cli))
- [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started) if you use [local Supabase](#local-supabase-cli)
- `kubectl` configured for your cluster (kind, minikube, Docker Desktop Kubernetes, etc.)
- A Supabase project (hosted or local) and API keys in `dummy_test/services/auth/.env` (copy from `.env.example`; see [Supabase prerequisites](#supabase-prerequisites))
- For local clusters, manifests use `imagePullPolicy: Never` — build images **on the machine that runs the cluster** (or load images into kind/minikube per your setup).

---

## Build

Run from the **repository root** (parent of `dummy_test/`). Context is the `dummy_test` directory.

### Standard build

```bash
docker build -f dummy_test/docker/Dockerfile.gateway -t dummy-test/gateway:latest dummy_test
docker build -f dummy_test/docker/Dockerfile.svc_a -t dummy-test/svc-a:latest dummy_test
docker build -f dummy_test/docker/Dockerfile.svc_b -t dummy-test/svc-b:latest dummy_test
docker build -f dummy_test/docker/Dockerfile.auth -t dummy-test/auth:latest dummy_test
```

### Build with no cache

```bash
docker build --no-cache -f dummy_test/docker/Dockerfile.gateway -t dummy-test/gateway:latest dummy_test
docker build --no-cache -f dummy_test/docker/Dockerfile.svc_a -t dummy-test/svc-a:latest dummy_test
docker build --no-cache -f dummy_test/docker/Dockerfile.svc_b -t dummy-test/svc-b:latest dummy_test
docker build --no-cache -f dummy_test/docker/Dockerfile.auth -t dummy-test/auth:latest dummy_test
```

---

## Run

1. **Create `dummy_test/services/auth/.env`** from [`services/auth/.env.example`](services/auth/.env.example) and fill in `SUPABASE_URL` and `SUPABASE_KEY` (anon key). Do not commit `.env`.

2. **Create the Kubernetes secret** `supabase-auth` in `dummy-test` from that file (required for the **auth** deployment):

   ```bash
   kubectl create secret generic supabase-auth \
     --from-env-file=dummy_test/services/auth/.env \
     -n dummy-test \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

   If the secret already exists, the same command updates it (or delete the secret first, then re-run). After changing `.env`, re-run this command and restart auth if needed: `kubectl rollout restart deployment/auth -n dummy-test`.

3. Apply manifests (namespace first via `k8s/00-namespace.yaml`; order is fine with `kubectl apply -f` on the directory):

   ```bash
   kubectl apply -f dummy_test/k8s/
   ```

4. Wait for rollouts:

   ```bash
   kubectl wait --for=condition=available deployment -l app.kubernetes.io/part-of=dummy-test -n dummy-test --timeout=120s
   ```

5. Expose the **external** gateway on your machine (keep this terminal open):

   ```bash
   kubectl port-forward -n dummy-test svc/gateway 8000:8000
   ```

6. In another terminal, call the entrypoint:

   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/chain
   curl -s -X POST http://localhost:8000/auth/signup -H "Content-Type: application/json" -d "{\"email\":\"user@example.com\",\"password\":\"your-password\"}"
   curl -s -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"email\":\"user@example.com\",\"password\":\"your-password\"}"
   ```

**Workload / scenario `base_url`:** `http://localhost:8000` while port-forward is active (or `http://gateway:8000` from a pod inside the same namespace).

---

## Stop

1. Stop port-forward: focus the terminal where it is running and press **Ctrl+C**.

2. Remove the playground from the cluster (pick one):

   ```bash
   kubectl delete -f dummy_test/k8s/
   ```

   Or delete the whole namespace (removes all resources in it):

   ```bash
   kubectl delete namespace dummy-test
   ```

---

## Logs (optional)

Gateway, chain services, and auth emit **INFO** logs. Auth logs include **passwords** at each step (by design for this repo).

```bash
kubectl logs -n dummy-test -l app.kubernetes.io/component=gateway
kubectl logs -n dummy-test -l app.kubernetes.io/component=svc-a
kubectl logs -n dummy-test -l app.kubernetes.io/component=svc-b
kubectl logs -n dummy-test -l app.kubernetes.io/component=auth
```

---

## Remote registry (optional)

If you use a registry instead of local images, push `dummy-test/gateway:latest`, `dummy-test/svc-a:latest`, `dummy-test/svc-b:latest`, and `dummy-test/auth:latest` (or retag), set `imagePullPolicy` to `IfNotPresent` or `Always` in the Deployments, and add `imagePullSecrets` if your cluster requires it.

---

## Minikube quick sequence (optional)

```text
minikube image load dummy-test/gateway:latest
minikube image load dummy-test/svc-a:latest
minikube image load dummy-test/svc-b:latest
minikube image load dummy-test/auth:latest
kubectl apply -f dummy_test/k8s/
kubectl wait --for=condition=available deployment -l app.kubernetes.io/part-of=dummy-test -n dummy-test --timeout=120s
```

```powershell
minikube docker-env | Invoke-Expression
# then run the same docker build commands from the README from repo root
```
