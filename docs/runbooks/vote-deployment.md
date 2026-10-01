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
  Public ingress authentication and both UI BFF membership reads also returned 200.
- Compiled migration v3 completed and PostgreSQL has 39 Vote public-schema tables.
  API/worker sessions use TLS; the Vote role has no elevated role privileges.
- Redis verified mTLS transport, PING, exchange Lua and other-prefix denial passed.
- Server/worker/authz/UI/admin are all Ready 1/1. Public server liveness and
  readiness return 200; unauthenticated protected API requests return 401.
- Argo Vote is Synced/Healthy at `eb2cb91` after scoped storage delivery and rollout.
- PostgreSQL, Redis master/replica and Istiod retained their original Ready Pod UIDs.
  Superseded Vote migration Jobs and the empty, incorrectly named initial Vote
  Namespace were pruned through Argo; no application/PVC/Secret was present there.

## Registered Wasabi storage and final verification

The original protected `.env` credentials were used only by the operator to
inspect the existing account. The existing Vote-named bucket was reused; its
seven original objects are unchanged. No bucket, backup, lifecycle, Object Lock,
or shared infrastructure was replaced. The bucket has no public ACL or bucket
policy. A dedicated programmatic IAM user has bucket ListBucket for readiness
HeadBucket and GetObject/PutObject/DeleteObject only on Vote's configured prefix.
Access to an existing object outside that prefix was denied with 403.

All five required Wasabi keys and three optional adapter settings are registered
in Doppler `vote/prd`, delivered only in server/worker runtime. Public UI/admin
and Authz Secrets contain no Wasabi keys. Credentials and actual bucket/account
values are omitted from Git and reports. Operator credentials are not delivered
to workloads; the temporary new-key receipt was removed after Doppler readback.

The bucket CORS configuration lists the two approved Vote HTTPS UI origins,
PUT/GET/HEAD, content-type and x-amz-* headers, and ETag exposure. Both origin
preflights returned 200 with the matching origin. Actual PUT returned the Wasabi
service's wildcard CORS response, which supports the image's cookie-free
presigned requests; strict runtime origin restriction is not established by the
stored CORS document. Object access is still governed by IAM and signed URLs.
See [Wasabi's documented CORS response behavior](https://docs.wasabi.com/apidocs/bucket-cors-support-with-the-wasabi-s3-api).

The deployed image's storage adapter generated a unique prefixed signed URL.
PUT/GET returned 200, HEAD verified size/metadata, downloaded bytes matched, and
the temporary object was deleted and confirmed absent. Both existing-client
OIDC login/callback/session flows and authenticated UI BFF API reads passed after
storage activation. Public ingress passed the existing Auth introspection,
issuer/audience/tenant checks, signed Authz assertion and protected API read.
Temporary tenant identities and sessions were removed. Shared PostgreSQL, both
Redis Pods and Istiod remain Ready with their original Pod UIDs.

No deployment blocker remains. These checks verify deployment and integration;
they do not constitute a complete business-flow test of creating and executing a vote.
