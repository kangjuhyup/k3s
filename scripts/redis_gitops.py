"""Shared Redis master/replica; private identities are mounted, never rendered."""
SETTINGS = "gitops/clusters/oci-a1/redis.json"
PATH = "gitops/clusters/oci-a1/redis"
ROOT = "gitops/clusters/oci-a1/root"
IMAGE = "docker.io/library/redis:8.2.9-alpine@sha256:30abb90e62f14b737010746def3ba99cc79fe19dcdb3d37b41f21fc62e7da19d"

START = r'''set -eu
umask 077
safe() { case "$1" in ''|*[!a-zA-Z0-9_-]*) exit 1;; esac; }
password() { case "$1" in ''|*[!a-f0-9]*) exit 1;; esac; [ "${#1}" -eq 64 ]; }
printf 'user default off\n' > /runtime/users.acl
for role in admin replication probe; do
  name=$(cat "/private/$role-username"); secret=$(cat "/private/$role-password")
  safe "$name"; password "$secret"
  case "$role" in
    admin) rules='~* &* +@all';;
    replication) rules='+psync +replconf +ping';;
    probe) rules='+ping +info';;
  esac
  printf 'user %s on >%s %s\n' "$name" "$secret" "$rules" >> /runtime/users.acl
done
for account in /accounts/*; do
  name=$(cat "$account/username"); secret=$(cat "$account/password"); prefix=$(cat "$account/prefix")
  safe "$name"; password "$secret"
  case "$prefix" in ''|*[!a-zA-Z0-9_:-]*) exit 1;; esac
  printf 'user %s on >%s ~%s* resetchannels -@all +@read +@write -@dangerous -@scripting -keys -scan -randomkey -dbsize +ping +hello +echo +client|setname +client|setinfo +client|getname +multi +exec +discard +watch +unwatch\n' "$name" "$secret" "$prefix" >> /runtime/users.acl
done
cp /private/probe-username /runtime/probe-username
cp /private/probe-password /runtime/probe-password
cp /config/redis.conf /runtime/redis.conf
if [ "$REDIS_ROLE" = replica ]; then
  host=$(cat /private/master-host); port=$(cat /private/port)
  case "$host" in ''|*[!a-zA-Z0-9.-]*) exit 1;; esac
  [ "$port" = 6379 ]
  name=$(cat /private/replication-username); secret=$(cat /private/replication-password)
  printf 'replicaof %s %s\nmasteruser %s\nmasterauth %s\n' "$host" "$port" "$name" "$secret" >> /runtime/redis.conf
fi
unset name secret prefix host port
exec redis-server /runtime/redis.conf
'''
HEALTH = r'''set -eu
export REDISCLI_AUTH="$(cat /runtime/probe-password)"
result=$(redis-cli --no-auth-warning --user "$(cat /runtime/probe-username)" --raw ping)
[ "$result" = PONG ]
if [ "${1:-}" = ready ] && [ "$REDIS_ROLE" = replica ]; then
  redis-cli --no-auth-warning --user "$(cat /runtime/probe-username)" --raw info replication | grep -q '^master_link_status:up'
fi
'''
CONFIG = '''bind 0.0.0.0
protected-mode yes
port 6379
daemonize no
loglevel warning
dir /data
aclfile /runtime/users.acl
databases 1
maxmemory 128mb
maxmemory-policy noeviction
replica-read-only yes
replica-ignore-maxmemory yes
replica-serve-stale-data no
maxclients 100
repl-backlog-size 1mb
client-output-buffer-limit replica 16mb 8mb 60
client-output-buffer-limit normal 4mb 2mb 60
client-output-buffer-limit pubsub 4mb 2mb 60
appendonly yes
appendfsync everysec
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 32mb
save ""
'''


