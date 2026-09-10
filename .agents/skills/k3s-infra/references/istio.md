# K3s에서 Istio 운영

## 설치 상태와 관리 방식

실제 K3s/Kubernetes·Istio·istioctl 버전, 기존 관리 원본, control plane namespace/revision, gateway workload/Service, LB 구현을 확인한다. 기존 Helm/istioctl 직접 설치는 조사·편입 대상이며 새 변경은 [GitOps 필수 정책](gitops.md)을 따른다. `istio-system`, `istio-ingressgateway`라는 이름을 고정하지 않는다. Ingress 사용만으로 모든 워크로드가 mesh에 가입되어 있다고 간주하지 않는다.

OCI A1에서는 istiod·gateway/proxy·CNI·ztunnel과 설치 Job의 실제 이미지가 `linux/arm64`를 제공하는지 확인한다. 로컬 istioctl은 실행하는 클라이언트 OS/아키텍처에 맞추며 Linux 노드용 바이너리와 구분한다. 플랫폼 조건은 [OCI A1 운영](oci-a1.md)을 따른다.

namespace·Pod의 실제 labels/annotations와 실행 중인 구성요소로 sidecar, ambient, mesh 미가입 상태를 구분한다. 신규 구성은 사용자 요구와 호환성에 맞게 선택하며 기존 모드를 임의로 전환하지 않는다. Istio CNI는 기반 Kubernetes CNI를 대체하지 않는다.

