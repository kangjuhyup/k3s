# Terraform으로 OCI 인스턴스 관리

실행 환경변수·비밀값은 [Doppler](doppler.md)에서 필요한 provider 환경변수/`TF_VAR_*`로 주입한다. 구조·노드 map·버전 선언은 Git에 유지한다. 비밀 tfvars를 별도 원본으로 만들거나 앱 비밀값을 Terraform state로 복사하지 않는다. Doppler 주입도 state/plan의 비밀값 노출을 자동 방지하지 않는다.

구성은 Git으로 관리하며 [GitOps 필수 정책](gitops.md)의 역할 분리를 따른다. 적용할 구성의 Git revision과 검증한 plan·실행 결과를 연결한다. Git에 없는 로컬 수정본을 운영에 적용하지 않는다.

## 관리 범위와 노드 모델

사용자 선택은 Terraform + OCI provider(`oracle/oci`)다. 초기 A1 1대·4 OCPU·24GB를 유지하면서 A1 agents를 추가한다. 인스턴스에 필요한 네트워크·NSG·볼륨은 현재 관리 주체를 확인하고 같은 리소스를 두 state/컨트롤러가 동시에 관리하지 않게 한다. 공유 VCN 등을 임의로 Terraform 소유로 가져오지 않는다. [OCI Terraform provider](https://docs.oracle.com/en-us/iaas/Content/dev/terraform/home.htm)

노드 입력은 이름을 키로 하는 map으로 정의하고 `for_each`를 사용한다. 키는 역할·주소·순서 변화에 독립적인 안정적인 식별자로 정한다. 값에는 역할, shape, OCPU/RAM, image OCID, subnet/AD와 필요한 볼륨 설정을 둔다. 기존 노드 사양만 확정값이며 추가 노드는 별도 입력을 받는다. [Terraform for_each](https://developer.hashicorp.com/terraform/language/meta-arguments/for_each)

배열 순서 기반 `count`로 신규 노드 모델을 만들지 않는다. 이미 `count`로 관리되는 리소스를 `for_each`로 바꾸거나 키·모듈 주소를 바꿀 때는 실제 주소를 확인하고 `moved` block 등 지원되는 state 이전 절차를 준비한다. 주소 변경을 삭제·재생성으로 해결하지 않는다. image OCID·기존 노드 입력을 고정해 새 노드 추가가 기존 노드 이미지 교체를 유발하지 않게 한다.

## 기존 A1 편입

1. Terraform root, backend, workspace, OCI profile·tenancy·compartment·region을 식별한다. state의 관리 여부와 실제 인스턴스 OCID를 대조한다. 자격 증명과 state 원문은 출력하지 않는다.
2. 이미 관리 중이면 기존 resource 주소를 유지한다. state 밖의 인스턴스는 현재 설정에 맞는 resource와 정확한 import 대상 주소를 준비한다. 존재하는 인스턴스를 새로 생성하지 않는다.
3. 해당 Terraform/provider 버전의 import 지원과 필요한 관련 리소스를 확인한다. state 변경 범위에서 import를 수행하고, 편입 후 교체·삭제 없는 plan이 되도록 구성과 실제 설정을 맞춘다. 기존 state가 있으면 보호된 백업을 확보한다. [Terraform import](https://developer.hashicorp.com/terraform/language/import)

import는 OS/K3s를 설치하거나 완전한 구성 파일을 자동 보장하는 작업이 아니다. generated configuration이 있더라도 실제 image, shape, metadata, 네트워크, boot/block volume 설정과 대조한다. drift를 숨기기 위해 광범위한 `ignore_changes`를 추가하지 않는다.

## state와 비밀정보

기존 backend를 우선 사용하고 원격 state의 접근 통제·암호화·버전/복구 기능과 잠금 지원을 확인한다. backend가 미정이면 지원 기능과 운영 환경에 맞게 선택하며 특정 Object Storage/S3 호환 backend가 잠금을 지원한다고 추측하지 않는다. 잠금이 없는 backend에서는 실행을 외부에서 직렬화한다. 잠금 충돌은 실행자를 확인하고 `-lock=false`나 무조건적인 force-unlock으로 우회하지 않는다. [State locking](https://developer.hashicorp.com/terraform/language/state/locking)

state·backup·plan·JSON 출력과 cloud-init user_data는 비밀값을 포함할 수 있다. `sensitive = true`는 출력 표시를 제한할 뿐 저장된 값을 없애지 않는다. OCI 개인키·K3s join token·kubeconfig를 HCL/tfvars/user_data/outputs에 평문으로 넣지 않고 기존 credential/secret 전달 경로를 이용한다. 원격 state에 접근하는 bootstrap 경로도 클러스터 장애 시 사용 가능해야 한다. [Terraform sensitive data](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)

`.terraform/`, state/backup, 저장된 plan과 비밀 tfvars는 Git에서 제외한다. `.terraform.lock.hcl`과 비밀값 없는 입력 예제는 버전 관리한다. 인증은 사용 가능한 OCI profile 또는 실행 환경의 지원되는 principal 방식으로 설정하며 Terraform 도입을 이유로 새 키를 무조건 생성하지 않는다.

## 검증과 적용

Terraform/provider 버전 제약과 lockfile을 존중한다. 해당 root에서 fmt check, init, validate를 수행하고 backend/workspace·변수 파일을 고정해 plan을 만든다. provider upgrade나 backend migration은 변경 범위가 있을 때만 수행한다. `plan -detailed-exitcode`의 0은 차이 없음, 2는 차이 있음, 1은 오류다. [Terraform plan](https://developer.hashicorp.com/terraform/cli/commands/plan)

추가·변경·교체·삭제를 구분하고 초기 노드/볼륨 보존을 확인한다. `for_each` 사용만으로 교체 방지가 보장되지는 않는다. 인스턴스 이미지·AD·metadata 등 변경의 실제 동작은 고정 provider 버전의 schema와 plan으로 판단한다. 지속성 데이터의 boot volume 보존 옵션, block volume·attachment 수명주기, 백업을 따로 확인한다. `prevent_destroy`는 구성 제거와 외부 삭제까지 막는 백업 수단이 아니다.

사용자 요청이 구성/plan 작성까지라면 적용하지 않는다. 생성·변경 적용까지 포함되면 검증한 plan을 적용하고, 예상 밖 교체·삭제가 있으면 해당 파괴적 단계 전에 사용자 범위를 확인한다. apply 실패 시 현재 state·부분 생성 리소스를 조사해 필요한 부분만 이어가며 destroy/recreate로 재시도하지 않는다.

apply 후 OCI 인스턴스 상태·사양·IP·볼륨을 확인하고 비밀값 없는 노드 outputs를 [Ansible inventory](ansible.md)로 전달한다. K3s 설치·가입은 Ansible로 수행한 뒤 [가입·증설 검증](scaling.md)을 따른다. Terraform provisioner나 cloud-init과 Ansible이 K3s 설정을 중복 관리하지 않게 한다. Istio·앱은 GitOps 컨트롤러로 반영하며 Terraform Helm/Kubernetes provider로 중복 배포하지 않는다.

문서 확인일: 2026-09-07. 이 스킬 설정 변경 자체는 Terraform apply/import 또는 OCI 변경 실행이 아니다.
