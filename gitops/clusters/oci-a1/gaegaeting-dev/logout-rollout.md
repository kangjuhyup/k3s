# 사용자 UI 로그아웃 개발 배포

대상은 `https://test-ggt-ui.rvkang.app`의 `gaegaeting-dev` 사용자 UI다. source `2ca2b5e38403f952d31fed3695b8263352a0564d`는 core 1.0.3 로그아웃 릴리즈이며 integration UI 이미지 digest만 변경한다. Account/Match/Gateway/Edge/Envoy 및 관리자 UI 이미지, 마이그레이션 Job, DNS/TLS/Secret 선언은 유지한다.

로그아웃은 UI 메모리의 인증 정보를 즉시 지우고, discovery의 revocation endpoint에서 access token을 폐기한 뒤 ID token hint로 Auth 세션을 종료한다. 기존 개발 `gaegaeting-web` client의 정확한 등록 주소인 UI origin `/`로 돌아가 로그인 화면을 표시한다. Auth client·역할·사용자 데이터 변경은 없다. 연결 실패 시 로컬 로그아웃을 유지하고 오류를 표시한다.

앱 전체 빌드, Node 테스트 71개, workspace 테스트와 두 릴리즈 PR의 필수 검사가 통과했다. main CI의 integration UI job은 native packaged runtime 및 amd64/arm64 이미지 발행에 성공했다. 익명 registry tag/digest 조회와 index body SHA256 및 두 플랫폼 검증은 [이미지 증거](logout-image-verification.json)에 기록한다. 개발 배포 선언 52개 리소스·10개 workload 정적 검사가 통과했다.

기존 main SonarCloud `develop` 분석의 quality gate 실패는 이전 배포 커밋에서도 동일하다. 이번 feature/release PR Sonar 분석은 통과했다. 이 배포는 기존 전체 저장소 Sonar 항목을 해결한 릴리즈로 간주하지 않는다.

Git→Argo 반영 뒤 정확한 digest, UI Ready, Argo Synced/Healthy, 기존 serving Pod·migration Job UID 유지, HTTPS 공개 경로와 브라우저 로그인→로그아웃→재로그인을 확인한다. 롤백은 Git에서 사용자 UI 이미지만 이전 digest로 되돌리고 Argo가 반영하게 한다.
