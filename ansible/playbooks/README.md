# Ansible 작업 진입점

Ubuntu A1의 [1단계 설치 안내](../README.md)를 따른다. 입력 검증, 호스트 사전 점검, 첫 server 설치, agent 가입, 읽기 전용 클러스터 검증 playbook을 구현했다. [2단계 Argo CD bootstrap](../../docs/runbooks/argocd-bootstrap.md)도 별도 진입점으로 추가했다. 원격 실행은 하지 않았고 실제 입력은 미확정이다. 유지보수·복구 playbook은 아직 없다.

목적별 진입점을 분리한다.

- [validate-inputs.yml](validate-inputs.yml): 컨트롤러 입력/주입 token 검사만 수행한다.
- [preflight.yml](preflight.yml): SSH로 기존 상태·소유권을 조회한다.
- [install-server.yml](install-server.yml): 첫 server 설치와 API/Node Ready 확인.
- [join-agents.yml](join-agents.yml): 새 agent만 설치하며 server에 위임하지 않는다.
- [verify-cluster.yml](verify-cluster.yml): 선언한 노드·버전·IP와 CoreDNS rollout을 조회한다.
- [bootstrap-doppler-auth.yml](bootstrap-doppler-auth.yml): localhost에서 명시적 kubeconfig/context/API·Git SHA를 검사한 뒤 최초 Doppler 인증 Secret만 create한다. 값은 보호된 환경에서 받고 기존 값은 덮어쓰지 않는다. [4단계 절차](../../docs/runbooks/doppler-bootstrap.md).
- [bootstrap-argocd.yml](bootstrap-argocd.yml): 최초 seed와 GitOps 인계를 수행한다. 실제 실행 전 로컬 Git SHA·원격 branch·도구·Doppler 입력을 검증한다.

- 호스트 준비와 K3s 설치: [host_prepare](../roles/host_prepare/README.md), [k3s_server](../roles/k3s_server/README.md), [k3s_agent](../roles/k3s_agent/README.md).
- 최초 GitOps 연결: [argocd_bootstrap](../roles/argocd_bootstrap/README.md), 별도 2단계로 구현했다.
- 일회성 유지보수: [운영 절차](../../docs/runbooks/README.md)에 검증·복구 범위를 기록한 뒤 해당 작업만 구현한다.

대상 inventory·host limit·실행 revision을 명시한다. Doppler 인증 또는 필수 입력 누락 시 값 출력 없이 중단한다. Istio·앱의 일상 배포를 Ansible로 추가하지 않는다.
