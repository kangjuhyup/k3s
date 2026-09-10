# host_prepare

Ubuntu ARM64 호스트의 패키지·커널 모듈·IPv4 forwarding 준비 [tasks](tasks/main.yml)를 구현했다. 반드시 `k3s_preflight` 이후 실행한다. 실제 호스트 실행은 하지 않았다.

사용자가 확인한 Ubuntu만 지원하고 실제 버전·접속 대상은 실행 전 검증한다. 디스크 포맷·데이터 삭제·방화벽 해제·자동 재부팅은 하지 않는다. swap이 활성화돼 있으면 사전 점검에서 실패하며 자동으로 끄지 않는다.

K3s server/agent 설정과 Kubernetes 앱 배포는 다른 계층의 책임이다. [Ansible 운영](../../../.agents/skills/k3s-infra/references/ansible.md)을 따른다.
