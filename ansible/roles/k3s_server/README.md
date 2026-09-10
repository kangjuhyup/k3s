# k3s_server

K3s server [tasks](tasks/main.yml)를 구현했다. 공통 `k3s_install` 역할을 호출하며 [Ansible 안내](../../README.md)의 첫 설치 계약을 따른다. 실제 설치는 하지 않았다.

입력은 명시적 server 대상, 고정 K3s 버전·SHA256, 네트워크·Ubuntu 버전과 Doppler token 참조다. 이번 구현은 SQLite 단일 server이며 control plane과 워크로드를 함께 담당한다. Traefik은 비활성화한다.

기존 미관리 설치를 덮어쓰지 않는다. 동일 계약의 완료된 설치만 재실행하고 token·DB·설정 변경은 별도 절차 전 차단한다. 무조건 재시작하지 않는다. agent 추가 때문에 server를 초기화하지 않는다. SQLite/etcd 전환과 HA는 [노드 확장 지침](../../../.agents/skills/k3s-infra/references/scaling.md)을 따른다.

설치 후 API·Node Ready·CNI/DNS 검증은 playbook의 명시적 단계로 연결한다. 이 README는 실제 서버 설치 상태를 나타내지 않는다.
