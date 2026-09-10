# Existing A1 Terraform Adoption Implementation Plan

> **For agentic workers:** 구현과 검증은 이 저장소에서 수행한다. 사용자 범위는 코드 준비뿐이며 commit/push, 실제 import/plan/apply, SSH, Doppler 접근은 제외한다.

**Goal:** 기존 A1을 나중에 재생성 없이 편입할 Terraform 코드와 인증 없는 검증을 준비한다.

**Architecture:** 환경 root에 안정적인 노드 map과 `for_each` 인스턴스, 선언적 import를 둔다. 이번 단계에서는 기존 인스턴스 OCID가 있는 노드만 허용하며 새 인스턴스 생성은 구현하지 않는다. 관련 네트워크는 ID로 참조하고 소유권을 가져오지 않는다.

**Tech Stack:** Terraform 1.16.1, oracle/oci 9.0.0, Terraform mock-provider tests.

**Spec:** [기존 저장소 설계](repository-layout.md)와 사용자의 기존 A1 편입·SSH 보류·코드만 준비 요청.

## 제약과 설계 결정

- A1 ARM64, 초기 4 OCPU·24GB, 역할은 server/agent. 노드 키는 역할이나 IP 변경과 독립적이다.
- 기존 설정은 아직 미확인이다. 입력 예제는 실행용 값이 아니며 실제 image/boot volume source, AD, subnet, metadata, tags를 대조해야 한다.
- 기본 노드 map은 비어 있다. 구성 확인 플래그 기본값은 false이며 nonempty map의 리소스 계획을 precondition으로 차단한다.
- `prevent_destroy`로 교체·삭제를 제한하지만 구성 제거·외부 삭제·잘못 승인한 변경까지 보장하지 않는다.
- backend를 임의로 선택하지 않는다. 실제 state 접근 전에 backend와 잠금·복구 경로를 별도 확정한다.
- OCI 인증은 provider 환경변수로 Doppler에서 주입한다. 비밀 metadata는 별도의 sensitive 입력이며 outputs에는 포함하지 않는다.
- Terraform은 SSH, cloud-init, provisioner, K3s·Argo CD 설치를 실행하지 않는다.
- native mock 테스트는 실제 import 가능 여부나 무변경 plan을 보장하지 않는다.

## 구현 순서

- [x] `terraform/environments/oci-a1/tests/adoption.tftest.hcl`: 빈 기본값, 승인 차단, server 입력 전달, 잘못된 역할·중복 OCID 검증을 먼저 작성하고 미구현 상태의 실패를 확인한다.
- [x] 같은 root의 `versions.tf`, `providers.tf`, `variables.tf`, `main.tf`, `imports.tf`, `outputs.tf`: 기존 인스턴스 편입과 선별 outputs를 구현한다.
- [x] `nodes.tfvars.example`, 환경 README와 `docs/runbooks/terraform-adoption.md`: 미확정 입력, Doppler 키 매핑, no-op 편입 기준과 SSH 보류를 문서화한다.
- [x] 공개 배포 파일의 SHA256을 검증한 임시 Terraform으로 `init -backend=false`, `validate`, `fmt -check`, mock `test`를 수행한다. provider lockfile을 보관한다.
- [x] 독립 코드 리뷰와 링크·Git 제외 규칙 검증 후 실제 실행하지 않은 범위를 보고한다.

## 검증 명령

아래는 저장소 루트에서 실행한다. 일반 plan/import/apply 명령은 검증에 포함하지 않는다.

```bash
rtk proxy terraform -chdir=terraform/environments/oci-a1 init -backend=false -input=false
rtk proxy terraform -chdir=terraform/environments/oci-a1 fmt -check -recursive
rtk proxy terraform -chdir=terraform/environments/oci-a1 validate
rtk proxy terraform -chdir=terraform/environments/oci-a1 test
```

`init`은 공개 provider 다운로드가 필요하다. `test`는 모든 OCI 호출을 mock으로 대체한다.

## 검증 기록

- Terraform mock/override 테스트 12개 통과. OCI import에는 일반 mock만 사용할 수 없어 테스트 전용 resource override를 추가했다.
- null 노드 입력과 루트 compartment의 tenancy OCID 처리를 실패 테스트로 재현한 뒤 수정했다.
- fmt/validate, Markdown 상대 링크 115개·셸 블록 5개, Git 제외/추적 대상 합성 경로 14개 검사 통과.
- provider lockfile에 darwin_arm64·linux_arm64의 검증된 체크섬을 기록했다.
- 독립 read-only 리뷰에서 발견한 루트 compartment 입력 검증 문제를 수정했고 재리뷰에서 남은 지적 없음.
- 실제 OCI/Doppler/SSH 접근, 운영 state 초기화, 실제 plan/import/apply, commit/push는 수행하지 않았다.
