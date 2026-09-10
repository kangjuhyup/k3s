# 외부 TLS 자동 발급·갱신

목표는 cert-manager가 ACME 인증서를 자동 발급·갱신하고 Istio gateway가 동일 Secret 이름을 소비하는 것이다. 기존 보유 인증서를 Doppler에 복사하는 방식 대신 **인증서 Secret은 cert-manager, DNS API 인증은 Doppler**로 분리한다. 내부 Istio mTLS 인증서는 기존 istiod 소유다. [Istio 연동](https://istio.io/latest/docs/ops/integrations/certmanager/).

## 현재 구현 범위

공통 cert-manager 설치 Application·AppProject·namespace·고정 chart/ARM64 values와
Cloudflare DNS-01 solver·Doppler 토큰 매핑·ACME Issuer·Certificate를 직접 관리한다.
Argo CD·Grafana 공개 경로가 연결되어 있다. 이번 생성기 정리는 로컬 선언 관리 방식만
변경하며 새 발급·갱신 시험이나 운영 변경을 수행하지 않는다.

DNS-01은 도메인의 TXT 레코드로 검증하므로 최초 발급을 위해 Istio 외부 TLS 라우팅을 미리 열 필요가 없다. DNS 업체의 API와 권한 범위, 전파/self-check 동작을 확인해야 한다. DNS 업체를 임의로 Cloudflare/OCI라고 가정하거나 무관한 webhook을 설치하지 않는다. [DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/).

## 직접 관리하는 설정

원본은 `gitops/clusters/oci-a1/root/cert-manager.yaml`, `cert-manager/`와
`gitops/platform/cert-manager/base.values.yaml`이다. Cloudflare DNS-01 Issuer는
`argocd-ingress/`에 있다. 도메인 변경 시 Certificate와 공유 Issuer의 dnsNames,
Gateway의 credentialName을 함께 맞춘다. 인증 토큰은 기존 Doppler 매핑으로 공급한다.
실제 키·인증서는 Git에 넣지 않는다. DNS zone 권한·CAA·TXT 전파·ACME 약관과
연락 이메일 필요성을 검토한다. 인증서 Secret을 여러 컨트롤러가 중복 소유하지 않는다.

bootstrap Git/branch·Kubernetes 버전과 Application 선언을 맞춘다. chart 지원 범위는
1.33~1.36이며 운영 버전을 자동 변경하지 않는다. 아래는 저장소 루트의 로컬 검사다.
Python은 PyYAML 포함 경로, Helm은 4.2.4, chart는 검증한 cert-manager-v1.21.1.tgz다.

```bash
rtk proxy "$CERT_MANAGER_PYTHON" scripts/cert_manager_validate.py --repo-root . --helm "$CERT_MANAGER_HELM" --chart "$CERT_MANAGER_CHART" --kube-version "$K3S_KUBE_VERSION"
rtk proxy "$CERT_MANAGER_PYTHON" scripts/gitops_validate.py --repo-root .
```

직접 편집한 Git을 Argo CD가 반영한다. Helm 설치나 kubectl apply로 우회하지 않는다.

## 예정된 활성화·검증 순서

1. cert-manager와 Istio baseline을 GitOps로 반영하고 기대 SHA·Synced/Healthy·webhook API 준비를 확인한다. 실제 context/namespace를 명시한다.
2. 선택 DNS provider의 제한된 인증만 Doppler로 전달한다. 기존 4단계 최초 sync 이전 bootstrap 순서에 포함해야 한다. 이미 활성화된 Doppler에 새 토큰을 추가하는 경우 별도 create-only 교체/추가 절차가 필요하다.
3. Let's Encrypt staging에서 별도 issuer·account key·인증서 Secret으로 발급을 시험한다. staging 인증서를 실제 외부 ingress에 연결하지 않는다.
4. 검토된 production issuer·Certificate를 Git으로 반영한다. 실제 인증서 Ready/observedGeneration·SAN·체인·만료·Secret 소유권을 확인한 뒤 ingress를 연결한다.
5. 갱신 일정과 실패 감시, Secret 갱신 후 Istio SDS/외부 handshake 반영을 확인한다. 직접 rollout restart를 자동 갱신 경로에 넣지 않는다.

발급 완료는 갱신 시험 완료가 아니다. CA의 실제 인증서 수명/renewalTime을 확인하고 고정 90일을 보장하지 않는다. 기존 정상 인증서는 새 발급 확인 전 삭제하지 않는다. 만료·발급 실패 감시와 정상 갱신 검증은 후속 구현·실행 대상으로 남아 있다. [Certificate 수명·갱신](https://cert-manager.io/docs/usage/certificate/).
