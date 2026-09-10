# k3s_agent

K3s agent [tasks](tasks/main.yml)를 구현했다. 공통 `k3s_install` 역할을 호출하며 [Ansible 안내](../../README.md)를 따른다. 실제 가입은 하지 않았다.

입력은 새 agent 대상, 고정 K3s 버전·SHA256, 확인된 server endpoint·노드 이름과 Doppler에서 주입된 CA-pinned secure token이다. 기존 server에 위임·재설치하거나 token을 재발급하지 않는다. kubelet 파일 생성 뒤에도 별도 verify-cluster로 Node Ready·버전·IP를 확인해야 한다.

새 host로 범위를 제한하되 필요한 위임 작업도 함께 검토한다. 가입 후 Ready·노드 간 CNI·DNS·Istio·스토리지 배치를 확인한다. agent 증설은 control-plane HA나 PV 복제를 의미하지 않는다. [노드 확장 지침](../../../.agents/skills/k3s-infra/references/scaling.md)을 따른다.
