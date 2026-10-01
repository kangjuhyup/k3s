# Gaegaeting dev deployment

The `gaegaeting-dev` Application references reusable workloads in `gitops/apps/gaegaeting`.
This cluster overlay owns development replicas/resource budgets, Secret delivery,
database preparation and ingress. Kafka is separate shared infrastructure under the
`kafka` Application and `gitops/clusters/oci-a1/kafka`; the old dedicated broker is retired with its namespace/PVC retained. Account, edge-authz and UI are running with one ready replica each. Match, Gateway
and Envoy remain at zero until the shared-topic-prefix Match release is verified.
Both current migration Jobs completed.
All five application images and both migration Jobs are pinned to main
`317f550e3fb4fbd773a606c1d58293e3cf7cb32d`; see [release image manifest](release-images.json).
Anonymous registry tag/digest fetch, index-body SHA256 and amd64/arm64 platforms were
independently verified. No GHCR pull credential is required for the current public images.
The dedicated token is scoped to the active `rvkang.app` zone. Public A records for
both approved hosts have been checked against the protected ingress target; DNS-only
mode and no AAAA records are required. Existing rvkang issuer/selectors and unrelated
DNS records remain unchanged. Certificate readiness is verified; application verification remains a separate gate.
Token readiness alone is insufficient. The app agent owns DNS writes.


Target: `https://test-ggt-ui.rvkang.app` and `https://test-ggt-api.rvkang.app`;
shared Auth at `https://auth.rvkang.app/t/gaegaeting-dev/oidc`. Public UI client is
`gaegaeting-web`. Initial authentication uses a dedicated Envoy proxy and private
edge-authz, with a distinct API audience matching the dev API URL. External assertion
headers are stripped before ext_authz; authentication fails closed. NetworkPolicy
permits ingress to the gateway only from this proxy. Account GraphQL is public for
signup; internal subject resolution, callbacks, health and other HTTP paths are not
exposed. Verify resolver authorization with the final application images.

## Ownership and activation sequence

1. Complete Doppler `gaegaeting/dev` keys and namespace-scoped read token bootstrap.
   Actual DB names, usernames, endpoints, keys and private certificates are never stored
   here. `secrets/` projects only the keys needed by each workload. UI receives only
   public configuration. Existing Auth and other service credentials are preserved.
2. Synchronize namespaces and secret delivery within the single Application.
   Wait for every required DopplerSecret to become ready before consumers start.
3. Add the development identity rules to the existing PostgreSQL Application
   **after** database identity Secrets exist. Do not create a second owner of
   `shared-postgres`. Preserve the existing Auth access rule and deny-by-default rule.
   The active source is `../postgresql/cluster.yaml`; the preparation reference
   `database/cluster-patch.yaml` is not independently applied.
4. Execute the separate GitOps provisioning Job with the short-lived PostgreSQL
   client certificate supplied through Doppler. It creates only fresh dev databases
   and restricted roles and rejects an existing unowned/privileged role. Do not change
   `bootstrap.initdb`: it is not replayed on an existing cluster. After success remove
   the temporary `postgres` certificate access rule through Git, suspend the Job and
   retire its short-lived credentials through the authorized credential lifecycle. No direct SQL
   or Kubernetes mutation bypass is needed. A certificate prepared before a long CI
   delay must be renewed before execution (24-hour lifetime).
5. Activate the shared single-node Kafka Application. Official Apache Kafka
   4.1.2 index digest includes ARM64; UID1000 startup/topic creation smoke passed. Broker configuration lives in Doppler. Match
   currently hardcodes plaintext/no SASL; the broker is cluster-private and ingress
   currently limited to Match and its own namespace. Environment topic prefixes are
   required for shared-broker isolation;
   not a production Kafka security or HA design. Five GiB local-path storage,
   24-hour retention, 1 GiB memory request / 2 GiB limit. No external consumer is
   implied: notification and chat services are not in this release.
6. The five image digests and registry pull access are verified. Migration Jobs use
   the same service digest, `/app`
   working directory and `node dist/src/migrations/migrate.js`. Jobs have
   release-specific names; unsuspend only after DB/TLS/Kafka/storage/Auth gates pass.
   Migration Jobs run before account/match, then gateway/edge/UI/proxy. Shallow HTTP
   probes do not replace dependency or signup/login verification.
7. Supply `infrastructure/prd:CLOUDFLARE_GAEGAETING_DNS_API_TOKEN`, scoped to
   `rvkang.app` DNS Edit and Zone Read. `ingress/` uses its own namespace Issuer
   and Secret; it does not modify the existing rvkang issuer. DNS A records `test-ggt-ui`
   and `test-ggt-api` use the `infrastructure/prd:GAEGAETING_INGRESS_IPV4` key, DNS only, TTL Auto.
   Do not publish the IP in source or logs. Wait for certificate readiness before
   enabling public routes and verify HTTPS/PKCE/external interaction end to end.
