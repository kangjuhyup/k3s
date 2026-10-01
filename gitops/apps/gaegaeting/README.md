# Gaegaeting application resources

Account, Match, Gateway, Edge authorization, integration UI, Envoy and release migration Jobs live here. The OCI dev overlay supplies replicas, resources, runtime Secret delivery, routing and access policies. Deploy through `gitops/clusters/oci-a1/gaegaeting-dev`, not directly from this base.

Kafka is shared infrastructure owned by the separate `kafka` Argo Application. Its endpoint and application topic prefix are injected through Doppler. Database and Redis servers are also shared infrastructure.
