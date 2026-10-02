# Gaegaeting dev deployment

The `gaegaeting-dev` Application references reusable workloads in `gitops/apps/base/gaegaeting`.
The `gitops/apps/dev/gaegaeting` overlay supplies development replicas and resource
budgets. This cluster overlay owns Secret delivery, database preparation and ingress.
Kafka is separate shared infrastructure under the `kafka` Application and
`gitops/clusters/oci-a1/kafka`; the old dedicated broker is retired with its namespace/PVC retained.
All seven serving Deployments have one ready replica. User/admin UI images use source
`7c06eaefbfd55186e6d6503c8f95f061f3ee2b94`; the four backend images and both completed
migration Jobs retain `7c3733450107934f08130f0ac7d0db1a8f54c59a`.
The independent admin UI is served under `/admin` without rewriting. Backend/Envoy Pod
UIDs and migration Job UIDs are unchanged. HTTPS path and runtime checks passed;
separate-UI browser E2E passed, user-client `tenant_roles` was removed, and explicit
requests for it now return `invalid_scope`. One authorized QA pet was deleted after
identity/photo/feed checks; the administrator profile and role are preserved.
See [admin UI rollout](admin-ui-rollout.md).
The actual new Account artifact passed the real dev USER/PET storage probe. Read-only
DB checks found all six Account migrations, three expected constraints and eight
photo-review columns. HTTPS/runtime/CSP and public negative checks passed. Browser
photo review E2E passed; the temporary QA ADMIN role was removed, sessions are zero,
and the former admin token is rejected with HTTP 401. The separately authorized
permanent dev administrator passed fresh PKCE login and review access. Automatic
sync and self-healing are restored; automatic prune remains disabled.
See [photo rollout contract](profile-image-rollout.md) and
[artifact evidence](photo-artifact-verification.json).
See the per-service revisions in [release image manifest](release-images.json).
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
workloads by itself. After dependency, migration, TLS and browser E2E gates passed,
the Application enables automatic synchronization and self-healing. Photo release
browser E2E and temporary QA privilege cleanup also passed. Automatic prune stays disabled.
Do not prune databases, buckets or Kafka PVCs when rolling back an application.
Git rollback does not reverse DB migrations or Doppler changes.

## Verified external state (2026-10-01)

- Independent `gaegaeting-dev` Auth tenant/scopes/three clients created; existing
  `dev` and `gaegaeting` clients preserved. Discovery issuer and browser-origin CORS
  checked. Provisioning client-credentials token and introspection credentials returned HTTP 200.
- All 13 Doppler Secret projections report SecretSyncReady=True; required keys and final
  public runtime configuration were checked without values.
- Certificate `gaegaeting-dev-public` Ready=True; both HTTPS hosts verify successfully.
- Account and Match release migration Jobs completed with exit code 0. All six serving
  Deployments are Ready 1/1. UI health/login/interaction return HTTPS 200; unauthenticated
  Gateway GraphQL returns 401 and private Account/health routes return 404.
  Full browser signup/PKCE login and protected GraphQL E2E passed with exactly one
  new synthetic QA user. Profile and pet creation/readback matched; location and daily-feed
  create/read returned HTTP 200 with no GraphQL errors. The recommendation list was empty
  because no other candidate users existed. Nine public readiness/negative checks passed,
  including forged/anonymous denial, exact-origin CORS and private-route blocking.
  Before profile creation, MyProfile returned INTERNAL_SERVER_ERROR; the UI handled setup
  and subsequent creation/readback passed. The photo release fixes this initial behavior: new
  users now receive null before profile creation, verified by its browser E2E.
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
  has verified the published ARM64 image against a real Kafka broker: 15 dev-prefixed
  events round-tripped, while legacy/production topic offsets stayed zero. The live
  Match runtime uses `KAFKA_TOPIC_PREFIX=dev.gaegaeting`.
- Production identity verification provider is unimplemented. Mock signup is allowed
  only in dev with NODE_ENV=development and REGISTRATION_MOCK_ENABLED=true.
  This preparation does not enable production signup or production deployment.

## Local validation

Use repository Python 3.12.9 / PyYAML 6.0.3 and kubectl 1.36.4 (Kustomize 5.8.1):

```sh
.local/os-cleanup-venv/bin/python scripts/gaegaeting_validate.py --release
```

This renders the single application tree, checks ownership, activation gates, dev-only secret
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

## Photo release browser verification (2026-10-02)

[Aggregate evidence](photo-e2e-verification.json) contains no user identifiers or
credentials. One new QA user verified signup identity reuse, three-field profile
creation, pet/feed flows, USER/PET pending visibility, owner preview and staging
replay isolation. Admin USER approval and PET rejection/re-upload/approval preserved
reviewed bytes; duplicate review was rejected. Deletion removed public/owner entries
and origin reads failed with browser cache bypassed (`cache: no-store`). Previously
cached private image responses may persist for their existing 300-second cache TTL.

The temporary QA direct ADMIN was revoked, user sessions explicitly deleted and
read back as zero, and the former admin bearer received HTTP 401 with no data. The
separately user-authorized permanent dev ADMIN remains assigned and passed fresh
PKCE login, review UI and admin-list API checks. No production tenant or other user
roles were changed. Passwords/tokens are excluded from all evidence.

## Seoul synthetic fixtures

The authorized dev-only data seed has 1,000 new users, profiles, pets and locations,
40 per Seoul district and 500 per gender. Existing account data and serving Pod/Job
identities were preserved. See [seed runbook](seoul-fixture-runbook.md) and
[aggregate verification](seoul-fixture-verification.json). No application image or
migration changed. Individual mappings and credentials are private local files.
