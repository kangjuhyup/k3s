# Gaegaeting dev deployment

One `gaegaeting-dev` Application is registered in root GitOps. Its resource tree
contains the services, Kafka, Secret projections, database preparation Jobs and ingress. Automated sync remains disabled, Deployments/StatefulSet have zero
replicas and Jobs are
suspended. All five application images and both migration Jobs are pinned to main
`317f550e3fb4fbd773a606c1d58293e3cf7cb32d`; see [release image manifest](release-images.json).
Anonymous registry tag/digest fetch, index-body SHA256 and amd64/arm64 platforms were
independently verified. No GHCR pull credential is required for the current public images.
The DNS token key `infrastructure/prd:CLOUDFLARE_GAEGAETING_DNS_API_TOKEN`
is now readable/nonempty and active; the single matching Cloudflare zone remains
`pending` (checked 2026-10-01). Token readiness does not clear the rollout gate:
verify registrar delegation, public DNS and Certificate Ready separately. The app
agent owns DNS record/registrar changes; K3s must not duplicate those writes.

Target: `https://dev.gaegaeting.app` and `https://api-dev.gaegaeting.app`;
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
2. Register namespaces and secret-delivery Applications through root GitOps only.
   Wait for every required DopplerSecret to become ready before consumers start.
3. Merge `database/cluster-patch.yaml` into the existing PostgreSQL Application as
   a patch **after** database identity Secrets exist. Do not create a second owner of
   `shared-postgres`. Preserve the existing Auth access rule and deny-by-default rule.
   The patch is deliberately absent from every active Kustomization.
4. Execute the separate GitOps provisioning Job with the short-lived PostgreSQL
   client certificate supplied through Doppler. It creates only fresh dev databases
   and restricted roles and rejects an existing unowned/privileged role. Do not change
   `bootstrap.initdb`: it is not replayed on an existing cluster. After success remove
   the temporary `postgres` certificate access rule through Git, suspend the Job and
   remove its credentials through the authorized credential lifecycle. No direct SQL
   or Kubernetes mutation bypass is needed. A certificate prepared before a long CI
   delay must be renewed before execution (24-hour lifetime).
5. Activate the dedicated single-node dev Kafka StatefulSet. Official Apache Kafka
   4.1.2 index digest includes ARM64; UID1000 startup/topic creation smoke passed. Broker configuration lives in Doppler. Match
   currently hardcodes plaintext/no SASL; the broker is cluster-private and ingress
   limited to Match and its own namespace. This is a dev isolation arrangement,
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
   `gaegaeting.app` DNS Edit and Zone Read. `ingress/` uses its own namespace Issuer
   and Secret; it does not modify the existing rvkang issuer. DNS A records `dev`
   and `api-dev` use the `infrastructure/prd:GAEGAETING_INGRESS_IPV4` key, DNS only, TTL Auto.
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
- Dev runtime secrets generated in Doppler; database resources not yet created.
- Original storage dev configuration reused the production bucket/key. Separate
  dev user and pet buckets were created; exact dev UI CORS configured; zero-byte
  canary PUT/HEAD/DELETE succeeded on each. Bucket names stay in Doppler only.
  Existing storage access key still shared; bucket isolation is verified, IAM-level
  credential isolation is not claimed. A least-privilege dev key remains desirable.
- Redis has no runtime imports/connections in current account/match/gateway code;
  account envSpec still requires REDIS_HOST/PORT. No Redis ACL or mTLS changes made.
- Match Kafka producer connects at module startup. Like and Pair emit notification
  and chat events. `@OnEvent` handlers are in-process, not Kafka consumers. Separate
  dev broker isolates the currently hardcoded topic names from production.
- Production identity verification provider is unimplemented. Mock signup is allowed
  only in dev with NODE_ENV=development and REGISTRATION_MOCK_ENABLED=true.
  This preparation does not enable production signup or production deployment.

## Local validation

Use repository Python 3.12.9 / PyYAML 6.0.3 and kubectl 1.36.4 (Kustomize 5.8.1):

```sh
.local/os-cleanup-venv/bin/python scripts/gaegaeting_validate.py
```

This renders all five paths, checks ownership, inactive gates, dev-only secret
mapping, nonroot security and edge bypass controls. `--release` additionally rejects
non-digest image references; it is not an external readiness attestation. The dedicated
Envoy configuration is also checked with its pinned ARM64 image in validation mode.

Upstream references: [Apache Kafka Docker](https://kafka.apache.org/41/getting-started/docker/),
[CNPG database management](https://github.com/cloudnative-pg/cloudnative-pg/blob/main/docs/src/declarative_database_management.md).
CNPG declarative database/role names cannot be Secret references; this repository's
private-identifier policy is why the bounded SQL Job reads identity from Secrets.

Pinned PostgreSQL 18.4 ARM64 local validation passed for fresh database/role creation,
idempotent rerun, restricted role flags and rejection of an unowned colliding role.
This test used disposable synthetic data; cluster databases remain unchanged.
