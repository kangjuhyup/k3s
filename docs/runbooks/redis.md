# 공유 Redis

Argo CD로 master 1개와 read-only replica 1개를 관리한다. 각 Pod는 메모리 제한 256MiB, Redis maxmemory 128MiB다. replica는 복제 일관성을 위해 maxmemory를 직접 집행하지 않지만 Kubernetes의 제한은 동일하다. 데이터는 중복되므로 용량이 합산되지 않는다. fork·복제 버퍼 때문에 부하에 따라 OOM이 가능하며 별도 부하 검증이 필요하다.

각 Pod는 AOF everysec와 local-path PVC 1GiB를 사용한다. PVC는 삭제·축소 시 Retain이며 요청 용량은 디스크 강제 쿼터가 아니다. 단일 노드 장애와 비동기 복제·AOF 미동기화 쓰기 유실 가능성이 있다. Sentinel·자동 승격·Wasabi 백업·TLS는 설치하지 않는다. ClusterIP 전용이며 구간 암호화가 필요한 소비자는 TLS 구성을 먼저 추가해야 한다.

## Doppler와 서비스 격리

- `infrastructure / prd`: `REDIS_ADMIN_USERNAME`, `REDIS_ADMIN_PASSWORD`, `REDIS_REPLICATION_USERNAME`, `REDIS_REPLICATION_PASSWORD`, `REDIS_PROBE_USERNAME`, `REDIS_PROBE_PASSWORD`, `REDIS_HOST`, `REDIS_REPLICA_HOST`, `REDIS_PORT`, `REDIS_DB`.
- `auth / prd`: `REDIS_USERNAME`, `REDIS_PASSWORD`, `REDIS_KEY_PREFIX` 및 공통 접속 키의 Doppler cross-project 참조. 앱에 infrastructure 토큰이나 관리자·복제 비밀값을 전달하지 않는다.
- default 계정은 비활성이다. 앱은 자기 접두사 키에만 접근하며 전체 키 탐색·전체 삭제·관리·스크립트·Pub/Sub 권한은 없다. ACL은 키 접근 격리이며 자원·장애 격리는 아니다. 모든 앱 키에 `REDIS_KEY_PREFIX`를 붙이고 `REDIS_USERNAME`으로 인증한다.
- 점검 계정은 PING/INFO, 복제 계정은 PSYNC/REPLCONF/PING만 허용한다. 실제 계정값은 Secret 파일에서 런타임 ACL로 구성하며 Git에는 참조만 둔다.

## 운영

원본은 `scripts/redis_gitops.py`, 활성화 게이트는 `gitops/clusters/oci-a1/redis.json`, 비밀값 매핑은 `gitops/clusters/oci-a1/doppler.json`이다. 저장소 Python으로 `scripts/argocd_gitops.py --repo-root . --write`를 실행하고 생성물·테스트·server dry-run을 검토한 뒤 Git으로 반영한다. 새 서비스는 자기 Doppler config·읽기 토큰·계정 Secret 매핑과 `/accounts/` 하위 mount를 추가한다. 기존 계정명 중복·접두사 겹침을 반드시 검사한다.

Secret/ConfigMap 변경만으로 실행 중 ACL·설정이 갱신되지 않는다. 계정 추가·교체는 Pod template의 Git 변경으로 재배포하며 master의 쓰기 중단을 고려한다. 자동 reload나 직접 ACL/CONFIG 변경으로 우회하지 않는다. 신규 config 인증은 기존 `bootstrap-doppler-auth.yml`에 `doppler_token_env`를 명시해 해당 인증 Secret만 create한다. 기존 토큰은 덮어쓰지 않는다.

검증: `scripts/redis_verify.py --run-config <보호된-run-config-경로>`는 명시한 kubeconfig/context로 일시적 로컬 port-forward를 열어 인증·ACL·복제를 검사하고 종료한다. 랜덤 키를 60초 TTL로 생성하고 검증 후 해당 키만 삭제한다. Argo CD revision·Synced/Healthy, 두 Pod Ready/PVC Bound도 별도로 확인한다. 백업 복원·노드 장애·최대 부하 검증과 구분한다.

근거: [Redis ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/), [복제와 replica 메모리](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/), [8.2 보안 릴리스](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisos-8.2-release-notes/).
