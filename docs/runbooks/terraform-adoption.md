# 기존 OCI A1 Terraform 편입

현재는 **코드 준비만 완료할 단계**다. OCI API 인증·기존 인스턴스 정보·backend 확인은 보류하고 SSH는 열지 않는다. 아래 실제 편입 절차는 후속 실행 요청과 사전 확인 후 진행한다.

후속 방향은 기존 A1을 유지한 채 [깨끗한 OS로 재구축](os-rebuild.md)하는 것으로 합의했다. 이 문서의 편입 단계는 여전히 무변경 기준이며 OS/부트 볼륨 교체는 별도 단계다.

## 현재 코드의 범위

[환경 root](../../terraform/environments/oci-a1/README.md)는 `oci_core_instance.nodes["node01"]`처럼 안정적인 주소로 기존 A1을 표현한다. `node01`은 예시 키이며 최초 편입 전에 정하고, 이후 역할이나 IP가 바뀌어도 키를 바꾸지 않는다.

- 노드 기본값 `{}`, `adoption_reviewed = false`.
- 각 노드에는 실제 기존 인스턴스 OCID가 필수다. import block은 같은 키의 resource를 대상으로 한다.
- `prevent_destroy = true`, `preserve_boot_volume = true`를 둔다. 보호 장치는 백업을 대체하지 않으며 구성 제거·외부 삭제를 모두 막는 것도 아니다.
- VCN/subnet/NSG/추가 볼륨은 만들거나 별도 import하지 않는다. 기존 subnet·NSG ID 참조만 가능하다.
- `create_vnic_details`와 `source_details`는 기존 인스턴스의 구성을 표현하기 위한 provider 필드다. 필드 이름에 create가 있다고 새 VNIC 생성을 요청한 것은 아니지만, 잘못된 값은 교체/변경을 유발할 수 있다.
- SSH 연결·보안 규칙 개방·cloud-init 실행·provisioner·Ansible·Kubernetes provider는 없다.
- OS, ARM64 이미지 여부, K3s 설치 상태, 실제 접속 가능 여부는 아직 확인하지 않았다. `role`은 inventory에 전달할 선언이지 설치 결과가 아니다.

## 1. 실제 작업 전 확인

1. OCI tenancy, compartment, region, 인스턴스 OCID와 인증 주체의 API 권한을 확인한다. 루트 compartment에 있는 인스턴스는 `compartment_id`에 tenancy OCID를 사용한다. SSH 인증과는 별개다.
2. 다른 Terraform workspace/state에 이미 관리 중인지 확인한다. 이미 관리 중이면 중복 import하지 않고 기존 주소와 관리 경로를 보존한다.
3. backend·workspace·state 잠금·접근 통제·암호화·백업/복구 경로를 선택한다. **backend 선언이 없으면 Terraform은 local state를 사용하므로 실제 init/import/plan/apply 전에 backend를 명시해야 한다.** 현재 `init -backend=false` 검증은 운영 backend 구성이 아니다. Wasabi 백업 선택도 state backend 선택이 아니다.
4. 기존 state가 있다면 접근 제한된 백업을 확보한다. backend 인증은 A1이 없어져도 접근할 수 있어야 한다.
5. OCI API로 실제 shape/4 OCPU/24GB, AD, 원본 source, subnet, public-IP 설정, NSG, tags, metadata, boot/block volume·attachment와 관리 주체를 조사한다. 전체 metadata/state를 터미널이나 대화에 출력하지 않는다.
6. 예제의 미확정 값은 실제 확인한 값으로 대체한다. 원본 이미지가 오래되었거나 조회되지 않아도 최신 이미지로 바꾸지 않는다. 기존 agent/platform/launch/availability/extended metadata 설정 등이 이 기본 코드로 표현되지 않으면 **코드를 확장하고 재검증한 뒤** 진행한다. 넓은 `ignore_changes`로 차이를 숨기지 않는다.

## 2. Git 선언과 Doppler 입력

Git에는 검토된 노드 구조·버전·참조만 기록한다. `nodes.tfvars.example`은 schema 안내로 유지하며 실제 값이나 비밀값을 채우지 않는다. 비밀값 없는 실제 노드 선언은 별도 검토된 `.auto.tfvars.json` 등으로 관리할 수 있지만, 현재 `.gitignore`에서 tfvars는 제외되어 있으므로 **해당 파일 경로만 명시적 예외로 검토**해야 한다. 이번 작업에서는 실제 환경 입력 파일을 만들지 않는다.

Doppler의 infra 전용 project/config는 아직 미정이다. API Key 방식의 키 매핑은 아래와 같다. 실제 인증 방식이 다르면 해당 OCI provider 방식으로 조정한다.

