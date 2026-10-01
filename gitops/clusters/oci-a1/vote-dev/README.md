# Vote development deployment

Vote server and UI use the same published ARM64 `0.1.0` source revision
`2da2042b520dd222ecc43734b0484e457186f8cc`. Images are pinned by registry digest.
Existing Auth tenant `e-vote` and clients `e-vote`/`vote-api` are reused.

The user UI is `https://vote.rvkang.app`; the administrator instance is
`https://vote-admin.rvkang.app`. Each has its own Doppler session secret and
`AUTH_URL`. The approved API origin is `https://vote-api.rvkang.app`.
The API image requires migration, API, worker and private authz processes.

Common workloads and Services live in `gitops/apps/vote`; this environment
overlay owns namespace, secrets, ingress and environment-specific policies.

Runtime values come from Doppler `vote/prd`. UI receives no database, Redis,
Auth administrator or introspection credentials. Only authz receives the
introspection client secret. DNS/TLS uses a separate namespaced issuer with
the existing infrastructure DNS token; the token is never injected into Vote
application Pods.

## Initial activation

Register the disabled Application through the root Application. Sync only the
Vote-dev Namespace through Argo CD at the committed revision. Issue a read-only
Doppler service token scoped to `vote/prd` and pass it as
`DOPPLER_VOTE_PRD_TOKEN` to
`ansible/playbooks/bootstrap-vote-doppler-auth.yml`, with an explicit protected
`doppler_run_config` and repository Python environment. This creates only the
missing operator authentication Secret through the existing bootstrap helper.
It does not apply application manifests or overwrite existing tokens.

After this bootstrap, enable automated synchronization in the Git Application,
push, and verify DopplerSecret conditions, workload rollouts, DNS and TLS.
Routine deployment changes are Git changes reconciled by Argo CD.

## API prerequisites

The published Redis adapter lacks client-certificate settings, while shared
Redis requires mTLS and per-application ACLs. Do not disable shared Redis TLS,
reuse the Auth ACL account or start a duplicate Redis. A Vote-specific TLS
transport must verify the server SAN and preserve ACL authentication.
Database credentials must identify a Vote-owned database and restricted role
on the existing PostgreSQL cluster. Preserve every current pg_hba rule and
coordinate changes with the current database operator.

API readiness also requires Wasabi configuration. Do not substitute another
application's bucket or credentials. Without those inputs API readiness and
authenticated API calls remain blocked. No existing `e-vote` user was present
at initial inspection; a completed real-user login needs a valid tenant user.
Production signup/provisioning remains disabled by the Vote application contract.
