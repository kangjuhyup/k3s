# 공유 Redis

Argo CD로 master 1개와 read-only replica 1개를 관리한다. 각 Pod는 메모리 제한 256MiB, Redis maxmemory 128MiB다. replica는 복제 일관성을 위해 maxmemory를 직접 집행하지 않지만 Kubernetes의 제한은 동일하다. 데이터는 중복되므로 용량이 합산되지 않는다. fork·복제 버퍼 때문에 부하에 따라 OOM이 가능하며 별도 부하 검증이 필요하다.

각 Pod는 AOF everysec와 local-path PVC 1GiB를 사용한다. PVC는 삭제·축소 시 Retain이며 요청 용량은 디스크 강제 쿼터가 아니다. 단일 노드 장애와 비동기 복제·AOF 미동기화 쓰기 유실 가능성이 있다. Sentinel·자동 승격·Wasabi 백업은 비활성이다. ClusterIP 전용이며 Redis 자체 mTLS를 적용하고 평문 TCP 포트는 비활성화한다.

## Doppler와 서비스 격리

- `infrastructure / prd`: `REDIS_ADMIN_USERNAME`, `REDIS_ADMIN_PASSWORD`, `REDIS_REPLICATION_USERNAME`, `REDIS_REPLICATION_PASSWORD`, `REDIS_PROBE_USERNAME`, `REDIS_PROBE_PASSWORD`, `REDIS_HOST`, `REDIS_REPLICA_HOST`, `REDIS_PORT`, `REDIS_DB`.
- `auth / prd`: `REDIS_USERNAME`, `REDIS_PASSWORD`, `REDIS_KEY_PREFIX` 및 공통 접속 키의 Doppler cross-project 참조. 앱에 infrastructure 토큰이나 관리자·복제 비밀값을 전달하지 않는다.
- default 계정은 비활성이다. 앱은 자기 접두사 키에만 접근하며 전체 키 탐색·전체 삭제·관리·스크립트·Pub/Sub 권한은 없다. ACL은 키 접근 격리이며 자원·장애 격리는 아니다. 모든 앱 키에 `REDIS_KEY_PREFIX`를 붙이고 `REDIS_USERNAME`으로 인증한다.
- 점검 계정은 PING/INFO, 복제 계정은 PSYNC/REPLCONF/PING만 허용한다. 실제 계정값은 Secret 파일에서 런타임 ACL로 구성하며 Git에는 참조만 둔다.

## 운영

원본은 `scripts/redis_gitops.py`, 활성화 게이트는 `gitops/clusters/oci-a1/redis.json`, 비밀값 매핑은 `gitops/clusters/oci-a1/doppler.json`이다. 저장소 Python으로 `scripts/argocd_gitops.py --repo-root . --write`를 실행하고 생성물·테스트·server dry-run을 검토한 뒤 Git으로 반영한다. 새 서비스는 자기 Doppler config·읽기 토큰·계정 Secret 매핑과 `/accounts/` 하위 mount를 추가한다. 기존 계정명 중복·접두사 겹침을 반드시 검사한다.

Secret/ConfigMap 변경만으로 실행 중 ACL·설정이 갱신되지 않는다. 계정 추가·교체는 Pod template의 Git 변경으로 재배포하며 master의 쓰기 중단을 고려한다. 자동 reload나 직접 ACL/CONFIG 변경으로 우회하지 않는다. 신규 config 인증은 기존 `bootstrap-doppler-auth.yml`에 `doppler_token_env`를 명시해 해당 인증 Secret만 create한다. 기존 토큰은 덮어쓰지 않는다.

검증: `scripts/redis_verify.py --run-config <보호된-run-config-경로>`는 명시한 kubeconfig/context로 일시적 로컬 port-forward를 열어 mTLS·ACL·복제를 검사하고 종료한다. 정상 인증서와 서버 SAN 검증, 평문·클라이언트 인증서 없음·신뢰하지 않는 CA·잘못된 서버 이름의 거부를 확인한다. 랜덤 키를 60초 TTL로 생성하고 검증 후 해당 키만 삭제한다. 검증에 필요한 임시 PEM은 제한된 임시 디렉터리의 0600 파일로 전달하고 종료 시 삭제한다. Argo CD revision·Synced/Healthy, 두 Pod Ready/PVC Bound도 별도로 확인한다. 백업 복원·노드 장애·최대 부하 검증과 구분한다.

