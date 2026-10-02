# Mobile UI and Match state rollout

Deploy core 1.0.4 user/admin UI artifacts and Match 1.0.2 through this existing
Argo CD application. Exact source revisions, image digests and workflow runs are
recorded per service in `release-images.json` and independently checked against
the anonymous GHCR tag and digest in `mobile-image-verification.json`.

The user application now contains responsive login, registration, recommendations,
pet/profile management and bottom navigation. Completed registrations enter the
recommendation screen after login. The existing logout action remains available.
Likes and chat screens are explicitly labelled sample previews; chat persistence
and backend delivery remain outside this UI release.

Match aligns GraphQL DELIVERY/VIEW/LIKE/PASS with the existing persisted codes
1/2/3/4. Entity transitions use those constants. No database schema, stored rows or
migration files change, verified against the deployed schema source. Both completed
migration Jobs retain their exact verified image, name and identity. `migrationImages`
records those schema artifacts separately from current serving images; the validator
still requires exact source revisions and digests for every Job. No Job is rerun.

Only integration-ui, admin-ui and match serving images change. Account, gateway,
edge-authz, edge-proxy, Auth configuration, Doppler values and fixtures are preserved.
Verification compares their running Pod identities with the pre-rollout baseline.

Pre-release validation passed: workspace build/tests, 14 UI tests, 71 script tests,
Match persisted-state regression tests and live onboarding/feed queries. A 320px
browser viewport verified login and sample navigation/message interaction without
horizontal overflow. Release PR checks include packaged runtime and ARM64 images.
GitOps static validation and the three changed resource server dry-runs precede merge.
Argo revision/health, seven ready serving Deployments, preserved completed Jobs, public
HTTPS and live API checks are required before reporting the deployment complete.

The previously reproduced Chrome Auth end-session confirmation `xsrf token invalid`
remains a separate investigation with the k3s project agent. HTTP logout/revocation
checks passed; this release does not claim Chrome logout E2E has been resolved.

Rollback the three workload declarations and the three per-service release entries
through Git. Argo CD performs the rollout; do not use direct Kubernetes mutations.
No database migration rollback or fixture deletion is required by these changes.
