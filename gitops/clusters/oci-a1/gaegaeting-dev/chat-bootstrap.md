# Chat dev bootstrap — prepared, not applied

Scope: existing shared PostgreSQL, namespace `gaegaeting-dev`, Doppler
`gaegaeting/stg`. Exact Chat image source `6aee44544e7db298be6ac756b7083a6214344e50`
and index `sha256:db5e36ac0707088c6da37e015ed796c82dea6a18b6d1f7a0597304a84cc9fac2`.
Root revalidates registry/platforms. No production, Auth overlay, QA linking,
keys, store enablement or paid operation is included.

## Existing procedure and preconditions

This one-off operation reuses the explicit-context CNPG primary/socket/STDIN
pattern in `scripts/vote_database.py`; the ordinary resource changes remain
Git→Argo. It never applies/patches Kubernetes objects directly. Python 3.12.9,
PyYAML 6.0.3 and kubectl 1.36.4/Kustomize5.8.1 are the repository pins.

Root already created the three new keys `CHAT_DATABASE_NAME`,
`CHAT_DATABASE_USERNAME`, `CHAT_DATABASE_PASSWORD` in `gaegaeting/stg`, with
round-trip and absence-before-write checks. They must not be overwritten or
rotated. The first two must match for existing `sameuser` TLS HBA. The bootstrap
script fetches only those keys into memory, sends shell-quoted values via STDIN
and consumes them with psql environment variables. Neither identifiers nor
password appear in argv, SQL constants, files, output or Git. No new credential
is created by this script. Keep Doppler as sole source.

Before executing, root must confirm the expected context/server from its private
run-config, the shared primary Ready1, existing scoped HBA rules followed by
`hostssl sameuser all all scram-sha-256` then catch-all reject, live CA projection,
existing app/migration UID baseline, and connection capacity (Chat pool up to10
plus one LISTEN connection). Existing PostgreSQL/HBA/PVC/roles are not changed.

The script additionally checks effective `pg_hba_file_rules` for parsing errors
and any network allow matching the new role besides sameuser. It rejects
collisions in expanded scoped identity rules, broad trust/password fallback,
role memberships, elevated attributes, unmarked role/database ownership and
explicit grants on other databases. PUBLIC ACL metadata is not used as proof of
network reachability: existing other-DB PUBLIC grants are left unchanged. The
TLS positive/negative probe below is mandatory before rollout.

## Root execution order

1. Review this commit and merge through the normal PR path. Do not let active
   Chat manifests reconcile before the prerequisite keys/DB/network are ready.
   Root can first merge only the scripts/runbook, then merge the already-reviewed
   manifests after bootstrap, or pause Gaegaeting automation through a reviewed
   Git change. Do not use a live patch. Existing completed Jobs and prune=false
   remain intact. Kafka's new Chat-only policy is a separate additive prerequisite
   in the existing Kafka Application; no broker Pod template is changed.
2. In a private copy of the existing run-config, set `expected_revision` to the
   exact reviewed commit containing this script (all other protected fields
   unchanged). The script requires its source to match that Git revision.
3. Execute from the reviewed clone with the pinned Python; arguments below are
   file paths only, never credential values:

   ```sh
   /Users/kangjuhyup/Documents/k3s/.local/os-cleanup-venv/bin/python scripts/gaegaeting_chat_database.py --run-config /tmp/chat-bootstrap-run-private.json
   /Users/kangjuhyup/Documents/k3s/.local/os-cleanup-venv/bin/python scripts/gaegaeting_chat_database.py --run-config /tmp/chat-bootstrap-run-private.json --write
   /Users/kangjuhyup/Documents/k3s/.local/os-cleanup-venv/bin/python scripts/gaegaeting_chat_database.py --run-config /tmp/chat-bootstrap-run-private.json --verify-access
   ```

   Default is read-only SQL guards. `--write` suppresses session log_statement,
   log_duration, log_min_duration_statement and log_min_error_statement before
   any password-bearing SQL; stdout/stderr are captured/suppressed. Do not enable
   tracing, SQL debug, or credential-bearing statement logging. Check any external
   audit extension first; normal PostgreSQL session settings do not promise to
   override an independently configured audit collector.

   Role is LOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS.
   Own role/database carry the `gaegaeting-dev-chat-gitops` ownership comment.
   Own database grants CONNECT/TEMPORARY only to that owner, revokes PUBLIC DB
   access and PUBLIC schema CREATE, grants owner public schema USAGE/CREATE for
   its two migrations/CRUD. No other DB/schema ACL is altered; HBA blocks their
   remote access even if an inherited PUBLIC grant exists.

   `--verify-access` uses the existing ready Account Node runtime and CA mount,
   passing only Chat credentials via STDIN. It opens own DB with verify-full and
   checks actual TLS; tries each other connectable database and requires HBA or
   CONNECT denial (SQLSTATE28000/42501). Password failure/timeouts do not count as
   isolation success. It only reports booleans/counts. No application/user query
   or mutation is performed.

