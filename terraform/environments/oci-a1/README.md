# OCI A1 Terraform 환경

이 경로는 기존 OCI A1 편입용 Terraform root다. **코드만 준비했으며 실제 OCI 조회·import·plan·apply는 수행하지 않았다.** SSH도 필요하지 않으며 개방하지 않는다.

Terraform 1.16.1과 `oracle/oci` 9.0.0을 고정하고 lockfile을 관리한다. 실행 머신의 아키텍처와 OCI A1 게스트 ARM64는 별개다. 재사용 경계가 아직 필요하지 않아 resource는 root에 직접 두며 [공통 모듈](../../modules/README.md)은 미구현 상태를 유지한다.

| 파일 | 역할 |
| --- | --- |
| `versions.tf`, `providers.tf` | 버전과 provider 환경변수 인증 |
| `variables.tf`, `nodes.tfvars.example` | 기본 빈 노드 map, 입력 검증·편입 검토 gate, 미확정 입력 예제 |
| `main.tf`, `imports.tf` | 안정적인 `for_each` 주소와 기존 OCID 편입, 교체·삭제 보호 |
| `outputs.tf` | 노드 역할·OCID·IP만 선별 |
| `tests/` | OCI API 대신 mock/override를 쓰는 로컬 테스트 |

**backend는 미정이다.** 선언이 없는 상태에서 실제 작업을 하면 local state가 사용되므로 실제 state 접근 전 backend를 확정해야 한다. Wasabi를 임의 backend로 지정하지 않는다. `adoption_reviewed=false`는 nonempty 노드의 계획을 차단하지만 인증 차단·RBAC 또는 변경 승인 시스템은 아니다.

## 인증 없는 코드 검증

저장소 루트에서 실행한다. `init`은 공개 provider 다운로드만 필요하며 backend 초기화는 건너뛴다. `test`는 모든 OCI 작업을 mock/override로 대체한다.

```bash
rtk proxy terraform -chdir=terraform/environments/oci-a1 init -backend=false -input=false
rtk proxy terraform -chdir=terraform/environments/oci-a1 fmt -check -recursive
rtk proxy terraform -chdir=terraform/environments/oci-a1 validate
rtk proxy terraform -chdir=terraform/environments/oci-a1 test
```

mock 테스트는 input 전달·검증·출력 경계를 검사한다. 실제 OCID 존재, provider import 동작, 기존 metadata 보존과 무변경 plan은 확인하지 못한다. `.example`은 Terraform이 자동 로드하지 않으며 placeholder와 null 입력으로 실제 사용을 막는다.

## 후속 편입

노드 입력과 OCI 인증 키별 값은 [설정값 입력 안내](../../../docs/runbooks/configuration-inputs.md#사전-단계-기존-a1-terraform-편입)를 따른다.

사용자는 기존 A1을 유지하면서 OS부터 새로 구축하기로 했다. 이 root는 무변경 편입용으로 유지하며, [OS/부트 볼륨 교체](../../../docs/runbooks/os-rebuild.md)는 별도 검토 작업이다. 이미지 입력 변경이나 `adoption_reviewed`만으로 초기화를 실행하지 않는다.

기존 A1의 state/import 여부, OCI 범위·이미지·네트워크·볼륨을 먼저 확인한다. 노드 추가만으로 기존 server나 데이터 볼륨을 교체하지 않게 plan을 검증한다. 비밀값은 Doppler에서 필요한 실행 변수로 주입한다.

Ansible에 전달할 outputs는 노드 키·역할·OCID·접속 주소 등 필요한 비밀값 없는 필드로 한정한다. token·kubeconfig·전체 state를 출력하지 않는다. 생성 inventory의 위치는 [inventory 안내](../../../ansible/inventories/oci-a1/README.md)를 따른다.

실제 실행 지침: [기존 A1 편입 runbook](../../../docs/runbooks/terraform-adoption.md), [Terraform 운영 스킬](../../../.agents/skills/k3s-infra/references/terraform.md). 신규 VM 생성·Ansible 설치·GitOps manifest는 이번 코드에 포함하지 않는다.
