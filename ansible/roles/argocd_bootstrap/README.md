# argocd_bootstrap

최초 Argo CD와 루트 Git 연결, 필요한 인증 전달을 위한 [tasks](tasks/main.yml)를 구현했다. [2단계 운영 안내](../../../docs/runbooks/argocd-bootstrap.md)를 따른다. 실제 토큰·설치 대상은 없고 원격 실행하지 않았다.

공식 chart 10.8.2/Argo CD v3.5.2, argocd namespace와 ARM64 digest를 기준으로 로컬 검증한다. 실제 구축 전 Git URL·branch·commit SHA·인증 참조와 K3s API 버전을 확인한다. GitOps 연결 원본은 [clusters/oci-a1](../../../gitops/clusters/oci-a1/README.md)에 두며 같은 values를 bootstrap 렌더링과 자기관리가 사용한다.

새 namespace에만 create로 최소 seed를 전달하고 지정 Git revision의 조정 성공을 확인한 뒤 [Argo CD 자기관리](../../../gitops/platform/argocd/README.md)로 인계한다. 기존 namespace는 소유권·상태 확인만 하며 Kubernetes 리소스를 덮어쓰지 않는다. 부분 실패나 기존 설치는 자동 삭제/편입하지 않고 복구 검토를 요청한다.

Doppler 최초 인증과 Git 인증이 아직 없는 클러스터에만 의존하지 않게 한다. 비밀값은 보호된 입력·`no_log`·`diff: false`로 취급한다. 일반 앱 설치는 이 역할에 포함하지 않는다. [GitOps 정책](../../../.agents/skills/k3s-infra/references/gitops.md), [Doppler 정책](../../../.agents/skills/k3s-infra/references/doppler.md)을 따른다.
