# Auth GitOps 배포

## 개발·운영의 Auth 공유

2026-09-19 결정: 개발 서비스도 기존 `https://auth.rvkang.app`을 사용하고
Auth 안에서 개발 전용 Tenant로 구분한다. Auth namespace·Application·DB·Redis와
Doppler `auth/prd`는 공유하며 별도 개발 Auth 배포를 만들지 않는다.
각 소비 서비스는 자기 환경 Tenant의 `/t/{tenantCode}/oidc` issuer와 전용 Client를 사용한다.
[Tenant 설정과 검증](dev-prod-environments.md)을 따른다. 개발 Tenant는 관리자 API로 생성하고 조회·discovery를 확인했다. Client 등록은 후속 단계다.

## 기존 배포 구성

배포 및 auth 전용 Redis EVAL 권한 변경을 승인받았다. 원본은
`gitops/apps/base/auth/`의 앱 원본, `gitops/clusters/oci-a1/auth/`의 환경 구성과
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

1. 현재 배포 선언은 ARM64가 확인된 **v0.3.2** 이미지와 OCI index digest를 고정한다.
   소스는 `26c510c0914a05800525099e0014fcb0aa9624dd`이며
   [Auth 릴리스](https://github.com/kangjuhyup/auth/releases/tag/auth-v0.3.2)와 일치한다.
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

## 2026-09-19 릴리스 버전 정합성 수정

[Auth PR #27](https://github.com/kangjuhyup/auth/pull/27)에서 package·Release Please·
컨테이너 버전의 불일치와 릴리스 workflow 태그 패턴을 수정했다.
GitHub 릴리스는 `auth-v0.2.1`, 배포 이미지 태그는 `v0.2.1`이다.
[이미지 게시 실행](https://github.com/kangjuhyup/auth/actions/runs/35436194086)이 성공했고,
두 이미지의 linux/arm64 manifest와 소스 revision을 GHCR에서 직접 확인했다.
기존 운영 소스 `c03573f` 이후 변경은 릴리스·버전·테스트 관련이며 앱과 DB migration 소스 변경은 없다.

| 이미지 | OCI index digest |
| --- | --- |
| auth-service | `sha256:d3a9a7aa642bc150a34dd98545affd68460e12a6283fc955a27cdf9619d33889` |
| auth-ui | `sha256:09bfb44892240f6fd6612495e92408c5a47f9b335d7560d723b271e1f36a242d` |

API·워커·migration은 동일 service digest를 사용한다. 새 Job 이름은
`auth-migrate-d3a9a7aa642b`이며 성공한 뒤 Deployment가 갱신된다.
Auth 공유 주소와 개발 Tenant는 유지한다.

최종 릴리스 digest를 고정한 배포 커밋 `1856cd0` 반영 후 migration Job의 `succeeded=1`, API·UI·워커의
새 digest 및 Ready 상태를 확인했다. UI HTTP 200, 관리자 로그인, 개발 Tenant 조회,
초대 전용 가입 정책과 OIDC discovery issuer 검증도 통과했다.
실제 OIDC Client의 authorization/token 발급 및 교차 Tenant 격리 QA는 별도다.

Argo CD operation은 `Succeeded`, health는 `Healthy`다. 자동 prune을 끈 정책에 따라
이전 완료 Job `auth-migrate-ddc1b1826f80`과 `auth-migrate-68eb965c5377`이 남아
Application sync 상태는 `OutOfSync`다. 새 선언 리소스는 동기화됐고 이 차이는
이전 Job의 `requiresPruning` 두 건이다.
기존 Job을 직접 삭제하거나 자동 prune 범위를 넓히지 않았다.

릴리스 전용 CI에서 발견한 Yarn 초기화 순서와 source revision 라벨은
[PR #28](https://github.com/kangjuhyup/auth/pull/28),
[PR #29](https://github.com/kangjuhyup/auth/pull/29)로 수정했다.
최종 릴리스 실행 전체가 성공했으며 두 이미지 모두 `latest`와 `v0.2.1`의
index digest가 같다. 이미지의 source revision과 기존 `auth-v0.2.1` 태그는
`a557a42bf2733638a50e634dd0280e6b301a6319`를 유지한다.
최종 digest의 새 Pod 3개 모두 Ready·재시작 0회이며 관리자·Tenant 검증도 재실행했다.

## 2026-10-05 Kakao 가입 지원 v0.3.0

[Auth PR #36](https://github.com/kangjuhyup/auth/pull/36)의 Kakao 외부 identity 가입,
고정 OAuth callback, 브라우저 바인딩, 서비스 인증 provisioning, IdP secret 암호화와
두 schema migration을 소스 `91efadc6462928c29ca262ca95df6a001ae1f145`로 릴리스했다.
[게시 실행](https://github.com/kangjuhyup/auth/actions/runs/37311209257)은 전체 검증 후
linux/amd64·linux/arm64 이미지를 게시했고 두 이미지 모두 `latest`, `0.3.0`, `v0.3.0`
태그의 OCI index가 일치한다.

| 이미지 | OCI index digest | linux/arm64 manifest digest |
| --- | --- | --- |
| auth-service | `sha256:fc84b42597983c0b50df21879d64c3c0088300f2e09c954bc32439610aae4278` | `sha256:5b8bf3d105402a599df0c089ffb34d91ef5914d6650b46253d20380bc5462761` |
| auth-ui | `sha256:bbcec5780fc43f6bc3565bdc36756c61324d9005c41efe12c1a1383c5d104c16` | `sha256:e31f0c8f9a18f4b5c6f2a8e67472ca08793ec1e119380bbfb39661e0b9c4ae94` |

API·worker·migration은 같은 service index를 사용하며 새 Job 이름은
`auth-migrate-fc84b4259798`이다. Job에는 기존 `JWKS_ENCRYPTION_KEY`를 주입해 schema
migration 뒤 legacy IdP secret을 같은 키로 보호한다. API에는 Doppler `auth/prd`의
`HTTP_CORS_ORIGINS`를 `auth-runtime` Secret으로 전달한다. 값 자체는 Git에 저장하지 않는다.

배포 직전 DB 확인은 provider 2개, 활성 provider 0개, 활성 plaintext secret 0개이며
`gaegaeting-dev` Kakao provider 2는 비활성 상태다. 따라서 migration과 RollingUpdate가
끝날 때까지 기존 활성 외부 로그인을 혼합 버전이 처리하는 경로는 없다. GitOps 반영 후에는
migration 성공, 모든 ready workload의 새 digest, health/readiness, exact-origin credentialed
CORS와 provider 비활성을 확인한다. Kakao provider 활성화는 이 배포와 분리된 후속 작업이다.

## 2026-10-05 migration runner 복구 v0.3.1

v0.3.0의 `auth-migrate-fc84b4259798` Job은 schema migration을 적용한 뒤 legacy IdP
secret 보호 단계에서 실패했다. MikroORM의 `allowGlobalContext: false` 기본 정책에서
global `orm.em.find()`를 호출한 것이 원인이며, Argo CD는 sync wave `-10`에서 멈춰
기존 v0.2.1 API·UI·worker를 Ready 상태로 보존했다. Kakao provider 2도 비활성 상태를
유지했으며 Job 우회나 global context 허용은 적용하지 않았다.

[Auth PR #37](https://github.com/kangjuhyup/auth/pull/37)은 소스
`c1484a190d67d57fc155719a5b7f605215569a95`에서 migration-time secret 보호에
`orm.em.fork()`를 사용하도록 수정한다. 기본 `runMigrations()` 경로를 PostgreSQL 16에서
실행해 schema 적용, plaintext secret backfill·복호화, 이미 적용된 schema 재시도와
ciphertext 멱등성을 검증했다. 같은 build의 `dist/cli/migrate.js`도 이미 schema가 적용된
별도 DB에서 두 번 연속 exit 0을 확인했다. [릴리스 실행](https://github.com/kangjuhyup/auth/actions/runs/37314856255)의
verify rerun은 service 전체 테스트, UI 전체 테스트, architecture 검사와 service·interaction UI·
admin UI build를 통과했다.

해당 실행은 최종 성공했고,
두 index의 `latest`, `0.3.1`, `v0.3.1` 태그와 양쪽 architecture의 source revision이
`c1484a190d67d57fc155719a5b7f605215569a95`로 일치한다.

| 이미지 | OCI index digest | linux/arm64 manifest digest |
| --- | --- | --- |
| auth-service | `sha256:609d4ca6a06fc142000b6d1bae3119e14d17db452438d6ddc24202c088903f76` | `sha256:6034ff76c9d03896d4d9fd0daff120f81e0b7b7e7b63345f07bf3852b87c08f6` |
| auth-ui | `sha256:820a6a884d1b49ad2b75f9770a51def9c85cb5ed2cc545b74d8dfc3abf026241` | `sha256:78ff3be07f732137ed4571757fa422c521e46eca6e5600300b799381cd08fdbe` |

API·worker·migration은 같은 service index를 사용하며 새 digest 기반 Job 이름은
`auth-migrate-609d4ca6a06f`이다. 실제 Argo rollout, readiness, CORS와 provider 비활성
확인 전에는 배포 완료로 간주하지 않는다.
배포 직전 DB 재확인 결과 provider는 2개, 활성 provider는 0개이며 Kakao provider 2는
비활성 상태다.

## 2026-10-07 GitHub hosted runner / native URI v0.3.2

사용자가 self-hosted 대신 GitHub 기본 runner를 승인했다. Auth PR39의 main
`26c510c0914a05800525099e0014fcb0aa9624dd`에서 공식 Release run37573245396이
ubuntu-24.04에서 성공했다. 서버 1781개 테스트와 architecture/UI/build 검증을
통과했고 QEMU/buildx로 amd64/arm64 이미지를 발행했다. Native custom URI
validator 수정은 PR38로 통합되어 있다.

| image | official OCI index digest |
| --- | --- |
| auth-service / worker / migration | `sha256:78a445d86e46d5c61771eb21a3e042e29568d3a6a08c4d684f6c045545c089d1` |
| auth-ui | `sha256:b034d47f96853f40ba621f89b93d2e5493053967c4544692c612809e94a270fa` |

Anonymous pull로 index/manifest/config SHA와 양쪽 platform의 source revision을
다시 검증했다. 새 immutable migration은 `auth-migrate-78a445d86e46`이다.
기존 완료/실패 Job과 prune=false, HPA, TLS/CA, secrets 및 bootstrap 경계를
보존한다. 이 문단은 배포 선언/발행 증거이며 실제 rollout과 gaegaeting-dev의
public native client `gaegaeting-mobile` 등록/PKCE 검증은 별도 실행 결과로 기록한다.
기존 다른 tenant/client/key/credential은 변경하지 않는다.
