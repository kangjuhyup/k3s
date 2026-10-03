# HTTP request trace rollout — core 1.0.7

Release PR [gaegaeting #150](https://github.com/kangjuhyup/gaegaeting/pull/150)
was squash-merged to source `5d6d7c0c218033d3bd70f074d4116d110af4c6e4`.
[Image publication](https://github.com/kangjuhyup/gaegaeting/actions/runs/37116677123)
passed complete workspace tests and packaged runtime checks.
`trace-image-verification.json` records CI artifact comparison and independent
anonymous GHCR tag/digest checks, index-body SHA256 and amd64/arm64 platforms.

This deployment updates the Account, Match and Gateway serving images. The
per-service revisions in `release-images.json` remain authoritative. Edge-authz,
edge-proxy and both UI artifacts retain their existing versions. The two completed
migration Jobs retain their image, name and UID because no migration/schema files
changed. Auth configuration, Doppler values, data fixtures and user roles are not
part of this release.

Gateway assigns one `x-trace-id` before authentication and passes it through
Account subject resolution, every GraphQL subgraph call and subsequent HTTP calls
using the shared client. Valid client IDs are retained; missing/invalid IDs receive
a UUID. Service Pino request logs use `traceId` and `req.id`; Gateway completion logs
and response headers use the same ID. This contract covers HTTP requests.

GitOps validation and server dry-runs of the three changed Deployments precede
merge. Existing sync waves prepare Account/Match before Gateway. Automatic
synchronization and self-healing stay enabled with pruning disabled.

Completion requires Argo CD to report the deployed Git revision as Synced/Healthy,
all seven serving Deployments to be ready, the completed migration Job identities
to match the baseline, and existing unaffected Pods to remain in place. A fresh
PKCE login with the existing dev QA fixture then reads Account `myProfile` and
Match `getDailyFeed` together through the public Gateway. For both client-supplied and
Gateway-generated IDs, the response and all three service logs must agree. Test
output must contain aggregate checks only; bearer tokens and account data are
excluded. The QA bearer is revoked after verification.

Rollback restores the three previous serving image references and per-service
manifest entries through Git, then verifies Argo health and the public API.
No DB rollback or migration rerun is required.

## Verified deployment

`trace-rollout-verification.json` records the aggregate live result at the
verification timestamp. Both requests returned HTTP 200 without GraphQL errors.
Supplied and generated IDs appeared in Gateway, Account and Match logs and in the
public response header. All seven Deployments were completely ready; the two
completed migration Jobs and unaffected Pods/images matched the predeploy
baseline. The QA bearer was revoked.

The QA fixture has no main-area row, so `mainArea` returned its existing 404
contract. The successful two-service check used `myProfile` and `getDailyFeed`
instead, without changing fixture data. Match application sources were unchanged
from the previously deployed Match revision.

A concurrent infrastructure change advanced main to `c960b599bd006ddcb3a2c325dd0c7b64f4ba70e0`
during verification. This revision contains the release GitOps commit
`3853694f0fba0647d9da54ef5e5c509751cef4ee` and preserves its three Deployment
manifests and image-release entries. Argo reported that descendant revision as
Synced/Healthy with a successful operation.
