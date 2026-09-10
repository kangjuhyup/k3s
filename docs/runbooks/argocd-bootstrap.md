# Argo CD 최초 bootstrap과 GitOps 인계

2단계 코드 안내다. **실제 A1 설치·SSH·Git 인증·Doppler 조회는 수행하지 않았다.** Git URL/branch·Doppler project/config·Kubernetes 버전이 비어 있으므로 현재 운영 입력으로는 실행이 차단된다. Argo CD 설치와 개인 계정 발급은 구분한다.

## 구성

Ansible이 namespace·필수 Secret·공식 chart의 최소 설치 리소스·초기 AppProjects·루트 Application을 만든다. 이후 루트 Application이 Git에서 자기관리 Application을 만들고, 자기관리 Application은 공식 chart와 Git values를 읽어 Argo CD 자체를 관리한다.

| 원본/코드 | 역할 |
| --- | --- |
| [bootstrap.json](../../gitops/clusters/oci-a1/bootstrap.json) | Git URL/branch, Kubernetes 버전, Doppler 참조; 현재 미확정 입력 |
| [base.values.yaml](../../gitops/platform/argocd/base.values.yaml) | 단일 A1·ARM64·ClusterIP·TLS·리소스 requests와 digest 고정 |
| [versions.json](../../gitops/platform/argocd/versions.json) | 공식 chart 10.8.2, Argo CD v3.5.2, chart SHA256, Helm v4.2.4 |
| [accounts.values.yaml](../../gitops/platform/argocd/accounts.values.yaml) | 기존 개인 계정/RBAC 생성물; 마지막 values로 병합 |
| [gitops_validate.py](../../scripts/gitops_validate.py) | root/self-management Application·AppProjects·Kustomization·values 직접 선언 검사 |
| [argocd_bundle.py](../../scripts/argocd_bundle.py) | 깨끗한 Git SHA·생성물·chart checksum·전체 렌더링을 검증한 공개 bundle 준비 |
| [argocd_remote_check.py](../../scripts/argocd_remote_check.py) | 실제 실행 시 원격 Git branch SHA 확인; Git 쓰기 없음 |
| [bootstrap-argocd.yml](../../ansible/playbooks/bootstrap-argocd.yml) | 확인된 server에 최소 bootstrap 역할 실행 |
| [argocd_bootstrap_runtime.py](../../scripts/argocd_bootstrap_runtime.py) | 명시적 kubeconfig/context로 최초 create 및 인계 검사; Ansible 전용 |

root/의 YAML Application·AppProject·Kustomization과 argocd.values.yaml은 직접 관리하는 원본이다. 배포 매니페스트와 Helm values는 YAML로 관리하며 실행 설정·버전 잠금은 JSON으로 유지한다.

## 운영 전 입력

