# 기존 Ubuntu 유지 · K3s 초기화

2026-09-10 선택: 기존 A1 인스턴스와 Ubuntu·SSH를 유지하고, 기존 K3s와 앱·DB/PVC 데이터는 보존하지 않고 제거한다. 이전 OS 교체 계획 대신 이번 작업에는 이 절차를 적용한다. 백업 목적지는 Wasabi이며 연동은 아직 구성하지 않았다.

## 대상과 관리 경로

- 실제 대상: `.env`의 `A1_DISPLAY_NAME`, `A1_PUBLIC_IP`, `A1_PRIVATE_IP`, Ubuntu 22.04 ARM64.
- Terraform 1.16.1 / OCI provider 9.0.0: `terraform/environments/oci-a1`의 기존 인스턴스 편입. VCN·NSG·서브넷·부트 볼륨을 별도 리소스로 새로 생성하지 않는다.
- 노드 선언은 `terraform/environments/oci-a1/nodes.inputs.json`이며 환경변수를 해석한 `.local/terraform/oci-a1/nodes.tfvars.json`을 plan에 명시한다. 테스트·기본 실행에 실제 노드를 자동 주입하지 않는다.
- Terraform state: `.local/terraform/oci-a1/terraform.tfstate`, 로컬 단일 실행자 전용. 상위 디렉터리 0700, state 0600. 이 파일을 잃으면 관리 상태를 재편입해야 한다. 원격 backend와 Wasabi 백업이 구성됐다는 뜻이 아니다.
- 기존 SSH metadata 입력: `.local/terraform/oci-a1/metadata.tfvars.json`. 값은 Git에 넣지 않고 plan/apply 시 `-var-file`로 전달한다.
- Ansible 2.21.4 / controller Python 3.12+: `reset-k3s.yml` → `install-server.yml` → `verify-cluster.yml`.
- 새 설치 입력: `ansible/inventories/oci-a1/settings.json`. K3s 버전·ARM64 checksum·SQLite·CIDR·노드 주소를 고정한다.

## 실행과 파괴 범위

초기화는 기존 서비스 전체를 중단하고 기존 etcd, 13개 local-path PV, 앱 및 Kubernetes 인증을 제거한다. 삭제한 데이터는 복구할 수 없다. 사용자 지시로 백업 없이 진행하며 원격 Wasabi 사본이 있다고 가정하지 않는다.

`ansible/playbooks/files/reset-legacy-k3s.py`는 검증한 구버전·노드·전용 경로만 초기화한다. replacement 설치 완료 표시가 있으면 거부하고, reset 완료 표시는 새 클러스터를 다시 지우지 않게 보호한다. 중간 실패 시 임의로 표시 파일을 만들거나 지우지 말고 실제 남은 서비스·mount·파일을 확인한다.

정지와 unmount 이후 인터페이스 정리에서 멈춘 경우에 한해, 구버전·노드·경로가 그대로이고 프로세스·mount가 없음을 검증한 뒤 `-e '{"k3s_reset_resume":true}'`로 남은 정리를 재개할 수 있다. 이 모드는 API 조회를 대신해 정지 상태를 검사하며, 임의의 부분 삭제나 새 클러스터에는 사용하지 않는다.

실제 제거 전 새 ARM64 바이너리를 내려받아 checksum을 검증한다. `--check`의 조회 검사와 실제 삭제는 구분한다. 비밀값은 `.env`에서 필요한 `K3S_SERVER_TOKEN`만 controller 환경에 공급하고 명령 인자·Git에 기록하지 않는다. 운영 원본은 향후 Doppler로 연결한다.

루트에서 `scripts/k3s_inventory.py`로 `.local/ansible/oci-a1/hosts.json`을 생성하고, Ansible 명령은 `ansible/` 디렉터리에서 실행하여 저장소의 roles/filter 설정을 사용한다. SSH는 기존 검증된 사용자 config 및 known_hosts를 사용한다.

```sh
ansible-playbook -i ../.local/ansible/oci-a1/hosts.json playbooks/reset-k3s.yml \
  -e k3s_reset_authorization=delete-legacy-cluster-and-local-data --check
# 실제 초기화 승인 범위에서만 --check를 제외하고 실행
ansible-playbook -i ../.local/ansible/oci-a1/hosts.json playbooks/install-server.yml
ansible-playbook -i ../.local/ansible/oci-a1/hosts.json playbooks/verify-cluster.yml
```

재설치 완료 기준은 SQLite 존재, 고정 버전·ARM64·노드 Ready, API readiness, CoreDNS readiness와 기본 Pod 상태다. Argo CD·Istio·앱·Wasabi 재설치는 이 K3s 초기화의 완료 조건과 별도로 진행한다. 기존 kubeconfig와 토큰은 새 클러스터에서 유효하지 않다.

## 2026-09-10 실행 결과

- 기존 인스턴스 import 완료. 부트 볼륨 보존 설정을 반영한 뒤 Terraform plan은 변경 없음(exit 0).
- 초기화 도중 이미 사라진 CNI 인터페이스 삭제 경합으로 정리 중단. 프로세스·mount 부재를 확인하고 검증된 resume 절차로 완료했다.
- Jenkins 잔여 apt 저장소의 서명 오류는 `jenkins.list.disabled`로 보존·비활성화하여 해결했다.
- 새 노드 `a1-server-1`, `v1.36.4+k3s1`, ARM64, SQLite, Secret 암호화 활성 확인.
- API·Node Ready, CoreDNS·local-path-provisioner·metrics-server 모두 Ready. DNS 질의가 `kubernetes.default.svc.cluster.local → 10.43.0.1`로 응답했다.
- 기존 PV 및 `/var/backups/k3s` 제거 확인. 디스크 사용률 19%, 여유 약 37GB. 부팅 직후 RAM 사용 약 0.9GB.
- Terraform 테스트 12개, K3s 설정 테스트 8개, 초기화 안전성 테스트 8개 통과. 실제 Ansible 설치·검증 성공.
- Argo CD·Istio·앱·Wasabi는 아직 새 클러스터에 설치하지 않았다.
