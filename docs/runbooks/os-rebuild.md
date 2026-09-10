# 기존 A1 유지 · 깨끗한 OS로 재구축

2026-09-07 사용자 합의: 기존 K3s 구성을 인계하지 않고 **깨끗한 OS에서 새로 구축**한다. OCI A1 인스턴스 자체는 유지하고, 호환성 확인 후 새 이미지로 부트 볼륨을 교체하는 경로를 우선한다.

현재는 준비 문서만 작성했다. 인스턴스 OCID·현재 OS·대체 이미지·API 인증·SSH·백업 상태는 미확인이다. 실제 교체·중단·삭제 명령이나 자동 실행 작업은 추가하지 않는다.

## 단계와 경계

1. [Terraform 편입](terraform-adoption.md): 현재 인스턴스를 변경 없이 관리 대상으로 편입한다. 새 이미지 적용을 import와 섞지 않는다.
2. 사전 점검: 인스턴스·기존 부트 볼륨·추가 볼륨·데이터·인증·교체 이미지와 서비스 중단 범위를 식별한다.
3. OS 교체: 실제 대상과 실행 시점을 확인한 별도 작업으로 부트 볼륨을 교체한다. 기존 부트 볼륨은 새 OS 정상 부팅과 복구 경로 확인까지 보존한다.
4. 관리 상태 정합성: 실제 OCI 상태와 Terraform 선언/state를 대조하고 의도하지 않은 재교체·삭제가 없는지 확인한다.
5. 신규 설치: SSH 확인 후 Ansible로 호스트·K3s·최소 Argo CD bootstrap을 구성한다. Istio·애드온·앱은 Argo CD로 배포한다.

기존 설치를 제거하는 Ansible 작업이나 K3s uninstall은 OS 초기화를 대신하지 않는다. 이번 결정은 OCI 계정·VCN·NSG·추가 데이터 볼륨·외부 DB까지 전부 삭제한다는 뜻이 아니다.

## OS 교체 전 필수 확인

- 정확한 tenancy/region/compartment, 인스턴스 OCID, 현재 부트 볼륨 OCID, 유지할 4 OCPU·24GB와 네트워크 연결을 기록한다.
- 현재 OS 배포판·이미지·launch options와 교체할 **깨끗한 ARM64 이미지의 OCID**를 확인한다. 기존 설치를 포함한 snapshot/custom image를 사용하면 초기화 목적을 충족하지 못한다.
- OCI 부트 볼륨 교체는 Linux 및 같은 배포판·호환되는 launch options를 요구한다. Windows·Marketplace 이미지 등 제약을 확인한다. 현재 이미지가 미확인이므로 이 A1에서 교체 가능하다고 아직 확정하지 않는다. 배포판 변경이 필요하거나 지원되지 않으면 중단하고 대안을 별도 합의한다. [OCI 공식 교체 절차](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/replacingbootvolume.htm)
- 기존 DB/PVC/호스트 파일의 실제 위치와 보존·폐기 대상을 구분한다. 보존할 데이터는 [Wasabi 백업 지침](../../.agents/skills/k3s-infra/references/wasabi.md)에 따라 일관된 사본과 읽기/복구 가능성을 확인한다. 백업하지 않을 데이터는 폐기 허용 범위를 명시한다. 부트 볼륨 보존만으로 앱 백업이 완료되었다고 판단하지 않는다.
- 기존 metadata/user_data·자동 실행 서비스·추가 볼륨 연결을 점검해 새 OS에서 예전 설치가 자동 복원되지 않게 한다. 기존 비밀값을 로그에 출력하거나 새 cloud-init으로 복사하지 않는다.
- OS 교체 후 사용할 SSH 공개키·사용자·관리 경로와 SSH 불가 시 콘솔 복구 수단을 준비한다. SSH host key가 달라지면 신뢰 가능한 경로로 새 fingerprint를 검증하며 host key 검증을 끄지 않는다.
- 부트 볼륨 교체 중 서비스 중단과 실패 시 복구 방법을 확인한다. 기존 볼륨 보존에 필요한 용량·할당량도 확인한다.

