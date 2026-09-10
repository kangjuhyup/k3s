# Ansible: Ubuntu A1 첫 K3s 설치

실제 IP·OCI 식별자는 Git이 아닌 환경변수에서 읽는다. [환경 입력 생성 절차](../docs/runbooks/environment-inputs.md)에 따라 `.env`를 주입한 뒤 inventory를 생성한다.

Ubuntu ARM64·systemd·cgroup v2의 첫 server 설치, 추가 server/agent 가입과 기존 단일 SQLite 서버의 etcd 전환을 지원한다. 실제 A1 입력은 `inventories/oci-a1/settings.json`이다. [etcd 전환·증설 절차](../docs/runbooks/k3s-etcd.md)를 따른다. Istio·Argo CD·Wasabi는 이 K3s 설치에서 자동 구성하지 않는다.

## 구현 범위와 안전 경계

- 현재 목표는 embedded etcd + Flannel VXLAN이다. 첫 server만 `cluster-init`으로 초기화하고 추가 server는 기존 endpoint로 가입한다. 단일 etcd 멤버는 HA가 아니며, 총 3대 이상의 홀수 server와 안정적인 API 접근 경로를 준비해야 한다. SQLite 단일 server 호환성도 유지한다. PV 복제는 제공하지 않는다.
- Traefik을 비활성화하고 ServiceLB 사용 여부는 입력으로 받는다. Istio나 외부 80/443 경로는 아직 설치하지 않는다.
- Ubuntu의 실제 배포판/버전·ARM64·systemd·메모리·swap·cgroup·노드 IP·인터페이스를 확인한 뒤 패키지, 커널 모듈과 IPv4 forwarding을 설정한다. 방화벽 해제·재부팅·디스크 포맷은 하지 않는다.
- K3s 버전과 공식 `k3s-arm64` 바이너리의 SHA256을 반드시 입력한다. `latest`나 원격 설치 스크립트를 실행하지 않는다. K3s 실행 버전은 Istio 호환성까지 검토한 뒤 운영 입력에 고정한다.
- 설치 playbook은 기존 미관리 K3s 경로가 있으면 중단한다. 현재 관리 중인 SQLite의 전환은 `migrate-sqlite-to-etcd.yml`로 수행하며 클러스터를 삭제하지 않는다.
- 완료 기록이 있는 재실행에서는 입력·바이너리·config·unit·token이 동일하고 영속 상태가 남아 있어야 한다. 설치 변경·업그레이드·token 회전·DB 복원은 지원하지 않는다. 서비스가 정지돼 있으면 다시 시작하지만 정상 서비스는 무조건 재시작하지 않는다.
- 설치가 중간에 실패해 완료 기록 없이 일부 경로만 남으면 재실행도 차단한다. **디렉터리를 지우거나 완료 기록을 조작해서 우회하지 않는다.** 실패 단계 조사와 별도 복구 검토가 필요하다.

## 파일과 진입점

| 파일 | 역할 |
| --- | --- |
| [settings.json.example](inventories/oci-a1/settings.json.example) | 비밀값 없는 입력 계약; 미확정 값은 빈 값이며 실행 불가 |
| [hosts.yml](inventories/oci-a1/hosts.yml) | 안전한 기본값인 빈 inventory; 설치 대상을 추측하지 않음 |
| [k3s_inventory.py](../scripts/k3s_inventory.py) | 검토한 JSON을 JSON/YAML 호환 inventory로 생성; 기본 비교만 수행 |
| [validate-inputs.yml](playbooks/validate-inputs.yml) | 컨트롤러에서 입력과 주입된 token 검증; SSH 없음 |
| [preflight.yml](playbooks/preflight.yml) | SSH로 호스트 상태를 조회; 호스트 설정 변경 없음 |
| [install-server.yml](playbooks/install-server.yml) | 첫 server의 호스트 준비·K3s 설치·API/Node Ready 확인 |
| [join-agents.yml](playbooks/join-agents.yml) | 선택한 agents만 순서대로 가입; server 위임/변경 없음 |
| [join-servers.yml](playbooks/join-servers.yml) | bootstrap 제외, 선택한 control-plane만 순차 가입 |
| [migrate-sqlite-to-etcd.yml](playbooks/migrate-sqlite-to-etcd.yml) | 관리 중인 단일 SQLite 서버를 동일 버전·인증으로 etcd 전환 |
| [prepare-etcd-peers.yml](playbooks/prepare-etcd-peers.yml) | 기존·신규 server의 UFW에 선언된 peer IP만 2379/2380 허용 |
| [verify-cluster.yml](playbooks/verify-cluster.yml) | server에서 전체 선언 노드의 Ready·버전·ARM64·IP 및 CoreDNS rollout 조회 |

