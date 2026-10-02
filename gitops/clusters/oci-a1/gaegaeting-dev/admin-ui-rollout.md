# 관리자 UI 경로 분리

관리자 UI는 `https://test-ggt-ui.rvkang.app/admin`에서 별도 이미지·Deployment·Service로 제공한다. 현재는 이미지 발행을 기다리는 비활성 준비 상태다. 새 파일은 기존 Kustomization에서 참조하지 않으며 기존 앱 렌더링·라우팅은 바뀌지 않는다.

## 준비된 계약

- `gaegaeting-dev` namespace, `admin-ui` Deployment/Service, UID/GID 1000, 포트 8080. Probe는 `/admin/health`다.
- Istio는 HTTPS의 exact `/admin` 또는 prefix `/admin/`만 `admin-ui:8080`으로 전달한다. rewrite는 없고 `/administrator` 등은 기존 사용자 UI로 간다. 관리자 서버·Vite·runtime config가 `/admin` 경로를 처리해야 한다.
- 별도 DNS·TLS·Gateway·CORS·버킷 CORS 변경은 없다. 두 UI의 origin은 동일하다.
- Auth public client `gaegaeting-admin-web` 생성·readback 완료. Redirect 및 logout URI는 `/admin/login`, external interaction은 `/admin/interaction`이다. `authorization_code`, PKCE, `prompt=login`, client authentication `none`, `skipConsent=true`, 기존 dev API audience를 사용한다.
- Client scopes: `openid profile email tenant_roles account:read account:write`. 기존 사용자 client와 관리자 역할은 변경하지 않았다.
- Doppler `gaegaeting/dev:ADMIN_UI_APP` → `UI_APP`, `ADMIN_UI_OIDC_CLIENT_ID` → `UI_OIDC_CLIENT_ID`. 두 키 저장·readback 완료. 나머지 `UI_OIDC_ISSUER`, `UI_API_AUDIENCE`, `UI_ACCOUNT_GRAPHQL_URL`, `UI_GATEWAY_GRAPHQL_URL`, `UI_IMAGE_STORAGE_ORIGIN`은 기존 키를 재사용한다. 별도 `gaegaeting-admin-ui-runtime` Secret에 필요한 키만 투영한다.
- 기본 경로 `/admin`, `/admin/config.js`, asset base `/admin/`는 새 실제 이미지에서 검증해야 한다. `UI_APP=admin` 이외에 별도 base-path env가 필요한지는 앱 최종 계약에 맞춘다.

## 활성화 순서

1. 새 integration-ui/admin-ui 두 main tag@digest, 익명 GHCR pull, amd64/arm64와 실제 ARM64 경로·config·CSP smoke 증거를 받는다. 기존 Account/Match/Gateway/Edge 이미지와 두 migration Job은 그대로 유지한다.
2. `apps/base/gaegaeting/admin-ui.yaml.template`의 `${ADMIN_UI_IMAGE}`를 검증된 exact tag@digest로 치환하고 `admin-ui.yaml`로 전환한다. template은 Kubernetes 선언이 아니며 현 상태로 적용하지 않는다. base Kustomization에 Deployment/Service, `admin-ui-patch.yaml.template`도 `.yaml`로 전환해 dev Kustomization에 연결한다. release manifest/validator에 여섯 번째 서비스와 UI별 revision을 반영한다.
3. cluster Kustomization에 `admin-ui-ingress-policy.yaml`, secrets Kustomization에 `admin-ui-runtime.yaml`을 연결한다. secret writer Role의 update resourceNames에 `gaegaeting-admin-ui-runtime`을 추가한다. Git→Argo로 Secret 동기화와 관리자 Pod `/admin/health` Ready를 확인한다.
4. `apps/dev/gaegaeting/admin-ui-route-patch.yaml.template`을 `.yaml`로 전환한 뒤 cluster Kustomization의 patchesStrategicMerge에서 참조한다(기존 VirtualService가 cluster ingress에 있으므로 dev overlay에는 연결하지 않는다). 관리자 Ready 뒤 Git→Argo로 경로를 활성화한다. 새 integration-ui 이미지를 고정하고 사용자 UI의 `/image-review` HTTP404 및 관리자 버튼 제거를 확인한다.
5. 담당 에이전트가 새 관리자 fresh PKCE 로그인, 사진 검토, 일반 사용자 거부, 사용자 UI 로그인 회귀를 검증한다. 관리자 UI와 사용자 UI 저장소 키·콜백이 서로 충돌하지 않는지도 검사한다.
6. 사용자 UI 전환 확인 후에만 기존 `gaegaeting-web` client allowed scope에서 `tenant_roles`를 제거하고 다른 필드를 보존한다. 기존 세션/발급 토큰이 scope 설정만으로 무효화된다고 가정하지 않는다. 불필요한 사용자 전체 세션 취소나 역할 변경은 하지 않는다.
7. Argo Synced/Healthy, 일곱 Deployment Ready, 두 migration Job 그대로 Complete, 기존 TLS Ready를 기록한다.

배포 중 실패하면 관리자 경로·새 UI 변경을 Git으로 되돌리는 범위를 검토한다. 이 작업은 DB migration을 추가하거나 되돌리지 않는다. 사용자 client scope 제거 후 이전 사용자 UI를 복구해야 한다면 관련 인증 호환성도 함께 검토한다. prod와 기존 Auth 사용자 권한은 유지한다.
