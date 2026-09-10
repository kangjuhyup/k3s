# 초기 인프라 단계별 구현

아래는 단계별 구현 당시 기록이다. 2026-09-11부터 고정 앱 생성기 대신 Git 매니페스트를
직접 관리하며 `scripts/gitops_validate.py --repo-root .`로 검사한다.
계정·Doppler 생성과 inventory·런타임 비밀값 처리는 유지한다.

실제 OCI·SSH·Doppler 접속 없이 코드를 구현하고 로컬에서 검증한다. 기존 인스턴스 편입과 OS 교체는 별도 운영 작업이며 설치 코드가 데이터를 삭제하지 않는다.

각 단계의 **입력 파일·키 이름·값·Doppler 보관 위치**는 [설정값 입력 안내](../runbooks/configuration-inputs.md)에 모았다. 구현된 필드와 후속 설계 항목을 구분한다.

## 단계와 완료 경계

1. Ansible: 명시적 inventory, 입력/호스트 사전 점검, ARM64 K3s 첫 server 설치·agent 가입, 서비스/API/Node Ready 검사. 고정 버전·체크섬을 필수 입력으로 사용한다. 실제 호스트 검증은 SSH 개방 후 수행한다.
2. Argo CD: 최소 bootstrap, Git 인증 연결, 루트 Application/AppProject, 자기관리 인계, 준비된 계정 values 연결.
3. Istio: 호환 버전·모드·노출 경로 결정 후 GitOps 선언, CRD/컨트롤러/라우팅 준비 검사.
4. Doppler: 연동 주체·키 매핑 결정, 제한된 최초 인증, Secret 동기화와 소비 확인.
5. Wasabi: datastore·앱 데이터별 백업, 보존 정책, 복구에 필요한 token 이력, 복원 시험.
6. 전체 초기화 검증과 운영 진입점: 단계별 실패 중단, 실행 revision·대상 기록, 자동화 검사.

## 1단계 설계

- 비밀값 없는 inventory와 환경 설정은 Git 원본이다. 실제 token은 컨트롤러에 Doppler로 주입된 환경변수만 읽고 보호된 원격 파일로 전달한다. 환경변수 이름은 설정에 명시한다.
- 사용자가 기존 A1의 OS를 Ubuntu로 확인했다. Ubuntu ARM64/systemd/cgroup v2의 apt 준비 경로를 구현한다. 정확한 Ubuntu 버전은 추후 확인하고 실제 버전과 검토한 입력이 일치해야 한다. 다른 OS는 실행하지 않는다.
- datastore는 신규 단일 server의 SQLite만 지원한다. 이는 이번 구현의 제한이며 HA 요구나 기존 DB 전환을 의미하지 않는다. 실행자가 SQLite를 명시적으로 선택해야 한다.
- Flannel VXLAN, Traefik 비활성화. ServiceLB 사용 여부·CIDR·DNS·TLS SAN·인터페이스·노드 IP는 필수 명시 입력이다. 방화벽은 자동 해제하지 않고 사전 검토 기록을 요구한다.
- 공식 ARM64 바이너리를 버전과 SHA256으로 고정해서 받는다. 직접 관리하는 systemd unit/config만 사용하며 원격 latest 설치 스크립트를 실행하지 않는다.
- 첫 설치는 K3s 데이터/설정/서비스가 없는 호스트에서만 허용한다. 재실행은 이 코드의 완료 기록·동일 입력/바이너리/config/token/unit이 확인될 때만 허용한다. 업그레이드·기존 설치 편입·token 회전·설정 변경은 별도 구현 전 차단한다.
- server 설치와 agent 가입 진입점을 분리한다. agent 작업은 기존 server에 위임하거나 쓰지 않으며 준비 상태는 별도 읽기 전용 server 검증 playbook에서 확인한다.
- check mode에서 미완성 신규 설치를 성공으로 오인시키지 않는다. 사전 점검은 별도 read-only playbook으로 제공하고 설치 playbook의 check mode는 차단한다.
- 이 1단계 범위에서는 Argo CD 이후 단계를 구현 완료로 표시하지 않는다. 후속 진행은 아래 단계별 상태를 따른다. account admin 전환과 OS 교체는 일괄 자동 실행에 포함하지 않는다.

