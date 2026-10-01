# Vote deployment

Common app manifests are in `gitops/apps/base/vote`; the active environment is
`gitops/clusters/oci-a1/vote-dev`. Use the existing ARM64 server/UI digests,
approved Vote hosts, existing `e-vote` tenant and Doppler `vote/prd` contract.
This environment name does not authorize changing Auth tenant/client contracts.

Deployment follows Git → Argo CD. Doppler Operator delivers workload-specific
keys. Scoped token bootstrap uses `bootstrap-vote-doppler-auth.yml`; no application
Secrets or deployments are applied manually. Preserve unrelated dirty files in
the shared checkout and stage only owned paths.

## Existing database and Redis

Preserve Auth and Gaegaeting pg_hba rules and projected identities. The additive
`hostssl sameuser all all scram-sha-256` rule admits a password-authenticated role
only to its identically named database. It needs no new volume or Pod template.
`DATABASE_NAME` and `DATABASE_USER` must match in Doppler. Vote's role must have
no superuser/create-role/create-database/replication/bypass-RLS privileges; revoke
PUBLIC database privileges. `scripts/vote_database.py --run-config <protected-json>`
is an explicitly scoped one-time operation against the existing primary's Unix
socket. It verifies committed code, context, cluster readiness and ownership,
reads only runtime Doppler values, rejects unknown roles/owners, and suppresses
SQL output. It neither deletes, resets nor moves existing data. Apply Vote's
compiled image migrations through the GitOps Job after preparation.

Shared Redis keeps its server configuration, Pods and PVCs. The existing private
Secret gains Vote credential references. Startup prepares Vote's restricted ACL
from that mounted Secret; the GitOps `vote-redis-acl-v1` Job adds/saves the same
ACL live, without restarting shared Redis. It preserves all existing accounts.
Vote may access only `participation-access:exchange:*`; grant only its exchange
Lua script commands and connection checks. The namespace is fixed by the current
published adapter. Verify allowed operations and denied access to other prefixes.

The published adapter lacks mTLS client settings. A loopback-only Vote Envoy
transport forwards Redis to the existing upstream using a dedicated clientAuth
certificate from the existing CA, CA verification and exact server SAN matching.
Store private endpoints in Doppler; generate the transport config at runtime.
Database uses verified TLS with the existing CA through `NODE_EXTRA_CA_CERTS`.
The published 0.1.0 image uses MikroORM 7 but its `DATABASE_SSL=true` path emits
obsolete v6 `driverOptions.connection.ssl`, replacing pg’s connection object.
For this digest only, Doppler `DATABASE_SSL_COMPAT` maps to runtime `DATABASE_SSL`
and skips that obsolete branch; `PGSSLMODE=verify-full` enables native pg TLS.
Validate actual TLS and restricted-role queries before activation. This does not
disable transport encryption or server certificate verification.
Migration v3 explicitly awaits compiled migrations with a process keep-alive
and requires a populated schema; a Job exit code alone is insufficient evidence.
No shared TLS mode or Auth certificate/account is changed.

Only Vote's inbound CUSTOM policy selects the new `vote-authz` provider.
Render the pinned Istiod chart before publishing its values change and ensure
Deployment/Pod templates are identical; only ConfigMaps may change. Verify live
shared Redis, PostgreSQL and Istiod Pod UIDs and readiness after reconciliation.

## Completion evidence

Record image revision/digests, Argo revision/health, migration completion,
API/worker/authz/UI rollouts, exact public TLS hosts, BFF/API responses, database
TLS and Redis ACL isolation. Test existing OIDC login/callback and audience/tenant
checks; distinguish authorization redirect from completed login. Keep provisioning
blocked; never inject a global Auth administrator credential into Vote Pods.
API `/readiness` also requires Wasabi. Missing Vote bucket/access configuration
must remain an explicit blocker; do not bypass readiness or use another app's
bucket. Missing tenant users prevents a real-user login test unless a valid
Vote tenant identity is provided or a scoped test identity is established.

Vote-dev has one replica per process. Use zero surge and 20m mesh proxy CPU
requests to fit the existing single-node capacity without altering shared apps.
The migration requests 25m CPU and may burst; observe Ready after each rollout.

## Observed verification: 2026-10-01

Server/UI are ARM64 `0.1.0`, source `2da2042b520dd222ecc43734b0484e457186f8cc`.
Server digest: `sha256:781e7db5b6f86b57f0d0367811cadcc06dd4ca28c3fe246100bc67fba741f497`.
UI digest: `sha256:81bf724b6809a034af42377a15884cb4857725a8f03821b2b43cab2e37cd5140`.

- Both UI hosts return HTTPS 200 and have Ready 1/1 workloads.
- Both existing-client OIDC login, consent, exact callback and authenticated UI
  session flows passed. Temporary tenant-only test identities/sessions were removed.
- Existing Auth introspection returned an active token for the exact issuer/API
  audience. Authz accepted it, rejected an invalid token with 401, and the API
  verified the signed assertion and existing tenant code/ID.
- A protected read of `/organizations/memberships` inside the API Pod returned 200.
  This does not establish external ingress/BFF success while API endpoints are unready.
- Compiled migration v3 completed and PostgreSQL has 39 Vote public-schema tables.
  API/worker sessions use TLS; the Vote role has no elevated role privileges.
- Redis verified mTLS transport, PING, exchange Lua and other-prefix denial passed.
- Worker/authz/UI/admin are Ready 1/1. Server liveness is 200, readiness is 503;
  storage reports `down/not_configured`. External API returns 503.
- PostgreSQL, Redis master/replica and Istiod retained their original Ready Pod UIDs.
  Superseded Vote migration Jobs and the empty, incorrectly named initial Vote
  Namespace were pruned through Argo; no application/PVC/Secret was present there.

Completion still requires Vote-owned Wasabi configuration in Doppler `vote/prd`:
`WASABI_ENDPOINT`, `WASABI_REGION`, `WASABI_BUCKET`, `WASABI_ACCESS_KEY_ID`,
`WASABI_SECRET_ACCESS_KEY`. Optional settings are `WASABI_KEY_PREFIX`,
`WASABI_FORCE_PATH_STYLE`, `WASABI_PRESIGNED_URL_EXPIRES_IN_SECONDS`.
Add only to server/worker runtime delivery when values are present, then verify
HeadBucket, scoped object upload/read/cleanup, exact-origin CORS, readiness,
external authenticated API/BFF calls and final rollout. Wasabi keys must not reach
UI/authz or reports. Keep the bucket private and grant only bucket ListBucket
(readiness HeadBucket) plus GetObject/PutObject/DeleteObject on Vote's prefix.
Browser presigned upload needs CORS for the two approved Vote UI origins.
