# Doppler 환경변수·비밀값 관리

## 원본과 변경 범위

사용자가 선택한 환경변수·비밀값 관리 도구는 **Doppler**다. 앱과 인프라 실행 환경별 값은 Doppler에서 공급한다. Git에는 인프라 구조·버전·배포 선언, Doppler project/config·키 이름·대상 Secret 참조를 둔다. `.env`, tfvars, inventory, Helm values, ConfigMap/Secret에 실제 환경변수 값을 이중 관리하지 않는다. Kubernetes Secret과 제한된 런타임 파일은 전달 결과이지 별도의 원본이 아니다.

project/config·환경·소비 워크로드·필수 키·주입 주체를 명시적으로 매핑한다. 작업 디렉터리의 암묵적 CLI 설정만으로 운영 환경을 선택하지 않는다. 현재 이름·계정·인증 방식이 미정이면 값을 추측하거나 빈 값으로 대체하지 않는다. infra 실행용과 앱용 접근 범위를 분리하고 불필요한 키를 다른 실행 환경에 전달하지 않는다.

[Wasabi 백업](wasabi.md)의 접속 키와 선택한 백업 도구의 암호화 비밀번호도 Doppler에서 공급한다. 백업·복원 실행 주체만 접근하게 하고, 백업 시점의 token/키가 현재 값 교체로 유실되지 않도록 보호된 복구 이력·보관 정책을 확인한다. Doppler 접근을 복원할 인증 수단은 대상 클러스터 밖에서도 사용할 수 있어야 한다.

GitOps의 대상은 배포·주입 선언이며 Doppler의 값 이력은 별도로 관리한다. 값 변경도 배포 영향을 가질 수 있으므로 변경 요청·Doppler 이력·영향 앱·검증 결과를 연결하되 값을 Git이나 작업 기록에 복사하지 않는다. Git revert는 Doppler 값 복원이 아니다. 스킬 편집이나 조회 요청으로 Doppler 값을 생성·갱신·삭제하지 않는다.

## 인증과 최초 부트스트랩

