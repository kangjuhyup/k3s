# 외부 도메인 · TLS · ServiceLB · 내부 mTLS

이 문서는 일반 앱의 gateway TLS 종료·sidecar mTLS 경로를 설명한다. Argo CD는 [별도 공개 도메인 경로](argocd-public-domain.md)로 기존 서버 HTTPS를 유지한다. 공통 ServiceLB overlay와 각 앱의 라우팅은 별도 선언이므로 개별 앱 경로 제거가 전체 외부 노출 중단을 뜻하지 않는다.

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

## 직접 관리하는 선언

원본은 `gitops/clusters/oci-a1/ingress.values.yaml`과 각 앱의 Certificate·Gateway·
VirtualService·DestinationRule이다. 메시 앱은 namespace sidecar 가입·STRICT 정책도
직접 선언한다. Kustomization의 resources에 명시적으로 연결한다.

- Gateway는 wildcard 없는 정확한 host와 istio-system TLS Secret 이름만 참조한다.
- VirtualService는 실제 ClusterIP Service namespace/name과 **Service port**를 사용한다.
  필요한 경로만 열고 외부 backend/ExternalName·불필요한 URI rewrite는 사용하지 않는다.
- DestinationRule의 ISTIO_MUTUAL은 backend의 실제 sidecar가 확인된 경우에만 사용한다.
- Namespace 소유권·기존 Pod·route 이름 및 대상 충돌을 확인한다. Argo CD·default·
  istio-system·kube-*에 일반 앱의 namespace-wide STRICT를 적용하지 않는다.

동일 namespace를 여러 Application이 소유하지 않게 한다. 실제 IP·토큰·PEM은 Git에 넣지 않는다.

### K3s와 연동

`ansible/inventories/oci-a1/settings.json`에 **`servicelb=true`**를 첫 설치부터 설정한다. 예제 기본값도 사용자 선택에 맞게 true로 바꿨다. `reviewed`, `network_reviewed`, 실제 K3s/Ubuntu/노드 입력도 필요하다. 검증기는 이 파일의 전체 입력 형식과 ServiceLB 활성화, `bootstrap.json.kube_version`과의 버전 일치를 검사한다. 생성 inventory는 이 원본에서 다시 만든다.

이는 **Git 입력 일치 검사**이지 실제 K3s 설정 검사 완료가 아니다. 설치 후 ServiceLB controller와 `svc-*`/`svclb-*` workload 상태를 확인한다. 이미 `servicelb=false`로 설치한 서버의 초기 설치 playbook을 재실행해 바꾸지 않는다. 그 playbook은 설정 변경을 차단하므로 별도 변경 절차가 필요하다. 여기서는 초기 설치 입력만 준비했다.

