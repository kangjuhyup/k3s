# Gaegaeting dev deployment

The Payment rollout adds an independent snack wallet and consumable in-app payment
service and updates Gateway federation. Apple and Google remain disabled in Doppler
until store credentials are configured. Product seeds are 10/50/100 snacks at
KRW 2,000/6,000/10,000. No actual store transaction is part of this rollout.

Payment identity, database password, proof encryption key and store switches come
from `gaegaeting/stg`. A bounded certificate-authenticated Job provisions only its
fresh database and restricted role, followed by its schema-specific migration Job,
Payment readiness and Gateway rollout. Database name and role are identical in
Doppler to reuse the existing `sameuser` password rule. The temporary PostgreSQL
provisioning certificate gate is removed after Job completion; the old Account and
Match provisioning/migration artifacts are retained.

Only exact `/payment/notifications/apple` and `/payment/notifications/google`
callbacks bypass end-user edge authentication; Payment performs provider validation.
Disabled providers return HTTP 503 without acknowledging or storing a notification.
Payment GraphQL and health are private; user wallet operations flow through Gateway
and require `payment:read` or `payment:write`. Those scopes are registered for the
existing user web client; callers must request them in a fresh authorization grant.
The Payment NetworkPolicy accepts only Gateway and the provider callback proxy.

See [signup identity rollout](signup-identity-rollout.md) for the earlier core 1.0.9
record; per-service entries in `release-images.json` are the current artifact source.

The `gaegaeting-dev` Application references reusable workloads in `gitops/apps/base/gaegaeting`.
The `gitops/apps/dev/gaegaeting` overlay supplies development replicas and resource
budgets. This cluster overlay owns Secret delivery, database preparation and ingress.
Kafka is separate shared infrastructure under the `kafka` Application and
`gitops/clusters/oci-a1/kafka`; the old dedicated broker is retired with its namespace/PVC retained.
In the earlier signup rollout, Account and user UI advanced to core 1.0.9 source
`dd302efac42a37d49ca2e782330a88b9d2d7d46c`. Gateway retained its existing image and
reloaded Account's schema through a tracked Pod annotation. Match, edge-authz, admin UI
and edge-proxy retained their previous images. The Account migration added nullable
verification metadata; the completed Match migration kept its original artifact.
The earlier [mobile rollout](mobile-ui-rollout.md) and photo sections below are
historical verification records; current references are in `release-images.json`.
The independent admin UI is served under `/admin` without rewriting. Earlier admin/logout rollouts preserved backend/Envoy Pod
UIDs and migration Job UIDs; the mobile rollout separately updates Match. HTTPS path and runtime checks passed;
separate-UI browser E2E passed, user-client `tenant_roles` was removed, and explicit
requests for it now return `invalid_scope`. One authorized QA pet was deleted after
identity/photo/feed checks; the administrator profile and role are preserved.
See [admin UI rollout](admin-ui-rollout.md) and [user logout rollout](logout-rollout.md).
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
signup; internal Account subject resolution, callbacks, health and other HTTP paths are not
exposed. Verify resolver authorization with the final application images.

## Ownership and activation sequence

1. Complete Doppler `gaegaeting/stg` keys and namespace-scoped read token bootstrap.
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
6. The seven service image digests and registry pull access must be verified. Migration Jobs use
   their verified schema artifact digest recorded in `migrationImages`, `/app`
   working directory and `node dist/src/migrations/migrate.js`. Jobs have
   schema-release-specific names; preserve completed Jobs when migration files are unchanged.
   Unsuspend new Jobs only after DB/TLS/Kafka/storage/Auth gates pass.
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

This renders the single application tree, checks ownership, activation gates, stg-config secret
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
Python, explicit protected run-config and DOPPLER_GAEGAETING_STG_TOKEN in the controller
environment. The helper verifies the committed revision and creates only the missing
operator-authentication Secret through the existing bootstrap ownership checks. It
does not apply workloads or overwrite existing credentials. A dev-to-stg transition
may add the stg credential while the existing Application is active after verifying
the existing Gaegaeting source and projection ownership. Normal Secret projections
remain owned by Argo plus Doppler Operator.

The scoped `gaegaeting/stg` read token is stored at
`bootstrap/prd:DOPPLER_GAEGAETING_STG_TOKEN` with a bounded read-only lifetime. Renew it before expiry through the protected
credential lifecycle. The previous dev credential remains available for recovery.

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

QA session cleanup is complete: only the first fixture sessions were revoked,
the same browser bearer changed from HTTP 200 to HTTP 401, and the QA tab was
closed. All 1,000 fixture accounts remain ACTIVE with their profiles, pets and
locations; existing accounts and other sessions were not mutated.

## User UI logout handover

