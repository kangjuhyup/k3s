# Shared Kafka

The separate `kafka` Argo Application owns the broker in namespace `kafka`. Reusable broker/service manifests are in `gitops/platform/kafka`; this overlay supplies namespace, replicas, NetworkPolicy and Doppler delivery from `infrastructure/prd`.

Apache Kafka 4.1.2 is pinned by multi-architecture digest. The single KRaft broker uses 5 GiB local-path storage, UID 1000 and retained PVCs. Initial activation completed through reviewed Git revisions; Argo automation is enabled after Synced/Healthy and broker API checks. No broker port is publicly exposed. The NetworkPolicy currently admits the Gaegaeting dev Match producer and broker-internal traffic; add other consumers explicitly.

Clients obtain their endpoint through their own Doppler configuration. Development and production topics must have distinct application/environment prefixes. Current clients use plaintext Kafka inside the cluster; this setup does not provide per-topic credential ACL isolation or broker high availability.

The former dedicated broker is scaled to zero before shared-broker activation; its topic inventory was empty. Its namespace and PVC are retained without a running broker.
