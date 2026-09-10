# OCI A1 K3s Infrastructure

OCI Ampere A1 ARM64에서 K3s·Istio를 운영하기 위한 인프라 저장소다. 초기 기준은 A1 1대, 4 OCPU·24GB RAM이며 추후 같은 클러스터에 agent를 추가한다.

현재는 기존 A1 Terraform 편입, Ubuntu ARM64 Ansible K3s 설치·agent 가입, Argo CD bootstrap·자기관리, Istio ServiceLB 외부 TLS 라우팅·앱 namespace STRICT mTLS, **Doppler Operator·최소 인증·Secret 동기화 코드**를 준비한 단계다. 실제 OCI·SSH·Kubernetes·Doppler 접속이나 배포는 하지 않았다. Git URL·도메인 등 운영 입력은 미확정이며 활성 GitOps 선언은 아직 생성하지 않았다. 자동 TLS용 cert-manager 공통 설치도 준비했으며, DNS 업체별 발급 연결·Wasabi 백업·종합 운영 검증은 남아 있다. 코드 준비는 운영 인프라 구성 완료가 아니다.

**어디에 어떤 값을 넣는지:** [단계별 설정값 입력 안내](docs/runbooks/configuration-inputs.md). Terraform 사전 준비부터 1~6단계까지 파일·키·값·Doppler 참조와 미구현 항목을 구분한다.

[Ansible 1단계 안내](ansible/README.md)와 [단계별 구현 계획](docs/architecture/2026-09-09-bootstrap-stages.md)을 따른다. 기존 A1의 Ubuntu를 전제로 하며 실제 버전은 추후 확인한다. 최초 실행으로 전체 플랫폼을 설치하는 상태는 아직 아니다.

[2단계 Argo CD bootstrap 안내](docs/runbooks/argocd-bootstrap.md)는 고정 chart·ARM64 이미지·기존 계정 values를 연결하고, 최초 seed 이후 GitOps 인계를 검증한다. 현재 Git/Doppler 입력과 실제 로그인 검증은 남아 있다.

[3단계 Istio 안내](docs/runbooks/istio-bootstrap.md)는 CRD Established → istiod Healthy → gateway 순서와 고정 ARM64 이미지를 검증한다. [외부 노출 확장](docs/runbooks/istio-external-ingress.md)은 사용자 선택인 K3s ServiceLB의 80/443, HTTP→HTTPS, 인증서 Secret 참조, Gateway/VirtualService 및 지정 앱 namespace STRICT mTLS를 구성한다. 기본 비활성이며 실제 도메인·인증서·backend 값은 나중에 입력한다.

[4단계 Doppler 안내](docs/runbooks/doppler-bootstrap.md)는 Operator 고정 버전·ARM64 이미지, 최초 인증 Secret 생성, 앱/TLS 키 매핑과 읽기 전용 검증을 연결한다. 기본은 비활성이며 인증 토큰 회전은 포함하지 않는다. [자동 TLS 단계](docs/runbooks/tls-automatic.md)는 cert-manager 공통 설치까지 준비했고 DNS 업체 확인 후 발급 연결을 완성한다.

[Argo CD 개인 계정/RBAC values 생성 도구](gitops/platform/argocd/README.md)도 준비했다. 기본 admin은 초기 설정에만 쓰고, 검증한 개인 관리자와 개발자 계정으로 전환한다. 현재 실제 계정 목록은 비어 있으며 설치·비밀번호 주입·계정 발급은 수행하지 않았다.

## 역할

| 도구 | 담당 |
| --- | --- |
| Terraform | OCI 인스턴스·관련 네트워크·볼륨 |
| Ansible | 호스트 준비, K3s 설치·설정·노드 가입, 최소 Argo CD bootstrap |
| Argo CD | 자기관리, Istio·애드온·앱의 GitOps 배포 |
| Doppler | 환경별 런타임 환경변수·비밀값의 원본 |
| Wasabi Object Storage | K3s·앱 데이터의 노드 외부 백업 사본 |

## 디렉터리

