# 설치, 배포와 구성 변경

모든 변경은 [GitOps 필수 정책](gitops.md)을 먼저 따른다. Terraform·Ansible 원본도 Git에 두며 Kubernetes 배포는 컨트롤러로만 반영한다.

환경변수·비밀값은 [Doppler](doppler.md)에서 공급하고 Git에는 참조·주입 선언만 반영한다. 생성된 Secret의 data를 직접 편집하지 않는다. Doppler 값 갱신과 앱이 실제 소비하는 시점, Git rollback과 값 복원이 별개임을 검증한다.

## 신규 설치와 노드 추가

대상은 OCI Ampere A1 ARM64다. 호스트 프로비저닝·노드 추가·이미지 선택 전에 [OCI A1 운영](oci-a1.md)의 아키텍처·네트워크·볼륨 조건을 확인한다.

OCI 인스턴스는 [Terraform 운영](terraform.md), K3s 설치·설정과 노드 가입은 [Ansible 운영](ansible.md)을 따른다. Terraform 구성 변경과 K3s 가입·배포 결과를 각각 검증하며, 인스턴스 생성 성공을 클러스터 가입 성공으로 보고하지 않는다.

초기는 A1 1대(4 OCPU·24GB)의 server·워크로드 겸용 구성이다. [노드 확장](scaling.md)에 맞춰 공통 설정과 노드별 inventory를 분리한다. OS, 서버 주소/TLS SAN, datastore, 네트워크 CIDR·CNI, ingress/LB, 저장소·백업 위치를 실제 정보로 확정한다. k3s 기본 구성요소가 다른 CNI/LB와 공존 가능한지 확인한다.

기존 Ansible playbook/role이 있으면 확장한다. 다른 방식으로 설치된 노드는 현재 설정을 조사해 Ansible 관리로 편입하며 재설치를 전제하지 않는다. 신규 설치를 위해 임의의 노드·도메인·비밀번호를 만들거나 로컬 Mac에서 서버 설치 스크립트를 실행하지 않는다. 실제 호스트가 미정이면 배포 전까지 검토 가능한 구성 파일과 필요한 입력을 준비한다.

노드 추가 시 server/agent 역할, 고정 버전, API 접근, token의 안전한 전달, 노드 이름 중복 및 서버 간 critical flag 일치를 확인한다. token은 기존 secret 저장소나 제한된 token 파일을 이용하고 평문 Git/명령 인자에 넣지 않는다. 가입 후 Ready, 예상 label/taint, CNI·스토리지 동작을 확인한다.

설정 확인 위치는 기본적으로 `/etc/rancher/k3s/config.yaml`과 `config.yaml.d/*.yaml`이며 `--config`/`K3S_CONFIG_FILE`로 바뀔 수 있다. drop-in 순서와 CLI 우선순위를 고려한다. config만 보고 실제 설정을 확정하지 않는다. 기본 data-dir는 `/var/lib/rancher/k3s`이나 변경 가능하다. [K3s configuration](https://docs.k3s.io/installation/configuration)

## 관리 원본 식별

리소스의 관리 labels/annotations, managedFields, ownerReferences와 저장소 선언을 비교한다. 인증 정보가 섞인 전체 manifest 대신 필요한 필드를 조회한다.

| 실제 관리자 | 영구 변경 위치와 검증 |
| --- | --- |
| Argo CD | Git의 Application/AppProject와 참조 경로·values. ApplicationSet이 생성했다면 그 template을 수정하고 revision·sync/health를 확인한다. |
| K3s Helm Controller | HelmChart와 같은 이름·namespace의 HelmChartConfig. 리소스 namespace와 chart targetNamespace를 혼동하지 않는다. |
| 직접 설치한 Helm release | 현재 chart/values·revision·hook 영향을 조사하고 GitOps 편입 계획을 세운다. 직접 upgrade/rollback을 계속하지 않는다. |
| 일반 manifest / Kustomize | Git의 대상 환경 manifest/overlay를 GitOps 컨트롤러에 연결한다. 다른 환경 overlay까지 반영하지 않는다. |
| K3s 설치·호스트 설정 | Ansible inventory, group_vars/host_vars, role, template과 handler. |
| OCI 리소스 | Terraform resource/module과 환경별 입력. |

Istio의 설치 values/profile/revision과 Gateway·route·보안 정책 선언은 각각의 관리 원본을 찾는다. 세부 절차는 [Istio 운영](istio.md)을 따른다. K3s Helm Controller로 관리되는 chart에는 HelmChart `spec.set`이 valuesContent보다 우선하므로 실제 사용된 값도 확인한다. [K3s Helm](https://docs.k3s.io/add-ons/helm)

## 변경 준비와 적용

1. 요청된 차이를 관리 원본에 최소 변경으로 작성한다. 이미지와 chart 버전을 추적 가능한 값으로 고정하고 initContainer·Job·Helm hook까지 실제 tag/digest의 `linux/arm64` 지원을 확인한다. 환경별 namespace, storage class, ingress class, secret 참조를 실제 환경과 맞춘다.
2. 저장소 검증 명령을 우선한다. Kustomize는 build, Helm은 lint/template을 사용하되 렌더링된 Secret·민감한 values가 출력되지 않게 한다. 클러스터 접근 전 검증과 API 검증을 구분한다.
3. 대상 context/namespace를 고정하고 관련 manifest만 server dry-run/diff로 검증한다. dry-run은 API/RBAC/admission 호출을 포함하며 Secret diff는 공유 로그로 출력하지 않는다. `kubectl diff` 종료값 0은 차이 없음, 1은 차이 있음, 1 초과는 오류다. [kubectl diff](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_diff/)
4. 변경 범위에 실제 배포가 포함되면 Git의 기존 검토·반영 절차를 거쳐 컨트롤러가 조정하게 한다. 직접 apply/Helm/istioctl 설치로 우회하지 않는다. 커밋·푸시·수동 sync가 자동 배포를 일으킬 수 있으므로 파일 작성 권한과 실제 배포 권한을 구분한다.
5. GitOps가 반영한 revision과 sync/health, 관련 rollout/Helm job을 제한된 timeout으로 관찰하고 Service EndpointSlice 및 사용자 기능을 검증한다. readiness가 회복되지 않으면 다음 변경을 멈추고 관련 events와 로그를 확보한다.

롤백은 Git 원본을 검증된 이전 상태로 되돌리고 컨트롤러가 반영하게 한다. 직접 `helm rollback` 또는 `rollout undo`를 실행하지 않는다. Git revert가 DB migration, PVC 데이터, 외부 리소스까지 되돌린다고 가정하지 않는다.

## 자주 놓치는 점

- controller가 존재한다는 사실만으로 모든 리소스가 그 controller 소유인 것은 아니다.
- Istio Gateway와 Kubernetes Gateway API의 Gateway는 API group이 다르다. 이름만으로 조회·수정 대상을 정하지 않는다.
- node join 성공 로그만으로 CNI·PVC·스케줄링 성공을 판정하지 않는다.
- 최초 설치, 재설치, datastore 전환은 서로 다른 작업이다. 설치 요청을 기존 클러스터 초기화로 해석하지 않는다.

문서 확인일: 2026-09-07. 실행 시 해당 K3s/Helm/컨트롤러 버전의 공식 문서로 지원 옵션을 재확인한다.
