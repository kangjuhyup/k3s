# OCI A1 GitOps 연결

클러스터의 루트 Application·AppProject와 환경별 platform/apps 연결을 둘 위치다. [bootstrap.json](bootstrap.json)과 [선언 생성기](../../../scripts/argocd_gitops.py), [2단계 bootstrap](../../../docs/runbooks/argocd-bootstrap.md)을 준비했다. 실제 Git URL/branch·Doppler 입력은 비어 있으므로 활성 Application·Kustomization은 아직 생성하지 않았다.

입력을 검토한 뒤 생성기는 `root/`에 root/self-management Application과 두 AppProject, Kustomization을 만들고 환경 values를 `argocd.values.json`에 둔다. 생성물도 Git 검토 대상이며 기본 명령은 일치 검사만 수행한다. [istio.json](istio.json)을 명시적으로 활성화하면 Istio Application/AppProject와 `istio/`의 namespace 선언도 연결한다. 현재는 비활성이다. [doppler.json](doppler.json)을 활성화하면 Doppler Application/AppProject와 `doppler/` 선언도 연결한다. 앱 Application은 아직 구현하지 않았다.

실제 파일·키·값은 [단계별 설정값 안내](../../../docs/runbooks/configuration-inputs.md)를 따른다. 생성 파일은 직접 수정하지 않는다.

외부 노출은 [ingress.json](ingress.json)에서 별도로 활성화한다. K3s ServiceLB 80/443·TLS Secret 참조·도메인/경로 라우팅과 지정 앱 namespace STRICT mTLS를 연결한다. 실제 값은 나중에 입력하며 현재 비활성이다. [상세 안내](../../../docs/runbooks/istio-external-ingress.md).

공통 원본은 [Argo CD](../../platform/argocd/README.md), [Istio](../../platform/istio/README.md), [Doppler 연동](../../platform/doppler/README.md), [앱](../../apps/README.md)에 둔다. 이 환경에 필요한 버전·values 참조·namespace·배치 차이는 이 클러스터 경로에서 명확히 연결한다.

실제 repoURL·targetRevision·destination·project 권한을 확인한 뒤 선언을 작성한다. CRD·컨트롤러·사용 리소스의 준비 순서를 검증하며 파일 순서만으로 앱 간 준비가 보장된다고 간주하지 않는다.

자동 sync·self-heal과 prune/삭제 보호는 [GitOps 정책](../../../.agents/skills/k3s-infra/references/gitops.md)을 따른다. 새 agent마다 루트 Application이나 별도 클러스터 경로를 만들지 않는다.

자동 TLS 공통 설치는 [cert-manager.json](cert-manager.json)의 `enabled`/`reviewed`로 연결한다. 기본 false다. chart v1.21.1·ARM64 values·Application/AppProject 생성 코드를 준비했으며 DNS 업체별 Issuer·Certificate는 아직 미구현이다. [자동 TLS 절차](../../../docs/runbooks/tls-automatic.md).
