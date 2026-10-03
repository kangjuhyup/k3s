# Signup identity verification — core 1.0.9

[Source release #165](https://github.com/kangjuhyup/gaegaeting/pull/165) squash commit
`dd302efac42a37d49ca2e782330a88b9d2d7d46c` requests identity verification on the
Account server during signup. The development mock returns stable DI for normalized
synthetic identity, a fresh transaction ID, verified identity and time. Account stores
DI HMAC and verification metadata; CI and raw DI are not persisted. Production and
explicitly disabled mock configurations reject these requests. A real provider remains
outside this release.

Target is the existing `gaegaeting-dev` Application and public development UI/API.
Doppler configuration, Auth clients, user roles, real account data and other
Applications are outside the change. Source CI validates Account, Match and UI images;
only Account and integration UI serving artifacts are updated. Other service image
references remain authoritative in `release-images.json`. Gateway's unchanged image
gets a Git-tracked Pod annotation so it reloads the new Account federation schema.

## Deployment gates

1. Require all source PR and main image publication checks to pass. Independently
   compare public GHCR tag/digest manifests with exact CI artifacts, including index
   SHA256 and `linux/amd64` and `linux/arm64`. Record `signup-image-verification.json`.
2. Render and validate GitOps declarations and server dry-run the changed Account,
   Gateway and UI Deployments plus the new Account migration Job.
3. Merge GitOps through its PR. Sync wave 0 runs the exact Account image and adds
   `AccountSignupVerification1791028800000`. Nullable fields and the all-null/all-set
   verification CHECK preserve existing rows. Existing Account can remain serving
   during this additive migration. The prior completed Match migration is retained.
4. Require the new migration to complete before wave 10 Account and wave 20
   Gateway/UI rollouts. Automatic synchronization/self-healing remain enabled and
   automatic pruning remains disabled. After new migration completion, retire only
   the obsolete completed Account migration Job through resource-scoped Argo pruning
   at the committed revision; no database rollback or application-wide prune occurs.
5. Verify exact serving image digests, all seven ready Deployments, unchanged
   service versions, seven recorded Account migrations, nullable verification columns,
   validated CHECK/DI uniqueness and absence of raw CI/DI columns. Run the packaged
   mock adapter with development settings and confirm stable identity, fresh IDs and
   production/disabled rejection. The database probe is read-only.
6. Through public HTTPS verify the new required signup fields, removal of CI/DI input,
   minor signup rejection before persistence, Gateway's refreshed schema and anonymous
   Gateway denial. Log in with the existing scoped QA fixture and read Account/Match
   through Gateway, then revoke the test bearer. Do not create accounts or grant roles.
   Record aggregate checks only in `signup-rollout-verification.json`.

## Recovery

Use a reviewed Git change to restore prior Account/UI image references and refresh
Gateway to the matching Account schema. Preserve the additive verification columns,
new completed migration history and its Job image; old migration runners reject
unknown newer history and must not be rerun against it. Do not fabricate metadata for
legacy rows or reverse migrations as part of image recovery. Prefer a forward fix
for new signup retry issues. Auth provisioning uses the same DI-derived idempotency
key as signup retries; real provider/key-scope transitions require a separate plan.

## Verified deployment — 2026-10-03

[GitOps PR #10](https://github.com/kangjuhyup/k3s/pull/10) deployed revision
`0fcde673f2fc56837901bb61c2232cc07d48a7bf`. Argo CD reported Synced/Healthy and a
successful operation; all seven serving Deployments were completely ready. Exact
Account/UI digests matched the verified source artifacts. Gateway reloaded the
signup schema. Other serving images and Pods and the completed Match migration Job
matched the predeploy baseline. The new Account migration completed and the obsolete
completed Account Job was retired through resource-scoped Argo pruning.

[Aggregate live evidence](signup-rollout-verification.json) confirms ARM64 Node
24.13.1, stable mock identity/fresh transaction IDs, production and disabled mock
rejection, seven Account migrations, nullable verification metadata and validated
CHECK/DI uniqueness. Raw CI/DI columns are absent. The public UI served the updated
bundle and the API rejected minor signup without creating a signup row. Both Account
and Gateway expose the new required identity input without CI/DI input. Anonymous
Gateway access was denied. Existing scoped QA login and Account/Match reads succeeded;
the test bearer was revoked. No new user or role assignment was created.

Source [main sync PR #167](https://github.com/kangjuhyup/gaegaeting/pull/167) merged
normally into dev/core. Feature, release and sync PR SonarCloud checks and all required
service-image checks passed. The optional main-wide SonarCloud gate remains at its
previous security/reliability C and 10 hotspots; duplication moved from 4.4% to 4.3%.