파일별 정확한 키·값·Doppler 대응은 [2단계 설정값 표](configuration-inputs.md#2단계-argo-cd--계정)를 따른다. `revision`은 branch, 로컬 실행의 `argocd_expected_revision`은 40자리 commit SHA다.

1. 1단계 K3s 설치와 노드 검증을 완료한다. 기존 OS 초기화나 K3s 삭제를 이 playbook에 맡기지 않는다.
2. `bootstrap.json`에 실제 HTTPS `.git` URL, 운영 branch, Kubernetes `major.minor.patch`, Doppler project/config를 명시한다. `reviewed=true`는 입력 검토 기록이지 실제 실행 승인을 대신하지 않는다.
3. Git 인증은 public 또는 `https-token`을 선택한다. private Git의 username/token은 해당 repo 읽기 권한만 갖고 Doppler에서 주입한다. 주소에 인증을 넣거나 TLS 검증·리다이렉트 보호를 해제하지 않는다. SSH Git, GitHub App, 사설 CA는 현재 지원하지 않는다.
4. root Git 경로의 변경 권한과 반영 branch를 플랫폼 관리자에게 제한한다. root가 AppProject를 관리하고 Argo CD가 cluster RBAC를 관리하므로 이 경로의 쓰기 권한은 높은 권한이다. 코드만으로 Git 보호 규칙을 적용한 것은 아니다.
5. bootstrap 단계의 계정 입력에는 활성 개인 계정을 두지 않는다. 기본 admin 로그인 검증 뒤 [개인 계정 절차](argocd-accounts.md)로 계정·비밀번호를 준비하고, 개인 관리자와 복구 경로를 확인한 후 별도 Git 변경으로 admin을 끈다.

초기 제공 values는 requests 합계가 CPU 500m·메모리 960Mi인 non-HA 구성이다. 사용량 보장이 아니며 실제 부하를 확인해 조정해야 한다. Dex/ApplicationSet/notifications/commit-server와 Redis HA는 끄고 4개 핵심 workload만 배치한다. API는 ClusterIP/TLS로 유지하며 공개 ingress·Istio·DNS 인증서는 3단계 이후 구성한다.

## 비밀값 소유권

Git에는 아래 값 자체를 넣지 않는다. `secret_env`와 `auth`에는 **Doppler에서 주입할 키 이름**만 저장한다.

- `admin_password_hash`: 초기 admin 비밀번호의 bcrypt hash. 현재 cost 10~16의 `$2a$`/`$2b$`/`$2y$` 형식만 받는다. 실제 로그인에 필요한 원문 비밀번호도 승인된 Doppler 경로로 보호하며 채팅에 전달하지 않는다.
- `server_secretkey`: 충분한 엔트로피의 세션 서명 키. 코드는 최소 32자 길이를 검사하지만 난수 품질을 증명하지 않는다.
- `redis_auth`: Redis 인증 값. 초기 Secret 생성 hook 대신 Doppler 값을 사용한다.
- HTTPS Git username/token: private 저장소일 때만 사용한다. 원격 SHA 검사는 임시 프로세스 환경의 URL 한정 HTTP 인증 헤더로 전달하며 명령 인자·Git 설정 파일에 값을 남기지 않는다.

chart의 `configs.secret.createSecret=false`, `redisSecretInit.enabled=false`를 유지한다. 최초 bootstrap이 `argocd-secret`, `argocd-redis`, 필요한 경우 `infra-git` Secret을 한 번 생성한다. 자기관리 AppProject에는 Secret 관리 권한을 허용하지 않아 chart/앱이 Secret을 중복 소유하지 않도록 한다. Argo CD 컨트롤러 자체의 Kubernetes 서비스 계정 권한과 AppProject 제약은 별개다.

Argo CD가 내부적으로 생성하는 self-signed TLS와 기타 내부 자격 증명은 자동 동작이며 이 코드가 Doppler로 내보내지 않는다. 이후 비밀번호·Git token·Redis 인증 교체나 개인 계정 비밀번호 추가를 위해 bootstrap을 재실행하지 않는다. 4단계에서 필드 소유권과 주입/교체 경로를 구체화하며 **전체 argocd-secret 덮어쓰기는 금지**한다.

## 로컬 준비 및 검증

저장소 루트에서 실행한다. bootstrap 설정과 직접 관리하는 선언을 함께 검토한다.
검사는 파일이나 외부 상태를 변경하지 않으며 자동 commit/push하지 않는다.

```bash
rtk proxy .local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .
rtk proxy python3 scripts/argocd_accounts.py --input gitops/platform/argocd/accounts.json --output gitops/platform/argocd/accounts.values.yaml
rtk proxy python3 -m unittest discover -s scripts/tests -v
```

Ansible controller는 1단계의 가상환경을 사용한다. bundle 렌더링에는 그 환경의 PyYAML이 필요하고, [실행 입력 예제](../../ansible/inventories/oci-a1/argocd-run.json.example)에 Python·검증된 Helm·공식 chart archive 절대 경로와 정확한 Git commit SHA를 지정한다. Helm/chart를 자동 설치하거나 운영자가 사용하는 전역 도구를 덮어쓰지 않는다.

아래는 **ansible 디렉터리에서** 수행하는 비접속 검사다.

```bash
rtk proxy ansible-playbook --syntax-check playbooks/bootstrap-argocd.yml
rtk proxy ansible-playbook -i ../.local/ansible/oci-a1/hosts.json --list-hosts playbooks/bootstrap-argocd.yml
rtk proxy ansible-lint --offline
```

공식 도구 통합 테스트에는 `ANSIBLE_TEST_BINARY`, `HELM_TEST_BINARY`, `ARGOCD_TEST_CHART`의 로컬 경로를 지정하고 Ansible 가상환경 Python으로 실행한다. 기존 Argo CD RBAC native 테스트까지 포함할 때는 `ARGOCD_TEST_BINARY`도 지정한다. 테스트는 합성 Git 저장소와 가짜 Kubernetes client를 사용하며 실제 원격 Git 검사/SSH/bootstrap을 실행하지 않는다.

## 실제 bootstrap 순서

현재는 실행하지 않는다. 이후 실제 구축 범위에서:

1. 전체 코드·입력·생성물을 검토/commit/push한다. 운영 branch에 bootstrap 대상 SHA가 올라갔는지 확인하고 bootstrap 중에는 branch 변경을 중지한다. 원격 SHA 사전 검사와 실제 pull 사이의 경쟁을 완전히 제거할 수 없으므로 이 절차가 필요하다.
2. 명시한 Doppler project/config로 필요한 키를 controller에 주입한다. `bootstrap.json`의 Doppler 참조는 인증 도구를 자동 호출하거나 현재 세션의 project/config를 증명하지 않는다. 실제 실행 환경을 운영자가 일치시켜야 한다.
3. 확인된 inventory/server limit과 실행 입력으로 `bootstrap-argocd.yml`을 실행한다. `--check`는 설치 검증이 아니므로 차단한다. 원격 Git SHA 확인 이후에만 SSH 작업으로 넘어간다.
4. 확인된 K3s marker와 API·Kubernetes 버전을 확인한다. Namespace 및 cluster-scoped Argo CD 이름 충돌이 없고 필수 Secret 입력이 유효할 때만 생성한다.
5. Secret → CRD Established → 핵심 controller rollout → 초기 AppProjects → 루트 Application 순서로 진행한다. 자기관리 Application은 Ansible이 아니라 루트 Application이 만든다.
6. 두 Application 각각의 source/destination/자동 sync 정책, `Synced`·`Healthy`, 성공 operation, 비교한 source와 실제 revision을 확인한다. 자기관리의 chart revision과 Git SHA도 각각 확인한다. 마지막으로 4개 workload rollout을 다시 검사한다.
7. 승인된 SSH 터널·loopback 전용 port-forward로 admin 로그인을 검증한다. `https://localhost:8443`은 초기 접근 URL이지 공개 도메인이 아니다. self-signed 인증서의 신뢰 확인은 별도이며 TLS를 끄지 않는다.

## 재실행·실패·복구 경계

- 인계된 namespace에서는 Kubernetes 쓰기를 하지 않고 상태만 검사한다. Ansible의 helper 파일 배치·로컬 Git/도구 검사는 여전히 수행될 수 있다. private Git 사전 검사에는 Git 읽기 인증이 필요하지만 이미 생성된 admin/Redis Secret을 다시 만들거나 갱신하지 않는다.
- 다른 설치의 namespace나 cluster-scoped 리소스와 충돌하면 거부한다. 관리자임을 이유로 기존 리소스를 강제 편입하지 않는다.
- 부분 실패로 namespace만 남거나 Application이 아직 준비되지 않았다면 완료로 보고하지 않는다. 재실행은 덮어쓰기나 자동 삭제를 하지 않는다. namespace/CRD/Secret/PVC 삭제나 상태 표식 조작 대신 실패 지점·소유권·복구 범위를 따로 검토한다. 완전 손실/부분 실패의 자동 복구 playbook은 아직 구현하지 않았다.
- `prune=false`, `allowEmpty=false`, Application 삭제 finalizer 없음이 기본이다. 자동 pruning은 별도 삭제 영향 검토 후 Git으로 도입한다. 업그레이드·일상 설정·계정 변경은 GitOps로 하며 Ansible seed를 배포 우회로 사용하지 않는다.

## 공식 근거와 검증 한계

[선언적 구성과 자기관리](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/), [다중 source values](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple_sources/), [Server-Side Apply](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/), [argocd-secret 필드](https://argo-cd.readthedocs.io/en/stable/operator-manual/argocd-secret-yaml/), [고정 chart](https://github.com/argoproj/argo-helm/tree/argo-cd-10.8.2/charts/argo-cd)를 확인했다.

2026-09-09에 공개 Quay Argo CD v3.5.2와 Docker Hub Redis 8.6.4-alpine의 OCI index에서 linux/arm64를 확인했고 index digest를 values에 고정했다. 전체 Helm 렌더링으로 initContainer를 포함한 활성 이미지, Secret/hook 부재, AppProject 허용 리소스와 계정 values 병합을 검사했다. 실제 컨테이너 실행·클러스터 Git 접근·SSA 소유권 인계·로그인·NetworkPolicy 동작은 SSH 개방 후 검증해야 한다.
