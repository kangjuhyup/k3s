# Challenge 저장소와 백엔드 배포

대상은 기존 `gaegaeting-dev` Application과 Doppler `gaegaeting/stg`다. 사용자 요청에 따라 Flutter 화면 연결은 별도 앱 작업에서 진행한다. 클라이언트 접점은 기존 `https://test-ggt-api.rvkang.app/gateway/graphql`이다.

## 저장소와 권한

- Challenge 전용 DB와 제한된 로그인 역할을 bounded GitOps Job으로 생성했다. DB명·계정·비밀번호는 `CHALLENGE_DATABASE_*`에만 둔다. PostgreSQL `sameuser` 정책을 사용하며 서버 인증은 `verify-full`이다.
- 생성용 4시간 인증서는 별도 `CHALLENGE_DB_PROVISION_TLS_*`다. Job 성공 후 인증서 provisioning 접근 규칙을 제거했고 완료 Job은 suspend 상태로 보존한다. 기존 Account·Match·Payment DB와 migration Job은 변경하지 않는다.
- `STORAGE_WALKING_BUCKET`은 별도 private 버킷이다. 익명 읽기는 거절되고 서명 PUT/GET으로 접근한다. CORS는 현재 공개 UI origin의 GET/HEAD/PUT만 허용한다. 7일 lifecycle은 `walking/uploads/`에만 적용하며, 확정 사진은 앱의 durable cleanup으로 제거한다.
- 실제 PNG 서명 업로드·제한 크기 읽기·정제·확정 객체 쓰기·서명 다운로드·익명 거절·검증 객체 삭제를 확인했다. 기존 앱의 S3 자격 증명을 사용하므로 버킷 전용 IAM 자격 증명 분리를 검증한 것은 아니다.
- Auth dev tenant에 `challenge:read`, `challenge:write` scope를 추가하고 기존 사용자/관리자 웹 client의 허용 scope에 덧붙였다. 기존 scope, client의 다른 필드, 사용자 역할은 유지했다. Flutter는 로그인 요청에 이 scope를 포함해야 한다.

## 반영 순서와 검증

앱 저장소 feature/core → dev/core → release/core/1.0.11 → main squash를 따른다. main의 실제 이미지 digest를 `release-images.json`과 manifest에 고정한다. DB migration Job(wave 0), Challenge(wave 10), Gateway(wave 20) 순서로 반영한다. 신규 subgraph는 2803 포트이며 Gateway만 접속할 수 있다. Challenge에서 Account로의 본인 보호자·반려견 조회는 명시적으로 허용한다.

기존 서비스의 이미지와 Pod UID를 비교하고 Challenge/Gateway rollout, 두 SQL migration 이력, 실제 TLS와 제한 DB 역할을 확인한다. 외부에는 `/challenge/graphql`과 내부 실적·삭제 API를 직접 라우팅하지 않는다.

`scripts/gaegaeting_challenge_smoke.mjs`는 배포된 Challenge Pod에서 stdin으로 실행하는 dev 전용 검증이다. 두 기존 합성 fixture(ordinal 998·999)의 Account subject·내부 ID·반려견 ID와 실제 tenant ID를 private runtime 입력으로 전달한다. DB에서 정확한 fixture username·issuer·가입 완료·반려견 소유 관계를 읽어서 입력을 확인하고 실제 값은 출력하거나 Git에 저장하지 않는다.

검증은 일반 사용자 scope의 짧은 내부 assertion으로 본인 산책, 좌표, 공개 코스, 다른 보호자의 따라 걷기, 실제 PNG 저장소, 일기 공개 범위, 챌린지 진행을 검사한다. 운영자 검수는 해당 합성 코스에 한해서만 서명된 내부 ADMIN assertion을 사용하며 실제 사용자 역할은 변경하지 않는다. 보호된 원본의 다른 사용자 접근과 일반 사용자의 검수는 거절되어야 한다. 시작 시 기존 진행 중 산책이 있으면 중단한다.

새로 생성한 산책 ID만 API로 삭제하고 참여 ID만 취소한다. 위치·본문·사진 레코드 삭제와 media cleanup queue 생성을 확인한다. 임시 공개 코스의 좌표는 합성 (0, 0) 부근으로 지역 검색에 실제 코스를 섞지 않는다. API 삭제가 남기는 idempotency tombstone과 취소 참여 이력은 보존한다. 사진은 서명 URL 유효 기간을 고려한 queue의 `not_before` 이후 worker가 삭제했는지 별도로 확인한다. 검증 stdout의 `privateCleanupKeys`는 운영 wrapper가 메모리/private runtime 파일로만 받고, 대화·Git에는 `proof`의 집계 결과만 남긴다.

## 복구

장애 시 Gateway 이미지와 Challenge subgraph 설정을 Git으로 이전 선언으로 되돌려 Argo CD가 반영하게 한다. 앱 롤백만으로 DB migration, Doppler 값, 버킷을 되돌리거나 삭제하지 않는다. 신규 데이터와 사진은 보존한다. 직접 kubectl patch/restart/rollout undo는 사용하지 않는다.

## 2026-10-05 배포 결과

앱 core 1.0.11 main `dfd6fca8b5297870fa9024622efd55b53c2a4488`, image workflow `37311557434`의 이미지로 배포했다. 인프라 PR #18의 `9e367874cfa5c8669b783f0c2beb41cfff5d9edc`에서 Argo CD Synced/Healthy와 migration 성공을 확인했다. Challenge와 Gateway가 Ready이며 기존 7개 서비스의 이미지·Pod UID는 그대로다. 배포 런타임은 ARM64 / Node 24.13.1이고, 주석을 제외한 live Federation SDL이 Flutter 연동 스키마와 일치한다.

실제 서버에서 두 합성 보호자의 본인 반려견 확인, 산책 GPS 저장, 코스 생성·검수·공개 조회, 다른 보호자의 코스 완주, 두 챌린지의 진행률 증가를 확인했다. 실제 private 버킷의 서명 PNG 업로드·정제·다운로드가 동작하고, 일기 본문 저장과 비공개/공개 조회 구분도 통과했다. 일반 사용자의 검수, 다른 보호자의 원본 산책/일기 조회, 무인증·scope 누락은 거절됐다.

Gateway의 실제 subject 매핑과 Account·Challenge·Payment 통합 조회도 통과했다. 외부 Gateway 무인증 접근은 401, 직접 Challenge GraphQL/health 및 내부 API는 404다. 검증용 산책은 API로 삭제해 좌표·이름·관련 코스·일기·사진 레코드를 정리했고, 검증 참여는 취소했다. 상세 집계는 [배포 검증](challenge-deployment-verification.json)에 있다.

임시 업로드 원본과 확정 PNG 모두 worker의 실제 삭제를 확인했다(객체 2개 없음, 대상 cleanup job 0개, 재시도 없음). 서명 업로드 URL 만료 후에 원본을 삭제하는 예약도 정상 동작했다. 배포 검증은 모두 완료되었다.
