# Payment 1.0.0 개발 API 배포

2026-10-06 사용자의 개발 API 실제 배포 승인에 따라 기존 `gaegaeting-dev`의 Payment serving image를 실제 교체하고 검증을 완료했다. production Gaegaeting, Flutter, Gateway/config, 스토어 활성화·Sandbox/실제 유료 결제·키 발급/회전/삭제는 수행하지 않았다. 이전 `docs/payment-mobile-release-readiness.md`의 배포 금지는 준비 dispatch 당시 기록이며 이번 개발 배포에 한해 승인 범위가 갱신됐다.

## 소스와 이미지

- Source PR [175](https://github.com/kangjuhyup/gaegaeting/pull/175): Payment 전용 수정 → `dev/payment` 정상 merge.
- Release PR [179](https://github.com/kangjuhyup/gaegaeting/pull/179): `release/payment/1.0.0` → main squash `a3c16411cea8f65a1479dfdc065d974d530f7bbf`, tag `payment/v1.0.0`.
- main → dev 동기화 PR [182](https://github.com/kangjuhyup/gaegaeting/pull/182): 정상 merge `ca030f3cfe34211074e5f3feb2ac989623e9c725`. shared dev reset/force push 없음.
- Publisher [run 37418365262](https://github.com/kangjuhyup/gaegaeting/actions/runs/37418365262): event=push, exact main SHA. 같은 SHA의 37418403570/37418398260은 동기화 PR 검증이며 게시 실행이 아니다.
- Serving image: `ghcr.io/kangjuhyup/gaegaeting/payment:sha-a3c16411cea8f65a1479dfdc065d974d530f7bbf@sha256:53822d4f371fa03e23755dbad60f7ba1c7da922ad48814913ace24a7ff9df48a`.
- CI artifact의 service/revision/digest와 익명 GHCR tag/digest/index body 및 AMD64/ARM64를 대조했다. [이미지 증거](payment-refund-history-image-verification.json).

변경은 Apple notification history의 Sandbox 30일 / Production 180일을 adapter/worker 양쪽에 적용하고 기간을 넘긴 cursor를 진행하지 않는 것이다. 양 스토어 false 예시, 오프라인 환경 preflight와 출시 인계 문서를 함께 반영했다. core·다른 도메인 runtime·스키마·migration 변경 없음.

## 검증

- Node 24.13.1 / pnpm 10.34.5: `pnpm install --frozen-lockfile`, `pnpm --filter payment... build`, `pnpm --filter payment exec tsc -p tsconfig.spec.json --noEmit` 성공.
- DB 미주입 실행: Payment 65 pass / 44 skip. `node --test scripts/payment-environment-preflight.test.mjs scripts/payment-edge-contract.test.mjs`: 7 pass.
- 격리 PostgreSQL 16.15와 pin Node 24.13.1을 같은 Docker VM 시계에서 실행: **8 suites / 109 tests pass**. 스토어는 fake 응답이며 실제 결제가 아니다. 임시 컨테이너는 제거했다.
- 최초 Mac Node ↔ Docker DB 실행은 22/23 tests 실패. 단건 진단에서 다른 소유권/SKU 조건은 일치했지만 DB createdAt가 합성 purchase 시각보다 50~51ms 앞섰다. 동일 Docker 시계 재검증으로 해결했으며 서버 구매 시간 검증을 완화하거나 개발 DB를 교체하지 않았다.
- Doppler `gaegaeting/stg` 주입 disabled preflight: 16/16 pass, 스토어 API 호출 없음.
- source PR/release PR: branch-policy, service-verification, 8 image checks, GitGuardian/SonarCloud 성공. 실제 이미지 build/publication은 Payment만 선택됐다.
- 인프라 Python 3.12.9: `scripts/gaegaeting_validate.py --release --kubectl .../kubectl-1.36.4` 성공, Python compile / `git diff --check` 성공.

재현 가능한 스크립트:

```sh
python scripts/payment_release_database_verify.py --source /Users/kangjuhyup/orca/workspaces/gaegaeting/결제
python scripts/payment_dev_public_verify.py
# 승인된 기존 사용자 세션이 있는 경우에만 사용. 값은 CLI에 전달하지 않는다.
python scripts/payment_dev_public_verify.py --bearer-file "$PAYMENT_QA_BEARER_FILE"
```

위 `python`은 확인된 Python 3.12.9 환경에서 실행한다. 선택적인 `PAYMENT_QA_BEARER_FILE`은 담당자가 승인된 기존 파일 경로를 주입하는 실행 변수이며 현재 세션 파일이 준비됐다는 뜻이 아니다. 첫 명령은 이미 설치된 source 의존성과 캐시된 공식 PostgreSQL 16.15 / 저장소 Dockerfile의 exact Node digest를 사용한다. 개발 DB 연결이나 스토어 접속 없이 새로운 격리 테스트 DB만 만들고 종료한다. 공개 API 검사에서 redirect는 따라가지 않으며 응답 body·토큰·사용자 거래 식별자는 출력하지 않는다.

## migration·secret·배포 gate

Serving image만 갱신하며 `payment-migration-75c5a2564ff3`의 이름·UID·완료 상태·이미지와 `migrationImages` 전체를 유지한다. 기존 migration 실행 source는 `75c5a2564ff3d87f8585672cd86c4da7422eb5d0`, 명령 `node dist/src/migrations/migrate.js`, history `Payment1791158400000` / `1791158400000` 한 건이다. 재실행/DDL/rollback migration 없음.

배포 전 live: Payment/Gateway health 200, Ready 1, 14 payment 테이블(이력 포함), 3상품/6offer, PostgreSQL verified TLS. 두 스토어 false와 worker true. 읽기용 합성 내부 principal의 wallet/transactions 성공, 미인증·잘못된 audience·scope 없는 요청 및 read-only principal의 mutation 거절. Gateway→Payment의 실제 SDL에 5문서 유효. 공개 Gateway 미인증/위조 owner 헤더 401, 비공개 Payment 경로 404.

비밀 원본은 `gaegaeting/stg`, workload Secret은 `gaegaeting-dev/gaegaeting-payment-runtime`이다. 기존 `INTERNAL_AUTH_ASSERTION_SECRET`과 `PAYMENT_PROOF_ENCRYPTION_KEY`를 발급/회전/삭제하지 않았다. 값 출력 없이 배포 전후 동일성과 Doppler projection을 비교한다. 앱 `packages/integration-ui/.dart-define.stg.example.json` 및 gitignored stg 설정의 `STORE_PURCHASES_ENABLED=false`를 읽기 확인했으며 앱 파일은 수정하지 않았다.

GitOps [PR22](https://github.com/kangjuhyup/k3s/pull/22)가 main squash `03aeb7689c8b11966b2fff2481f0f9dd8a192278`로 반영됐다. Argo 자동 동기화로 exact new Payment image / Ready 1을 확인했고 동일 revision에서 `Synced/Healthy`다. 직접 kubectl 배포·override·수동 sync는 수행하지 않았다.

배포 후 live 검증:

- Payment/Gateway health 200, Gateway→Payment의 5 SDL문서 유효, 합성 내부 wallet/transactions 조회 성공.
- 스토어 false / worker true, 양 catalog `STORE_UNAVAILABLE`. 미인증/잘못된 audience `UNAUTHENTICATED`, scope 없음 및 read-only principal의 prepare mutation `FORBIDDEN`.
- **실제 새 image의 compiled adapter/worker**를 읽기 검증 child process에서 mock port로 실행해 31일 Sandbox gap을 거절·cursor 보존하고 Production에서는 처리함을 확인했다. 실제 스토어/DB write를 수행한 테스트가 아니다.
- 동일 Payment migration Job UID `16518911-dd26-4e7d-8203-72d5e6552832`, 기존 이미지/Complete/history 한 건 보존. 테이블 14 / 상품3 / offer6 / purchase·wallet·job 0, verified TLS.
- Doppler/runtime 일치 및 기존 내부 assertion/proof 암호화 키 배포 전후 동일성을 값 출력 없이 확인했다. 스토어 API 호출·유료 결제·DDL 0.
- 공개 Gateway 미인증/위조 owner 헤더 401과 비공개 Payment 경로 404를 새 배포 후 재확인했다. 실제 native 사용자 Bearer 및 인증된 Gateway resolver는 아직 미검증.

집계 증거: [배포 검증 JSON](payment-refund-history-deployment-verification.json). 보호된 실행용 경로는 기존 k3s checkout `.local/payment-dev-api-verify.py`와 `.local/payment-dev-{before,after}-public.json`이며 키 비교용 원본 baseline은 보호된 `.local/payment-dev-before.json`에만 둔다. JSON/보고서에는 key 값이나 fingerprint를 넣지 않았다.

## 남은 외부 검증과 롤백

현재 인증된 native 사용자 Bearer 검증은 없다. 내부 assertion 합성 읽기·SDL·공개 미인증 차단은 실제 로그인 E2E를 대신하지 않는다. Auth 담당의 `gaegaeting-dev` / `gaegaeting-mobile` native 등록과 승인된 기존 QA 세션이 준비되면 공개 스크립트로 wallet/transactions 및 양 disabled catalog를 확인한다. 원본 사용자 Bearer/관리 token/영수증·구매 token은 답변·소스·일반 artifact에 저장하지 않는다.

preparedId 유실 cross-device 복구, 계정 삭제/법정 거래 보관 정책, Apple SendConsumptionInformation 및 별도 승인 Sandbox 구매/환불 검증은 기존 출시 준비 문서에 남아 있다. 이번 disabled API 개발 배포가 판매 준비 완료를 의미하지 않는다.

롤백 조건: 새 Payment Ready 실패, 잔액 조회/권한 거절 회귀, compiled 기간 정책 불일치, 양 store false 위반 또는 migration/비밀 보존 실패. Git에서 **Payment serving image와 해당 release entry만** 이전 `sha-75c5a2564ff3d87f8585672cd86c4da7422eb5d0@sha256:1371157b93112cecb6e882a23b9528db91e567c2bc1a84db9d2b59cc57fb4d1e`로 되돌리고 Argo CD로 반영한다. 다른 도메인/완료 migration/거래 데이터/원래 key를 되돌리거나 삭제하지 않는다. 직접 kubectl patch/rollout undo는 사용하지 않는다.

담당 터미널 `term_d0391ad1-b52b-452f-89c6-e699725b2efd`는 외부 사용자 소유이므로 완료 후 닫지 않는다.
