# 저장소 구조 설계

2026-09-07 사용자가 승인한 역할별 디렉터리 구조를 기준으로 한다.

## 범위

저장소 골격 단계에서는 디렉터리와 안내 문서, Git 제외 규칙만 생성했다. 이후 [기존 A1 편입 계획](2026-09-07-terraform-adoption-plan.md)에 따라 Terraform resource·import 선언·mock 테스트를 추가했다. [단계별 구현](2026-09-09-bootstrap-stages.md)의 1단계로 Ubuntu ARM64 Ansible 설치·가입 playbook과 inventory 생성기를, [2단계](2026-09-09-argocd-bootstrap-plan.md)로 Argo CD 최소 bootstrap·GitOps 선언 생성·자기관리 인계 코드를 추가했다. 실제 Git 입력이 미정이라 활성 Application은 생성하지 않았으며 접속·편입·설치도 하지 않았다. 이후 Istio ServiceLB ingress·mTLS와 Doppler Operator·최소 인증·Secret 매핑 코드를 추가했다. 인증서 자동 발급·Wasabi 백업·종합 운영 검증은 후속 단계다. 기존 스킬은 보존한다.

## 확정된 기준

- OCI Ampere A1 ARM64 1대, 4 OCPU·24GB RAM에서 시작한다.
- 기존 A1은 Terraform에 무변경 편입한 뒤, 호환성 확인 후 별도로 부트 볼륨을 교체하여 깨끗한 OS에서 재구축한다. 기존 K3s 구성을 그대로 인계하지 않는다. [OS 재구축 절차](../runbooks/os-rebuild.md)에 따라 이전 볼륨은 새 OS 검증까지 보존하며 현재는 실제 교체를 실행하지 않는다.
- OCI 리소스는 Terraform, 호스트·K3s 설치와 노드 가입은 Ansible로 관리한다.
- Istio·애드온·앱의 선언은 Git, 반영은 Argo CD가 담당한다.
- 환경별 런타임 환경변수·비밀값의 원본은 Doppler다. Git에는 참조와 주입 선언만 둔다.
- 노드 외부 백업 사본은 Wasabi Object Storage에 보관하고 접속 자격 증명은 Doppler로 공급한다. Wasabi bucket·전송 도구·보존 정책과 Terraform state backend는 별도 미확정 사항이다.
- 증설은 같은 클러스터에 A1 agent를 추가하는 경로를 기본으로 한다. HA 전환은 별도 작업이다.
- 최초 Argo CD와 필요한 인증 연결만 Ansible로 bootstrap하고 이후 자기관리를 Argo CD로 인계한다.

## 경로와 책임

| 경로 | 책임 |
| --- | --- |
| `terraform/environments/oci-a1/` | 해당 환경의 Terraform 실행 root와 노드 정의 |
| `terraform/modules/` | 환경에서 재사용할 OCI 리소스 모듈 |
| `ansible/inventories/oci-a1/` | 환경의 비밀값 없는 inventory 원본·변수 참조 |
| `ansible/playbooks/` | 설치·가입·bootstrap·유지보수 작업 진입점 |
| `ansible/roles/host_prepare/` | Linux 호스트 공통 준비 |
| `ansible/roles/k3s_server/` | K3s server 설치·설정 |
| `ansible/roles/k3s_agent/` | K3s agent 설치·가입 |
| `ansible/roles/argocd_bootstrap/` | 최소 Argo CD bootstrap과 소유권 인계 |
| `gitops/clusters/oci-a1/` | 루트 Application, AppProject, 환경별 연결과 설정 |
| `gitops/platform/argocd/` | Argo CD 자기관리 원본 |
| `gitops/platform/istio/` | Istio 공통 배포·정책 원본 |
| `gitops/platform/doppler/` | Doppler 연동의 공통 주입 선언, 실제 값 제외 |
| `gitops/apps/` | 앱별 재사용 배포 원본 |
| `scripts/` | 추후 로컬 검증·inventory 생성 유틸리티 |
| `docs/architecture/` | 구조·설계·구현 전 결정 사항 |
| `docs/runbooks/` | 환경별 증설·백업·복구 절차의 진입점 |

`oci-a1`은 저장소 안의 논리적 환경 식별자다. 실제 Kubernetes context, OCI 리소스 이름, Doppler project/config 이름이 아니다. 노드가 추가되어도 이 환경 경로를 복제하지 않는다. 새로운 클러스터가 필요할 때만 새 환경 경로를 추가한다.

## 경계와 데이터 흐름

Terraform의 선별된 비밀값 없는 node outputs를 inventory 생성 입력으로 사용한다. 생성 inventory는 `.local/ansible/oci-a1/`에 두고 Git 원본과 구분한다. 자격 증명은 Doppler에서 실행 시 주입하며 전체 Terraform state나 Doppler config를 inventory에 복사하지 않는다.

Ansible의 bootstrap 완료 후 Argo CD가 GitOps 경로를 읽는다. 공통 platform/apps 원본과 클러스터별 연결을 분리하며 동일 리소스를 여러 Application·도구가 동시에 소유하지 않는다. Doppler 연동이 생성하는 Secret data는 Argo CD 관리 원본에 넣지 않는다.

일반 배포·rollback은 Git 변경으로 처리한다. Git rollback과 Doppler 값 복원, datastore/PVC 복원은 별도다. 기존 스킬의 [GitOps 정책](../../.agents/skills/k3s-infra/references/gitops.md)과 [Doppler 정책](../../.agents/skills/k3s-infra/references/doppler.md)을 따른다.

## 구현 전에 확인할 입력

현재는 다음 값을 확정하지 않았으므로 실행 설정에 가짜 기본값을 만들지 않는다.

- OCI tenancy/compartment/region, 기존 인스턴스 OCID·이미지·OS, 네트워크·볼륨 관리 현황.
- Terraform backend·state와 잠금 경로. 코드 검증 기준은 Terraform 1.16.1·OCI provider 9.0.0으로 고정했으며 실제 운영 도입 시 검토한다.
- SSH 접속과 API endpoint, 현재 K3s 설치·datastore, K3s·Istio·Argo CD 버전 및 Istio 모드.
- Git 저장소 URL·반영 branch·인증, Doppler project/config·키 매핑·최초 인증의 실제 값. Kubernetes 동기화는 Doppler Operator GitOps로 코드 준비했다.
- DNS·TLS 발급/갱신(ServiceLB 외부 노출은 선택됨), 런타임 스토리지, Wasabi bucket·region·endpoint·prefix·백업 도구·보존 정책, CI 실행 환경.

## 완료 기준

승인한 경로가 파일과 함께 존재하고 문서의 상대 링크가 유효해야 한다. `.gitignore`는 비밀값·state·plan·생성 파일을 제외하되 Terraform lockfile, 배포 선언, 스킬과 안내 문서는 제외하지 않아야 한다. 추가된 Terraform 코드는 fmt·validate·mock 테스트로 검증한다. 공개 도구/provider 다운로드 외에 OCI·Doppler API 인증·배포는 실행하지 않는다.