K3s에서 Istio CNI를 사용할 때 실제 CNI 설정·바이너리 경로를 확인한다. 번들 CNI와 기본 경로를 사용하는 ambient 설치는 Git의 Helm values에 `global.platform=k3s` 설정을 해당 버전에서 확인해 반영한다. custom CNI/data-dir이면 경로를 직접 검증한다. [Istio K3s prerequisites](https://istio.io/latest/docs/ambient/install/platform-prerequisites/#k3s)

## Gateway API를 구분한다

| 사용 API | 확인할 연결 관계 |
| --- | --- |
| Kubernetes Gateway API | `gateways.gateway.networking.k8s.io`, GatewayClass의 Istio controller, listener, HTTPRoute의 parentRefs·backendRefs, cross-namespace ReferenceGrant·allowedRoutes, certificateRefs. Gateway의 Accepted/Programmed와 route의 Accepted/ResolvedRefs를 관찰한다. |
| Istio networking API | `gateways.networking.istio.io`의 selector·servers, VirtualService의 gateways·hosts·route, DestinationRule의 subset·TLS, 선택된 gateway Pod. |

두 API의 Gateway를 `kubectl get gateway`처럼 축약해 혼동하지 않는다. 실제 사용 중인 API/버전과 CRD를 먼저 찾고 해당 route를 수정한다. controller가 생성한 Deployment/Service는 Gateway 및 지원되는 customization 원본에서 관리한다. [Istio Gateway API](https://istio.io/latest/docs/tasks/traffic-management/ingress/gateway-api/)

## 진단

확인한 context·namespace를 각 명령에 명시한다. 설치된 istioctl의 `--help`로 지원 옵션을 확인하고 아래에서 필요한 명령만 선택한다. `proxy-status`는 mesh 전체 정보를 조회할 수 있으므로 요청 범위에 맞게 실행한다.

```sh
rtk proxy istioctl --context "$K3S_CONTEXT" analyze -n "$K3S_NAMESPACE"
rtk proxy istioctl --context "$K3S_CONTEXT" proxy-status
rtk proxy istioctl --context "$K3S_CONTEXT" proxy-config routes "$ISTIO_GATEWAY_POD" -n "$ISTIO_GATEWAY_NAMESPACE"
rtk proxy istioctl --context "$K3S_CONTEXT" proxy-config endpoints "$ISTIO_GATEWAY_POD" -n "$ISTIO_GATEWAY_NAMESPACE"
```

`analyze` 결과와 proxy 동기화 상태는 실제 요청 성공을 대체하지 않는다. 필요한 listener/route/cluster/endpoint만 조회하고 bootstrap·secret config 전체 덤프는 피한다. [Debugging Envoy and Istiod](https://istio.io/latest/docs/ops/diagnostic-tools/proxy-cmd/)

- 404: 요청 Host/SNI/path와 listener/route 매칭을 확인한다.
- 503/연결 reset: gateway access log의 response flags, endpoint readiness, backend port·프로토콜, DestinationRule subset 및 TLS와 PeerAuthentication의 일치를 확인한다. 관측 없이 mTLS를 비활성화하지 않는다.
- 403: 해당 workload/gateway에 실제 적용되는 AuthorizationPolicy와 인증 상태를 확인한다. 장애 진단을 위해 mesh 전체 정책을 제거하지 않는다.
- sidecar: 주입 labels/revision, 실제 `istio-proxy`, istiod 연결과 xDS 동기화를 확인한다. namespace label 변경만으로 기존 Pod가 새 proxy로 바뀐다고 가정하지 않는다.
- ambient: mesh 가입, Istio CNI, 노드별 ztunnel과 HBONE 연결, 필요한 L7 waypoint 연결을 확인한다. `istio-proxy`가 없는 것을 주입 실패로 판단하지 않는다. 해당 버전의 `istioctl ztunnel-config`와 제한된 로그를 사용한다. [ztunnel 진단](https://istio.io/latest/docs/ambient/usage/troubleshoot-ztunnel/)

## 설치·변경·업그레이드

기존 values·revision을 보존하고 지원 Kubernetes 버전 및 Istio 구성요소 간 호환성을 확인한다. Argo CD Application의 Helm source와 Git의 고정 chart·values를 관리한다. base CRD, istiod, gateway와 모드에 필요한 CNI/ztunnel을 해당 버전의 순서와 준비 조건으로 표현한다. 직접 `helm install/upgrade`나 `istioctl install`은 실행하지 않는다. [Helm 설치](https://istio.io/latest/docs/setup/install/helm/)

Gateway와 routes를 렌더링·분석한 뒤 요청 범위에 맞게 반영한다. 변경 후 TLS/SNI·host/path, backend 응답, 필요한 mesh 통신과 접근 정책을 검증한다. Istio 업그레이드는 revision 및 dataplane 갱신 계획을 함께 세우고 이전 경로로 되돌릴 수 있는 시점을 명시한다. K3s 업그레이드 요청만으로 Istio도 동시에 업그레이드하지 않는다.

## 기존 Traefik에서 전환할 때만

실제 전환이 요청된 경우 기존 host/path/TLS·middleware 기능을 Istio route/정책으로 매핑하고 인증서 참조, 외부 주소/포트, DNS 전환과 복구 경로를 준비한다. 기존 80/443 점유와 충돌하지 않는 검증 경로에서 새 gateway를 확인한 뒤 트래픽을 옮긴다.

번들 Traefik 비활성화는 모든 K3s server의 관리 설정에 `disable: [traefik]`에 해당하는 항목을 반영하되 기존 disable 목록을 보존한다. 기본 `server/manifests/traefik.yaml`의 직접 수정은 재시작 때 유지되지 않는다. ServiceLB 사용 여부는 별도로 결정한다.

비활성화·chart 제거 전에 Gateway API CRD의 소유권과 삭제 전파를 확인한다. K3s 2026년 4월 수정 릴리스 이전에는 Traefik 비활성화가 Gateway API CRD 삭제로 이어질 수 있다. 실제 버전의 수정 포함 여부, CRD 보존 및 관리 주체 이전 절차를 검증하기 전 기존 설치를 제거하지 않는다. 공유 CRD 삭제는 Istio가 사용하는 Gateway/route까지 제거할 수 있다. [K3s networking services](https://docs.k3s.io/networking/networking-services)

문서 확인일: 2026-09-07. 버전별 공식 문서와 실제 리소스를 기준으로 실행한다.
