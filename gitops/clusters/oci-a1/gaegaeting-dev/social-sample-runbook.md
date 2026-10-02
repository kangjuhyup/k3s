# Dev outgoing-like sample operation

User-authorized data-only operation: add five active outgoing likes from the exact
requested dev account to five preselected existing Seoul synthetic fixtures.
No reverse likes, pairs, chat records, feed edits, notifications or Kafka publishing.

Before writing, revalidate Auth tenant/subject and issuer-to-Account mapping, target
fixture membership, ACTIVE profiles and pets, and the Doppler dev database identity.
Keep all identities and planned target mappings in mode0600 non-Git files. Snapshot
existing Account and Match rows; no preexisting relationship may be reactivated.

Run one short transaction with bounded lock/statement timeouts. Validate existing
rows and absence of reverse/pair relations, insert only missing planned edges with
active=true and source=0 (the existing like event source), and verify exactly five
planned edges. Check all preexisting rows and other Match tables before COMMIT;
any failed guard rolls back. A retry must use the same private plan and recognize
only its exact already-created edges; it must not select new targets.

After commit, recheck Account fingerprints and Match preservation. Keep newly
created like IDs and target mapping in a private cleanup manifest; cleanup is not
executed without a separate request. Export only five synthetic public nicknames
and pet name/breed/age/size/personalities for the UI preview. No subject, internal
ID or credentials go into the public sample or aggregate proof.

## Result — 2026-10-02

Committed five active outgoing edges, source=0. Preexisting Match rows and all
Account rows matched their fingerprints after commit. Reverse likes, pairs, chat
records and events were not created. The five synthetic public nickname/pet
records are in `/tmp/ggt-social-ui-sample.json`; identities and newly created like
IDs are confined to a mode0600 local cleanup manifest. No deployment changes.
See [aggregate verification](social-sample-verification.json).