- 운영 소비자는 필요한 config에 한정된 읽기 권한을 사용한다. Service Token을 사용하는 경우 쓰기 권한 없는 범위와 만료·교체 정책을 확인한다. 개인의 광범위한 토큰을 모든 앱에 공유하지 않는다. 기존에 지원되는 자동화 인증 경로가 있으면 확인하여 유지한다. [Doppler Service Tokens](https://docs.doppler.com/docs/service-tokens)
- 최초 Doppler 인증은 승인된 운영자 인증 또는 CI의 보호된 자격 증명 전달 경로에서 확보한다. 그 자격 증명을 아직 접근할 수 없는 동일 Doppler config나 아직 없는 클러스터에서만 꺼내도록 설계하지 않는다. 대화로 토큰 전달을 요청하지 않는다.
- 필요한 Kubernetes 인증 Secret은 Git에 기록된 최소 Ansible bootstrap/교체 절차가 보호된 입력으로 주입한다. 토큰 값은 명령 인자·Git에 넣지 않고 작업에 `no_log`, `diff: false`를 적용한다. 이 절차는 일반 앱 Secret을 수동 배포하는 예외가 아니다.
- 새 자격 증명으로 동기화·소비가 정상인지 확인한 뒤 이전 자격 증명을 폐기한다. 발급·폐기는 실제 요청 범위에서만 수행하며 클러스터 외부의 복구 접근 경로를 보존한다.

## Terraform·Ansible 실행

Doppler CLI의 `doppler run -- <명령>`은 자식 프로세스에 값을 환경변수로 주입한다. 실제 실행 시 셸은 `rtk proxy`를 사용하고 확인한 project/config·인증을 고정한다. CLI 버전·실행 OS/아키텍처와 지원 옵션을 확인하며 노드에 무조건 CLI를 설치하지 않는다. [Doppler CLI](https://docs.doppler.com/docs/cli)

Terraform은 필요한 provider 환경변수 또는 명시적으로 매핑한 `TF_VAR_*`로 전달한다. 모든 키를 일괄 변환하거나 앱 비밀값을 Terraform으로 가져오지 않는다. 환경변수 주입이 state/plan에 비밀값이 저장되는 것을 막아주지는 않는다. provider/data source로 비밀값을 읽는 방식을 기본으로 추가하지 않고 실제 state·출력 노출 범위를 검토한다. plan과 apply 사이 환경값이 바뀌면 검증했던 입력과의 일치 여부를 재확인한다. [Doppler Terraform 연동](https://docs.doppler.com/docs/terraform)

Ansible은 컨트롤러 프로세스에 주입된 필요한 키만 명시적 lookup/변수 매핑으로 소비한다. 자식 프로세스 환경이 원격 호스트에 자동 전달된다고 가정하지 않는다. 필요한 원격 파일·template·작업에만 값을 전달하고 `no_log: true`, `diff: false`, 제한된 파일 권한을 유지한다. 키 누락은 값 출력 없이 실패시키고 debug·fact cache·인벤토리에 값을 기록하지 않는다.

기존 K3s token·인증서를 Doppler 도입 때문에 재생성하지 않는다. 필요한 기존 자격 증명의 Doppler 편입은 별도 승인 범위에서 값을 보존해 수행한다. 시스템이 자동 생성·회전하는 내부 자격 증명을 무조건 Doppler와 양방향 동기화하지 않는다.

## Kubernetes와 Argo CD

기존 Doppler 연동이 있으면 먼저 조사한다. 신규 연동은 Doppler Kubernetes Operator 등 실제 사용할 동기화 방식을 구축 전에 확정하고, 정확한 버전·CRD·이미지의 ARM64 지원을 검증한다. Doppler 선택 자체가 특정 operator의 설치까지 확정한 것은 아니다.

Doppler Kubernetes Operator를 선택하면 Argo CD가 고정 버전의 operator·CRD와 Git의 `DopplerSecret` 선언을 관리하고, operator가 Doppler 값을 Kubernetes Secret에 동기화한다. 인증 Secret → 동기화 리소스 → 대상 Secret 준비 → 소비 앱 순서를 검증한다. Argo CD가 생성된 Secret의 data를 중복 관리하거나 repo-server에서 평문 비밀값을 렌더링하지 않게 한다. 공식 문서의 직접 apply 설치 예시 대신 이 저장소의 GitOps 경로를 사용한다. [Doppler Operator](https://docs.doppler.com/docs/kubernetes-operator), [Secret 동기화](https://docs.doppler.com/docs/doppler-k8s-operator-syncing-secrets)

앱은 필요한 키만 `secretKeyRef`/`envFrom` 또는 지원되는 파일 mount로 소비한다. Secret 변경만으로 이미 실행 중인 프로세스 환경변수가 바뀐다고 가정하지 않는다. 현재 GitOps 정책에서는 자동 reload 기능을 기본 활성화하지 않고 Git의 Pod template 변경으로 재배포하거나 앱의 검증된 파일 재로딩 방식을 사용한다. 자동 reload 도입은 조정 주체와 Argo CD drift 처리 범위를 별도로 합의한 뒤 Git으로 선언한다.

생성 Secret에도 Kubernetes RBAC·저장 시 암호화·백업 접근 통제가 필요하다. Doppler에 원본이 있다는 이유로 클러스터 내 비밀값이 사라졌다고 표현하지 않는다. [Operator 보안](https://docs.doppler.com/docs/doppler-k8s-operator-security)

## 검증·장애·복구

값 대신 인증 성공 여부, project/config 매핑, 필수 키 존재 여부, 동기화 상태·마지막 성공 시각, 대상 Secret 존재와 앱 readiness·기능을 검증한다. `doppler secrets` 전체 조회, `printenv`, `env`, `set -x`, Secret 덤프를 진단 기본 명령으로 사용하지 않는다. CLI fallback 파일·캐시·임시 파일·로그도 보호 대상으로 취급한다.

Doppler 접근 장애 시 신규 주입·값 교체가 검증되지 않으면 변경을 멈춘다. 기존 Secret/앱의 동작은 실제 연동 상태로 확인하며 삭제·빈 값 덮어쓰기·임의 `.env` 대체로 재시도하지 않는다. fallback 사용 여부와 허용되는 값의 오래된 정도는 사전에 정의하고, 캐시로 성공한 실행을 최신 값 검증으로 보고하지 않는다.

복구에는 Git revision뿐 아니라 필요한 Doppler config·값 이력·인증 접근도 포함한다. 이미 폐기된 DB/외부 자격 증명은 Doppler의 이전 값 복원만으로 다시 유효해지지 않는다. Doppler는 datastore·PVC 백업을 대체하지 않는다.

문서 확인일: 2026-09-07. 실제 Doppler 연동 버전과 권한을 확인한 뒤 실행한다. 이 문서 작성은 Doppler 접근·비밀값 조회·연동 설치를 수행한 것이 아니다.
