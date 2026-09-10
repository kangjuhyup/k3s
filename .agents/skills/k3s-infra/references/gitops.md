# GitOps 필수 정책

사용자가 선택한 GitOps 컨트롤러는 **Argo CD**다. 신규 구성에 Flux를 병행 도입하지 않는다. 기존에 다른 관리자가 있으면 소유권을 조사하고 요청된 편입 범위에서만 전환한다.

## 역할과 단일 관리 원본

이 저장소의 인프라·배포 선언 변경은 Git을 필수로 경유한다. 환경변수·비밀값은 사용자가 선택한 [Doppler](doppler.md)를 원본으로 두고 Git은 참조·주입 선언을 관리한다. 선언적 상태, 버전 이력, 자동 pull, 지속적 reconciliation을 갖추는 것이 Kubernetes GitOps의 기준이다. CI에서 `kubectl apply`만 실행하는 push 배포는 이 기준을 충족하지 않는다. [OpenGitOps 원칙](https://opengitops.dev/)

| 계층 | Git에 관리할 원본 | 반영 주체 |
| --- | --- | --- |
| OCI 인스턴스·네트워크·볼륨 | Terraform module/resource, 비밀값 없는 입력·버전 잠금 | 확인된 Git revision의 plan을 검증하는 Terraform 실행 경로 |
| 호스트·K3s 설치·설정·노드 가입 | Ansible inventory 원본, role/playbook/template, 고정 버전 | 확인된 Git revision의 Ansible 실행 경로 |
| Istio·애드온·앱·라우팅·정책 | Argo CD Application/AppProject, 고정 chart/image, values, manifest/overlay | Argo CD의 pull·지속적 조정 |

Terraform·Ansible은 Git 기반 IaC 실행 계층이며 그 자체를 Kubernetes GitOps 컨트롤러로 설명하지 않는다. CI 또는 승인된 운영 실행에서 사용한 Git revision과 Doppler config·변경 이력 및 결과를 추적한다. Terraform state/plan, kubeconfig, token, 개인키, 백업 데이터는 Git에 넣지 않는다. 실제 환경변수·비밀값은 Doppler에서 공급하며 암호화한 복사본도 별도 Git 원본으로 기본 도입하지 않는다. 최초 Doppler 인증과 생성 Secret의 소유권은 [Doppler 운영](doppler.md)을 따른다.

## 최초 부트스트랩과 소유권 인계

1. 기존 Argo CD 설치, 관리 경로·환경, 인증 방식과 실제 이미지의 ARM64 지원을 조사한다. 신규 설치는 버전·namespace·Git 주소/경로·인증 참조를 확인한다. 이 스킬 편집만으로 Argo CD·Git 호스팅·CI를 설치하지 않는다.
2. Terraform으로 OCI, Ansible로 K3s를 준비한다. Argo CD와 루트 Application·필요한 AppProject·Git 인증 연결을 위한 **최소 seed**만 Git에 버전 고정된 재실행 가능한 Ansible 부트스트랩 절차로 설치한다. 실제 실행은 구축 요청 범위일 때만 한다.
3. Argo CD가 지정한 Git revision을 읽고 정상 조정하는지 확인한다. 이후 Argo CD 자신의 원하는 상태도 Git의 Application으로 관리하며 seed와 일상 관리가 동일 리소스를 계속 덮어쓰지 않게 인계한다. 최초 접근과 복구를 아직 설치하지 않은 Istio gateway에만 의존시키지 않는다.
4. CRD → 필요한 컨트롤러의 준비 → custom resource·Istio·앱 순서를 의존성/health gate로 표현한다. Git 연결 전에 Istio나 앱을 Ansible/Helm으로 미리 배포하지 않는다.

K3s가 생성·관리하는 시스템 구성은 Git의 Ansible 설정을 원본으로 유지하고 생성된 파일·리소스를 이중 관리하지 않는다. HelmChartConfig가 필요한 경우 선언은 GitOps로 전달하고 K3s Helm Controller와 GitOps의 소유 범위를 구분한다. 기존 직접 설치한 release는 현재 values·버전·소유권을 조사하여 별도 편입 계획으로 옮긴다. 편입을 위해 release·CRD·PVC를 삭제하지 않는다.

## Argo CD 선언과 검증

- 앱은 Git의 `argoproj.io/v1alpha1` `Application`으로 정의한다. `spec.project`, `source` 또는 `sources`의 repoURL·targetRevision·path/chart·values, `destination`의 확인된 cluster와 namespace를 명시한다. AppProject의 sourceRepos·destinations·리소스 권한을 업무 범위로 제한한다. Argo CD 자체를 관리하는 프로젝트·Git 경로는 관리자 범위로 분리한다. [선언적 구성](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/)
- 반복 앱 생성이 실제로 필요할 때만 `ApplicationSet`을 사용한다. 그 경우 생성된 Application 대신 Git의 ApplicationSet template을 변경한다. A1 agent가 늘어도 같은 클러스터이므로 노드마다 Application이나 Argo CD 인스턴스를 만들지 않는다.
- Istio Helm chart는 Application의 source와 Git의 고정 버전·values로 관리한다. Argo CD에서 Helm은 렌더링 도구이며 배포 수명주기는 Argo CD가 관리한다. `helm list`/release revision을 Argo CD 배포의 성공 기준으로 사용하지 않는다. [Argo CD Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
- Argo CD CLI를 쓸 때 확인된 서버와 CLI context를 명시하고 Kubernetes context와 구분한다. Git의 기대 revision과 Application의 sync revision(다중 source는 각 revision), `Synced`·`Healthy`, sync operation·resource 오류를 확인한 뒤 실제 서비스 기능을 검사한다. Application 생성 성공만으로 배포 완료라고 보고하지 않는다.

## 일상 변경과 롤백

- Git 원본 수정 → 정적 검사·안전한 diff → 저장소의 검토/반영 절차 → 컨트롤러 조정 → revision·health·실제 기능 검증을 따른다. 파일 작성 요청은 commit/push/merge/sync 또는 배포 권한이 아니다.
- Git의 Application에 `spec.syncPolicy.automated.enabled: true`와 `selfHeal: true`를 명시하고 선택한 Argo CD/CRD 버전의 지원을 확인한다. `allowEmpty: false`를 유지한다. `prune`은 삭제 영향과 소유권을 검토해 명시하며 초기 편입·검토 전에는 false로 둔다. pruning을 활성화할 때 CRD/PVC·Application 연쇄 삭제 보호를 따로 검증한다. [Argo CD 자동 동기화](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- 수동 sync/reconcile 요청은 승인된 배포 범위에서 **이미 Git에 기록된 원하는 revision**을 반영하는 용도로만 허용한다. Git을 무시한 override, 로컬 manifest 배포, 임의 revision 전환을 사용하지 않는다.
- 롤백도 Git revert 또는 검증된 이전 버전으로 Git 원본을 변경한 뒤 Argo CD가 반영한다. 직접 `argocd app rollback`, `helm rollback`, `rollout undo`, live patch로 우회하지 않는다. UI/CLI parameter override도 사용하지 않는다. Git revert는 DB migration·PVC 데이터·외부 시스템을 복원하지 않는다.
- 재시작이 필요하면 추적 가능한 Pod template 변경 등 GitOps가 관리할 원본에 명시한다. HPA·operator·Gateway controller가 생성/조정하는 필드는 해당 선언적 상위 원본을 관리하며 모든 live 필드를 Git으로 고정하지 않는다.

## 장애와 운영 작업

Argo CD가 멈춰도 긴급 이미지 변경을 직접 apply/Helm으로 배포하지 않는다. Git 변경을 준비하고 조회로 Git 접근·인증, repo-server/application-controller 및 Application의 source/render/sync 오류·자원을 진단한다. 필요한 권한이나 접속 정보가 없으면 해당 실행만 중단하고 원인과 필요한 입력을 보고한다.

컨트롤러 자체가 손실되어 정상 조정이 불가능하면 확인된 Git revision의 **최소 부트스트랩 복구 절차**만 재실행하고 자기관리 인계를 다시 검증한다. 일반 앱 장애를 부트스트랩으로 재분류하지 않는다. Git·복구 인증·백업은 대상 클러스터가 죽어도 접근 가능하게 준비한다.

백업·datastore 복구·cordon/drain·노드 유지보수처럼 지속적인 원하는 상태 변경이 아닌 일회성 운영은 Git에 기록된 Ansible playbook/runbook으로 요청 범위에서 실행하고 대상·revision·결과를 남긴다. 이를 임의 manifest 수정의 우회 통로로 사용하지 않는다. 복구 시 조정 재개 순서와 목표 Git revision을 맞춰 이전 상태가 즉시 덮어써지지 않게 한다. 데이터 백업은 GitOps와 별도로 유지한다.

## 강제 수준

이 스킬은 에이전트의 운영 지침이다. 실제 접근 제어까지 강제하려면 별도 구축 범위에서 사용자·일반 CI의 쓰기 권한 최소화, 컨트롤러 서비스 계정 범위, 보호된 Git 반영 경로, 감사 기록 및 분리된 bootstrap/복구 자격 증명을 설계·검증한다. 스킬 파일만으로 RBAC·브랜치 보호가 적용되었다고 보고하지 않는다.

문서 확인일: 2026-09-07. 실제 컨트롤러 버전의 공식 문서로 bootstrap·self-management·drift 복구 옵션을 확인한다.