8. Keep the single Application sync-disabled until deployment gates pass. Activate
   dependencies and workloads in reviewed Git phases; verify Secret delivery, shared
   DB access, Kafka, migrations and TLS before enabling the serving workloads.
   Grouping resources in one Application is not proof of dependency readiness.

The project and single Application declaration live in `../root/gaegaeting-dev*.yaml`
and are referenced by root Kustomization. Registration does not synchronize their
workloads: the Application retains `automated.enabled: false`. Initial prune stays disabled.
Do not prune databases, buckets or Kafka PVCs when rolling back an application.
Git rollback does not reverse DB migrations or Doppler changes.

## Verified external state (2026-10-01)

- Independent `gaegaeting-dev` Auth tenant/scopes/three clients created; existing
  `dev` and `gaegaeting` clients preserved. Discovery issuer and browser-origin CORS
  checked. Provisioning client-credentials token and introspection credentials returned HTTP 200.
- All 13 Doppler Secret projections report SecretSyncReady=True; required keys and final
  public runtime configuration were checked without values.
- Certificate `gaegaeting-dev-public` Ready=True; both HTTPS hosts verify successfully.
- Account and Match release migration Jobs completed with exit code 0.
- Shared Kafka reports Ready 1/1; its separate Argo Application is Synced/Healthy and
  the broker metadata/API handshake passes. The former broker had zero application
  topics and is stopped; its namespace/PVC are retained. The existing PostgreSQL server reports Ready 1/1;
  fresh dev database/role provisioning Job completed successfully.
- Original storage dev configuration reused the production bucket/key. Separate
  dev user and pet buckets were created; exact dev UI CORS configured; zero-byte
  canary PUT/HEAD/DELETE succeeded on each. Bucket names stay in Doppler only.
  Existing storage access key still shared; bucket isolation is verified, IAM-level
  credential isolation is not claimed. A least-privilege dev key remains desirable.
- Redis has no runtime imports/connections in current account/match/gateway code;
  account envSpec still requires REDIS_HOST/PORT. No Redis ACL or mTLS changes made.
- Match Kafka producer connects at module startup. Like and Pair emit notification
  and chat events. `@OnEvent` handlers are in-process, not Kafka consumers. The shared
  broker requires distinct development/production topic prefixes; the application agent
  is preparing this configurable prefix before serving rollout.
- Production identity verification provider is unimplemented. Mock signup is allowed
  only in dev with NODE_ENV=development and REGISTRATION_MOCK_ENABLED=true.
  This preparation does not enable production signup or production deployment.

## Local validation

Use repository Python 3.12.9 / PyYAML 6.0.3 and kubectl 1.36.4 (Kustomize 5.8.1):

```sh
.local/os-cleanup-venv/bin/python scripts/gaegaeting_validate.py --release
```

This renders the single application tree, checks ownership, inactive gates, dev-only secret
mapping, nonroot security and edge bypass controls. `--release` additionally rejects
non-digest image references; it is not an external readiness attestation. The dedicated
Envoy configuration is also checked with its pinned ARM64 image in validation mode.

Upstream references: [Apache Kafka Docker](https://kafka.apache.org/41/getting-started/docker/),
[CNPG database management](https://github.com/cloudnative-pg/cloudnative-pg/blob/main/docs/src/declarative_database_management.md).
CNPG declarative database/role names cannot be Secret references; this repository's
private-identifier policy is why the bounded SQL Job reads identity from Secrets.

Pinned PostgreSQL 18.4 ARM64 local validation passed for fresh database/role creation,
idempotent rerun, restricted role flags and rejection of an unowned colliding role.
This test used disposable synthetic data. Live Job completion is recorded separately.

## Scoped authentication bootstrap

After Argo creates target namespaces and RBAC, run
`ansible/playbooks/bootstrap-gaegaeting-doppler-auth.yml` with the repository-pinned
Python, explicit protected run-config and DOPPLER_GAEGAETING_DEV_TOKEN in the controller
environment. The helper verifies the committed revision and creates only the missing
operator-authentication Secret through the existing bootstrap ownership checks. It
does not apply workloads or overwrite existing credentials. Normal Secret projections
remain owned by Argo plus Doppler Operator.

The scoped `gaegaeting/dev` read token is stored at
`bootstrap/prd:DOPPLER_GAEGAETING_DEV_TOKEN` and expires on 2026-12-30. Renew it
before expiry through the protected credential lifecycle.

The six dev serving containers request 25m CPU each (150m total), without CPU
limits. This reserves room for migrations and rolling updates on the shared
4-core node; requests are scheduling reservations, not throughput caps. At the
initial rollout, each existing Gaegaeting container used approximately 1m CPU
while total node usage was 10%, but node-wide CPU requests had reached 98%.
