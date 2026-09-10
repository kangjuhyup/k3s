# OCI A1 inventory

현재 [hosts.yml](hosts.yml)은 의도적으로 비어 있다. 실제 호스트 주소·SSH 사용자·Ubuntu 버전은 미확정이며 기본 파일로 설치되는 대상은 없다.

[settings.json.example](settings.json.example)의 비밀값 없는 입력을 검토한 뒤 [생성기](../../../scripts/k3s_inventory.py)로 `.local/ansible/oci-a1/hosts.json`을 생성한다. JSON은 Ansible YAML inventory로 읽을 수 있다. 생성 파일은 Git에서 제외하며 손으로 수정하지 않는다. Terraform 선별 outputs에 SSH·OS·인터페이스 등의 확인한 입력을 매핑하는 작업은 아직 수동이며 전체 state를 입력으로 받지 않는다.

노드의 안정적인 키를 `inventory_hostname`, 실제 주소를 `ansible_host`로 구분한다. server와 agent 그룹은 겹치지 않게 하고 초기 server 1대·agent 0대를 지원한다. group_vars/host_vars에는 구조와 Doppler 참조를 두며 실제 비밀값은 실행 시 주입한다.

소비자는 [playbooks](../../playbooks/README.md)다. 사용법과 정확한 필드는 [Ansible 안내](../../README.md)를 따른다. 새 agent 설치 범위와 위임 작업의 영향은 [Ansible 운영](../../../.agents/skills/k3s-infra/references/ansible.md)에서 확인한다.
