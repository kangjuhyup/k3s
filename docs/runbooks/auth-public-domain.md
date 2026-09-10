# Auth GitOps 배포

배포 및 auth 전용 Redis EVAL 권한 변경을 승인받았다. 원본은
`gitops/apps/auth/`의 앱 원본, `gitops/clusters/oci-a1/auth/`의 환경 구성과
`gitops/clusters/oci-a1/root/auth.yaml` Application이다. 앱 원본에는 Deployment·Service·Job·UI 설정을,
환경 구성에는 리소스/공개 URL 패치·HPA·Namespace·Doppler 주입·인증서·라우팅을 둔다.
Application의 `spec.source.path`는 전체 `auth` 환경 overlay를 참조한다.
클러스터의 auth Kustomization에서 앱 원본과 환경 패치를 합친다.
Cloudflare DNS는 기존 ingress 대상으로 연결했다. Doppler `auth/prd`에는
누락된 런타임 암호화 키·초기 관리자 자격 증명과 DB CA를 준비했다. 기존 값은 보존했다.

## 준비한 구성

| 구성 | 기본 개수 | CPU 요청 | 메모리 요청 / 제한 |
| --- | --- | --- | --- |
| API | HPA 1~3 | 100m | 256Mi / 768Mi |
| 관리자 UI | 1 | 10m | 32Mi / 64Mi |
| OIDC 정리 워커 | 1 | 10m | 128Mi / 384Mi |
| 마이그레이션 Job | 이미지별 1회 | 100m | 256Mi / 768Mi |

상시 최소 요청 합계는 CPU 120m, 메모리 416Mi다. 실측 최솟값이 아닌 초기 예산이다.
API HPA는 CPU 요청 대비 70%, 확장/축소는 분당 최대 1개, 축소 안정화는 300초다.
CPU 제한은 두지 않아 시작·해시 연산의 불필요한 throttling을 피한다.
Argo CD는 API replicas를 조정하지 않으며 UI·워커는 HPA 대상이 아니다.
단일 노드이므로 복제본 증가가 노드 장애에 대한 HA를 제공하지 않는다.

UI는 `https://auth.rvkang.app/`, API는 같은 호스트의 `/admin/`, `/auth/`, `/t/`,
`/interaction-assets/`를 원본 경로 그대로 전달한다. 공개 `/health`, `/ready`는 노출하지 않는다.
인증 backend 응답에는 ingress에서 `Cache-Control: no-store`를 설정한다.
UI nginx는 비루트 UID 101, 포트 8080, 읽기 전용 루트와 제한된 `/tmp`를 사용한다.
TLS는 Istio에서 종료하고 내부 HTTP로 전달한다. Namespace의 sidecar는 최소 리소스를 위해
비활성화했으며 앱 구간 mTLS라고 표현하지 않는다. Redis 자체 mTLS는 별개로 필수다.

## 런타임 계약

- `auth-runtime` Secret: Doppler `auth/prd`의 DB 접속 키, Redis 접속·접두사·mTLS PEM 키,
  `OIDC_COOKIE_KEYS`, `JWKS_ENCRYPTION_KEY`, `OTP_TOKEN_SECRET`를 같은 환경변수 이름으로 전달한다.
  Redis 계약은 게시된 `812ed68`과 대조했다. URL 없이 분리 설정을 주입하며
  INFO ready check와 CLIENT SETINFO는 앱에서 비활성화한다.
- DB 소비자는 `DB_SSLMODE` Secret 키를 node-postgres의 `PGSSLMODE`에 매핑한다.
  `DB_TLS_CA_CERT`는 읽기 전용 파일로 mount하고 `NODE_EXTRA_CA_CERTS`로 신뢰한다.
  CNPG CA 교체 시 Doppler의 CA와 Pod 재배포도 함께 관리한다.
- `auth-bootstrap` Secret의 `ADMIN_USERNAME`, `ADMIN_PASSWORD`는 마이그레이션 Job에만 전달한다.
  DB명·사용자·비밀번호·개인 주소·PEM을 Git에 적지 않는다. 누락 키는 Doppler에서 준비한다.
- API/워커는 이미지 entrypoint 대신 각각 `node dist/main.js`, `node dist/worker.js`로 시작한다.
  Job은 `node dist/cli/migrate.js`를 실행한다. Job 성공 후 Deployment를 진행한다.
  이미지 digest 기반 Job 이름을 사용하며 self-heal마다 migration을 다시 실행하지 않는다.
  완료 Job은 자동 삭제하지 않는다. 이전 버전 Job 정리와 실패 Job 재시도는 별도 검토한다.
- API의 `/ready`와 `/health`, 읽기 전용 루트 실행, migration 출력의 비밀값 비노출,
  기존 Pod와 새 migration의 동시 호환성을 확인한다.
- UI 빌드가 mock 없이 same-origin API base를 사용하는지 확인한다.
  프록시 신뢰 홉 수 1과 실제 클라이언트 IP·Secure cookie·OIDC issuer 동작은 배포 전 확인한다.
- worker는 DB 키만 받으며 Redis·초기 관리자·OIDC 암호화 키를 받지 않는다.
- API는 OIDC 캐시 TTL margin/negative/backfill과 비밀번호 재설정 TTL을 명시한다.
  이 필수 설정은 readiness만으로 검증되지 않으므로 배포 후 실제 로그인도 확인한다.

## 배포 및 갱신 확인

1. 현재 이미지 태그는 ARM64가 확인된 **main-812ed68**이다.
   API·워커·마이그레이션 Job은 동일 service digest이며 Job 이름도 갱신했다.
   UI도 같은 소스 revision의 게시된 digest로 고정했다.
2. auth 수정 결과와 위 Secret/환경변수/명령/라우팅 계약을 대조하고 필요한 선언을 수정한다.
3. auth 전용 Redis ACL은 EVAL 허용이 필요하다. INFO·SCRIPT LOAD·EVALSHA는 불필요하다.
   승인된 EVAL 권한은 `/accounts/auth` 마운트의 계정에만 허용한다. 키 격리와
   다른 스크립팅 명령 차단은 유지한다. ACL 갱신은 Git의 Pod template revision으로 반영한다.
4. Doppler 필수 키·기존 읽기 전용 서비스 토큰과 대상 DB 준비 상태를 확인한다.
   운영 DB 변경은 백업·기존 스키마/데이터 영향 확인 후 수행한다.
5. Cloudflare에 auth 레코드를 기존 검증된 ingress 대상으로 연결하고 TLS/캐시 규칙을 검토한다.
   인증·세션·OIDC 응답은 캐시하면 안 된다.
6. 준비 후에만 `root/auth.yaml`의 `spec.source.path`를
   `gitops/clusters/oci-a1/auth`로 전환한다. 공유 ClusterIssuer의 DNS-01 solver
   `dnsNames`에도 `auth.rvkang.app`을 명시적으로 추가한다. 자동 연동은 없다.
7. GitOps로 반영하고 Job, Secret, 인증서, rollout,
   UI 로그인·OIDC·Redis 격리 및 `kubectl top`/HPA metrics를 검증한다.

```sh
.local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .
kubectl kustomize gitops/clusters/oci-a1/auth
```

활성화 후 bootstrap 경로로 되돌리거나 파일을 지우는 것은 uninstall/rollback이 아니다.
prune=false이므로 기존 워크로드가 남는다. 철거는 소유권·영향을 별도로 검토한다.
롤백은 검증된 이미지/선언을 Git으로 반영하며 DB migration은 Git revert로 되돌아가지 않는다.
