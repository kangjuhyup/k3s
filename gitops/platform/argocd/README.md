# Argo CD 자기관리

[공개 도메인 연결](../../../docs/runbooks/argocd-public-domain.md): `argo.rvkang.app`을 Istio TLS passthrough로 연결하고 Cloudflare DNS-01로 인증서를 발급하는 GitOps 선언을 추가했다. 아래 bootstrap 설명과 별도로 공개 URL은 환경 values에서 설정한다. 실제 DNS·토큰 준비 및 배포 검증은 해당 절차를 따른다.

Argo CD의 설치 원본과 설정을 둘 위치다. **개인 계정/RBAC용 Helm values 생성 코드**와 [2단계 bootstrap/자기관리 연결 코드](../../../docs/runbooks/argocd-bootstrap.md)를 준비했다. [base.values.yaml](base.values.yaml), [versions.json](versions.json)에 공식 chart·ARM64 image digest와 단일 노드 설정을 고정했다. 실제 Git 입력은 비어 있어 운영 Application 생성·설치는 하지 않았다.

최초 seed는 [Ansible bootstrap](../../../ansible/roles/argocd_bootstrap/README.md), 일상적인 자기관리 변경은 [클러스터 Application](../../clusters/oci-a1/README.md)을 통해 수행한다. 두 경로가 동일 리소스를 계속 중복 관리하지 않도록 인계한다.

계정 운영은 **기본 admin은 초기 설정에만 사용하고, 이후 개발자별 로컬 개인 계정을 발급**하는 방향으로 확정했다. [개인 계정 운영 절차](../../../docs/runbooks/argocd-accounts.md)에 따라 계정·활성화 여부·RBAC는 Git으로 관리한다. 개인 관리자 로그인·권한과 복구 경로를 검증한 후 별도 Git 변경으로 기본 admin을 비활성화한다. 개발자 전체에게 관리자 권한을 부여하지 않는다.

실제 계정명·담당 프로젝트·Git 인증 값은 아직 미정이다. 최초 admin/Redis/Git 인증은 Doppler에서 Ansible controller에 주입하고 최소 seed에서만 생성하도록 구현했다. 개인 계정 비밀번호와 이후 값 교체의 연동은 후속 범위다. 이 디렉터리에 비밀번호·해시·토큰·실제 Secret data를 넣지 않는다. 최초 접근은 ClusterIP/TLS와 별도 loopback port-forward를 사용하며 아직 설치되지 않은 Istio에 의존하지 않는다. 실제 계정 발급·비밀번호 주입·설치는 수행하지 않았다.

## 계정 입력과 생성물

| 파일 | 역할 |
| --- | --- |
| [accounts.json](accounts.json) | 검토할 비밀값 없는 계정 목록과 전환 확인 기록; 현재 bootstrap·빈 목록 |
| [accounts.json.example](accounts.json.example) | 비활성 합성 계정의 입력 형식; 실제 사용자 아님 |
| [accounts.values.yaml](accounts.values.yaml) | 공식 argo-cd chart가 읽을 생성 Helm values; Git 검토 대상 |
| [생성 도구](../../../scripts/argocd_accounts.py) | Python·PyYAML로 검증·YAML 렌더링 |
| [테스트](../../../scripts/tests/test_argocd_accounts.py) | 권한·전환 조건·입력 거부·CLI 쓰기/검사 테스트 |

계정의 `name`, `enabled`, `role`, `projects`를 모두 명시한다. 이름은 32자 이하의 소문자/숫자/하이픈이며 소문자로 시작하고 하이픈으로 끝나지 않는다. `admin`은 예약 이름이다. project는 wildcard가 아닌 실제 AppProject 이름을 사용한다.

- `developer`: 지정한 project의 애플리케이션과 프로젝트 조회만 허용한다. sync·로그·exec·override·삭제·설정 변경은 부여하지 않는다. 더 많은 권한은 별도 검토·코드/테스트 변경이 필요하다.
- `platform-admin`: 전체 Argo CD 관리자 역할이다. 프로젝트 제한 관리자처럼 오해하지 않도록 `projects`는 빈 배열이어야 한다. 실제 지정된 플랫폼 관리 담당자에게만 사용한다.
- `enabled=false`: 계정 정의는 남기되 로그인 비활성화와 이 생성 도구의 권한 매핑 제거를 표현한다. 기존 토큰/세션 폐기 여부는 별도 검증한다.

모든 사람 계정은 `login`만 사용하며 API 토큰 발급 capability는 이 도구에서 지원하지 않는다. 기본 역할은 별도 권한을 부여하지 않은 `role:authenticated`, 익명 접근은 비활성화다. SSO와 별도 AppProject role/policy 조각을 병합하는 경우의 추가 권한은 이 도구의 검증 범위 밖이다.

