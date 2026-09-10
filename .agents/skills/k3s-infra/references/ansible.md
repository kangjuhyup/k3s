# Ansible로 K3s 설치와 노드 가입

## Terraform과 역할 분리

사용자 선택은 Terraform으로 OCI 리소스를 관리하고 Ansible로 호스트 준비·K3s 설치·설정·노드 가입을 관리하는 것이다. Istio·애드온·앱은 GitOps 컨트롤러로 배포한다. 기존 Ansible 버전·collection·role을 확인하고 지원 버전을 고정한다.

Ansible 원본은 Git으로 관리하며 실제 실행한 revision·대상·결과를 추적한다. [GitOps 필수 정책](gitops.md)에 따라 최초 Argo CD와 루트 Application·Git 연결의 최소 부트스트랩만 Ansible이 담당하고, 이후 Argo CD 자기관리를 인계한다. Ansible의 Kubernetes/Helm 모듈을 일상 앱 배포 우회 수단으로 사용하지 않는다.

Terraform의 특정 환경 outputs에서 노드 키, OCID, 역할, 접속 IP 등 필요한 비밀값 없는 필드만 가져와 inventory를 생성하거나 갱신한다. 전체 state/outputs를 덤프하지 않는다. `inventory_hostname`은 안정적인 노드 키, `ansible_host`는 실제 접속 주소로 분리한다. server/agent 그룹은 서로 겹치지 않게 하고, 초기에는 server 1대·agents 0대로 정상 실행되게 한다. 사용자명·SSH 키 참조·become·Python interpreter는 실제 OS와 접속 환경에서 확인한다.

공통 설정은 group_vars/공통 role에, 역할별 설정은 server/agent role에 둔다. 노드별 IP·labels·추가 사양은 host_vars 또는 생성 inventory로 전달한다. 생성 파일은 입력 원본과 구분하고 손으로 중복 편집하지 않는다. SSH host key 검증을 기본 유지한다.

## 설치와 재실행

1. 대상 Linux ARM64 호스트의 연결·권한·OS·기존 K3s 버전, 서비스, config/drop-in, datastore, data-dir와 볼륨 mount를 확인한다. 새 role 적용을 위해 기존 DB·token·설치 디렉터리를 지우지 않는다.
2. 공통 role은 필요한 OS 패키지·커널/네트워크 조건·디렉터리를 관리한다. 패키지·파일·template·service 모듈을 우선하고, 설치 스크립트가 필요한 경우 출처·내용·목표 버전과 기존 인자를 검증해 조건부로 실행한다. 매 실행마다 최신 설치 스크립트를 실행하지 않는다.
3. 고정 K3s 버전과 역할별 config를 관리한다. template은 해당 파일의 소유권을 확인한 뒤 기존 설정을 보존·병합한다. binary/config 변경이 있을 때만 handler로 서비스를 재시작한다. `changed_when: false`로 실제 변경을 숨기지 않는다.
4. 첫 server를 명시적 inventory 키로 선택하고 API 준비를 기다린 뒤 agents를 가입시킨다. inventory 순서나 `run_once`만으로 bootstrap server를 결정하지 않는다. `cluster-init`은 선택된 datastore 설계에만 적용한다. worker 추가 때문에 기존 server를 초기화·재시작하거나 token을 다시 만들지 않는다.

추가 agent 실행은 inventory를 갱신한 뒤 새 호스트를 `--limit` 대상으로 지정한다. 기존 server에서 token을 읽어야 하는 경우에만 보호된 읽기 작업을 명시적으로 위임한다. `delegate_to`는 제한된 호스트 밖에서도 실행할 수 있고 `run_once`는 serial batch마다 동작할 수 있으므로, limit만 보고 전체 영향 범위를 판단하지 않는다. [Ansible delegation](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_delegation.html)

서버 설정 변경·업그레이드는 `serial: 1`과 건강성 확인을 사용하고 실패하면 다음 서버 작업을 중단한다. 재시작 handler를 다음 단계의 readiness 검사 전에 실행시킨다. 단일 server의 중단 영향과 내장 etcd quorum은 [유지보수 지침](maintenance.md)을 따른다.

## token과 인증 정보

환경변수·join token·kubeconfig·registry 자격 증명의 관리 원본은 [Doppler](doppler.md)다. 필요한 값을 Ansible 컨트롤러에 주입하고 명시적 변수 매핑으로 사용한다. 기존 노드에서 생성된 token은 임의로 바꾸지 않고 필요한 편입 범위를 확인한다. 민감한 읽기·등록 변수·template 작업에 `no_log: true`, `diff: false`와 제한된 파일 권한(예: root 소유 `0600`)을 적용한다. 평문 inventory, Terraform outputs, 프로세스 인자에 token을 넣지 않는다.

Ansible Vault를 신규 비밀값 원본으로 병행 도입하지 않는다. 기존 Vault가 있으면 Doppler 이전·검증이 완료되기 전 삭제하지 않는다. register/set_fact 결과의 debug·fact cache·CI 로그·fetch된 로컬 파일도 확인하며 주입만으로 실행 중 노출이 방지된다고 간주하지 않는다. [Ansible logging](https://docs.ansible.com/projects/ansible/latest/reference_appendices/logging.html)

## 검증

실제 inventory·playbook 경로와 대상 host를 명시해 syntax-check, lint(구성된 경우), list-hosts로 먼저 검사한다. inventory 출력에 비밀값이 섞이지 않게 하고 예상 host 목록을 확인한다. 그 뒤 작업 범위에 맞는 check mode를 사용한다.

`--check`는 시뮬레이션이며 미지원 모듈·등록 변수 의존 작업은 완전히 검증되지 않을 수 있다. `check_mode: false` 작업은 check 실행에서도 실제 변경할 수 있으므로 먼저 검사한다. secret 작업의 diff는 비활성화한다. syntax/check 통과만으로 설치가 검증되었다고 보고하지 않는다. [Check and diff mode](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html)

실제 설치 요청 범위에서 실행한 뒤 service 상태, 설치 버전, API, Node Ready, DNS/CNI·Istio 경로를 확인한다. 테스트 환경 또는 허용된 대상에서 재실행하여 불필요한 재설치·token 변경·재시작이 없음을 확인한다. node Ready 이후의 검증은 [노드 확장](scaling.md)을 따른다. Playbook 작성만 요청되었다면 호스트 실행 없이 정적 검증 범위를 보고한다.

문서 확인일: 2026-09-07. 이 지침 추가 자체는 호스트에 Ansible을 실행하거나 K3s를 설치하는 작업이 아니다.
