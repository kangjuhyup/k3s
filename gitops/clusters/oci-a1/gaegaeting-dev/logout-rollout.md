# 사용자 UI 로그아웃 개발 배포

대상은 `https://test-ggt-ui.rvkang.app`의 `gaegaeting-dev` 사용자 UI다. source `2ca2b5e38403f952d31fed3695b8263352a0564d`는 core 1.0.3 로그아웃 릴리즈이며 integration UI 이미지 digest만 변경한다. Account/Match/Gateway/Edge/Envoy 및 관리자 UI 이미지, 마이그레이션 Job, DNS/TLS/Secret 선언은 유지한다.

로그아웃은 UI 메모리의 인증 정보를 즉시 지우고, discovery의 revocation endpoint에서 access token을 폐기한 뒤 ID token hint로 Auth 세션을 종료한다. 기존 개발 `gaegaeting-web` client의 정확한 등록 주소인 UI origin `/`로 돌아가 로그인 화면을 표시한다. Auth client·역할·사용자 데이터 변경은 없다. 연결 실패 시 로컬 로그아웃을 유지하고 오류를 표시한다.

앱 전체 빌드, Node 테스트 71개, workspace 테스트와 두 릴리즈 PR의 필수 검사가 통과했다. main CI의 integration UI job은 native packaged runtime 및 amd64/arm64 이미지 발행에 성공했다. 익명 registry tag/digest 조회와 index body SHA256 및 두 플랫폼 검증은 [이미지 증거](logout-image-verification.json)에 기록한다. 개발 배포 선언 52개 리소스·10개 workload 정적 검사가 통과했다.

기존 main SonarCloud `develop` 분석의 quality gate 실패는 이전 배포 커밋에서도 동일하다. 이번 feature/release PR Sonar 분석은 통과했다. 이 배포는 기존 전체 저장소 Sonar 항목을 해결한 릴리즈로 간주하지 않는다.

## 실제 배포·검증 결과

GitOps PR #1이 main `3e7fdec584bbe23c07bc841f7a3969a1a52c3e43`에 병합되어 이미 배포됐다. 인수 시 live UI exact digest 일치, 7개 Deployment Ready, Argo Synced/Healthy를 다시 확인했다. 기존 기준선과 비교해 UI 이외 6개 Gaegaeting Deployment 이미지·Pod UID 및 migration Job UID/Complete가 보존됐다. 최초 배포 담당이 확인한 UI 외 10개 serving Pod·Job 보존 증거는 [배포 증거](logout-deployment-verification.json)에 별도로 기록한다. 운영 변경이나 중복 rollout은 수행하지 않았다.

HTTP PKCE 로그인 → gateway 200 → access token 폐기 → gateway 401 → Auth 세션 종료 → 등록된 UI `/` 복귀 → 재로그인 interaction 요구가 통과했다. token/discovery/revocation fetch에는 쿠키를 보내지 않고 navigation/interaction에만 보내는 조건에서도 통과했다. 이는 HTTP 검증이며 실제 Chrome E2E 완료를 뜻하지 않는다.

## 미해결: 기존 Chrome SSO 로그아웃 확인 오류

실제 Chrome에서는 로그아웃 버튼과 로컬 인증 상태 삭제 뒤 Auth의 `Yes, sign me out` 제출 시 `invalid_request / xsrf token invalid`가 재현됐다는 인계를 받았다. 브라우저 E2E는 미완료다.

배포된 Auth v0.2.1 / oidc-provider 9.6.0 코드에서 이 오류는 제출한 xsrf와 `session.state.secret` 불일치를 의미한다. 로그아웃 확인 화면을 만들 때 state가 교체된다. 오래된 확인 폼 또는 중복 로그아웃 요청, 세션 저장소 일관성을 조사해야 하지만 어느 것이 실제 원인인지는 아직 확정하지 않았다. 현재 Auth는 단일 Pod, hybrid adapter, trust proxy 활성 상태이며 쿠키 키는 존재한다. 단일 Pod 확인으로 과거 다중 Pod의 일관성을 입증할 수 없다. 제한된 최근 로그에 오류 문자열이 없다는 사실도 브라우저 오류를 부정하지 않는다.

현재 Chrome 창은 존재하지만 Orca Computer Use의 접근성 읽기가 `permission_denied`로 차단된다. 권한 조회는 granted이며, CUA 연결 표면도 구성되지 않았다. 이전 확장 프로그램 창 차단과 구분되는 현재 blocker다. 사용자에게 macOS 손쉬운 사용 권한을 껐다 켜고 확장 창을 닫도록 요청했다.

접근 복구 후 기존 세션과 새 fixture 세션을 비교하고, end_session GET 중복 여부·confirm POST의 폼/쿠키 일치·세션 state 저장/조회 흐름을 값 노출 없이 확인한다. 브라우저 요청이 정상이면서 저장값이 달라질 경우 Auth 세션 adapter를, 중복 navigation이면 해당 요청 발생 경로를 수정 대상으로 삼는다. 원인 확정 전 CSRF 검증 우회, 공유 세션·키 삭제, Auth 재배포는 하지 않는다. [인수 재검증](logout-handover-verification.json)에 확인 사실과 한계를 기록한다.

롤백이 필요하면 별도 판단 후 Git에서 사용자 UI 이미지만 조정하고 Argo가 반영하게 한다. 이번 인수에서는 이전 이미지 복원이나 재배포를 수행하지 않았다.
