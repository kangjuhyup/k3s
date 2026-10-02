# 서울 dev fixture 1000명 생성

승인 범위: 서울25구×40명, 가상 남녀 각500명, 신규 username prefix `qa_seoul_20261002_`와 ordinal0001..1000, 프로필·pet1·위치. 앱·이미지·rollout·migration·권한 변경 없이 data-only 실행한다. manifest SHA256 `7ae584c6558fd5926a12d3865da0bf1f6e19bcea7d5b8d0cc75a299f85811a2f` 및 mode0600을 확인한다. 위치와 개인별 합성 fixture/자격 증명은 Git에 넣지 않는다.

## 실행 및 복구

- 기존 Auth 사용자 API 응답과 Account/Match의 모든 기존 행에 대한 private row fingerprint를 보관한다. Auth prefix 충돌은 실행을 중단한다. 백엔드 PodUID/JobUID도 기준을 보관한다.
- `scripts/gaegaeting_fixture_worker.mjs`는 현재 배포된 Account/Match Node 환경에서 stdin으로 실행한다. 입력은 최대25명의 synthetic fixture, memory/private0600 고유 랜덤 비밀번호와 실제 Auth tenant ID다. 외부 로그인 subject와 Account 내부 ULID를 합성하거나 서로 치환하지 않는다.
- Account는 실제 로컬 `registerAccount` GraphQL을 호출한다. 기존 mock verifier와 Auth provisioning/idempotency 및 account_signup/external_user_subject 완료 경로를 그대로 사용한다. 이 signup 경로는 별도 eligibility handoff를 필요로 하지 않으며, mapping tenant_id는 `AUTH_ISSUER`다.
- 일반 범위(`account:read/write`, `match:read/write`, roles=[])의 짧은 내부 assertion으로 신규 fixture의 createProfile/createPet/setCurrentLocation API를 호출한다. 운영자가 기존 서비스 credential을 현재 Pod 안에서만 소비하며 외부로 출력하지 않는다. ADMIN·사진·review·notification 호출은 없다.
- API가 받지 않는 location city/district만 새 fixture 내부 ID와 좌표 일치 확인 후 채운다. main_area는 삽입하지 않는다. 기존 사용자는 대상 집합에 포함하지 않는다.
- 등록은 순차, 시작 간격 최소1.3초(최대약46명/분)다. Auth token/provisioning 요청은 각각 이 속도 이하이며 설정·rate limit은 변경하지 않는다. 25명 단위로 checkpoint를 저장하고 실패 시 부분 성공을 저장한 채 중단한다. 제한/5xx를 숨기고 계속 생성하지 않는다.
- account_signup은 DI HMAC/idempotency로 재조회한다. profile 존재 시 값 일치, pet은 owner+정확 이름/설명 및 최대1행, location은 좌표/구 일치 확인 후 재사용한다. 랜덤 비밀번호는 최초 checkpoint에만 생성하고 재실행으로 기존 비밀번호를 바꾸지 않는다. 단일 실행 file lock으로 동시 중복 생성을 방지한다.
- 최초3명 Ready 후 fixture0001 로그인 정보를 private0600 파일로만 인계한다. 이후 브라우저 QA는 신규 fixture만 사용하므로 fixture의 feed 생성은 허용된 검증 효과다. 기존 회원의 profile/pet/location/feed는 바뀌면 실패다.
- 최종 Auth/Account/profile/pet/location 1000 및 구별40, 무ADMIN, 무사진, 기존 행 fingerprint 불변, migration/PodUID 보존을 검사한다. cleanup manifest에는 신규 IDs/mapping만 private0600으로 저장하고 비밀번호는 별도 private checkpoint에 둔다. 공개 기록은 집계와 불변 조건 결과만 남긴다.
