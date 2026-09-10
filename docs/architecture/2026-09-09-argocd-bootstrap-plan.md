# 2단계: Argo CD bootstrap과 GitOps 인계

이 문서는 당시 구현 계획의 기록이다. 2026-09-11부터 고정 앱의 생성기를 제거하고
Application·AppProject·매니페스트·values를 직접 관리한다. 현재 명령은
[운영 안내](../runbooks/argocd-bootstrap.md)를 따른다. 계정·Doppler 생성기는 별도로 유지한다.
같은 정리에서 배포 파일은 YAML로 전환했다. 아래 JSON 생성 설명은 당시 구현 기록이다.

## 범위

사용자의 2단계 구현 요청에 따라 코드와 로컬 검증만 수행한다. OCI/SSH/클러스터/Doppler 접속, commit/push, 실제 설치·계정 발급은 하지 않는다. 실제 Git URL/branch는 필수 입력이며 임의 값을 활성 설정에 넣지 않는다.

## 설계

- 검증된 공식 argo-cd chart 10.8.2 / Argo CD v3.5.2를 2단계 호환성 기준으로 고정한다. 모든 활성 이미지의 ARM64 manifest와 digest를 확인하여 Git values에서 고정한다. 운영 전 K3s 호환성은 별도 확인한다.
- public HTTPS 또는 HTTPS username/token Git 인증을 지원한다. SSH Git·GitHub App·사설 CA는 후속 범위다. 저장소 주소에 인증을 넣거나 TLS 검증을 끄지 않는다.
- Python 생성기가 비밀값 없는 환경 입력을 검증해 root Application, root/self-management AppProjects, Argo CD 자기관리 Application과 환경 values를 만든다. 생성물도 Git에서 검토한다. JSON manifest는 Kustomize 리소스로 연결한다.
- root는 클러스터 root 경로의 Application/AppProject만 관리한다. 자기관리 Application은 고정 공식 Helm chart와 같은 Git의 values를 다중 source로 읽는다. 계정/RBAC values도 기존 생성물을 그대로 연결한다.
- 자동 sync/selfHeal, allowEmpty=false, prune=false, ServerSideApply=true. Application 삭제 finalizer를 기본 추가하지 않는다. root Git 경로의 쓰기 권한은 플랫폼 관리자에게만 허용해야 한다.
- non-HA 1 replica 구성, Redis 단일 replica, Dex/ApplicationSet/notifications 불필요 구성요소 비활성화. ClusterIP/TLS 유지, 공개 ingress 없음. 최초 접근은 승인된 SSH 터널/loopback port-forward로 분리한다.
- chart의 argocd-secret 생성과 Redis secret-init hook을 끈다. 최소 bootstrap에서 Doppler 주입값으로 argocd-secret, argocd-redis, 필요한 Git repository Secret을 한 번만 생성한다. Git에는 값·hash·토큰을 넣지 않는다. 이후 Secret 전체 덮어쓰기와 account admin 전환은 이 단계에서 하지 않는다.
- Ansible은 고정 로컬 Helm으로 공개 manifest를 렌더링하고 선별 검증한 bundle을 server에 전달한다. Helm install/upgrade는 하지 않는다. 원격 실행기는 명시적 kubeconfig/context/namespace를 사용하고 Secret을 stdin으로만 전달한다.
- namespace가 없을 때만 최소 seed를 생성한다. namespace·cluster-scoped 이름 충돌은 생성 전 확인하며 기존 다른 설치는 거부한다. namespace가 이미 있으면 소유권 확인 후 root/self-management 상태만 검사하며 쓰지 않는다. 부분 실패는 자동 삭제/덮어쓰기 없이 복구 검토를 요청한다.
- 완료 판정은 root와 자기관리 Application의 Synced/Healthy, 성공 sync operation, 실제 Git SHA(다중 source 각각), chart revision과 컨트롤러 rollout이다. 로컬 checkout의 확인된 Git SHA와 generated 파일 일치를 사전 확인한다. 오래된 성공 상태만으로 인계를 완료하지 않는다.

## 검증

- 입력·생성물·권한/소유권/비밀값 분리 단위 테스트.
- 공식 Helm chart 전체 렌더링, 활성 ARM64 이미지·ClusterIP·replica·Secret 부재·계정 values 병합 확인.
- 가짜 Kubernetes client로 bootstrap 순서, 충돌·부분 실패·revision 불일치 거부, 인계 후 쓰기 0건 검사.
- Ansible syntax/lint, 기존 1단계·계정 테스트, 문서 링크 검사.
- 실제 cluster health, Git 접근, 로그인·DNS·TLS·네트워크 경로는 현재 확인하지 않는다.

## 결과 (2026-09-09)

- 2단계 코드와 운영 문서를 구현했다. 실제 Git 입력이 비어 있어 활성 선언 생성은 차단된다. 기존 파일은 보존했고 commit/push·SSH·운영 API·Doppler 호출은 하지 않았다.
- 전체 43개 테스트 통과: Ansible native 6, 계정 단위/CLI 10·공식 도구 2, K3s 입력/inventory 8, GitOps 생성/원격 Git 검사 모의 7, bootstrap 상태/전달 7, 공식 chart·로컬 Git bundle 3.
- ansible-core 2.21.4 / ansible-lint 26.8.0, Helm v4.2.4, chart 10.8.2를 사용했다. Ansible lint 실패/경고 0, 6개 playbook syntax 검사, 문서 39개·상대 링크 202개·셸 예제 12개 검사 통과.
- 실제 subprocess 명령에서 Secret은 stdin, Git 인증은 URL 한정 임시 프로세스 환경으로 전달되는지 모의 검사했다. 실제 SSH/프로세스 감사나 운영 비밀값 노출 검증을 대신하지 않는다.
- 공개 OCI registry index의 linux/arm64 항목과 고정 image digest, Helm 전체 렌더링의 Secret/hook 부재·ClusterIP·replica·계정/RBAC 병합·AppProject 허용 범위를 확인했다.
- 실제 SSA 소유권 인계·원격 Git 인증·배포 성공·로그인·NetworkPolicy·복구는 아직 확인하지 않았다. 부분 bootstrap 실패 자동 복구, 개인 계정 비밀번호 전달과 이후 Secret 교체는 후속 구현 범위다.
