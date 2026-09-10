# 3단계: Istio GitOps baseline

2026-09-10 `이력 정리 전 검증 revision`을 Argo CD로 배포했다. Istio 1.30.4의 CRD·istiod·내부 gateway가 설치됐고 Application은 Synced/Healthy, Pod는 Ready다. 정확한 필드별 입력은 [단계별 설정값](configuration-inputs.md#3단계-istio)을 따른다. 기존 OS의 Traefik/Istio를 제거하거나 인계하는 도구가 아니다.

gateway의 고정 proxy digest·xDS 연결·CDS/LDS 설정 거부 0을 확인했다.
전체 테스트는 93개 통과, 선택 도구가 필요한 6개는 생략했다.
외부 DNS/TLS/라우트와 앱 mesh 가입은 아직 비활성이며, 사용자 트래픽 및
앱 간 mTLS 시험은 수행하지 않았다. 자동 백업도 비활성 상태를 유지한다.

## 제공 범위

Istio 1.30.4의 base·istiod·gateway Helm chart를 **하나의 `istio` Application**에서 렌더링한다. 같은 설치의 의존 관계를 한 sync operation 안에서 기다리도록 구성했다. 별도 Application 사이의 wave만으로 순서가 보장된다고 가정하지 않는다.

| wave | 리소스 / 준비 조건 |
| --- | --- |
| -20 | Git이 소유하는 `istio-system` namespace |
| 0 | base CRD·RBAC·ConfigMap·istiod Service·webhooks; CRD `Established=True` 대기 |
| 10 | istiod Deployment; Argo CD의 Deployment health로 준비 완료 대기 |
| 20 | gateway chart 리소스; istiod의 gateway injection 후 Deployment 준비 대기 |

CRD health Lua는 2단계 Argo CD `base.values.yaml`에 포함한다. NamesAccepted 실패/종료 중인 CRD는 Degraded다. **기존 2단계를 이미 설치했다면 이 health 설정이 실제 argocd-cm에 반영된 것을 먼저 확인한 후 별도 Git 변경으로 Istio를 켠다.** Argo CD의 자기관리와 root 앱에는 재귀적인 Application health를 추가하지 않는다. 2단계 bootstrap 완료 판정은 여전히 Argo CD 인계만 검사하며 Istio 성공을 대신하지 않는다.

신규 namespace를 자동 sidecar 가입시키지 않는다. `sidecar` baseline만 지원하며 CNI/ztunnel/ambient는 설치하지 않는다. gateway workload는 같은 `istio-system` namespace에서 pod의 gateway injection template을 사용한다. chart에 보이는 `image: auto`는 실제 운영 이미지가 아니라 주입 표식이다. 실제 proxy·init 이미지 원본은 istiod values의 고정 `proxyv2` digest다. 실제 Pod의 주입 결과는 배포 후 별도 확인한다.

Istiod/gateway는 각각 1 replica, requests 합계 350m CPU·640Mi 메모리, memory limits 1536Mi/512Mi다. HPA·단일 replica PDB는 비활성이다. A1 부하 측정 전 제안 baseline이지 용량 보장이 아니다. agent 추가만으로 replica/HA가 늘어나지 않으며 설정은 클러스터 단위로 관리한다.

이 baseline만 켜면 외부 LoadBalancer·NodePort·hostNetwork·DNS·TLS Secret·Gateway/VirtualService·앱 자동 mesh 가입은 만들지 않는다. 별도의 [외부 ingress 확장](istio-external-ingress.md)을 켜면 사용자 선택인 K3s ServiceLB 80/443과 TLS Secret 참조·라우팅·지정 앱 namespace의 sidecar 가입/STRICT mTLS를 추가한다. 실제 도메인·인증서·backend는 미입력이므로 외부 서비스 개통 완료가 아니다. `PILOT_ENABLE_GATEWAY_API=false`를 유지하며 Gateway API 선택은 별도 설계 변경이다.

## 로컬 준비

1. [bootstrap.json](../../gitops/clusters/oci-a1/bootstrap.json)의 실제 Git/branch/Kubernetes 입력을 검토한다. Istio 1.30 지원 범위와 실제 K3s 버전을 맞춘다.
2. [Istio Application](../../gitops/clusters/oci-a1/root/istio.yaml), `istio/`와 platform values를 직접 검토·수정한다. 기존 리소스 소유권을 먼저 확인한다.
3. 공개 공식 chart 3개를 로컬에 확보한다. [versions.json](../../gitops/platform/istio/versions.json)의 SHA256과 맞아야 한다. URL 패턴은 `https://blob.istio.io/istio-release/charts/<chart>-1.30.4.tgz`, chart는 `base`, `istiod`, `gateway`다. Helm v4.2.4와 PyYAML이 설치된 controller Python을 사용한다.
4. 아래 로컬 명령으로 검사한다. 변수에는 실제 로컬 절대 경로와 검토한 Kubernetes 기본 버전을 지정한다. 비밀값은 필요 없다.

```bash
rtk proxy python3 scripts/istio_validate.py --repo-root . --helm "$ISTIO_HELM_BINARY" --chart-dir "$ISTIO_CHART_DIR" --kube-version "$K3S_KUBE_VERSION"
rtk proxy .local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .
```

root/istio-project.yaml·root/istio.yaml, istio/의 namespace·Kustomization과 Helm values를 직접 관리한다. gitops_validate.py는 쓰기 옵션 없이 검사만 수행한다.

5. Git 변경을 검토하고 별도 반영 권한 아래 commit/push/merge한다. Argo CD가 Git에서 배포한다. 이 문서 작성 중에는 commit/push/sync를 수행하지 않았다. 최초 설치 전 기존 Istio CRD·webhook·namespace 소유권과 이름 충돌을 확인한다.

AppProject는 해당 Git/공식 chart 저장소, `istio-system` 목적지와 필요한 kind만 허용한다. namespace/cluster RBAC/admission 관리 권한은 강력하므로 플랫폼 관리자 전용 Git 경로다. Secret data는 GitOps 앱에 넣지 않는다. istiod가 만드는 CA 및 webhook CA bundle은 controller 소유다. caBundle만 차이/재적용에서 제외하고 validation `failurePolicy=Fail`은 Git과 맞춘다.

## 배포 후 읽기 전용 검사

```bash
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n argocd get application istio -o jsonpath='{.status.sync.status}{"\n"}{.status.health.status}{"\n"}{.status.sync.revisions}{"\n"}{.status.operationState.phase}{"\n"}'
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n istio-system rollout status deployment/istiod --timeout=300s
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n istio-system rollout status deployment/istio-ingress --timeout=300s
rtk proxy kubectl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" -n istio-system get pods,services,endpointslices
rtk proxy istioctl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" analyze -n istio-system
rtk proxy istioctl --kubeconfig "$K3S_KUBECONFIG" --context "$K3S_CONTEXT" proxy-status
```

App의 4개 source revision이 `[1.30.4, 1.30.4, 1.30.4, 기대 Git SHA]`인지, Synced/Healthy·성공 operation·오류 조건 없음인지 확인한다. 실제 Pod의 ARM64 이미지 digest, CRD Established, gateway injection/xDS와 endpoints를 확인한다. 도메인 요청·TLS·backend 응답·mTLS/접근 정책은 라우팅이 추가된 뒤 별도 검증한다. `istioctl`은 같은 검토한 Istio 버전과 실행 머신 아키텍처를 사용한다.

`prune=false`, Application cascading finalizer 없음, namespace Delete/Prune 보호를 유지한다. 파일 삭제나 source 연결 해제는 uninstall이 아니며 기존 리소스가 남을 수 있다. 장애 시 리소스 삭제·직접 Helm/istioctl 설치·강제 재시작으로 우회하지 않는다. 업그레이드는 단순 버전 치환이 아니라 CRD 호환·revision·dataplane 갱신·Git 복귀 계획을 별도로 검토한다.

## 검증 근거

- [Istio 지원 범위](https://istio.io/latest/docs/releases/supported-releases/): 1.30은 확인일 현재 지원 릴리스, Kubernetes 1.32~1.36. 실제 설치 시 다시 확인한다.
- [Istio Helm 지침](https://istio.io/latest/docs/setup/install/helm/): CRD/istiod/gateway 의존성, SSA의 validation failurePolicy 처리.
- [Argo CD sync waves](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)와 [health](https://argo-cd.readthedocs.io/en/stable/operator-manual/health/): 동일 Application의 wave/건강 상태 대기.

2026-09-09 공식 HTTPS chart와 Docker Hub `istio/pilot`, `istio/proxyv2` OCI index를 확인했다. 두 고정 digest 모두 linux/arm64 항목이 있다. 로컬 렌더링은 실제 admission·CNI·xDS·트래픽/부하 시험을 대체하지 않는다. chart SHA는 로컬 검사에 사용하며 Argo CD Helm source 자체는 버전으로 선택하므로 upstream archive 재게시 방지까지 보장하지 않는다.