4. Root ensures the following **nonempty values and semantics**, with no dumps:

   | Doppler keys | Required check |
   | --- | --- |
   | DATABASE_HOST/PORT/SSL_MODE, DATABASE_TLS_CA_CERT | existing shared PostgreSQL, verify-full and CA preserved |
   | CHAT_DATABASE_NAME/USERNAME/PASSWORD | root-created exact keys, no replacement |
   | CHAT_SERVICE_API_PORT | 2804 |
   | MATCH_SERVICE_HOST | existing Match service origin/port, HTTP `/match/graphql` |
   | CHAT_KAFKA_ENABLED | enabled after retained-topic review |
   | CHAT_KAFKA_GROUP_ID | independent dev Chat consumer group; never production/shared other consumer group |
   | KAFKA_BROKERS / KAFKA_TOPIC_PREFIX | existing shared broker, prefix `dev.gaegaeting` |
   | INTERNAL_AUTH_ASSERTION_SECRET | existing value, no rotation |
   | CHAT_SERVICE_URL | new Chat service port2804 `/chat/graphql` |
   | CHAT_WS_ALLOWED_ORIGINS | exact permitted dev UI origin(s); no wildcard; absent Origin native handling remains in Gateway |
   | OIDC_ISSUER/API_AUDIENCE/INTROSPECTION_CLIENT_ID/SECRET | existing gaegaeting-dev/API contract, same existing introspection credential as Edge, no new Auth client |

   New nonsecret config values require explicit Doppler assignment; copying this
   runbook does not silently set them. Existing key conflicts stop and are reviewed.
5. Git→Argo phases: Secret/RBAC sync(-30/-20), service(-10), exact Chat migration(0)
   Complete → Chat(10) Ready → Gateway(20) → Envoy(30). New
   `chat-migration-6aee44544e7d` uses exactly the same Chat image and two SQL migrations.
   All existing service images/migration metadata remain unchanged. Gateway/Envoy
   receive a deterministic Chat-contract Pod annotation to load the added config;
   these two roll once and no existing application is restarted gratuitously.

## HTTP, Kafka and WebSocket contract

Chat exposes internal port2804, health `/chat/health`, DB readiness
`/chat/health/ready`, GraphQL/WS `/chat/graphql`. Only Gateway reaches Chat through
its ingress policy. Chat may reach Match2801 for `chatPairs` with a signed principal
(issuer gaegaeting-gateway, audience match); Match keeps Gateway access. Current
Chat resolver scopes are **match:read / match:write**, not new chat:* scopes.
No Auth scope/client/role change is part of this patch.

Kafka ingress adds a distinct policy permitting only `gaegaeting-dev` Chat Pod
labels to broker9092. Existing Match policy stays byte-for-byte intact. Consumer
subscribes to `dev.gaegaeting.chat.room.created.v1`, fromBeginning=true with its
own group. It can create Chat room/participant rows from retained pair events on
startup; this is real application processing, not QA mapping/seed. Root must review
retained event validity and confirm this activation effect before enabling it.
Do not alter Kafka offsets or delete topics to mask bad legacy events.

Public HTTP remains exact `/gateway/graphql` with fail-closed Edge auth. WS uses
that same exact path with GET+Upgrade:websocket only; it bypasses HTTP ext_authz
because browser/native credentials arrive in graphql-transport-ws connection_init.
Gateway directly introspects the token, resolves Account subject, checks Origin
when present, enforces 5s authentication timeout, and opens Chat upstream only
after successful authentication. It rechecks token every30s and on subscription,
allows only chatEvents subscriptions, and forwards fresh short-lived internal
assertions. No direct public Chat route or generic upgrade bypass is added.
Spoofed principal/assertion headers remain stripped. WS is disabled globally and
only enabled for the exact route; plain HTTP continues through ext_authz.

## Verification and recovery

Local render/security tests are preparation evidence only, not actual database or
native E2E success. Root must run pinned Envoy binary `--mode validate` on the
synthetic config emitted by gaegaeting_chat_validate.py (no real addresses), then
actual DB preflight/write/idempotent second write/TLS isolation, migrations2,
Chat health/ready, Match HTTP proof, consumer startup and public HTTP/WS negative
checks. Unauthenticated WS may upgrade101 but must close4401/4408 before any
protected data. Disallowed Origin must403. Native paired-user mutation/WS E2E
requires separately authorized QA identity/mapping and is not part of bootstrap.

CREATE DATABASE cannot be transactional with CREATE ROLE. Failed first creation
may leave a marked restricted role; a same-identity retry never rotates password.
A DB created before ownership-comment completion is deliberately not auto-adopted:
stop for reviewed recovery. Do not claim whole-bootstrap rollback or auto-delete
partial state. Existing marked identities are checked, never reactivated or granted
cross-DB access. On failures preserve evidence, keys and data; no blind retries.
After serving writes, rollback must preserve Chat data and consumer group. Restore
Gateway/Envoy configuration through Git only if needed; never drop DB/users or
rerun/delete old migration Jobs as a deployment shortcut.
