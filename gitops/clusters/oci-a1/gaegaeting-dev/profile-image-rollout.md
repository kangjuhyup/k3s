# Profile image review release gate

Target remains the existing dev environment and `gaegaeting-dev` tenant. Production
and other shared-service workloads are outside this release. Current serving images
remain active until the application agent supplies the verified main SHA and all five
public multi-platform image digests.

## Runtime and identity

Doppler `gaegaeting/stg:UI_IMAGE_STORAGE_ORIGIN` must equal the exact HTTPS origin of
`STORAGE_HOST`. Only that public origin is projected to the UI; storage credentials
remain Account-only. The new image must expose it through its runtime allowlist and
use it for upload/display CSP. Old UI code does not consume this newly projected key.

The existing `gaegaeting-web` client allows the additional `tenant_roles` scope.
Normal login scopes remain unchanged. Only admin login requests the role scope;
Account authorization requires the direct tenant role code `ADMIN`, introspected as
`tenant_roles: [{id, code}]` and signed through Edge/Gateway. No real-user role is
assigned without the explicitly designated account. A real reviewer designation is
not an application rollout gate. After AppReady, the application agent creates exactly
one new QA user and supplies its identity. Temporary direct ADMIN assignment to that
QA identity, review E2E and removal are authorized as a bounded test sequence. Verify
removal afterward; do not reuse an arbitrary real user or grant an unconfirmed identity.

## Storage

Only the existing marked dev USER/PET buckets may be changed. Verify private access,
exact dev UI CORS for PUT/GET/HEAD and Content-Type, and actual Account credential
PUT, conditional HEAD, bounded full GET snapshot with IfMatch and response-ETag
verification, server-side PUT to a fresh review key, GET and DELETE. Wrong/stale GET
ETag conditions and anonymous object reads must be denied. CopyObject is no longer
a required photo permission or safety mechanism. Enforce the 5 MiB stream limit,
validate the snapshot, and retain exactly those bytes in the review object.
Use synthetic canaries and remove only their exact keys. Preserve existing policies
and lifecycle rules. The physical staging prefix is the Doppler `STORAGE_PROFILE_PREFIX` value followed
by `/profile-images/uploads/`; it expires after seven days. Preserve this application
prefix when configuring lifecycle; the bare logical prefix would not match objects.
The corresponding `profile-images/review/` path has no new expiration rule. Presigned URL expiry
and real browser upload/approval remain release E2E gates.

## Ordered Git → Argo rollout

1. Verify all five published digests, ARM64 runtime, revision, migration artifacts
   and unchanged Match `KAFKA_TOPIC_PREFIX=dev.gaegaeting` behavior. Before any
   Account stop or migration, execute the reviewed application-supplied
   `/tmp/ggt-photo-new-artifact-probe.mjs` with Node at `/app` in the exact new
   Account image. Inject only the seven Account STORAGE_* settings from Doppler
   gaegaeting/stg after checking both dev bucket markers; require ARM64, nonroot
   and matching OCI revision. Keep anonymous-access checks enabled. Require both
   bucket checks to pass, including compiled StorageService/ProfileImageService,
   snapshot isolation, PENDING/APPROVED visibility and malformed/oversized input
   rejection. Capture only aggregate output, suppress raw SDK errors, and verify
   probe cleanup. Record image digest and reviewed script SHA256 with the evidence.
   This in-memory repository probe does not prove live DB or ADMIN authorization;
   those remain post-AppReady browser E2E checks. Temporarily set
   only the `gaegaeting-dev` Application automatic sync to false through Git/Argo;
   confirm the live gate before committing new desired images. Preserve self-heal
   and automatic-prune policy for restoration; other Applications remain untouched.
2. Commit dev Account replicas 0 and selectively synchronize its Deployment. Confirm
   zero old Account Pods, including terminating Pods. A short dev Account API 503 and
   signup/profile write interruption is explicitly authorized for this transition.
3. With Account stopped, use the exact new Account image in a release-specific Job.
   Require six recorded migrations including `AccountSignupIdentity1790859600000`
   and `ProfileImageReview1790899200000`, successful Job exit and schema verification.
4. Start the new Account and require Ready before new UI exposure. Then roll out
   Edge-authz, same-main Match, Gateway, and UI in that dependency order. Keep old UI
   until its backend gates pass. Match migration uses its matching new image if its
   digest is updated. No database or shared Kafka reset is involved.
5. Application agent performs one-new-QA-user browser E2E: signup identity reuse,
   user/pet upload, pending visibility, temporary ADMIN review for the supplied new QA
   identity, approval/readback, normal-user denial, snapshot isolation and cleanup
   evidence. Revoke that QA role and verify removal after review tests. Real reviewer
   designation remains independent of rollout and this temporary QA flow.
   Validate both HTTPS endpoints and existing edge/private-route negative checks.
6. Restore automatic synchronization after gates pass; require Synced/Healthy,
   successful migration Jobs and serving Deployments Ready. Automatic prune stays
   false. Only obsolete completed migration Jobs may be selectively retired.

## Rollback boundary

The new attachment CHECK ties `is_active` to `review_status=APPROVED`. Old Account
photo writes are incompatible, including activating a new row and deactivating an
approved row. Old readers cannot translate newly frozen storage keys to signed GET
URLs. Consequently an old-image-only rollback is unsafe after new photo data exists.
Do not automatically reverse migrations or discard review metadata. Prefer a forward
fix on the new schema, or a separately reviewed compatible-code/database procedure.
Existing signup rows retain unknown identity fields as null; do not fabricate data.

## Preparation findings (2026-10-02)

The UI origin key was stored in Doppler and projected successfully; the existing
release remains Synced/Healthy. The additional Auth client scope was read back
successfully without granting any user a role.

Live storage probing observed success for CopyObject with a deliberately mismatched
`CopySourceIfMatch`. Treat this as a **release blocker**, not a successful permission
check. The app agent is replacing copying with a bounded full GET snapshot,
validation and server-side PUT to the review key. Confirm wrong/stale IfMatch GET
denial with the published Node SDK, response ETag verification and staging overwrite
independence. The validated bytes must be the exact bytes saved for review. Do not infer safety from HTTP 200 or from a
local S3 test server. Keep old serving images until this gate and the new release
image checks are resolved.

Published ARM64 Account image (source `317f550e3fb4`, Node 24.13.1) SDK probes passed
for both dev buckets: wrong/stale IfMatch GET denied, returned ETag and snapshot bytes
matched, review PUT/readback matched the validated snapshot, subsequent staging
replacement did not change review bytes, anonymous review access denied, and actual
CORS preflight passed. All probe objects were deleted. This proves storage primitives,
not the pending snapshot-fix application's validation or 5 MiB limit implementation.
See [aggregate evidence](photo-storage-verification.json). Recheck the final new image
and browser E2E before enabling the feature.

## Release completion (2026-10-02)

Main `7c3733450107934f08130f0ac7d0db1a8f54c59a` passed the exact new Account
artifact probe, ordered migrations/rollout and browser photo E2E. Temporary QA ADMIN
was removed and sessions read back as zero; its old bearer received HTTP 401/no data.
The explicitly authorized permanent dev ADMIN remains assigned and passed fresh
login/review access. Restore automatic sync/self-heal with prune=false; the preparation
blockers above are retained as history and do not indicate a current conditional-copy
dependency. See photo-e2e-verification.json and photo-rollout-verification.json.