## 로컬 검증 계획

- 실제 Ansible의 syntax-check, 합성 inventory list-hosts, 로컬 입력 검증의 정상/실패 사례.
- template 렌더링과 비밀값 분리, 기존 설치/입력 변경 차단, 단계 순서에 대한 회귀 검사.
- 기존 Argo CD 계정 테스트 및 Markdown 링크 검증.
- 원격 설치·재실행 멱등성·CNI/DNS/PVC·실제 로그인은 로컬 검사로 대체하지 않는다.

## 1단계 코드 검증 결과 (2026-09-09)

- K3s 입력/렌더링/inventory 8개, 실제 Ansible controller 검사 5개, 기존 Argo CD 검사 12개: 총 25개 통과. Ansible의 기존 상태 검사 테스트에는 동일 계약 허용, 깨끗한 호스트 허용, 바이너리/config/token/unit/설정 변경·DB 유실·미관리 경로·실행 중 프로세스 거부 사례가 포함된다.
- Python 3.12.14, ansible-core 2.21.4, ansible-lint 26.8.0으로 검사했다. native 바이너리 입력 없이 Python 3.9로 실행하면 일반 테스트 18개 통과, 선택적 native 테스트 7개는 건너뛴다.
- 5개 playbook syntax-check, 합성 agent limit 검사, ansible-lint 실패 0개·경고 0개, 계정 생성물 일치 검사를 확인했다. Markdown 상대 링크와 셸 예제 구문도 확인했다.
- 운영 입력은 비어 있다. Terraform 선별 outputs의 자동 매핑, 실제 설치·재실행, 원격 네트워크/방화벽, 전체 DNS/CNI/PVC 검증은 완료하지 않았다.
- **1단계는 코드·로컬 검증 완료이며 인프라 구축 완료가 아니다.** 다음은 2단계 Argo CD bootstrap/GitOps 인계다. Git URL/revision·인증 참조와 고정 설치 버전·Secret 소유권을 확인하며 구현한다.

## 2단계 진행 (2026-09-09)

[구현 설계](2026-09-09-argocd-bootstrap-plan.md)와 [운영 안내](../runbooks/argocd-bootstrap.md)에 따라 Argo CD 최소 bootstrap·GitOps 선언 생성·자기관리 인계 코드를 추가했다. 공식 chart, ARM64 image digest, ClusterIP/TLS, 계정 values 연결, 초기 Secret 분리와 재실행 시 Kubernetes 쓰기 방지를 구현했다.

실제 Git URL/branch·Doppler project/config·Kubernetes 버전이 비어 있어 활성 선언 생성과 실제 실행은 차단된다. 이번에도 원격 접속/설치는 하지 않는다. 후속 진행은 아래 상태를 따른다.

## 3단계 진행 (2026-09-09)

[Istio 운영 안내](../runbooks/istio-bootstrap.md)에 따라 Istio 1.30.4의 base/istiod/gateway를 하나의 Application으로 연결하는 생성기·values·입력 gate·로컬 chart 검사기를 준비했다. 동일 sync의 CRD Established → istiod Healthy → gateway 순서를 사용하며 공식 ARM64 image digest와 chart checksum을 고정했다.

sidecar/istio-system/내부 ClusterIP는 명시적 baseline이다. 현재 `enabled=false`, `reviewed=false`라 활성화하지 않았다. 이후 사용자 요청에 따라 아래 외부 노출 확장을 추가했다. 이는 코드 준비이지 ingress 개통 완료가 아니다. 4단계 Doppler 지속 동기화, 5단계 Wasabi 백업과 6단계 종합 실행/운영 검증은 남아 있다.

