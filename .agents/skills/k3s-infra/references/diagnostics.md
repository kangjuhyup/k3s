# 상태 점검과 장애 진단

## 대상 식별과 초기 조회

먼저 로컬 kubeconfig의 context 목록을 확인한다. kubeconfig의 exec 인증 플러그인도 실행될 수 있으므로 출처가 확인된 설정을 사용한다.

```sh
rtk proxy kubectl config get-contexts
```

확인된 context 이름을 `K3S_CONTEXT` 환경 변수로 export한 후 아래 블록을 실행한다. 이 변수에는 기본값을 넣지 않는다. `--minify`의 출력은 API 주소만 선택하며 토큰/인증서 원문은 출력하지 않는다.

```sh
rtk proxy sh -eu -c '
: "${K3S_CONTEXT:?Set the verified target context}"
kubectl --context "$K3S_CONTEXT" config view --minify \
  -o jsonpath="{.clusters[0].cluster.server}{\"\n\"}"
kubectl --context "$K3S_CONTEXT" --request-timeout=20s get nodes -o wide
kubectl --context "$K3S_CONTEXT" --request-timeout=20s get --raw="/readyz?verbose"
kubectl --context "$K3S_CONTEXT" --request-timeout=20s -n kube-system get pods -o wide
'
```

이 블록은 첫 오류에서 중단된다. 실패 지점을 보고하고 아래에서 필요한 조회를 개별 실행한다. `Forbidden`은 권한 문제이며 리소스 부재나 클러스터 장애의 증거가 아니다. metrics API 실패만으로 전체 클러스터 장애를 판정하지 않는다.

namespace가 정해졌다면 해당 범위의 Pods, Deployments/StatefulSets, events를 먼저 확인한다. 전체 클러스터 점검 요청에서만 `-A`로 넓힌다. events는 최근 시각순, 로그는 `--since=15m --tail=150`처럼 제한한다. API readiness와 Node Ready는 개별 etcd 멤버 건강성의 대체 지표가 아니다.

## 증상별 다음 확인

| 증상 | 확인할 증거와 판단 |
| --- | --- |
| API 연결 실패 | 선택된 API 주소, DNS/TCP, VPN/방화벽, 인증서 만료와 SAN, 호스트 서비스. TLS 검증을 끄는 것을 해결책으로 삼지 않는다. |
| Node NotReady | node conditions, taints, heartbeat, 디스크/inode·메모리·시각 동기화, kubelet/containerd 및 `k3s`/`k3s-agent` 서비스 로그. |
| Pending | scheduler events, requests/allocatable, taints/tolerations, affinity, PVC binding, 스토리지 topology. |
| CrashLoopBackOff | container별 현재/`--previous` 로그, 종료 이유·코드, OOMKilled, probe, 필요한 설정의 존재. 컨테이너/환경변수 전체 덤프는 피한다. |
| ImagePullBackOff | 정확한 이미지/tag, registry 접근, imagePullSecrets 참조, 노드의 registries.yaml 설정. 자격 증명은 출력하지 않는다. |
| no matching manifest / exec format error | A1 노드의 arm64와 실제 이미지 digest·내부 실행 파일의 아키텍처를 비교한다. initContainer·hook도 확인하고 shebang/실행 파일 형식 문제와 구분한다. [OCI A1 운영](oci-a1.md) 참조. |
| DNS 실패 | CoreDNS Pod/Service/EndpointSlice, upstream DNS, NetworkPolicy, 실제 CNI. 테스트 Pod 생성이나 exec는 진단 권한과 범위를 확인한다. |
| Istio Gateway 404/502/503 | DNS → 외부 LB/포트 → Gateway listener·host/path/TLS → HTTPRoute 또는 VirtualService → Service/EndpointSlice → 준비된 Pod 순서로 좁힌다. API 종류별 상태와 Envoy upstream·mTLS는 [Istio 운영](istio.md)을 따른다. |
| Istio 403·메시 통신 실패 | AuthorizationPolicy, PeerAuthentication, 실제 데이터플레인 모드와 proxy/ztunnel 상태를 [Istio 운영](istio.md)에서 확인한다. |
| LoadBalancer Pending | 실제 LB 컨트롤러, ServiceLB Pod 스케줄링과 hostPort 충돌, node 선택 조건. MetalLB를 설치되어 있다고 가정하지 않는다. |
| PVC Pending/마운트 실패 | PVC/PV/StorageClass, provisioner/CSI events, capacity, access mode, binding mode, node affinity, reclaim policy. |

`describe pod`, 로그와 events에도 민감한 값이 들어갈 수 있다. 조사 목적에 필요한 필드만 추출하거나 안전한 위치에서 마스킹하고 공유한다.

## 호스트 조회

SSH 호스트와 서비스 이름을 inventory에서 확인한다. 접속할 수 없으면 가능한 Kubernetes API/로컬 분석을 마치고 호스트 검증이 미수행임을 보고한다. 임의로 다른 호스트를 탐색하지 않는다.

확인된 노드에서 `systemctl is-active k3s` 또는 `k3s-agent`, 최근 `journalctl -u` 로그, `df -h`, `df -i`, `free -m`, 시각 동기화와 필요한 포트만 조회한다. systemd 환경 파일과 서비스 인자에는 토큰·DB URL이 있을 수 있으므로 `systemctl cat`/`show`의 원문을 대화로 덤프하지 않는다.

원인 가설 하나마다 검증할 관측값을 정한다. 재시작으로 일시 해소되어도 원인이 증명되었다고 보고하지 않는다.

## K3s 특이점

- Istio는 K3s 번들 구성요소라고 가정하지 않는다. 실제 설치 버전·namespace·gateway Service와 관리 원본을 찾는다.
- ServiceLB는 호스트 포트를 사용한다. Istio gateway의 외부 노출 방식과 80/443 충돌을 확인하고, 기존 ingress가 남아 있으면 [전환 절차](istio.md)를 따른다.
- local-path PVC는 노드 로컬 데이터다. 다른 노드로 Pod를 옮기는 것만으로 데이터가 따라오지 않는다.

근거: [K3s networking services](https://docs.k3s.io/networking/networking-services), [Volumes and Storage](https://docs.k3s.io/add-ons/storage). 문서 확인일: 2026-09-07.