def render(bootstrap, config):
    if config != {"enabled": True, "credentials_ready_reviewed": True}:
        raise ValueError("Redis requires reviewed credential delivery")
    namespace = "databases"
    destination = {"server": "https://kubernetes.default.svc", "namespace": namespace}
    policy = {"automated": {"enabled": True, "selfHeal": True, "prune": False, "allowEmpty": False},
              "syncOptions": ["ServerSideApply=true", "FailOnSharedResource=true"]}
    def obj(api, kind, name, **fields):
        return {"apiVersion": api, "kind": kind, "metadata": {"name": name, "namespace": namespace}, **fields}
    project = obj("argoproj.io/v1alpha1", "AppProject", "platform-redis", spec={
        "sourceRepos": [bootstrap["repo_url"]], "destinations": [destination], "clusterResourceWhitelist": [],
        "namespaceResourceWhitelist": [{"group": g, "kind": k} for g, k in [
            ("", "ConfigMap"), ("", "Service"), ("apps", "StatefulSet")]]})
    app = obj("argoproj.io/v1alpha1", "Application", "redis", spec={
        "project": "platform-redis", "destination": destination,
        "source": {"repoURL": bootstrap["repo_url"], "targetRevision": bootstrap["revision"], "path": PATH},
        "syncPolicy": policy})
    for resource, wave in [(project, "-10"), (app, "50")]:
        resource["metadata"].update(namespace="argocd", annotations={"argocd.argoproj.io/sync-wave": wave})
    files = {ROOT + "/redis-project.json": project, ROOT + "/redis.json": app}
    resources = []
    def add(filename, resource):
        files[PATH + "/" + filename] = resource
        resources.append(filename)
    add("config.json", obj("v1", "ConfigMap", "shared-redis-config", data={
        "redis.conf": CONFIG, "start.sh": START, "health.sh": HEALTH}))
    for role in ["master", "replica"]:
        name = "shared-redis-" + role
        labels = {"app.kubernetes.io/name": "shared-redis", "app.kubernetes.io/component": role}
        add(role + "-service.json", obj("v1", "Service", name, spec={"type": "ClusterIP", "selector": labels,
            "ports": [{"name": "redis", "port": 6379, "targetPort": "redis"}]}))
        add(role + "-headless.json", obj("v1", "Service", name + "-headless", spec={"clusterIP": "None", "selector": labels,
            "ports": [{"name": "redis", "port": 6379, "targetPort": "redis"}]}))
        probe = {"exec": {"command": ["sh", "/config/health.sh"]}, "timeoutSeconds": 3, "periodSeconds": 10}
        statefulset = obj("apps/v1", "StatefulSet", name, spec={
            "serviceName": name + "-headless", "replicas": 1, "selector": {"matchLabels": labels},
            "persistentVolumeClaimRetentionPolicy": {"whenDeleted": "Retain", "whenScaled": "Retain"},
            "template": {"metadata": {"labels": labels, "annotations": {"sidecar.istio.io/inject": "false"}}, "spec": {
                "automountServiceAccountToken": False, "terminationGracePeriodSeconds": 60,
                "securityContext": {"runAsNonRoot": True, "runAsUser": 999, "runAsGroup": 1000,
                    "fsGroup": 1000, "fsGroupChangePolicy": "OnRootMismatch", "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{"name": "redis", "image": IMAGE, "command": ["sh", "/config/start.sh"],
                    "env": [{"name": "REDIS_ROLE", "value": role}], "ports": [{"name": "redis", "containerPort": 6379}],
                    "resources": {"requests": {"cpu": "50m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}},
                    "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                    "startupProbe": {**probe, "failureThreshold": 60}, "livenessProbe": {**probe, "failureThreshold": 6},
                    "readinessProbe": {**probe, "exec": {"command": ["sh", "/config/health.sh", "ready"]}},
                    "volumeMounts": [{"name": n, "mountPath": p, "readOnly": ro} for n, p, ro in [
                        ("data", "/data", False), ("runtime", "/runtime", False), ("config", "/config", True),
                        ("private", "/private", True), ("auth-account", "/accounts/auth", True)]]}],
                "volumes": [{"name": "runtime", "emptyDir": {"medium": "Memory", "sizeLimit": "1Mi"}},
                    {"name": "config", "configMap": {"name": "shared-redis-config"}},
                    {"name": "private", "secret": {"secretName": "shared-redis-private", "defaultMode": 288}},
                    {"name": "auth-account", "secret": {"secretName": "auth-redis-credentials", "defaultMode": 288}}]}},
            "volumeClaimTemplates": [{"metadata": {"name": "data"}, "spec": {"accessModes": ["ReadWriteOnce"],
                "storageClassName": "local-path", "resources": {"requests": {"storage": "1Gi"}}}}]})
        statefulset["metadata"]["annotations"] = {"argocd.argoproj.io/sync-wave": "10" if role == "master" else "20",
            "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"}
        add(role + ".json", statefulset)
    add("kustomization.yaml", {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", "resources": resources.copy()})
    return files
