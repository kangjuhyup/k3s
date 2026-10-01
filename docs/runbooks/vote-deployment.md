# Vote deployment

Common app manifests are in `gitops/apps/vote`; the active environment is
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
