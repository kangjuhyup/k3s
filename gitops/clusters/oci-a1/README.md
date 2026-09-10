# OCI A1 GitOps 연결

`root/`의 Application·AppProject가 이 환경의 플랫폼과 앱을 연결한다. 배포 매니페스트와 Helm values는 YAML 원본을 직접 관리한다. `bootstrap.json`은 최초 부트스트랩 실행 입력이며 `doppler.json`은 키 매핑 입력으로 유지한다.

- 공통 플랫폼 구성: `gitops/platform/`
- 앱 배포 원본: [gitops/apps](../../apps/README.md)
- auth 환경 구성: [auth/kustomization.yaml](auth/kustomization.yaml). 공통 앱 원본에 리소스·공개 URL 패치를 적용하고 HPA·Secret 주입·라우팅을 연결한다.
- auth Application은 `auth/` 환경 overlay를 참조한다. 배포 조건과 검증은 [운영 문서](../../../docs/runbooks/auth-public-domain.md)를 따른다.

공개 도메인 외 실제 접속 주소·계정·비밀값은 Doppler에서 주입한다. 노드 추가는 클러스터 경로나 Application을 복제하는 이유가 아니다.

검증은 `.local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .`로 수행한다. 환경 패치는 로컬 `kubectl kustomize`로 렌더링해 검증하며 API에는 연결하지 않는다. 이 검사에는 Python/PyYAML과 kubectl이 필요하다.

변경 반영은 별도 승인된 Git 커밋·푸시 후 Argo CD로 수행한다. 직접 apply나 Helm 설치로 GitOps를 우회하지 않는다. `prune: false`이므로 파일 제거만으로 기존 리소스가 삭제되지는 않는다. 상세 절차는 [부트스트랩](../../../docs/runbooks/argocd-bootstrap.md), [입력·관리 원본](../../../docs/runbooks/configuration-inputs.md)을 참고한다.
