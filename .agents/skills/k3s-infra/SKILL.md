---
name: k3s-infra
description: Use when managing K3s and Istio on OCI Ampere A1 arm64 with Terraform, Ansible, Argo CD GitOps, Doppler and Wasabi backups, including node expansion, deployments, secret delivery, sync failures, cluster health, backup, restore, or upgrades. OCI A1·ARM64·Terraform·Ansible·ArgoCD·Doppler·Wasabi·GitOps·K3s·Istio 인프라 관리 요청에 사용한다.
---

# K3s 인프라 관리

대상 클러스터와 실제 관리 원본을 확인한 뒤 요청된 운영 작업을 수행한다. 환경별 주소·버전·토폴로지를 추측하거나 이 스킬에 자격 증명을 저장하지 않는다. 사용자에게는 한국어로 결과와 근거를 설명한다.

이 스킬의 Ingress·서비스 메시 기준은 **Istio**다. 실제 설치 상태, Gateway API 사용 여부, sidecar/ambient 모드는 실행 시 확인한다. 스킬 설정 변경을 실클러스터 마이그레이션 권한으로 해석하지 않는다.

대상 서버는 사용자가 지정한 **OCI Ampere A1, Linux ARM64(aarch64)**이며 현재 **1대, 4 OCPU·24GB RAM**이다. 초기에는 한 server에서 control plane과 워크로드를 함께 운영하고, 향후 A1 노드를 추가할 수 있게 구성한다. 기본 확장 경로는 agent 추가이며 control-plane HA는 별도 목표로 구분한다. 노드 이미지·서버 바이너리·컨테이너는 ARM64에 맞춘다. OS 배포판, 리전, 네트워크, datastore와 추가 노드의 사양은 실제 구성 또는 후속 지시로 확인한다.

**OCI 인스턴스는 Terraform, K3s 설치·노드 가입과 호스트 설정은 Ansible, Istio·애드온·앱은 Argo CD**로 관리한다. 인프라·배포 선언은 Git에 둔다. 기존 A1을 재생성하지 않고 현재 state 또는 import로 관리하며, 노드 증설은 안정적인 키를 가진 map과 `for_each`로 표현한다. Terraform의 비밀값 없는 출력을 Ansible inventory로 연결하고 공통·server·agent 설정을 분리한다.

**환경별 런타임 환경변수·비밀값의 관리 원본은 Doppler**다. Git에는 project/config·키 이름·주입 선언 등 참조를 두고 실제 값을 중복 저장하지 않는다. 구조·버전·노드 정의는 Git으로 관리하며 환경변수 값과 구분한다. 최초 인증, Terraform·Ansible 주입, Kubernetes 동기화와 값 교체는 [Doppler 운영](references/doppler.md)을 따른다. 이 선택은 Doppler 값 변경·토큰 발급 또는 실제 연동 설치 권한이 아니다.

**노드 외부 백업 사본은 Wasabi Object Storage**에 보관한다. 접속 자격 증명은 Doppler에서 공급하며 [Wasabi 백업](references/wasabi.md)에 따라 datastore·앱 데이터·복구 인증을 구분한다. 이 선택만으로 버킷을 생성하거나 Terraform state backend·앱의 실시간 저장소를 Wasabi로 변경하지 않는다.

**GitOps는 선택 사항이 아니라 필수 정책이며 컨트롤러는 Argo CD로 확정되었다.** Kubernetes 원하는 상태는 Git 변경을 Argo CD가 가져와 지속적으로 조정하게 한다. 직접 `kubectl apply/edit/patch/set/scale`, `helm install/upgrade/rollback`, `istioctl install` 또는 `rollout undo/restart`로 배포·설정을 우회하지 않는다. 긴급 장애도 예외로 간주하지 않는다. 조회·렌더링·dry-run은 허용하며 최초 Argo CD 부트스트랩, 복구와 일회성 운영 작업의 경계는 [GitOps 필수 정책](references/gitops.md)을 따른다. 버전·저장소 주소·인증·외부 노출 방식은 실제 구축 시 확인한다.

## 시작