```text
infrastructure/
├── .agents/skills/k3s-infra/       # 기존 운영 스킬
├── .gitignore                    # 비밀값·state·생성 파일 제외
├── terraform/
│   ├── environments/oci-a1/       # 환경별 Terraform root
│   └── modules/                   # 재사용 OCI 모듈
├── ansible/
│   ├── inventories/oci-a1/        # 환경별 inventory 원본과 참조
│   ├── playbooks/                 # 작업 진입점
│   └── roles/
│       ├── k3s_preflight/
│       ├── host_prepare/
│       ├── k3s_server/
│       ├── k3s_agent/
│       ├── k3s_install/
│       ├── k3s_verify/
│       └── argocd_bootstrap/
├── gitops/
│   ├── clusters/oci-a1/           # 루트 Application·환경별 연결
│   ├── platform/
│   │   ├── argocd/
│   │   ├── istio/
│   │   └── doppler/               # 연동 선언만, 실제 값 제외
│   └── apps/
├── scripts/                      # 로컬 검증·inventory 생성 유틸리티 자리
└── docs/
    ├── architecture/
    └── runbooks/
```

`oci-a1`은 저장소의 논리적 환경 식별자다. 실제 Kubernetes context·OCI 인스턴스 이름·Doppler project/config를 의미하지 않는다. 노드 증설 시 같은 환경의 노드 정의와 inventory를 확장하며 환경 디렉터리나 Argo CD를 노드마다 복제하지 않는다.

## 다음 구현 순서

1. [구조 설계와 미확정 입력](docs/architecture/repository-layout.md)을 확인한다. 실제 계정·주소·버전·도메인을 추측하지 않는다.
2. [Terraform 환경](terraform/environments/oci-a1/README.md)의 코드를 검증하고, 인증·실제 구성·backend를 확인한 뒤 [기존 A1 편입](docs/runbooks/terraform-adoption.md)을 진행한다. 공통 모듈 추출과 신규 노드 생성은 후속 범위다.
3. 기존 A1은 유지하고 [깨끗한 OS로 재구축](docs/runbooks/os-rebuild.md)한다. 현재 OS와 새 ARM64 이미지의 호환성을 확인한 뒤 별도 작업으로 부트 볼륨을 교체한다. 이전 볼륨은 새 OS 검증까지 보존한다.
4. 새 OS의 SSH를 확인하고 비밀값 없는 outputs에 명시적 호스트 입력을 더해 [inventory](ansible/inventories/oci-a1/README.md)를 구성한다. 준비된 [playbook](ansible/playbooks/README.md)의 사전 점검·설치·검증을 단계별로 실행한다.
5. 최소 Argo CD bootstrap 후 [클러스터 GitOps 연결](gitops/clusters/oci-a1/README.md)을 통해 platform과 앱을 반영한다.
6. [운영 절차](docs/runbooks/README.md)에 실제 대상·검증·복구 기준을 기록한다.

이 순서는 후속 구현의 안내이며 실행 명령이 아니다. Terraform apply/import, Ansible 호스트 실행, Argo CD sync와 Doppler 변경은 실제 요청 범위에서만 수행한다.

## 비밀값과 생성 파일

Git에는 인프라·배포 선언과 Doppler 참조만 저장한다. `.env`, 토큰, 개인키, kubeconfig, Terraform state/plan, 백업 내용을 커밋하지 않는다. 로컬 생성 inventory 등은 `.local/` 아래에 두고 원본처럼 수정하지 않는다. 노드 외부 백업 사본은 Wasabi에 보관하고 접속 자격 증명은 Doppler에서 공급한다. 실제 bucket·region·전송 도구·보존 정책은 아직 미정이며 업로드·복구를 수행한 상태가 아니다. Wasabi 선택은 Terraform state backend나 앱의 실시간 저장소 선택을 의미하지 않는다.

`.gitignore`는 파일명 기반의 실수 방지 장치일 뿐 비밀값 검사·암호화·접근 통제를 대체하지 않는다. `.example` 파일에도 실제 값을 넣지 않는다. Terraform `.terraform.lock.hcl`은 버전 관리 대상이다. 공개 인증서 PEM을 의도적으로 관리해야 하면 그 경로만 검토해 예외를 추가한다.

## 운영 지침과 검증 범위

- [K3s 인프라 스킬](.agents/skills/k3s-infra/SKILL.md)
- [GitOps 필수 정책](.agents/skills/k3s-infra/references/gitops.md)
- [Doppler 운영](.agents/skills/k3s-infra/references/doppler.md)
- [Wasabi 백업](.agents/skills/k3s-infra/references/wasabi.md)
- [유틸리티와 검증 범위](scripts/README.md)

일상 배포·rollback은 Git 변경으로 수행한다. 최초 bootstrap과 복구의 제한된 경계는 스킬을 따른다. Doppler MCP는 이 구조에 포함하지 않는다. 런타임은 고정 Doppler Operator를 GitOps로 연결하는 방식이며 실제 입력·활성화는 남아 있다.