로컬 검증: 선택적 native 도구를 모두 지정한 51개 테스트 통과, 공식 Istio chart 3개의 38개 리소스 렌더링·프로젝트 권한 검사, Argo CD CLI의 CRD health Lua 검사, ansible-lint 실패/경고 0개를 확인했다. 공식 chart index의 SHA256과 archive를 대조했고 pilot/proxyv2 OCI index의 linux/arm64 지원을 확인했다. native 도구 미지정 시 38개 통과·13개 건너뜀이며 원격 설치 성공을 의미하지 않는다.

### 3단계 외부 노출 확장

사용자 선택인 [K3s ServiceLB 외부 ingress](../runbooks/istio-external-ingress.md)를 준비했다. 80/443만 노출하고 NodePort 자동 할당·상태 포트 외부 노출을 막는다. HTTP→HTTPS, 정확한 host/Secret 참조, backend FQDN 라우팅, gateway ISTIO_MUTUAL, 앱 namespace sidecar label·STRICT PeerAuthentication을 생성한다. 외부 활성화 전에 Git K3s 설정의 ServiceLB/버전 일치를 검사하고 인증서·네트워크 수동 확인을 요구한다.

실제 도메인·인증서·backend 값은 사용자 지시로 나중에 입력한다. 인증서 발급/갱신·Doppler TLS Secret 전달·실제 mTLS/외부 트래픽 검증은 아직 수행하지 않았다. 전체 클러스터 모든 트래픽에 mTLS가 적용되었다고 해석하지 않는다.

확장 후 로컬 검사: native 도구 포함 58개 테스트, ServiceLB gateway chart 렌더링, 고정 Istio CRD의 생성 필드/enum 검사, ServiceLB 비활성·버전 불일치·미검토 입력·기존 route 제거 차단을 확인했다. ansible-lint 실패/경고 0개다. 실제 인증서/포트/ServiceLB helper 이미지·Pod/mTLS 검증은 로컬 검사에 포함하지 않았다.

## 4단계 코드 준비

Doppler Operator 1.7.1의 checksum·ARM64 image digest를 고정하고, 공식 chart를 제한된 RBAC·보안 설정으로 변환해 Git에 두었다. root 생성기에 Operator AppProject/Application과 환경 매핑을 연결했다. 최초 설치(sync 비활성) → 최소 인증 Ansible create → 대상 확인 → Git의 sync 활성화 순서다.

[4단계 runbook](../runbooks/doppler-bootstrap.md)에 정확한 입력·단계별 gate·소유권·조회 검증·실패/복구 제약을 기록했다. 기존 Secret 덮어쓰기·Deployment 자동 reload·Git prune 없는 동기화 제거를 차단한다. 기본값은 비활성·빈 매핑이다.

Doppler의 앱/TLS 값 전달 코드까지 준비했다. TLS 발급·자동 갱신 방식은 아직 선택이 필요하며 Wasabi 백업·종합 운영 검증은 미구현이다. 실제 API/SSH/Doppler 연결·Git push·배포·인증서 검증은 수행하지 않았다.

추가 후 로컬 검사: native 도구 포함 72개 테스트 통과, 고정 Doppler chart 렌더링·CRD 필드·프로젝트 권한·실제 Argo CD Lua health 검사. ansible-lint 실패/경고 0개, Markdown 43개·로컬 링크 273개·셸 블록 20개 오류 없음. 실제 기본 입력으로 선언 생성은 의도대로 차단됨을 확인했다.

## 자동 TLS 공통 기반

사용자는 인증서 자동 발급·갱신을 선택했다. cert-manager 1.21.1의 chart checksum과 ARM64 image digest, 단일 A1 자원 baseline, GitOps Application/AppProject·namespace와 오프라인 검사를 추가했다. 기본 비활성이며 실제 인증서는 발급하지 않았다.

DNS 업체가 미확인이라 provider별 DNS-01 solver·Doppler DNS 인증 매핑·Issuer·Certificate는 아직 구현하지 않았다. 실제 도메인·이메일·인증값은 나중에 채우고, 먼저 업체명 확인이 필요하다. [자동 TLS 절차](../runbooks/tls-automatic.md)에 구현/미구현과 설정 위치를 구분했다.
