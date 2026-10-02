# Profile image review release gate

Target remains the existing dev environment and `gaegaeting-dev` tenant. Production
and other shared-service workloads are outside this release. Current serving images
remain active until the application agent supplies the verified main SHA and all five
public multi-platform image digests.

## Runtime and identity

Doppler `gaegaeting/dev:UI_IMAGE_STORAGE_ORIGIN` must equal the exact HTTPS origin of
`STORAGE_HOST`. Only that public origin is projected to the UI; storage credentials
remain Account-only. The new image must expose it through its runtime allowlist and
use it for upload/display CSP. Old UI code does not consume this newly projected key.

The existing `gaegaeting-web` client allows the additional `tenant_roles` scope.
Normal login scopes remain unchanged. Only admin login requests the role scope;
Account authorization requires the direct tenant role code `ADMIN`, introspected as
`tenant_roles: [{id, code}]` and signed through Edge/Gateway. No real-user role is
assigned without the explicitly designated account. Any temporary QA role assignment
and removal needs the separately specified QA identity and test authorization.

## Storage

Only the existing marked dev USER/PET buckets may be changed. Verify private access,
exact dev UI CORS for PUT/GET/HEAD and Content-Type, and actual Account credential
PUT, conditional HEAD, Range GET, ETag-conditional same-bucket CopyObject, GET and
DELETE. Both mismatched ETag conditions and anonymous object reads must be denied.
Use synthetic canaries and remove only their exact keys. Preserve existing policies
and lifecycle rules. The staging prefix `profile-images/uploads/` expires after
seven days; `profile-images/review/` has no new expiration rule. Presigned URL expiry
and real browser upload/approval remain release E2E gates.

## Ordered Git → Argo rollout

1. Verify all five published digests, ARM64 runtime, revision, migration artifacts
   and unchanged Match `KAFKA_TOPIC_PREFIX=dev.gaegaeting` behavior. Temporarily set
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
   user/pet upload, pending visibility, designated/authorized temporary ADMIN review,
   approval/readback, normal-user denial, frozen-copy protection and cleanup evidence.
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
