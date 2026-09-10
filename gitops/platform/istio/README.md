# Istio 공통 구성

Istio 1.30.4의 고정 chart·ARM64 image digest와 단일 A1 baseline values를 둔다. [3단계 안내](../../../docs/runbooks/istio-bootstrap.md), [필드별 입력값](../../../docs/runbooks/configuration-inputs.md#3단계-istio)을 따른다. 실제 설치하지 않았다.

`versions.json`은 chart checksum/이미지 잠금, `base.values.json`은 CRD/validation, `istiod.values.json`은 제어부·proxy 주입 설정, `gateway.values.json`은 내부 gateway 설정이다. sidecar baseline만 구현했으며 Istio CNI/ambient/ztunnel/Kubernetes Gateway API는 활성화하지 않는다. 환경별 활성화는 [istio.json](../../clusters/oci-a1/istio.json)에서 명시적으로 검토한다.

동일 Argo CD Application에서 namespace → CRD Established → istiod Healthy → injected gateway를 기다린다. 별도 App 사이의 wave에 의존하지 않는다. baseline의 namespace·Service type을 임의 변경하지 않는다. 별도 [ingress.json](../../clusters/oci-a1/ingress.json)을 검토·활성화하면 ServiceLB용 LoadBalancer overlay, Gateway/VirtualService, gateway의 ISTIO_MUTUAL과 지정 앱 namespace STRICT 정책을 생성한다.

Istio는 Argo CD가 배포한다. 직접 Helm/istioctl 설치나 앱·gateway의 live patch로 GitOps를 우회하지 않는다. 외부 방식은 K3s ServiceLB로 확정했고 DNS·TLS 발급/전달과 실제 값은 추후 결정한다. [외부 ingress 안내](../../../docs/runbooks/istio-external-ingress.md), [Istio 운영 지침](../../../.agents/skills/k3s-infra/references/istio.md)을 따른다.
