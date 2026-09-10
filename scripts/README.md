# 로컬 유틸리티

GitOps YAML 검사·계정/Doppler 생성에는 저장소 가상환경
`.local/os-cleanup-venv/bin/python`(Python 3.12.9, PyYAML 6.0.3)을 사용한다.
아래 `python3` 예시는 이 환경을 활성화한 뒤 실행한다. 매니페스트·Helm values는
YAML, bootstrap·Doppler·계정 입력과 versions 잠금 파일은 JSON으로 유지한다.

검증·선별된 Terraform outputs의 inventory 변환처럼 반복되는 작업을 구현할 때 유틸리티를 둔다. 현재 [argocd_accounts.py](argocd_accounts.py)는 비밀값 없는 계정 입력을 검증하고 Argo CD Helm values를 생성한다. 저장소의 Python 3.12.9·PyYAML 6.0.3 환경을 사용하며 사용법은 [Argo CD 안내](../gitops/platform/argocd/README.md)를 따른다. 기본은 생성물 비교 검사이고 명시적 `--write`일 때만 파일을 갱신한다. 실제 계정 발급이나 외부 API 호출은 하지 않는다.

[k3s_inventory.py](k3s_inventory.py)는 명시적인 비밀값 없는 설정 JSON을 검증해 `.local/ansible/oci-a1/hosts.json`을 생성한다. 기본은 비교만 하며 쓰기는 `--write`로 요청한다. [Ansible 안내](../ansible/README.md)를 따른다. 전체 Terraform state·Doppler config·토큰을 입력으로 받거나 덤프하지 않는다.

2단계 도구는 [Argo CD bootstrap 안내](../docs/runbooks/argocd-bootstrap.md)를 따른다. `gitops_validate.py`는 직접 관리하는 선언의 읽기 전용 검사, `argocd_bundle.py`는 로컬 Git/공식 chart 렌더링 검사다. `argocd_remote_check.py`는 실제 실행 시 원격 Git SHA를 읽는다. **`argocd_bootstrap_runtime.py`는 검증 유틸리티가 아니라 Ansible 전용 원격 설치 실행기**이며 실제 구축 요청 때만 사용한다. 입력을 stdin으로 받고 기존 namespace에서는 Kubernetes 쓰기를 하지 않는다.

검증 유틸리티와 apply/deploy 작업을 분리한다. 단순 검사 명령이 terraform apply·ansible-playbook 호스트 실행·Argo CD sync·Doppler 값 변경을 호출하지 않게 한다. 셸 명령은 저장소 운영 지침에 따라 `rtk`로 실행한다.

3단계 [istio_validate.py](istio_validate.py)는 명시적 로컬 chart 3개의 checksum과 Helm 버전, 전체 렌더링, 내부 Service/ARM64 이미지 참조와 wave 설정을 검사한다. PyYAML이 필요하며 API에 연결하지 않는다. Istio Application·namespace는 Git 매니페스트를 직접 관리한다. [Istio 안내](../docs/runbooks/istio-bootstrap.md), [전체 입력값 표](../docs/runbooks/configuration-inputs.md)를 따른다.

Istio native 테스트는 `HELM_TEST_BINARY`, `ISTIO_TEST_CHART_DIR`, `ARGOCD_TEST_BINARY` 절대 경로를 지정한다. 공식 chart 렌더링과 Argo CD CLI의 로컬 Lua health 평가를 실행하며 미지정 시 건너뛴다. chart 디렉터리에는 `base-1.30.4.tgz`, `istiod-1.30.4.tgz`, `gateway-1.30.4.tgz`가 필요하다.

`istio_validate.py --with-ingress`는 직접 관리하는 ingress overlay와 Git의 K3s settings를 함께 검사하고 ServiceLB용 gateway overlay를 렌더링한다. native 테스트는 실제 chart의 80/443·NodePort 비할당·gateway label과 고정 Istio CRD의 필드/enum 일치를 검사한다. 실제 TLS 인증서·SDS·DNS·sidecar 트래픽 검사는 아니다. [외부 ingress 절차](../docs/runbooks/istio-external-ingress.md)를 따른다.

현재 검증 범위는 경로 존재, Markdown 상대 링크·공백, 합성 경로에 대한 Git ignore 규칙과 [Terraform 환경](../terraform/environments/oci-a1/README.md)의 fmt·validate·mock 테스트, Argo CD 계정 생성기와 K3s 입력/inventory 생성기의 단위/CLI 테스트다. 선택적 공식 도구 테스트는 로컬 파일로 RBAC·chart ConfigMap 렌더링과 Ansible 컨트롤러 입력·거부 조건을 검사한다. 실제 OCI import/plan/apply, Ansible 원격 설치/Kubernetes 실행 검증이나 운영 환경의 비밀값 탐지·접근 통제 검증을 의미하지 않는다.

## Doppler 4단계

- [doppler_gitops.py](doppler_gitops.py): 비밀값 없는 strict schema·Operator AppProject/Application·키 매핑·대상별 RBAC. Doppler 전용 생성 흐름으로 관리한다.
- 저장소 루트에서 `python scripts/doppler_gitops.py --repo-root .`로 비교 검사하고,
  매핑을 수정한 뒤에만 `--write`로 갱신한다. root Kustomization은 직접 관리한다.
- [doppler_vendor.py](doppler_vendor.py): 공식 chart 1.7.1 checksum 확인 후 강화한 Git 설치 선언 재현. 기본 비교, `--write`는 로컬 생성만.
- [doppler_runtime.py](doppler_runtime.py): `bootstrap-auth`는 최초 인증 Secret create만, `verify`는 읽기만. 둘 다 실제 Kubernetes 접근이므로 단순 오프라인 검사에 실행하지 않는다.
- 테스트 `test_doppler_*.py`: schema·소유권·재실행·키 누락·권한·고정 chart/CRD·Argo CD health. native 검사 입력은 `DOPPLER_TEST_CHART`, 기존 `HELM_TEST_BINARY`/`ARGOCD_TEST_BINARY`다.

[실행 순서와 정확한 설정값](../docs/runbooks/doppler-bootstrap.md)을 따른다. Operator health는 최신 Doppler 값·TLS 유효성 검증을 대신하지 않는다.

## 자동 TLS 공통 기반

cert-manager의 Application·AppProject·namespace는 Git에서 직접 관리한다. [cert_manager_validate.py](cert_manager_validate.py)는 로컬 chart checksum·Helm·CRD·ARM64 이미지·webhook·권한을 검사한다. native 테스트에는 CERT_MANAGER_TEST_CHART와 HELM_TEST_BINARY를 전달한다.

공통 설치 검증기는 발급·갱신 실행기가 아니다. Cloudflare DNS-01 Issuer·Certificate·Argo CD TLS passthrough는 `gitops/clusters/oci-a1/argocd-ingress/`에서 직접 관리한다. [공개 도메인 절차](../docs/runbooks/argocd-public-domain.md)의 소유권·외부 준비·검증 조건을 따른다.