| Doppler 키 이름 | 소비 대상 |
| --- | --- |
| `OCI_AUTH` | OCI provider 인증 방식(API Key라면 `APIKey`) |
| `OCI_TENANCY_OCID`, `OCI_USER_OCID` | OCI provider 계정/사용자 |
| `OCI_FINGERPRINT`, `OCI_PRIVATE_KEY` | API 서명 인증; Git/HCL/인자에 값 금지 |
| `OCI_PRIVATE_KEY_PASSWORD` | 암호화된 키에 필요할 때만 공급 |
| `OCI_REGION` | 대상 리전; 명시한 `oci_region` 입력이 있으면 그 값이 우선 |
| `TF_VAR_metadata_by_node` | 기존 metadata 보존에 필요한 경우에만 노드 키 → 문자열 map의 JSON |

기존 metadata에는 user_data 등 비밀정보가 있을 수 있다. sensitive 입력은 화면 표시를 줄일 뿐 state/저장 plan을 암호화하지 않는다. 새로운 K3s token이나 cloud-init을 이 입력으로 설치하지 않는다. 누락된 optional 값이 기존 값을 항상 보존한다고 가정하지 말고 실제 provider plan으로 판단한다.

Doppler 최초 인증은 클러스터 밖의 승인된 인증 경로에서 확보한다. project/config를 명시한 `doppler run`으로 필요한 infra 키만 주입하고, 앱 비밀값이나 전체 Doppler 값을 Terraform에 복사하지 않는다. MCP는 필요하지 않으며 이번에 설정하지 않았다.

## 3. 편입 검토 및 후속 실행

사전 확인과 Git 반영 후 `adoption_reviewed`를 true로 바꾸는 것은 **검토용 plan 허용**이지 apply 승인이 아니다. 실제 실행 환경의 Terraform 버전·lockfile·backend·workspace·Doppler project/config를 고정한다.

1. 선언적 import를 포함한 plan을 보호된 경로에 저장하고 확인한다. 예: `.local/terraform/oci-a1/adoption.tfplan`. plan 원문·JSON은 비밀정보가 있을 수 있으므로 공개 로그에 올리지 않는다.
2. 최초 편입의 기준은 대상 수만큼 import하고 **새 인스턴스 생성·기존 인스턴스 변경·교체·삭제가 없는 것**이다. 차이가 있으면 적용하지 않고 입력/schema를 실제 값과 대조한다. `preserve_boot_volume` 등 provider의 로컬 state 전용 설정 차이도 일반 변경과 분리해서 원인을 확인하고 별도 검토한다.
3. import block을 포함한 apply는 import뿐 아니라 plan의 다른 변경도 실행한다. 따라서 import라는 이유로 apply를 안전하다고 가정하지 않는다. 검증한 Git revision·동일 입력·저장 plan의 실행은 후속 승인 범위에서만 진행한다.
4. 편입 후 다시 plan으로 변경 없음과 실제 OCI ID·사양·볼륨 보존을 확인한다. 실제 편입 전에는 이 검증을 통과했다고 보고하지 않는다.
5. 잘못된 state 연결을 발견하면 중단하고 백업·정확한 주소를 대조해 별도 state 복구 계획을 세운다. `destroy`, 재생성 또는 임의 state 삭제로 되돌리지 않는다.

이 단계에는 SSH가 필요 없다. 편입 후 [OS 교체 절차](os-rebuild.md)의 데이터·이미지·복구 점검을 완료하고 별도로 재구축한다. 새 OS의 SSH·사용자·권한을 확인한 뒤 [inventory](../../ansible/inventories/oci-a1/README.md) 연결과 Ansible 설치를 진행한다. outputs에 public IP가 있다고 SSH가 허용되거나 그 주소를 inventory로 선택해야 하는 것은 아니다.

## 4. 추후 노드 확장

기존 A1 agent를 편입할 때는 다른 안정적인 키·OCID·실제 사양을 map에 추가할 수 있다. 현재 server 1대의 4 OCPU·24GB를 기본값으로 모든 노드에 복제하지 않는다.

**아직 존재하지 않는 A1 생성은 이번 코드 범위가 아니다.** 실제 증설 요청 시 creation/import 입력을 명확히 분리하고 quota·이미지 ARM64·네트워크·키·용량·Ansible 가입을 설계한다. import OCID에 가짜 값을 넣거나 import block을 지워 신규 생성을 우회하지 않는다. 같은 환경을 확장하며 노드마다 Argo CD를 복제하지 않는다.

## 공식 근거

- [OCI instance resource 및 import 형식](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/core_instance.html)
- [OCI provider 인증 환경변수](https://docs.oracle.com/en-us/iaas/Content/dev/terraform/configuring.htm)
- [Terraform import](https://developer.hashicorp.com/terraform/language/import)
- [Terraform mock/override 테스트](https://developer.hashicorp.com/terraform/language/tests/mocking)

작성 기준: 2026-09-07. 코드 검증과 실제 환경 편입 검증은 구분한다.