ServiceLB는 Service의 80/443을 hostPort로 사용한다. Traefik은 계속 비활성화하고 해당 포트를 사용하는 다른 호스트 프로세스/Pod가 없는지 확인한다. gateway Service는 `LoadBalancer`로 바뀌지만 **K3s 내장 ServiceLB를 사용하며 OCI LB를 만드는 설정이 아니다.** 15021 상태 포트는 외부 Service에서 제외하고 `allocateLoadBalancerNodePorts=false`로 NodePort 자동 할당을 끈다. health probe는 Pod에 직접 접근한다. [K3s ServiceLB](https://docs.k3s.io/networking/networking-services#service-load-balancer).

`externalTrafficPolicy=Cluster`로 두며 클라이언트 원본 IP 보존을 보장하지 않는다. 따라서 X-Forwarded-For 또는 원본 IP 기반 접근 제한을 별도 검증 없이 신뢰하지 않는다. OCI 공인 IP의 NAT 경로와 Service 상태에 표시된 주소도 다를 수 있으므로 DNS에는 실제 접근 가능한 A1 공인 주소를 사용한다. IPv6 경로를 구성하지 않은 상태에서는 AAAA를 추가하지 않는다.

현재 ServiceLB는 K3s 기본 노드 선택 동작을 사용한다. **agent를 추가하면 사용 가능한 포트를 가진 새 노드에도 ServiceLB Pod가 배치될 수 있다.** 자동으로 ingress 전용 node pool을 만들거나 모든 신규 노드의 공인 방화벽을 열지 않는다. 노드 증설 전에 `enablelb`/`lbpool` 제한과 Git/Ansible의 노드 label 관리 방식을 별도로 검토한다. ServiceLB helper 이미지도 선택한 실제 K3s 릴리스의 ARM64 지원을 실행 전에 확인해야 한다. Istio chart 이미지 검사로 K3s helper까지 검사했다고 보지 않는다.

### TLS 인증서 준비

Gateway는 `spec.servers[].tls.credentialName`으로 **준비된 Secret을 소비**한다.
외부 인증서는 [cert-manager](tls-automatic.md)의 Cloudflare DNS-01을 사용한다.
보유 인증서를 전달할 때는 [Doppler](doppler-bootstrap.md)의 별도 소유권 조건을 따른다.
평문 Secret data나 인증서 values를 Git에 추가하지 않는다.

보유 인증서를 Doppler로 공급한다면 `gitops/clusters/oci-a1/doppler.json`에서 실제 project/config·인증서 키명·개인키 키명을 정해 각각 Secret의 `tls.crt`, `tls.key`에 매핑한다. 실제 PEM 값은 Doppler에만 보관한다. cert-manager를 선택하면 인증서 Secret은 그 컨트롤러가 관리하고 DNS API 자격 증명 등은 Doppler에서 공급한다. 같은 Secret data를 두 컨트롤러가 동시에 관리하지 않는다.

TLS 경로 연결 전 확인 사항:

- gateway와 같은 `istio-system` namespace, 정확한 Secret 이름/type/키 매핑.
- host를 포함하는 SAN, 정상 체인·유효기간, 인증서와 개인키 일치, 클라이언트가 신뢰하는 인증서.
- gateway ServiceAccount의 필요한 SDS Secret 접근, 해당 관리 주체의 동기화 성공.
- 발급·갱신·만료 알림·키 보호·회전 후 Envoy SDS 반영 검증 경로.

인증서 Secret이 없거나 유효하지 않아도 Argo CD의 manifest Sync만 성공할 수 있다. **수동 확인 flag는 인증서 상태를 계속 감시하지 않는다.** TLS handshake·만료·SDS를 실제로 확인하기 전 서비스 개통 성공으로 판정하지 않는다. [Istio Secure Gateways](https://istio.io/latest/docs/tasks/traffic-management/ingress/secure-ingress/).

## 선언과 검증 순서

먼저 [Istio baseline](istio-bootstrap.md)이 준비되고, TLS 전달 및 앱의 실제 sidecar 가입을 확인한 뒤 외부 노출을 활성화한다. 코드상 동일 Istio Application의 wave는 다음과 같다.

| wave | 역할 |
| --- | --- |
| -20 / 0 / 10 | Istio namespace / CRD Established / istiod Healthy |
| 15 | 지정한 앱 namespace와 `istio-injection=enabled` label |
| 20 | gateway Deployment와 ServiceLB용 Service 준비 |
| 30 | 앱 namespace STRICT PeerAuthentication, gateway용 ISTIO_MUTUAL DestinationRule |
| 40 | 정확한 host·Secret을 참조하는 Gateway 및 VirtualService |

wave는 Kubernetes 리소스 준비 순서를 표현할 뿐 Secret/SDS·sidecar 없는 기존 Pod·별도 앱 rollout까지 자동으로 검증하지 않는다. namespace label 변경은 **기존 Pod를 재시작하거나 주입하지 않는다.** 기존 앱이 있다면 앱의 Git Pod template 변경으로 재배포하고 실제 sidecar를 확인한 뒤 STRICT/외부 노출을 진행한다. 직접 rollout restart로 우회하지 않는다.

로컬 준비 후 저장소 루트에서 실행한다. Python에는 PyYAML, Helm은 고정 v4.2.4, chart 디렉터리는 baseline의 검증한 archive 3개가 필요하다. 아래 명령은 읽기 전용 선언 검사와 chart 렌더링만 한다.

```bash
rtk proxy python3 scripts/istio_validate.py --repo-root . --helm "$ISTIO_HELM_BINARY" --chart-dir "$ISTIO_CHART_DIR" --kube-version "$K3S_KUBE_VERSION" --with-ingress
rtk proxy .local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .
```

직접 관리 원본은 `gitops/clusters/oci-a1/ingress.values.yaml`과 앱별 라우팅·보안 매니페스트다. Git 검토 후 별도 권한 범위에서 Argo CD가 반영한다. Ansible/Helm 직접 설치로 우회하지 않는다.

`prune=false`인 상태에서 route를 목록에서 빼거나 이름을 바꾸면 기존 공개 route가 살아남을 수 있다. 기존 Kustomization의 항목 제거와 실제 삭제 영향을 별도 검토한다. **파일을 지워 검사를 우회하지 않는다.** 제거/철거는 영향·소유권·삭제 정책을 별도로 검토해야 한다.

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
