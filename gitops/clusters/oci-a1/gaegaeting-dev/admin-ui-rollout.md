# 관리자 UI 경로 분리

관리자 UI는 `https://test-ggt-ui.rvkang.app/admin`에서 별도 이미지·Deployment·Service로 배포됐다. 관리자 Pod Ready 선행(`b655014`) 후 경로·사용자 UI 전환(`9b8860e`)을 Git→Argo로 완료했다. 7개 Deployment Ready, Argo Synced/Healthy, 기존 인증서 Ready를 확인했다. 브라우저 로그인·사진 검토 E2E, 사용자 client scope 정리 및 승인된 QA 반려견 정리까지 완료했다.

## 배포 계약

- `gaegaeting-dev` namespace, `admin-ui` Deployment/Service, UID/GID 1000, 포트 8080, read-only root filesystem. Probe는 `/admin/health`다.
- 기존 `ingress/ui.yaml` VirtualService가 HTTPS exact `/admin` 및 prefix `/admin/`만 `admin-ui:8080`으로 보낸다. rewrite는 없고 나머지 경로는 사용자 UI로 간다. 별도 DNS·TLS·Gateway·CORS·버킷 CORS 변경은 없다.
- Auth public client `gaegaeting-admin-web`: redirect/logout `/admin/login`, external interaction `/admin/interaction`, `authorization_code`/PKCE, `prompt=login`, client authentication `none`, `skipConsent=true`, 기존 dev API audience.
- 관리자 client scopes: `openid profile email tenant_roles account:read account:write`. 기존 client·사용자 역할은 유지했다.
- Doppler `gaegaeting/dev:ADMIN_UI_APP` → `UI_APP`, `ADMIN_UI_OIDC_CLIENT_ID` → `UI_OIDC_CLIENT_ID`. 나머지 `UI_OIDC_ISSUER`, `UI_API_AUDIENCE`, `UI_ACCOUNT_GRAPHQL_URL`, `UI_GATEWAY_GRAPHQL_URL`, `UI_IMAGE_STORAGE_ORIGIN`은 기존 키를 재사용한다. 별도 `gaegaeting-admin-ui-runtime` Secret에 필요한 키만 투영한다.
- `UI_APP=admin`이 basePath `/admin`을 결정한다. 추가 base-path 환경변수는 없다. `/admin/config.js`, `/admin/assets/`, `/admin/health`는 이미지가 직접 처리한다.
- 두 UI는 main `7c06eaefbfd55186e6d6503c8f95f061f3ee2b94` exact digest다. Account/Match/Gateway/Edge는 기존 `7c3733450107934f08130f0ac7d0db1a8f54c59a`를 유지하며 migration Job도 재실행하지 않았다. 버전은 [release manifest](release-images.json)를 따른다.

## 검증 및 완료 결과

익명 GHCR 조회·dualarch·실제 ARM64/UID1000/read-only smoke는 [이미지 증거](admin-ui-image-verification.json)에 기록했다. 배포 뒤 [클러스터 증거](admin-ui-cluster-readiness.json)는 backend 네 개와 Envoy Pod UID 및 두 migration Job UID/Complete 보존을 확인한다. [공개 경로 증거](admin-ui-public-readiness.json)는 HTTPS, 사용자·관리자 callback/interaction/health, 정확한 client/basePath와 사용자 `/image-review` 및 `/administrator` HTTP404를 확인한다.

- 기존 관리자 fresh PKCE 로그인·USER 승인·PET 거절/재등록/승인·사진 삭제·사용자 UI 회귀·일반 사용자 검토 거부 E2E가 통과했다. [브라우저 증거](admin-ui-e2e-verification.json).
- `gaegaeting-web`의 `tenant_roles`만 제거했다. 나머지 client 설정과 역할·세션은 유지했다. 새 일반 authorization은 interaction으로 정상 이동하고, 역할 scope 명시 요청은 `invalid_scope`로 거부됐다. 이는 제거 후 새 로그인 요청 계약 검증이며, 제거 전 발급 토큰의 소급 무효화를 의미하지 않는다. 관리자 client의 역할 scope와 ACTIVE ADMIN은 readback으로 확인했다. [scope 증거](admin-ui-scope-verification.json).
- 지정 QA pet 한 행을 owner/subject/issuer/name·사진0·feed0 확인 후 SERIALIZABLE 트랜잭션으로 삭제했다. personality는 pet 행의 text 컬럼이며 별도 연결 행은 없었다. 관리자 프로필 전체 행은 보존됐고 post-commit pet 부재와 프로필 존재를 재확인했다. [정리 증거](admin-ui-qa-cleanup-verification.json), [승인된 정리 절차](qa-pet-cleanup.md).
- 최종 7Ready/SyncedHealthy, backend·Envoy Pod UID와 migration Job UID/Complete 유지, TLS Ready를 재확인했다. autoSync/selfHeal=true, prune=false 유지.

장애 시 관리자 경로·UI 변경은 Git으로 복구하되, 사용자 client scope 제거 후 이전 UI 복구가 필요하다면 인증 호환성도 함께 검토한다. DB migration을 추가하거나 되돌리지 않는다. prod 및 기존 사용자 권한은 유지한다. 이전 `admin-ui-preparation.json`은 준비 시점의 역사적 기록이다.
