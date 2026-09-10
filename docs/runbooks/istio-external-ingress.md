# 외부 도메인 · TLS · ServiceLB · 내부 mTLS

이 문서는 일반 앱의 gateway TLS 종료·sidecar mTLS 경로를 설명한다. Argo CD는 [별도 공개 도메인 경로](argocd-public-domain.md)로 기존 서버 HTTPS를 유지한다. Argo CD 전용 설정만으로도 공통 ServiceLB overlay를 생성하므로 `ingress.json` 비활성이 전체 외부 노출 비활성을 뜻하지 않는다.

사용자 선택: **외부 노출은 K3s ServiceLB**, 실제 도메인·인증서·서비스 값은 나중에 입력한다. OCI LB/NLB, NodePort 노출, 호스트 NAT 규칙을 추가하지 않는다. 코드 준비만 했으며 SSH·OCI 변경·실제 배포·DNS 변경은 수행하지 않았다.

## 통신 경계

```text
클라이언트 ── HTTPS/TLS ── A1 공인 IP:443 / ServiceLB ── Istio gateway
                                                         │
                                                    Istio mTLS
                                                         │
                                                 앱 Pod의 sidecar
                                                         │
                                               Pod 내부 앱 HTTP 포트
```

80번은 HTTPS 리다이렉트 전용이고 앱으로 평문 외부 요청을 전달하지 않는다. 외부 TLS는 gateway에서 종료한다. gateway → backend는 `DestinationRule: ISTIO_MUTUAL`, 지정한 앱 namespace의 수신은 `PeerAuthentication: STRICT`다. 앱 ↔ 앱은 sidecar와 Auto mTLS를 사용하며 STRICT 수신자는 평문을 거부한다. [Istio TLS 구분](https://istio.io/latest/docs/ops/configuration/traffic-management/tls-configuration/), [STRICT 정책](https://istio.io/latest/docs/reference/config/security/peer_authentication/).

**모든 클러스터 내부 트래픽이 mTLS인 것은 아니다.** 지정하지 않은 namespace, sidecar 없는 Pod, hostNetwork/메시 우회 경로, Pod 내부 앱과 sidecar 사이까지 암호화한다는 의미가 아니다. Argo CD·kube-system·istio-system에는 namespace-wide STRICT를 넣지 않는다. mTLS는 상대 워크로드 인증·전송 암호화이며 어떤 사용자가 어떤 API를 쓸 수 있는지 결정하는 앱 인증/AuthorizationPolicy를 대신하지 않는다. 앱별 최소 허용 정책은 별도 검토한다.

## 입력 파일과 키

원본: [ingress.json](../../gitops/clusters/oci-a1/ingress.json), 구조 예제: [ingress.json.example](../../gitops/clusters/oci-a1/ingress.json.example). 예제는 `.invalid` 가짜 도메인이며 활성 설정에 그대로 쓰지 않는다. 현재 운영 파일은 비활성·빈 목록이다.

| 키 | 나중에 입력할 값 |
| --- | --- |
| `enabled` | 준비 완료 후 검토한 Git 변경에서 true |
| `reviewed` | namespace 소유권·route·메시 가입 영향 확인 후 true |
| `exposure` | 확정값 `k3s-servicelb`, 다른 방식은 거부 |
| `network_reviewed` | A1 공인 경로·DNS·OCI/Ubuntu 방화벽·80/443 충돌·ServiceLB 운영 범위 확인 후 true |
| `tls_ready_reviewed` | 아래 인증서 준비 점검을 실제 완료한 후 true. 자동 인증서 검증 결과가 아니라 수동 확인 기록 |
| `mesh_namespaces` | 이번 코드가 namespace와 sidecar 가입 label·STRICT 정책을 소유할 앱 namespace 배열 |
| `routes[].name` | 고유한 소문자 이름. 최대 40자, 영문 시작, 영문/숫자/하이픈, 하이픈 끝 불가 |
| `routes[].host` | 실제 외부 DNS 호스트명. 소문자 ASCII/punycode, URL·포트·wildcard 없음 |
| `routes[].tls_secret` | `istio-system`에 준비할 `kubernetes.io/tls` Secret 이름. **인증서/개인키 내용 아님** |
| `routes[].backend_namespace` | `mesh_namespaces` 중 하나. `argocd`, `default`, `istio-system`, `kube-*`는 대상 불가 |
| `routes[].backend_service` | 실제 앱 ClusterIP Service 이름, ExternalName/외부 backend는 사용하지 않음 |
| `routes[].backend_port` | Service의 HTTP 포트 정수(1~65535), containerPort/NodePort가 아니라 **Service port** |
| `routes[].path_prefix` | `/` 또는 `/api` 같은 접두 경로. query/fragment/`..` 없음. URI rewrite는 하지 않음 |

현재는 host당 한 route, backend Service당 한 DestinationRule만 지원한다. 같은 host나 backend를 반복하면 거부한다. 기존 gateway/VirtualService/DestinationRule/PeerAuthentication의 이름·대상 충돌과 소유권을 먼저 확인한다. namespace는 해당 Istio Application이 관리하므로 앱 Application이 같은 namespace를 다시 소유하지 않는다. 이미 다른 관리자가 소유한 namespace를 임의 편입하지 않는다.

### K3s와 연동

`ansible/inventories/oci-a1/settings.json`에 **`servicelb=true`**를 첫 설치부터 설정한다. 예제 기본값도 사용자 선택에 맞게 true로 바꿨다. `reviewed`, `network_reviewed`, 실제 K3s/Ubuntu/노드 입력도 필요하다. 생성기는 이 파일의 전체 입력 형식과 ServiceLB 활성화, `bootstrap.json.kube_version`과의 버전 일치를 검사한다. 생성 inventory는 이 원본에서 다시 만든다.

이는 **Git 입력 일치 검사**이지 실제 K3s 설정 검사 완료가 아니다. 설치 후 ServiceLB controller와 `svc-*`/`svclb-*` workload 상태를 확인한다. 이미 `servicelb=false`로 설치한 서버의 초기 설치 playbook을 재실행해 바꾸지 않는다. 그 playbook은 설정 변경을 차단하므로 별도 변경 절차가 필요하다. 여기서는 초기 설치 입력만 준비했다.

ServiceLB는 Service의 80/443을 hostPort로 사용한다. Traefik은 계속 비활성화하고 해당 포트를 사용하는 다른 호스트 프로세스/Pod가 없는지 확인한다. gateway Service는 `LoadBalancer`로 바뀌지만 **K3s 내장 ServiceLB를 사용하며 OCI LB를 만드는 설정이 아니다.** 15021 상태 포트는 외부 Service에서 제외하고 `allocateLoadBalancerNodePorts=false`로 NodePort 자동 할당을 끈다. health probe는 Pod에 직접 접근한다. [K3s ServiceLB](https://docs.k3s.io/networking/networking-services#service-load-balancer).

`externalTrafficPolicy=Cluster`로 두며 클라이언트 원본 IP 보존을 보장하지 않는다. 따라서 X-Forwarded-For 또는 원본 IP 기반 접근 제한을 별도 검증 없이 신뢰하지 않는다. OCI 공인 IP의 NAT 경로와 Service 상태에 표시된 주소도 다를 수 있으므로 DNS에는 실제 접근 가능한 A1 공인 주소를 사용한다. IPv6 경로를 구성하지 않은 상태에서는 AAAA를 추가하지 않는다.

현재 ServiceLB는 K3s 기본 노드 선택 동작을 사용한다. **agent를 추가하면 사용 가능한 포트를 가진 새 노드에도 ServiceLB Pod가 배치될 수 있다.** 자동으로 ingress 전용 node pool을 만들거나 모든 신규 노드의 공인 방화벽을 열지 않는다. 노드 증설 전에 `enablelb`/`lbpool` 제한과 Git/Ansible의 노드 label 관리 방식을 별도로 검토한다. ServiceLB helper 이미지도 선택한 실제 K3s 릴리스의 ARM64 지원을 실행 전에 확인해야 한다. Istio chart 이미지 검사로 K3s helper까지 검사했다고 보지 않는다.

### TLS 인증서 준비

이번 코드는 `Gateway.spec.servers[].tls.credentialName`으로 **이미 준비된 Secret을 소비**한다. 외부 인증서는 자동 발급·갱신을 선택했고 [cert-manager 공통 설치](tls-automatic.md)를 준비했다. DNS 업체별 ACME/DNS-01 issuer 연결은 남아 있다. 보유 인증서의 Doppler 전달 코드는 [4단계](doppler-bootstrap.md)에 추가했으며 기본 비활성이다. 별도 인증서 Secret 생성 코드나 평문 values는 추가하지 않는다.

보유 인증서를 Doppler로 공급한다면 `gitops/clusters/oci-a1/doppler.json`에서 실제 project/config·인증서 키명·개인키 키명을 정해 각각 Secret의 `tls.crt`, `tls.key`에 매핑한다. 실제 PEM 값은 Doppler에만 보관한다. cert-manager를 선택하면 인증서 Secret은 그 컨트롤러가 관리하고 DNS API 자격 증명 등은 Doppler에서 공급한다. 같은 Secret data를 두 컨트롤러가 동시에 관리하지 않는다.

`tls_ready_reviewed=true` 전 확인 사항:

- gateway와 같은 `istio-system` namespace, 정확한 Secret 이름/type/키 매핑.
- host를 포함하는 SAN, 정상 체인·유효기간, 인증서와 개인키 일치, 클라이언트가 신뢰하는 인증서.
- gateway ServiceAccount의 필요한 SDS Secret 접근, 해당 관리 주체의 동기화 성공.
- 발급·갱신·만료 알림·키 보호·회전 후 Envoy SDS 반영 검증 경로.

인증서 Secret이 없거나 유효하지 않아도 Argo CD의 manifest Sync만 성공할 수 있다. **수동 확인 flag는 인증서 상태를 계속 감시하지 않는다.** TLS handshake·만료·SDS를 실제로 확인하기 전 서비스 개통 성공으로 판정하지 않는다. [Istio Secure Gateways](https://istio.io/latest/docs/tasks/traffic-management/ingress/secure-ingress/).

## 생성과 검증 순서

먼저 [Istio baseline](istio-bootstrap.md)이 준비되고, TLS 전달 및 앱의 실제 sidecar 가입을 확인한 뒤 외부 노출을 활성화한다. 코드상 동일 Istio Application의 wave는 다음과 같다.

| wave | 역할 |
| --- | --- |
| -20 / 0 / 10 | Istio namespace / CRD Established / istiod Healthy |
| 15 | 지정한 앱 namespace와 `istio-injection=enabled` label |
| 20 | gateway Deployment와 ServiceLB용 Service 준비 |
| 30 | 앱 namespace STRICT PeerAuthentication, gateway용 ISTIO_MUTUAL DestinationRule |
| 40 | 정확한 host·Secret을 참조하는 Gateway 및 VirtualService |

wave는 Kubernetes 리소스 준비 순서를 표현할 뿐 Secret/SDS·sidecar 없는 기존 Pod·별도 앱 rollout까지 자동으로 검증하지 않는다. namespace label 변경은 **기존 Pod를 재시작하거나 주입하지 않는다.** 기존 앱이 있다면 앱의 Git Pod template 변경으로 재배포하고 실제 sidecar를 확인한 뒤 STRICT/외부 노출을 진행한다. 직접 rollout restart로 우회하지 않는다.

로컬 준비 후 저장소 루트에서 실행한다. Python에는 PyYAML, Helm은 고정 v4.2.4, chart 디렉터리는 baseline의 검증한 archive 3개가 필요하다. 아래 명령은 Git 생성/렌더링만 한다.

```bash
rtk proxy python3 scripts/istio_validate.py --repo-root . --helm "$ISTIO_HELM_BINARY" --chart-dir "$ISTIO_CHART_DIR" --kube-version "$K3S_KUBE_VERSION" --with-ingress
rtk proxy python3 scripts/argocd_gitops.py --repo-root . --write
rtk proxy python3 scripts/argocd_gitops.py --repo-root .
```

생성물은 `gitops/clusters/oci-a1/ingress.values.json`과 `istio/`의 namespace·Gateway·VirtualService·DestinationRule·PeerAuthentication이다. Git 검토 후 별도 권한 범위에서 반영하면 Argo CD가 조정한다. Ansible/Helm 직접 설치 경로는 추가하지 않는다.

`prune=false`인 상태에서 route를 목록에서 빼거나 이름을 바꾸면 기존 공개 route가 살아남을 수 있다. 생성기는 이전 Kustomization의 항목이 사라지는 변경을 차단한다. **파일을 지워 검사를 우회하지 않는다.** 제거/철거는 영향·소유권·삭제 정책을 별도로 검토해야 한다.

## 배포 후 검사 — 현재 미실행

변수는 실제 kubeconfig/context·도메인·mesh namespace·backend를 명시한다. Secret data, 인증서 개인키, 전체 proxy secret dump는 출력하지 않는다.

```bash
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n istio-system get service istio-ingress
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n kube-system get daemonsets,pods
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n istio-system get gateways.networking.istio.io,virtualservices.networking.istio.io,destinationrules.networking.istio.io
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n "$MESH_NAMESPACE" get peerauthentications.security.istio.io,pods,services,endpointslices
rtk proxy istioctl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" analyze -n "$MESH_NAMESPACE"
rtk proxy curl --head --max-time 15 "http://$PUBLIC_HOST/"
rtk proxy curl --head --max-time 15 "https://$PUBLIC_HOST/"
```

Argo CD 기대 revision·Synced/Healthy, 실제 sidecar·gateway rollout·ServiceLB hostPort·DNS·외부 80→443 리다이렉트·TLS 체인/SAN·원하는 host/path의 backend 응답을 확인한다. 잘못된 host/path가 backend로 전달되지 않는지도 검사한다. 인증서 검증을 끄는 `curl -k`는 쓰지 않는다.

mTLS 확인은 실제 proxy의 upstream TLS/xDS 상태와 승인된 GitOps 테스트 workload를 사용한다. 메시 client → backend 성공, sidecar 없는 client → STRICT backend 실패를 확인하고 시스템/헬스체크 영향도 살핀다. 아직 테스트 workload의 이미지·권한·manifest와 실제 통신 시험은 준비/실행하지 않았다. 코드·로컬 chart/필드 검사는 실제 mTLS 강제 검증을 대체하지 않는다.