## mTLS 인증서와 갱신

Redis 전용 CA 개인키 `REDIS_TLS_CA_KEY`는 `infrastructure / prd`에만 보관하며 Kubernetes Secret 매핑에 포함하지 않는다. 같은 config의 읽기 토큰을 가진 Doppler Operator는 원본 config 접근 권한이 있으므로, 이 방식이 CA 키의 오프라인 격리를 의미하지는 않는다. 서명 권한의 더 강한 격리는 별도 signing config/외부 PKI로 이전하는 후속 작업이다.

master·replica는 각각 `REDIS_MASTER_TLS_CERT/KEY`, `REDIS_REPLICA_TLS_CERT/KEY`를 별도 Secret으로 받는다. 이 인증서는 serverAuth/clientAuth 용도다. `REDIS_OPERATIONS_TLS_CERT/KEY`는 운영 클라이언트용이며 `auth / prd`의 `REDIS_TLS_CERT/KEY`는 auth 앱 전용 clientAuth 인증서다. 앱에는 `REDIS_TLS_CA_CERT`를 cross-project 참조로 공급하며 CA 개인키·다른 앱 인증서를 주지 않는다. `REDIS_TLS_ENABLED`를 사용하고, 클라이언트에 CA·인증서·개인키를 로딩해 서버 호스트명 검증과 기존 ACL 인증을 모두 켠다. 인증서와 ACL 계정 사이의 자동 identity binding은 없으며 둘은 독립적으로 검증된다.

Python 의존성은 `scripts/requirements-pki.txt`를 사용한다. 저장소 루트에서 다음 명령을 실행한다.

```sh
"$PKI_PYTHON" scripts/redis_pki.py --check
# 최초 발급에만 사용. 기존 CA가 있으면 거부한다.
"$PKI_PYTHON" scripts/redis_pki.py --write
# 승인된 정기 갱신: 기존 CA를 유지하고 leaf 키와 인증서를 교체한다.
"$PKI_PYTHON" scripts/redis_pki.py --write --renew-leaves
```

CA 유효기간은 1095일, leaf는 90일이다. `--check`는 잔여 30일 미만이면 실패한다. **자동 갱신·알림은 아직 없다.** 만료 전 운영자가 갱신한 뒤 `--check`, Doppler Secret의 인증서·키 일치 검증을 수행하고 `redis.json`의 `tls_revision`을 증가시켜 생성·검토·Git 반영한다. 앱도 새 클라이언트 인증서를 로딩해야 한다. 서버는 시작 시 인증서를 보호된 메모리 볼륨에 복사하므로 Secret 변경만으로 재로딩되지 않는다. 순차 master/replica 재배포 중 쓰기·복제 중단이 발생할 수 있다. CA 교체·긴급 인증서 폐기는 단순 leaf 갱신과 구분하여 신뢰 번들 전환을 별도로 계획한다.

Redis 8.2.9의 복제 TLS는 CA 체인 검증을 하지만 SNI 설정만으로 호스트명 대조까지 수행하지는 않는다. 전용 CA와 client-only 앱 인증서로 신뢰 범위를 줄였으나, 복제 연결에서 서버 SAN을 검증했다고 보고하지 않는다. 앱/검증 클라이언트는 SAN 대조를 수행한다. [Redis TLS 구현](https://github.com/redis/redis/blob/8.2.9/src/tls.c), [TLS 설정](https://redis.io/docs/latest/operate/oss_and_stack/management/security/encryption/).

근거: [Redis ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/), [복제와 replica 메모리](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/), [8.2 보안 릴리스](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisos-8.2-release-notes/).
