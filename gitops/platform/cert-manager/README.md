# cert-manager: 자동 TLS 발급·갱신 기반

사용자 선택은 외부 TLS 인증서 자동 발급·갱신이다. 공통 설치와 함께 [Argo CD 공개 도메인](../../../docs/runbooks/argocd-public-domain.md)의 Cloudflare DNS-01 ClusterIssuer·Certificate 및 Doppler 토큰 매핑을 준비했다. 환경 입력에서 설치를 활성화했으며 실제 배포·인증서 발급은 아직 검증하지 않았다. 토큰·DNS 준비 없이 설치만으로 연결이 완료되지 않는다.

- [base.values.json](base.values.json): controller/webhook/cainjector 각 1 replica, ARM64/Linux, image digest, 요청량 합계 200m CPU / 320Mi RAM.
- [versions.json](versions.json): chart `v1.21.1`, SHA256, Helm `v4.2.4`, Kubernetes 지원 범위 `1.33~1.36`.
- [환경 입력](../../clusters/oci-a1/cert-manager.json): `enabled`, `reviewed` 두 boolean. Argo CD 도메인 연결을 위해 true.
- [생성기](../../../scripts/cert_manager_gitops.py): 기존 root 생성기에 연결한 Application·AppProject·namespace. 생성물은 Git 대상.
- [로컬 검사](../../../scripts/cert_manager_validate.py): 공개 고정 chart만 렌더링. 실제 클러스터나 ACME/DNS에 접근하지 않음.

공식 [Helm 설치](https://cert-manager.io/docs/installation/helm/)·[지원 버전](https://cert-manager.io/docs/releases/)을 2026-09-09 확인했다. legacy Helm repository `https://charts.jetstack.io`를 Argo CD Helm source로 사용한다. chart SHA256은 `c27101f3f3e2349fb4a9e704316105bf7b52ad73b8c8257d3498ef7f2f6a4adc`다. 로컬 검사는 다운로드 파일을 확인하며 Argo CD의 매 sync마다 archive hash를 강제하는 공급망 검증은 아니다.

네 이미지(controller/webhook/cainjector/acmesolver)의 공개 Quay manifest index에서 `linux/arm64`를 확인하고 digest를 고정했다. DNS-01 계획에서는 acmesolver Pod를 사용하지 않지만 차트가 controller 인자에 넣는 이미지까지 고정한다. API 확인용 Helm hook Job은 비활성화하여 Argo CD PostSync 수명주기와 별도 Certificate 준비 단계가 서로 기다리지 않게 했다.

namespace·CRD(6개)·RBAC/Service → Deployment(wave 10) 순서다. CRD Established health는 기존 Argo CD 설정을 사용한다. webhook readiness와 API admission 준비는 같은 의미가 아니므로 실제 설치 후 **Issuer 생성 전 API 검사**가 필요하다. 여러 Application의 root wave만으로 이 준비를 보장하지 않는다.

CA injector가 관리하는 webhook `caBundle`만 drift 비교/동기화에서 제외한다. webhook failurePolicy는 Fail이다. Kubernetes 기본 user role로 cert-manager 권한을 자동 확장하는 aggregateClusterRoles는 끄고, leader election은 `cert-manager` namespace로 제한했다. chart가 제공하는 controller의 cluster-wide Secret 접근 권한은 남으므로 고신뢰 관리자 구성요소다. 이는 개별 앱에 인증서 발급 권한을 부여하는 정책이 아니다.

auto prune=false, Application finalizer 없음, namespace Prune/Delete 보호, CRD의 Helm keep, Certificate Secret ownerRef 자동 삭제 비활성을 유지한다. `enabled=false`로 기존 선언을 없애는 것은 제거 절차가 아니며 생성기가 차단한다. 실제 폐기는 CRD·인증서·연쇄 삭제 영향을 별도 검토한다.

인증서와 ACME account/webhook 내부 키는 cert-manager가 생성·회전한다. Doppler는 DNS 공급자 인증을 전달하며 인증서 Secret을 이중 관리하지 않는다. Istio 내부 mTLS CA·발급 방식, ServiceLB 80/443, Istio networking API는 바꾸지 않는다. 자세한 다음 단계는 [자동 TLS 절차](../../../docs/runbooks/tls-automatic.md)를 따른다.
