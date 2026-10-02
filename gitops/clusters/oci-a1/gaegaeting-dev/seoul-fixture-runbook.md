# 서울 dev fixture 1000명 생성

승인 범위: 서울25구×40명, 가상 남녀 각500명, 신규 username prefix `qa_seoul_20261002_`와 ordinal0001..1000, 프로필·pet1·위치. 앱·이미지·rollout·migration·권한 변경 없이 data-only 실행한다. manifest SHA256 `7ae584c6558fd5926a12d3865da0bf1f6e19bcea7d5b8d0cc75a299f85811a2f` 및 mode0600을 확인한다. 위치와 개인별 합성 fixture/자격 증명은 Git에 넣지 않는다.

## 실행 및 복구

- 기존 Auth 사용자 API 응답과 Account/Match의 모든 기존 행에 대한 private row fingerprint를 보관한다. Auth prefix 충돌은 실행을 중단한다. 백엔드 PodUID/JobUID도 기준을 보관한다.
- `scripts/gaegaeting_fixture_worker.mjs`는 현재 배포된 Account/Match Node 환경에서 stdin으로 실행한다. 입력은 최대25명의 synthetic fixture, memory/private0600 고유 랜덤 비밀번호와 실제 Auth tenant ID다. 외부 로그인 subject와 Account 내부 ULID를 합성하거나 서로 치환하지 않는다.
- Account는 실제 로컬 `registerAccount` GraphQL을 호출한다. 기존 mock verifier와 Auth provisioning/idempotency 및 account_signup/external_user_subject 완료 경로를 그대로 사용한다. 이 signup 경로는 별도 eligibility handoff를 필요로 하지 않으며, mapping tenant_id는 `AUTH_ISSUER`다.
- 일반 범위(`account:read/write`, `match:read/write`, roles=[])의 짧은 내부 assertion으로 신규 fixture의 createProfile/createPet/setCurrentLocation API를 호출한다. 운영자가 기존 서비스 credential을 현재 Pod 안에서만 소비하며 외부로 출력하지 않는다. ADMIN·사진·review·notification 호출은 없다.
- Account/Match 모두 NODE_ENV=development, 확정 dev issuer 입력과 현재 DATABASE_NAME이 Doppler dev DB identity와 일치해야 실행한다. Match runtime에는 AUTH_ISSUER가 없으므로 임의 환경변수/배포 추가 없이 이 guard로 대상 환경을 확인한다.
- API가 받지 않는 location city/district만 새 fixture 내부 ID와 좌표 일치 확인 후 채운다. main_area는 삽입하지 않는다. 기존 사용자는 대상 집합에 포함하지 않는다.
- 등록은 순차, 시작 간격 최소0.9초(최대약67명/분)다. Auth token/provisioning 요청은 각각 이 속도 이하이며 설정·rate limit은 변경하지 않는다. 25명 단위로 checkpoint를 저장하고 실패 시 부분 성공을 저장한 채 중단한다. 제한/5xx를 숨기고 계속 생성하지 않는다.
- account_signup은 DI HMAC/idempotency로 재조회한다. profile 존재 시 값 일치, pet은 owner+정확 이름/설명 및 최대1행, location은 좌표/구 일치 확인 후 재사용한다. 랜덤 비밀번호는 최초 checkpoint에만 생성하고 재실행으로 기존 비밀번호를 바꾸지 않는다. 단일 실행 file lock으로 동시 중복 생성을 방지한다.
- 최초3명 Ready 후 fixture0001 로그인 정보를 private0600 파일로만 인계한다. 이후 브라우저 QA는 신규 fixture만 사용하므로 fixture의 feed 생성은 허용된 검증 효과다. 기존 회원의 profile/pet/location/feed는 바뀌면 실패다.
- 최종 Auth/Account/profile/pet/location 1000 및 구별40, 무ADMIN, 무사진, 기존 행 fingerprint 불변, migration/PodUID 보존을 검사한다. cleanup manifest에는 신규 IDs/mapping만 private0600으로 저장하고 비밀번호는 별도 private checkpoint에 둔다. 공개 기록은 집계와 불변 조건 결과만 남긴다.

## 2026-10-02 실행 결과

1,000명 생성 및 대조 완료. Auth ACTIVE/가입/issuer-subject mapping/profile/pet/location 각각1,000, 서울25구각40, 남녀각500이다. Auth contact/direct role/group 및 seed 사진은 모두0, main_area삽입0이다. 대표25명에 실제 추천 제외 조건을 적용한 후보 수는 최소279였다. 사용자 브라우저 fresh PKCE 및 추천카드2개/대상프로필·pet 조회도 통과했다.

기존 Auth6 사용자 응답, Account28행·Match12행 fingerprint가 모두 동일하다. 증가한 feed1/items2는 owner/target 모두 신규 fixture인 브라우저 QA분임을 확인했다. Gaegaeting7개 Ready, 이미지·PodUID·migration JobUID 보존, Argo SyncedHealthy를 확인했다. Auth는 기존Pod를 유지하며 기존HPA가1개를 추가해2replica가 됐고 수동scaling/rollout은 없었다.

집계 증거는 [seoul-fixture-verification.json](seoul-fixture-verification.json)이다. 개별 cleanup mapping과 비밀번호 checkpoint 및 fixture0001 QA 로그인 파일은 로컬 mode0600 비Git 파일에만 있다. QA 세션 폐기는 root의 직전 보호요청200·폐기준비 통지를 기다리며 아직 수행하지 않았다.