agent playbook의 서비스 활성화·kubelet 파일 생성만으로 가입 완료를 판정하지 않는다. 가입 후 `verify-cluster.yml`까지 실행하고, 실제 DNS 질의·노드 간 통신·PVC·앱 기능은 후속 GitOps 테스트 워크로드로 검증한다.

## 입력 준비

필드마다 넣을 값과 Doppler 키 대응은 [1단계 설정값 표](../docs/runbooks/configuration-inputs.md#1단계-ansible--k3s)를 따른다. 검토한 최종 비밀값 없는 원본 경로는 `ansible/inventories/oci-a1/settings.json`, 생성 inventory는 `.local/ansible/oci-a1/hosts.json`으로 구분한다.

Ansible controller에는 Python 3.12+와 [requirements.txt](requirements.txt)의 ansible-core 2.21.4를 별도 가상환경으로 설치한다. 검증 도구는 [requirements-dev.txt](requirements-dev.txt)를 사용한다. 원격 Ubuntu에는 SSH·sudo와 해당 ansible-core가 지원하는 `/usr/bin/python3`가 필요하다. Python 설치를 위해 SSH를 우회하거나 임의 root 명령을 실행하지 않는다.

비밀값 없는 환경 원본은 Git, 생성 inventory는 `.local/`로 구분한다. Terraform의 선별된 `nodes` output에 SSH 사용자·OS 버전·인터페이스 등을 확인해서 매핑한다. 전체 state를 넘기는 자동 변환은 하지 않는다.

필수 항목:

- `reviewed`, `network_reviewed`: 실제 대상과 네트워크를 확인한 기록. true가 실제 확인이나 실행 승인을 대신하지 않는다.
- `version`, `sha256`: 공식 릴리스 및 ARM64 바이너리 검증 값. 테스트의 합성 버전/체크섬은 실행에 사용하지 않는다.
- `datastore=etcd`, `bootstrap_server`, `pod_cidr`, `service_cidr`, `cluster_dns`: bootstrap은 실제 server 키를 명시한다. IPv4 Pod/Service CIDR은 OCI VCN·VPN·노드 대역과 겹치면 안 된다. 기존 SQLite 입력에는 bootstrap_server와 server_join 참조를 넣지 않는다.
- `endpoint`: 노드에서 접근할 수 있는 `https://주소:6443`. 해당 주소를 `tls_sans`에도 포함한다. 실제 도메인·IP를 추측하지 않는다.
- `servicelb`: 외부 노출을 K3s ServiceLB로 선택했으므로 첫 설치부터 **true**로 둔다. 예제도 true로 변경했다. [외부 ingress](../docs/runbooks/istio-external-ingress.md)는 Git 입력이 true인지 검사한다. 기존 false 설치의 변경/재시작은 이 초기 설치 playbook으로 수행하지 않는다.
- `nodes`: etcd는 server 1대 이상, SQLite는 정확히 1대. HA 목표는 server 3대이며 추가 agent는 선택 사항이다. 노드 이름·주소는 실제 값이어야 한다. 가입 server는 `token_env.server_join`의 CA-pinned server token을 사용한다.
- `token_env.server`, `token_env.agent`: 필요한 Doppler 키 이름만 입력한다. 실제 값은 넣지 않는다.

SSH host key 검증은 유지한다. 확인된 known_hosts와 SSH agent/개인키 접근을 준비해야 한다. OCI 보안 규칙과 Ubuntu 방화벽의 SSH·6443·노드 간 VXLAN/metrics 경로는 별도로 검토한다. VXLAN 포트는 인터넷에 공개하지 않는다.

## Token 전달

최초 server의 자체 CA가 생성되기 전에는 검토한 랜덤 short token을 Doppler의 server 키에서 주입한다. 코드에서는 32자 이상의 영문/숫자/밑줄/하이픈을 요구하지만 길이 검사 자체가 엔트로피 검증은 아니다.

agent 키는 CA 해시를 포함하는 `K10...::...` secure token을 요구한다. server 시작 후 승인된 보호 경로로 확보하여 Doppler에 보관해야 하며, 이 단계에서 자동으로 조회·출력·등록하지 않는다. 초기 short token을 agent 키에 복사하지 않는다. 기본 agent token은 server token과 동일한 권한을 가질 수 있으므로 제한된 agent token의 발급/전달은 실제 구축 전 검토한다. server token은 DB 복구에도 필요하므로 백업 시점의 이력을 보존한다.

두 키는 서로 다른 이름을 사용하고 작업 대상에 필요한 값만 주입한다. `doppler run`의 실제 project/config·인증은 아직 미정이다. 셸에 값을 직접 쓰거나 Git·inventory·Ansible 인자로 전달하지 않는다. 민감한 작업은 `no_log`, `diff: false`, 원격 파일 `0600`으로 보호하지만 외부 디버깅·프로세스 환경 덤프까지 막는 것은 아니다.

## 로컬 검사 명령

아래 명령은 저장소 루트 기준이다. 생성 inventory의 상위 `.local/ansible/oci-a1` 디렉터리는 먼저 준비해야 한다. 기본 비교는 파일을 쓰지 않는다.

```bash
rtk proxy python3 scripts/k3s_inventory.py --input .local/ansible/oci-a1/settings.json --output .local/ansible/oci-a1/hosts.json --write
rtk proxy python3 scripts/k3s_inventory.py --input .local/ansible/oci-a1/settings.json --output .local/ansible/oci-a1/hosts.json
rtk proxy python3 -m unittest discover -s scripts/tests -v
```

Ansible 명령은 **ansible 디렉터리에서** 실행해야 해당 설정 파일이 선택된다. 아래 syntax-check/list-hosts는 SSH 접속 없이 실행된다. 예제의 노드 이름은 실제 검토한 inventory 키로 바꾼다.

```bash
rtk proxy ansible-playbook -i ../.local/ansible/oci-a1/hosts.json --syntax-check playbooks/install-server.yml playbooks/join-agents.yml
rtk proxy ansible-playbook -i ../.local/ansible/oci-a1/hosts.json --list-hosts --limit a1-server-1 playbooks/install-server.yml
rtk proxy ansible-lint --offline
```

기본 빈 inventory로 playbook이 아무 호스트도 처리하지 않았거나 syntax-check만 통과한 것은 설치 성공이 아니다. 설치 playbook은 `--check`를 차단한다. `preflight.yml`은 읽기 전용 작업이지만 SSH 접속·sudo·fact 수집이 필요하므로 현재는 실행하지 않는다.

실제 실행 시 확인된 Git revision과 대상·limit·Doppler project/config를 기록하고, 입력 검사 → preflight → server 설치 → 검증 순서로 진행한다. agent 추가는 새 agent만 limit으로 선택한 뒤 별도 server 검증을 수행한다. `--skip-tags`·추가 변수로 검증을 우회하지 않는다. SSH가 닫힌 현재는 실행 명령을 일괄 배포 스크립트로 연결하지 않았다.

## 검증 근거와 제한

[K3s 설정](https://docs.k3s.io/installation/configuration), [요구사항](https://docs.k3s.io/installation/requirements), [token 형식과 복구](https://docs.k3s.io/cli/token), [Ansible 설치 요구사항](https://docs.ansible.com/projects/ansible/latest/installation_guide/intro_installation.html)을 확인했다. 확인일 2026-09-09. 특정 K3s 운영 버전이나 Ubuntu 버전의 실기기 호환성을 인증한 것은 아니다.

선택적 native 테스트에는 로컬 `ANSIBLE_TEST_BINARY` 절대 경로를 지정한다. 합성 inventory로 컨트롤러 입력 검증·template 평가·syntax-check·list-hosts·기존 상태 거부 조건만 실행한다. 원격 설치 playbook은 실행하지 않으며 check-mode 거부 테스트도 첫 assert에서 종료된다. 실제 설치 성공·재실행 멱등성은 SSH 개방 후 테스트해야 한다.