The core 1.0.3 logout UI is deployed and HTTP revocation/end-session checks passed.
Existing Chrome SSO confirmation still reports `xsrf token invalid`; browser E2E
is **not complete**. Live deployment was rechecked without another rollout. See
[logout rollout and unresolved investigation](logout-rollout.md).

## HTTP request trace release

The core 1.0.7 deployment updates Account, Match and Gateway to source
`5d6d7c0c218033d3bd70f074d4116d110af4c6e4`. See the
[rollout contract](request-trace-rollout.md),
[registry verification](trace-image-verification.json) and exact per-service
[release image references](release-images.json). Existing completed migration
Jobs retain their original artifacts.

## Doppler stg transition (2026-10-03)

On the user's request, the existing deployed environment now reads
`gaegaeting/stg`. The 111 variables copied from `dev_personal` were retained;
14 consumed connection/authentication settings were aligned with the existing
cluster so local-only endpoints and different tenant/bucket settings do not
replace working service connections. Actual values remain exclusively in Doppler.
The previous `dev` and `dev_personal` configs and dev authentication token remain
available; no shared database, broker, tenant, bucket or data was recreated.

All 12 Gaegaeting DopplerSecret sources use config `stg` with the dedicated
read-only `doppler-auth-gaegaeting-stg` credential. Cloudflare still reads the
existing infrastructure config. Projected values were compared with `stg` after
SecretSyncReady became true. Workload reload was a separate GitOps step after
successful delivery. All seven Pod templates record their Doppler config and
all seven serving Deployments completed rollout with Ready 1/1. Namespace,
public routes and the latest upstream images remain unchanged.

Verification passed: Argo Synced/Healthy; user/admin UI health and login HTTPS
200; unauthenticated public `/gateway/graphql` 401 and private `/account/health`
404; Account/Match verified TLS database queries; both configured storage bucket
HeadBucket requests; existing Auth provisioning token and introspection client
credentials HTTP 200; Match's configured Kafka endpoint ApiVersions handshake
with error code 0. Shared PostgreSQL/Redis/Kafka/Istio running Pod identities and
Ready states were preserved. This verifies the config transition and connections,
not a new complete signup/match business-flow E2E run.


## Payment rollout verification (2026-10-05)

Core 1.0.10 source `75c5a2564ff3d87f8585672cd86c4da7422eb5d0` passed
workspace checks and all seven image jobs. Payment and Gateway deployment digests
were checked against CI artifacts, anonymous registry tags and index-body SHA256,
including AMD64/ARM64 platforms. The 59-resource render and all namespace-scoped
server dry-runs passed; the pinned Envoy image accepted the callback configuration.

The dedicated provisioning Job and Payment migration completed successfully.
Payment and Gateway HTTP health returned 200 and federation schema retrieval
included the new wallet and purchase fields. Read-only database checks confirmed
verified TLS, restricted role flags, one migration, three products, six offers and
no purchases, jobs or wallets created by the smoke. Product quantities and KRW
prices matched 10/2,000, 50/6,000 and 100/10,000.

The internally signed read returned a zero wallet and empty purchase history;
missing assertions and missing scopes were rejected. Both disabled stores rejected
catalog and purchase preparation. Public Gateway rejected anonymous access with
401; direct Payment GraphQL/health and non-exact callback paths returned 404;
exact disabled-provider callbacks returned 503 without acceptance.

Seven existing Account/Match/edge-authz/user-UI/admin-UI Pod identities, including
completed migration Pods, were preserved. The provisioning certificate was retired
in Doppler after verifying no active consumers. The completed provisioning Job is
now declared suspended and the temporary PostgreSQL certificate gate is removed.
Argo synchronization and PostgreSQL access-rule retirement must also be checked
against the final Git revision. No real store transaction or browser purchase E2E
was performed; providers remain disabled at the user's request.


## Challenge rollout verification (2026-10-05)

Core 1.0.11 (`dfd6fca8b5297870fa9024622efd55b53c2a4488`) adds the independent
Challenge backend for walking tracks, shared routes, diaries, private PNG photos
and challenge participation. Challenge and Gateway run the CI-verified ARM64
images recorded in `release-images.json`. Existing Account, Match, Payment and UI
images and Pod identities were preserved.

The dedicated restricted database, verified TLS, private walking bucket, Doppler
stg mappings and Auth read/write scopes are configured. Both migrations and
Argo CD rollout succeeded. Live synthetic-user verification covered course
publication and completion by another user, actual signed PNG storage, private
and public diaries, progress updates and authorization denials. Gateway subject
mapping and existing Account/Payment reads passed.

See [Challenge rollout and recovery](challenge-rollout.md),
[preparation evidence](challenge-preparation-verification.json) and
[deployment evidence](challenge-deployment-verification.json). Flutter UI wiring
is a separate follow-up using the application repository's Challenge integration
contract; the deployed Federation schema matches that contract.