## Terraform과 교체 작업의 관계

현재 [환경 코드](../../terraform/environments/oci-a1/README.md)는 **편입 전용**이다. `adoption_reviewed=true`는 OS 교체를 허가하지 않으며, `source_id`만 새 이미지로 바꿔 바로 apply하지 않는다. `prevent_destroy`와 기존 노드 키·OCID를 유지하고 인스턴스 destroy/recreate로 초기화하지 않는다.

실행 경로는 고정 provider 버전의 지원과 실제 plan을 확인한 뒤 정한다. Terraform이 지원하는 안전한 인플레이스 교체 경로가 확인되면 별도 검토한 코드·plan으로 수행한다. 지원되지 않아 OCI API의 일회성 작업이 필요하면 Git에 기록된 대상 제한 절차와 별도 승인으로 실행하고, 전후 Terraform 상태를 정합화한다. 이 문서만으로 API 작업을 실행하지 않는다.

교체 후 실제 source/부트 볼륨/metadata와 Git 선언을 일치시키고 state를 안전하게 갱신한다. 오래된 선언으로 예전 이미지나 metadata를 다시 적용하지 않는다. 단순 state refresh가 Git의 설정도 수정한다고 가정하지 않는다. 광범위한 `ignore_changes`나 보호 장치 해제로 차이를 숨기지 않는다.

OCI 교체 작업의 **이전 부트 볼륨 보존 옵션**을 명시적으로 확인한다. Terraform resource의 `preserve_boot_volume` 설정이 별도로 호출한 OCI API/콘솔 작업까지 제어한다고 가정하지 않는다. OCI 공식 문서상 보존 옵션이 꺼져 있으면 성공적인 교체 후 이전 볼륨이 종료된다.

## 교체 후 확인과 재구축

- 기존 인스턴스 OCID·A1 사양·의도한 네트워크가 유지되고 새 부트 볼륨으로 부팅되는지 확인한다.
- OS/버전/ARM64, SSH·권한·패키지 상태와 예전 K3s 서비스·데이터·자동 설치 흔적이 없는지 확인한다. OS 교체는 다른 볼륨·백업에 남은 데이터의 완전 삭제를 보장하지 않는다.
- 추가 데이터 볼륨은 내용을 확인하기 전 포맷하거나 자동 재사용하지 않는다. OCI 보안 규칙도 초기화되지 않으므로 남은 노출을 별도 Terraform 변경으로 검토한다.
- [Ansible](../../.agents/skills/k3s-infra/references/ansible.md)로 신규 K3s와 최소 bootstrap을 구성한다. 이전 클러스터 token/kubeconfig를 새 클러스터 인증으로 자동 재사용하지 않는다. 새 인증은 Doppler 관리 경로로 연결하고 이전 복구용 인증은 분리한다.
- Argo CD의 Git 연결·자기관리 후 Istio·애드온·앱을 [GitOps 정책](../../.agents/skills/k3s-infra/references/gitops.md)에 따라 배포한다. 기존 datastore를 통째로 복원하는 것을 기본값으로 삼지 않는다. 필요한 앱 데이터만 별도 복원한다.
- 이전 부트 볼륨 삭제는 새 OS 부팅·SSH·Terraform 정합성 및 필요한 데이터/복구 경로 검증 후 정확한 볼륨 OCID와 삭제 범위를 재확인한 별도 작업으로 수행한다. 자동 삭제하지 않는다.

실패하면 신규 설치와 후속 변경을 중단하고 OCI 작업 상태·양쪽 볼륨을 확인한다. OCI 자동 rollback은 모든 경우의 복구를 보장하지 않으므로 보존된 이전 볼륨·검증된 백업으로 복귀할 절차를 준비한다. 새 OS에서 이미 쓴 데이터가 있다면 이전 상태로 되돌릴 때의 유실도 확인한다.