## 생성 및 검사

저장소 루트에서 실행한다. Python 3.12.9·PyYAML 6.0.3이 있는
`.local/os-cleanup-venv` 환경을 활성화한 뒤 아래 `python3` 명령을 사용한다.
기본 동작은 read-only이며 `--write`를 명시해야 YAML 생성 파일을 갱신한다.
외부 API·인증·배포는 호출하지 않는다.

```bash
rtk proxy python3 -m unittest discover -s scripts/tests -p 'test_argocd_accounts*.py' -v
rtk proxy python3 scripts/argocd_accounts.py --input gitops/platform/argocd/accounts.json --output gitops/platform/argocd/accounts.values.yaml
```

기본 실행은 로컬 단위 테스트를 수행하며 선택적 공식 도구 테스트는 필요한 도구가 없으면 건너뛴다. [공식 도구 테스트](../../../scripts/tests/test_argocd_accounts_native.py)까지 실행하려면 검증된 로컬 바이너리와 chart 압축 파일의 절대 경로를 지정한다. 아래 경로는 설명용이며 실제 파일 경로로 바꾼다.

```bash
rtk proxy env ARGOCD_TEST_BINARY=/absolute/path/argocd HELM_TEST_BINARY=/absolute/path/helm ARGOCD_TEST_CHART=/absolute/path/argo-cd-10.8.2.tgz python3 -m unittest discover -s scripts/tests -p 'test_argocd_accounts*.py' -v
```

로컬 검증 기준은 Argo CD CLI v3.5.2, argo-cd chart 10.8.2, Helm v4.2.4다. 테스트는 합성 계정과 임시 설정으로 RBAC 허용/거부 12개 사례 및 bootstrap/managed ConfigMap 렌더링을 검사한다. 실제 인증 파일을 사용하지 않으며 다운로드·클러스터 설치·계정 발급을 수행하지 않는다. 이 검증이 실제 로그인이나 전체 설치 구성 검증을 대체하지는 않는다.

검토한 계정 입력을 바꾼 뒤 생성물을 갱신한다. 두 파일을 함께 Git에서 검토하고 반영한다. `.example`을 운영 입력으로 사용하지 않는다.

```bash
rtk proxy python3 scripts/argocd_accounts.py --input gitops/platform/argocd/accounts.json --output gitops/platform/argocd/accounts.values.yaml --write
```

`phase=bootstrap`은 기본 admin을 유지한다. 개인 관리자 로그인·권한과 복구 경로를 실제 확인한 후에만 `cutover.verified_admin`에 해당 활성 개인 관리자 이름을 기록하고 `cutover.recovery_verified=true`, `phase=managed`로 별도 전환한다. 도구는 이 조건이 맞지 않으면 생성을 거부한다. **확인 기록은 사용자 선언이지 실클러스터 검증이나 실행 승인이 아니다.** 한 번 managed로 전환한 환경의 일상 변경에서는 bootstrap으로 되돌리지 않는다. Git 리뷰에서 이전 phase와 검증 기록의 유효성을 확인한다.

## Argo CD 설치에 연결할 때

계정 생성물은 Kubernetes manifest가 아니라 `configs.cm`/`configs.rbac`를 포함하는 **Helm values 조각**이다. 직접 관리하는 자기관리 Application의 공식 chart source는 Git의 이 파일을 `$values` 참조로 읽는다. bootstrap도 동일한 base·환경·계정 values 순서로 렌더링한다. 생성 출력은 YAML이며 계정 입력 accounts.json은 JSON으로 유지한다.

계정 ConfigMap을 별도 Application이나 직접 apply로 중복 생성하지 않는다. 다른 values/parameters가 계정·admin/RBAC를 덮어쓰거나 별도 `policy.*.csv`가 권한을 추가하지 않도록 전체 렌더링 결과를 검증한다. 생성물 비교 검사만으로 최종 RBAC 안전성을 보장하지 않는다.

이 계정 파일만으로 전체 설치가 완성되지는 않는다. 2단계에서 단일 A1의 chart·ARM64·ClusterIP/TLS·AppProject·초기 Secret 소유권을 연결했으며 공개 도메인·Istio·개인 계정 비밀번호 주입은 별도다. 계정 생성기 자체는 여전히 Secret을 생성하거나 읽지 않는다.

공식 입력 구조: [argo-cd chart 10.8.2 values](https://github.com/argoproj/argo-helm/blob/argo-cd-10.8.2/charts/argo-cd/values.yaml). 해당 버전은 2단계 코드의 고정 기준이며 운영 클러스터에 설치한 버전이 아니다.