1. 현재 저장소의 `AGENTS.md`, 운영 문서, 변경 상태를 읽는다. `rg --files`로 Helm/Kustomize, Argo CD Application/AppProject/ApplicationSet, Ansible/Terraform, 서버 설정의 위치를 찾는다. 빈 저장소는 미구성 상태로 취급하며 운영 환경을 임의로 생성하지 않는다.
2. 요청이 조회·진단인지, 파일 변경인지, 실제 배포·운영인지 구분한다. 이미 승인된 범위는 계속 수행한다. 조회 요청은 결과와 수정안까지 제공하고 실제 변경으로 확대하지 않는다.
3. 대상 kubeconfig/context와 API 주소, namespace, 노드/SSH 대상, 설치 버전, server/agent 역할, datastore 종류, 리소스 관리 주체 중 작업에 필요한 정보를 확인한다. 모르는 항목은 미확인으로 남긴다. 대상이 모호하면 로컬 자료를 먼저 조사하고 필요한 항목만 질문한다.
4. **조회에도** `kubectl --context "$K3S_CONTEXT"`, `helm --kube-context "$K3S_CONTEXT"`, `istioctl --context "$K3S_CONTEXT"`를 명시한다. namespaced 리소스에는 `-n "$K3S_NAMESPACE"`를 쓴다. 전역 `use-context` 변경은 필요하지 않다. SSH 대상은 사용자 지시나 inventory에서 확인한다.
5. 셸은 로컬 `RTK.md` 지침을 따른다. 아래 예시는 `rtk proxy`로 원래 출력을 보존한다. 원격 서버에 RTK가 있다고 가정하지 않는다. `systemctl`과 `k3s` 서버 명령은 확인된 Linux 노드에서 실행한다.

## 작업별 참고 문서

| 요청 | 읽을 문서 |
| --- | --- |
| 모든 구성 변경·배포·복구, Argo CD 부트스트랩·동기화 장애 | [GitOps 필수 정책](references/gitops.md) |
| 환경변수·비밀값, Doppler 주입·동기화·토큰·값 교체 | [Doppler 운영](references/doppler.md) |
| 상태 점검, NotReady, CrashLoopBackOff, DNS/Ingress/PVC 장애 | [진단](references/diagnostics.md) |
| 신규 설치, 노드 추가, Helm/Kustomize/GitOps 배포, 설정 변경 | [배포와 설정](references/changes.md) |
| OCI A1 프로비저닝, ARM64 이미지, 네트워크·볼륨 확인 | [OCI A1 운영](references/oci-a1.md) |
| Terraform 인스턴스 관리, 기존 노드 import, plan/apply·state | [Terraform 운영](references/terraform.md) |
| Ansible K3s 설치·설정, inventory, server/agent 가입 | [Ansible 운영](references/ansible.md) |
| 현재 단일 노드 구성, A1 노드 증설, control-plane HA 계획 | [노드 확장](references/scaling.md) |
| Istio 설치·Gateway·라우팅·mTLS·sidecar/ambient 진단 | [Istio 운영](references/istio.md) |
| 백업·복구, 업그레이드, drain, 노드 제거 | [유지보수](references/maintenance.md) |
| Wasabi 백업 사본·S3 연결·보존 정책·원격 사본 복구 | [Wasabi 백업](references/wasabi.md) |

현재 작업에 해당하는 문서만 읽는다. 버전별 옵션·지원 범위·차트 값은 실제 설치 버전의 `--help`, 저장소 설정, 링크된 공식 문서와 릴리스 노트로 확인한다. 특정 버전을 항상 최신이라고 간주하지 않는다.

## 운영 원칙

- Git의 선언과 실제 소유자를 **리소스별로** 확인한다. 기존 수동 Helm/manifest는 GitOps 편입 대상으로 취급하며 수동 배포를 계속하는 근거로 사용하지 않는다. 생성 리소스를 직접 수정하거나 여러 관리자가 동일 필드를 중복 관리하지 않는다.
- 변경 전 대상·예상 영향·검증·복구 경로를 구체화한다. 사용자 요청에 포함된 일반 변경은 불필요한 재승인 없이 수행한다. 삭제, 데이터 덮어쓰기, 복원, 서비스 중단이 요청 범위에 없으면 해당 단계만 확인한다.
- server token, kubeconfig 인증 정보, Secret 값, registry/DB/S3 자격 증명은 출력·커밋하지 않는다. manifest, Helm values, 로그, diff도 비밀값을 포함할 수 있으므로 출력 전에 필요한 필드만 선택한다. `config view --raw`, 전체 Secret 덤프를 사용하지 않는다.
- 장애 증거를 먼저 확보한다. 재시작·재설치·PVC 삭제·finalizer 강제 제거·`cluster-reset`을 일반 진단 절차로 사용하지 않는다.
- 명령 성공과 서비스 복구를 구분한다. 변경 후 rollout/컨트롤러 상태, 관련 endpoint, 사용자 관점 기능을 확인하고 실패 시 무작정 반복 적용하지 않는다.

## 결과 보고

확인한 대상 → 핵심 결과와 근거 → 수행한 변경 → 검증 결과 → 남은 문제 순서로 짧게 보고한다. 명령 실행 실패, 권한 부족, 접속 불가, 실제로 실행하지 않은 검증을 명시한다. 로컬 파일만 수정했다면 운영에 반영했다고 표현하지 않는다.
