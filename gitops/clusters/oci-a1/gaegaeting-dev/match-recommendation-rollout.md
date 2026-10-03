# Match recommendation release 1.0.3

Release [#149](https://github.com/kangjuhyup/gaegaeting/pull/149) publishes Match source
`6743d8e6b77642be3e6d96353251445f68061e60`. Exact serving image metadata and independent
anonymous GHCR tag/digest/index-body/platform checks are recorded in
[image verification](match-recommendation-image-verification.json).

Automatic and manual recommendation creation now share the same candidate lookup.
The actual geographic distance must be at most 10 km; the closest two eligible users
are selected. Active pairs and recommendations from the last seven days remain excluded.
Current location updates replace stored coordinates. Feed generation and retrieval use
Korea dates, slots follow 08:00/12:00/18:00 KST, and expiration is next-day 00:00 KST.
Manual creation before 08:00 uses the current day's morning slot.

Only the Match serving image changes in this GitOps rollout. Other serving images,
current Doppler stg projections, completed migration Jobs, identities and schema
artifacts are preserved. No database migration or user-data update is required.
The deployed namespace and public test endpoints remain gaegaeting-dev and the existing
test-ggt UI/API hosts. Automatic Argo CD sync applies the Git change.

Pre-release verification passed Match 96 tests including PostgreSQL integration and
UTC time-boundary cases. Release/main CI passed workspace tests and packaged Match
runtime plus amd64/arm64 image verification. Static release validation and a server
side dry-run of the changed Deployment precede GitOps merge. Completion requires
Argo revision/Synced/Healthy, seven ready serving Deployments, unchanged unrelated
Pods and migration Jobs, Match health and a read-only real candidate query against the
new artifact. Post-rollout aggregate results are recorded on the deployment PR.

Rollback changes only the Match Deployment image and corresponding release manifest
entry to the previously verified digest through Git, then lets Argo CD reconcile.
No database rollback, fixture cleanup or direct Kubernetes mutation is needed.
