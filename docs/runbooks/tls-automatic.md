# 외부 TLS 자동 발급·갱신

목표는 cert-manager가 ACME 인증서를 자동 발급·갱신하고 Istio gateway가 동일 Secret 이름을 소비하는 것이다. 기존 보유 인증서를 Doppler에 복사하는 방식 대신 **인증서 Secret은 cert-manager, DNS API 인증은 Doppler**로 분리한다. 내부 Istio mTLS 인증서는 기존 istiod 소유다. [Istio 연동](https://istio.io/latest/docs/ops/integrations/certmanager/).

## 현재 구현 범위

공통 cert-manager 설치 Application·AppProject·namespace·고정 chart/ARM64 values·오프라인 검사를 준비했다. 실제 DNS 업체가 미확인이라 provider별 DNS-01 solver·인증 Secret 매핑·ACME Issuer·Certificate 생성 코드는 아직 작성하지 않았다. 실제 DNS/OCI/Kubernetes 접속·Git push·발급·갱신 시험도 수행하지 않았다.

DNS-01은 도메인의 TXT 레코드로 검증하므로 최초 발급을 위해 Istio 외부 TLS 라우팅을 미리 열 필요가 없다. DNS 업체의 API와 권한 범위, 전파/self-check 동작을 확인해야 한다. DNS 업체를 임의로 Cloudflare/OCI라고 가정하거나 무관한 webhook을 설치하지 않는다. [DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/).

## 지금 소비되는 설정

파일: `gitops/clusters/oci-a1/cert-manager.json`

| 키 | 값 |
| --- | --- |
| `enabled` | cert-manager 설치 선언을 생성할 때 true. 기본 false |
| `reviewed` | 버전·관리 권한·리소스·기존 설치 부재를 검토한 뒤 true. 실제 검증/승인을 대신하지 않음 |

기존 `bootstrap.json`의 Git URL/branch/Kubernetes 버전도 채워야 한다. 현재 chart의 지원 범위는 1.33~1.36이며 1.32는 활성화 검사에서 거부한다. 현재 운영 버전을 자동 변경하지 않는다.

저장소 루트에서 아래는 **로컬 코드 생성/검사만** 수행한다. `CERT_MANAGER_PYTHON`=PyYAML 포함 Python 절대 경로, `CERT_MANAGER_HELM`=검증한 Helm 4.2.4 절대 경로, `CERT_MANAGER_CHART`=공식 `cert-manager-v1.21.1.tgz` 절대 경로, `K3S_KUBE_VERSION`=검토한 `bootstrap.json.kube_version`이다.

```bash
rtk proxy "$CERT_MANAGER_PYTHON" scripts/cert_manager_validate.py \
  --repo-root . --helm "$CERT_MANAGER_HELM" \
  --chart "$CERT_MANAGER_CHART" --kube-version "$K3S_KUBE_VERSION"
rtk proxy "$CERT_MANAGER_PYTHON" scripts/argocd_gitops.py --repo-root . --write
rtk proxy "$CERT_MANAGER_PYTHON" scripts/argocd_gitops.py --repo-root .
```

생성되는 `root/cert-manager*.json`, `cert-manager/`는 Git 검토 대상이다. 직접 Helm 설치나 kubectl apply로 반영하지 않는다. 기본 설정은 미입력이라 활성 선언 생성이 차단된다.

## 다음 구현에 필요한 정보

지금 필요한 선택은 **DNS 관리 서비스명**이다. 나머지 실제 값은 사용자 요청대로 나중에 채운다. 아래는 아직 작동하는 JSON 키가 아니라 후속 입력 목록이다.

| 입력 | 보관 위치/용도 |
| --- | --- |
| DNS 서비스 | provider별 solver 및 필요 시 ARM64 webhook 선정. 업체 확인 전 추가 배포 없음 |
| 관리 zone·인증서 도메인 | Git의 값 없는 공개 도메인 선언. zone 범위·CAA·TXT 전파 확인 |
| ACME 연락 이메일 | Git의 issuer 설정. 공개 CA 약관 검토 필요 |
| DNS API 인증 키 | Doppler의 전용 최소 권한 config. 선택 provider에 맞춰 정확한 키명·Secret 위치를 후속 명시 |
| Doppler project/config·Service Token 참조 | 기존 4단계 매핑 원본 및 보호된 최초 인증 경로 |
| 인증서와 Secret 이름 | Istio gateway와 같은 `istio-system` namespace. `ingress.json.routes[].tls_secret`과 연결 |

## 예정된 활성화·검증 순서

1. cert-manager와 Istio baseline을 GitOps로 반영하고 기대 SHA·Synced/Healthy·webhook API 준비를 확인한다. 실제 context/namespace를 명시한다.
2. 선택 DNS provider의 제한된 인증만 Doppler로 전달한다. 기존 4단계 최초 sync 이전 bootstrap 순서에 포함해야 한다. 이미 활성화된 Doppler에 새 토큰을 추가하는 경우 별도 create-only 교체/추가 절차가 필요하다.
3. Let's Encrypt staging에서 별도 issuer·account key·인증서 Secret으로 발급을 시험한다. staging 인증서를 실제 외부 ingress에 연결하지 않는다.
4. 검토된 production issuer·Certificate를 Git으로 반영한다. 실제 인증서 Ready/observedGeneration·SAN·체인·만료·Secret 소유권을 확인한 뒤 ingress를 연결한다.
5. 갱신 일정과 실패 감시, Secret 갱신 후 Istio SDS/외부 handshake 반영을 확인한다. 직접 rollout restart를 자동 갱신 경로에 넣지 않는다.

발급 완료는 갱신 시험 완료가 아니다. CA의 실제 인증서 수명/renewalTime을 확인하고 고정 90일을 보장하지 않는다. 기존 정상 인증서는 새 발급 확인 전 삭제하지 않는다. 만료·발급 실패 감시와 정상 갱신 검증은 후속 구현·실행 대상으로 남아 있다. [Certificate 수명·갱신](https://cert-manager.io/docs/usage/certificate/).
