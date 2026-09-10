# 단계별 설정값 입력 안내

모든 경로는 저장소 루트 기준이다. **실제 비밀값은 Doppler에만 입력**하고 JSON/HCL에는 값이 아니라 키 이름·구조·참조를 넣는다. 아래 예시는 설명용이며 운영값이 아니다. 빈 문자열·`reviewed=false`는 미확인 상태로 유지한다. true로 바꾼다고 실제 검증이나 실행 승인이 생기지 않는다.

| 단계 | 직접 편집할 위치 | 현재 상태 |
| --- | --- | --- |
| 사전: Terraform 편입 | `terraform/environments/oci-a1/nodes.tfvars.example`을 참고한 별도 환경 입력 | 편입 코드만 있음, 실제 값·backend 미정 |
| 사전: Ubuntu 초기화 | [OS 교체 점검 기록](os-rebuild.md) | 자동 실행 코드 없음 |
| 1. K3s | `ansible/inventories/oci-a1/settings.json` — 아래 예제를 복사해 신규 작성 | 설치·입력 검증 코드 있음 |
| 2. Argo CD | `gitops/clusters/oci-a1/bootstrap.json` 및 `gitops/platform/argocd/accounts.json` | 코드 있음, 실제 값 미입력 |
| 3. Istio | `gitops/clusters/oci-a1/istio.json`, `gitops/clusters/oci-a1/ingress.json` | 내부 baseline 및 ServiceLB 외부 TLS·라우팅·mTLS 코드 있음, 비활성 |
| 4. Doppler 동기화 | `gitops/clusters/oci-a1/doppler.json`, 로컬 `doppler-run.json` | Operator·인증 bootstrap·매핑·조회 검사 코드 있음, 비활성 |
| TLS 자동화 기반 | `gitops/clusters/oci-a1/cert-manager.json` | cert-manager 설치 코드 있음. DNS 업체 미확인으로 Issuer·Certificate는 아직 미구현 |
| 5. Wasabi 백업 | 아래 5단계 준비 항목, 추후 백업 schema 작성 | 미구현 — 현재 입력해도 소비되지 않음 |
| 6. 종합 검증 | 아래 6단계 준비 항목 | 통합 실행기 미구현 |

## 공통: 값과 키 이름의 차이

예를 들어 `bootstrap.json`의 `secret_env.redis_auth`에는 **`ARGOCD_REDIS_AUTH`라는 문자열**을 적는다. 실제 랜덤 비밀번호는 선택한 Doppler project/config의 **`ARGOCD_REDIS_AUTH` 키 값**에 저장한다. 이 문자열은 예제의 기본 키 이름이며 같은 이름으로 맞추거나 참조와 Doppler 키를 함께 변경해야 한다.

Doppler project/config는 아직 정하지 않았다. `infra`/`prd` 같은 이름을 미리 운영 환경으로 간주하지 않는다. 실행할 때 CLI의 `--project`·`--config`를 명시한다. 1단계 입력에는 Doppler project/config 필드가 없으므로 JSON에 임의 키를 추가하지 않는다. 2단계의 `doppler` 필드도 비밀값을 내려받지 않으며, 실행자가 그 config로 주입한 환경변수를 코드가 읽는다.

최초 Doppler 로그인/자동화 인증은 클러스터 밖의 보호된 경로에서 준비한다. 아직 접근할 수 없는 같은 config에서 최초 인증 토큰을 꺼내야 하는 순환 의존을 만들지 않는다. MCP 설정은 실행의 필수 조건이 아니다. SSH 개인키·kubeconfig도 채팅·Git에 넣지 않는다.

## 사전 단계: 기존 A1 Terraform 편입

원본 예제: [nodes.tfvars.example](../../terraform/environments/oci-a1/nodes.tfvars.example). 실제 입력을 `terraform/environments/oci-a1/nodes.auto.tfvars.json` 등 별도 파일로 작성한다. **현재 tfvars는 Git에서 제외된다.** 비밀값 없는 실제 선언을 확정할 때만 이 파일 하나를 `.gitignore` 예외로 검토하고 Git으로 관리한다. 예제 자체를 운영 입력으로 채우지 않는다.

| 키 | 넣을 값 / 확인 위치 |
| --- | --- |
| `adoption_reviewed` | 처음 false; 대상·backend·기존 state 소유권·무변경 편입 검토 후 true |
| `oci_region` | 선택 사항. 실제 OCI 리전 식별자. 생략하면 Doppler `OCI_REGION` 사용 |
| `nodes.<고정키>` | 인스턴스를 식별할 안정적인 이름. 예: `a1-server-1`. 이후 IP 때문에 변경하지 않음 |
| `nodes.<키>.existing_instance_ocid` | 편입할 기존 A1의 실제 instance OCID |
| `nodes.<키>.compartment_id` | 기존 compartment OCID, 루트면 tenancy OCID |
| `nodes.<키>.availability_domain` | 해당 인스턴스의 실제 AD 전체 문자열 |
| `nodes.<키>.display_name` | 기존 이름 그대로 |
| `nodes.<키>.role` | 첫 노드 `server`, 추후 기존 agent 편입 시 `agent` |
| `nodes.<키>.ocpus` / `memory_in_gbs` | 현재 A1은 확인 후 `4` / `24`; 다른 노드에 복제하지 않음 |
| `nodes.<키>.subnet_id` | 현재 VNIC의 subnet OCID |
| `nodes.<키>.assign_public_ip` | 기존 설정과 일치하는 true/false, null 불가 |
| `nodes.<키>.source_type` / `source_id` | 기존 원본 `image` 또는 `bootVolume`과 그 OCID. **새 Ubuntu 이미지로 바꾸지 않음** |
| 선택 필드 | `boot_volume_size_in_gbs`, `boot_volume_vpus_per_gb`, `kms_key_id`, `fault_domain`, `hostname_label`, `private_ip`, `nsg_ids`, `skip_source_dest_check`, `freeform_tags`, `defined_tags`: 기존 값이 필요할 때 정확히 매핑 |

API Key 인증을 선택할 때 Doppler infra config에 아래 키를 준비한다. 다른 인증 방식은 별도 검토한다.

| Doppler 키 | 값 |
| --- | --- |
| `OCI_AUTH` | `APIKey` |
| `OCI_TENANCY_OCID`, `OCI_USER_OCID` | OCI 인증 주체의 실제 OCID |
| `OCI_FINGERPRINT` | API 서명 공개키 fingerprint |
| `OCI_PRIVATE_KEY` | 등록한 API 서명 키와 짝인 PEM 개인키, 실제 값은 Doppler만 |
| `OCI_PRIVATE_KEY_PASSWORD` | 해당 개인키가 암호화된 경우만 암호 |
| `OCI_REGION` | 실제 대상 리전 |
| `TF_VAR_metadata_by_node` | 필요한 경우만 기존 metadata의 `노드키 → 문자열 map` JSON. 비밀정보 가능, state에도 남을 수 있음 |

backend 유형·주소·workspace·잠금·인증은 미정이며 현재 소비되는 backend 입력 키는 없다. **실제 import/plan/apply 전에 backend를 별도로 구성한다.** SSH를 열 필요는 없다. [편입 절차](terraform-adoption.md).

Ubuntu 초기화에서는 instance OCID, 이전 boot volume OCID, 새 **Ubuntu ARM64 image OCID**, launch options 호환성, 이전 볼륨 보존, 새 SSH 사용자/공개키와 콘솔 복구 수단을 기록한다. 자동화 입력 파일은 아직 없다. `source_id` 변경으로 교체를 우회하지 않는다. [OS 재구축 절차](os-rebuild.md).

## 1단계: Ansible · K3s

[settings.json.example](../../ansible/inventories/oci-a1/settings.json.example)의 구조를 `ansible/inventories/oci-a1/settings.json`으로 작성한다. 비밀값 없는 운영 원본은 Git 검토 대상이다. 준비 중 `.local/`을 사용할 수 있지만 최종 관리 원본으로 삼지 않는다. `hosts.yml`이나 생성 inventory를 직접 채우는 방식은 사용하지 않는다.

| JSON 키 | 넣을 값 |
| --- | --- |
| `reviewed`, `network_reviewed` | 대상·OS·입력 및 OCI/Ubuntu 방화벽·라우팅 점검 후 각각 true |
| `version` | 검토한 고정 K3s 릴리스 `v1.MINOR.PATCH+k3sN`. 실제 선택 필요, 테스트 버전 복사 금지 |
| `sha256` | **같은 릴리스의 `k3s-arm64`** 공식 SHA256 64자리, amd64 checksum 사용 금지 |
| `datastore` | 현재 구현은 `sqlite`만 지원 |
| `pod_cidr` | VCN/VPN/노드/Service 대역과 겹치지 않는 Pod IPv4 CIDR |
| `service_cidr` | Pod/VCN/VPN/노드 대역과 겹치지 않는 Service IPv4 CIDR |
| `cluster_dns` | Service CIDR 내부의 사용할 DNS 서비스 IP |
| `endpoint` | 모든 노드에서 접근할 `https://실제-주소:6443` |
| `tls_sans` | endpoint의 호스트/IP를 포함하는 인증서 SAN 배열; URL/포트가 아니라 호스트/IP |
| `servicelb` | 사용자 선택에 따라 첫 설치부터 **true**. 외부 ingress 생성기가 true인지 검사 |
| `token_env.server` | Doppler 키 이름, 기본 `K3S_SERVER_TOKEN` |
| `token_env.agent` | Doppler 키 이름, 기본 `K3S_AGENT_TOKEN`; server 키와 이름 달라야 함 |
| `nodes.<고정키>.role` | 첫 노드 `server`, 추가 노드 `agent`; server 정확히 1대 |
| `nodes.<키>.ssh_host` | 실제 SSH 접속 IP/호스트. public IP 또는 접근 가능한 private 경로 |
| `nodes.<키>.ssh_user` | 실제 sudo 가능한 계정. Ubuntu라는 이유만으로 사용자명을 추측하지 않음 |
| `nodes.<키>.node_ip` | 해당 노드의 실제 내부 IPv4 |
| `nodes.<키>.flannel_iface` | 위 IP를 가진 실제 인터페이스 이름 |
| `nodes.<키>.os_distribution` | `Ubuntu` |
| `nodes.<키>.os_version` | 새 OS의 `/etc/os-release`에서 확인한 `VERSION_ID`, `YY.MM` 형식. point-release 설명 전체가 아니라 이 값을 입력 |

| Doppler 키(기본명) | 실제 값과 준비 시점 |
| --- | --- |
| `K3S_SERVER_TOKEN` | 첫 server용 충분히 무작위인 32자 이상 short token. 허용 문자 영문·숫자·`_`·`-` |
| `K3S_AGENT_TOKEN` | server 시작 후 보호된 경로로 확보한 CA-pinned `K10…::…` secure token. **agent 가입 전 필요**, 초기 short token 복사 금지 |

SSH는 검증한 known_hosts와 SSH agent/보호된 개인키를 controller에 준비한다. JSON에는 개인키를 넣지 않는다. SSH 사용자·sudo·Python3·Ubuntu 버전은 preflight에서 재확인한다. 노드 이름은 Terraform과 매핑해야 하며 전체 state를 자동 변환하지 않는다.

생성 inventory: `.local/ansible/oci-a1/hosts.json` (상위 디렉터리 사전 준비). 저장소 루트에서 다음은 **로컬 생성/비교만** 한다.

```bash
rtk proxy python3 scripts/k3s_inventory.py --input ansible/inventories/oci-a1/settings.json --output .local/ansible/oci-a1/hosts.json --write
rtk proxy python3 scripts/k3s_inventory.py --input ansible/inventories/oci-a1/settings.json --output .local/ansible/oci-a1/hosts.json
```

Ansible 실행은 `ansible/`에서 명시적 inventory를 사용한다. controller Python/Ansible 설치와 실제 실행 순서는 [1단계 안내](../../ansible/README.md). 설치 전 preflight, 설치 후 verify-cluster가 필요하다.

## 2단계: Argo CD · 계정

직접 편집: [bootstrap.json](../../gitops/clusters/oci-a1/bootstrap.json).

| JSON 키 | 넣을 값 |
| --- | --- |
| `reviewed` | Git·버전·인증·Doppler config 검토 후 true |
| `repo_url` | 실제 HTTPS Git URL, `.git`로 끝남. 사용자명/토큰/쿼리 포함 금지 |
| `revision` | Argo CD가 추적할 실제 **branch 이름**, 예: `main`. `HEAD` 또는 commit SHA 아님 |
| `kube_version` | 설치할 K3s의 Kubernetes 기본 버전 `1.MINOR.PATCH` — `v`와 `+k3sN` 제거. API 실제 버전과 같아야 함 |
| `auth.mode` | 공개 Git `public`, 비공개 HTTPS Git `https-token` |
| `auth.username_env` / `password_env` | 기본 `ARGOCD_GIT_USERNAME` / `ARGOCD_GIT_TOKEN`; public도 참조 필드는 유지, 실제 값 불필요 |
| `doppler.project` / `doppler.config` | 이번 bootstrap 실행에 사용할 실제 Doppler project/config 이름 |
| `secret_env.admin_password_hash` | 기본 키 이름 `ARGOCD_ADMIN_PASSWORD_HASH` |
| `secret_env.server_secretkey` | 기본 키 이름 `ARGOCD_SERVER_SECRETKEY` |
| `secret_env.redis_auth` | 기본 키 이름 `ARGOCD_REDIS_AUTH` |

위에서 선택한 Doppler config에 실제 값을 입력한다.

| Doppler 키(기본명) | 값 |
| --- | --- |
| `ARGOCD_GIT_USERNAME` | Git 호스팅이 요구하는 HTTPS 인증 사용자명, private일 때만 |
| `ARGOCD_GIT_TOKEN` | 해당 Git 저장소 읽기 범위의 토큰, private일 때만 |
| `ARGOCD_ADMIN_PASSWORD_HASH` | 초기 admin 비밀번호의 bcrypt hash, cost 10~16. 원문 비밀번호를 넣지 않음 |
| `ARGOCD_SERVER_SECRETKEY` | 충분한 무작위성을 가진 32자 이상 세션 서명 키 |
| `ARGOCD_REDIS_AUTH` | 충분한 무작위성을 가진 32자 이상 Redis 비밀번호 |

admin 원문 비밀번호도 승인된 Doppler 키로 보관하되, 현재 자동화는 그 원문 키를 읽지 않는다. 초기 Secret의 생성과 일상 회전은 다른 절차다. Istio CA/TLS처럼 컨트롤러가 생성하는 내부 Secret을 Doppler와 무조건 양방향 동기화하지 않는다.

로컬 실행 입력: [argocd-run.json.example](../../ansible/inventories/oci-a1/argocd-run.json.example)을 `.local/ansible/oci-a1/argocd-run.json`으로 작성한다.

| 키 | 넣을 값 |
| --- | --- |
| `argocd_controller_python` | requirements가 설치된 controller Python의 절대 경로 |
| `argocd_helm_binary` | 검증한 Helm v4.2.4 실행 파일의 절대 경로 |
| `argocd_chart_archive` | 공식 `argo-cd-10.8.2.tgz`의 로컬 절대 경로. versions.json checksum과 일치해야 함 |
| `argocd_expected_revision` | 검토·커밋·원격 반영된 해당 branch HEAD의 **40자리 Git commit SHA**. 위 `revision`의 branch 이름과 다름 |

설정/생성물을 먼저 검토하고 Git에 반영한 뒤 SHA를 기록한다. bootstrap 중 branch를 바꾸지 않는다. 현재 저장소에는 커밋/푸시를 수행하지 않았다. 정확한 로컬 검사와 원격 실행 경계는 [2단계 절차](argocd-bootstrap.md).

계정 선언: [accounts.json](../../gitops/platform/argocd/accounts.json), 구조 예제: [accounts.json.example](../../gitops/platform/argocd/accounts.json.example).

| 키 | 넣을 값 |
| --- | --- |
| `phase` | 최초 `bootstrap`; 개인 관리자/복구 검증 후 `managed` |
| `accounts` | 최초 빈 배열. 이후 사람별 객체 추가 |
| `accounts[].name` / `enabled` | 개인 고유 로그인명 / 활성 true·비활성 false |
| `accounts[].role` | `platform-admin` 또는 `developer` |
| `accounts[].projects` | developer가 읽을 실제 AppProject 이름 배열; platform-admin은 빈 배열 |
| `cutover.verified_admin` | 최초 null; 전환 시 검증한 활성 개인 관리자 이름 |
| `cutover.recovery_verified` | 최초 false; admin 없이 복구 가능함을 확인한 뒤 true |

현재 developer는 지정 프로젝트 조회 권한이며 임의 직접 배포 권한은 없다. **계정 선언은 비밀번호 발급이 아니다.** 개인 비밀번호/회전 자동화는 미구현이며 초기 `argocd-secret` 전체 덮어쓰기로 처리하지 않는다. [계정 운영](argocd-accounts.md).

## 3단계: Istio

직접 편집: [istio.json](../../gitops/clusters/oci-a1/istio.json). 활성화 전에 2단계 Argo CD 자기관리와 CRD health 설정 반영을 확인한다.

| 키 | 값 / 지원 범위 |
| --- | --- |
| `enabled` | 현재 false. 실제 배포 준비가 되면 검토한 Git 변경에서 true |
| `reviewed` | 모드·namespace·호환 버전·내부 노출·기존 리소스 충돌 확인 후 true |
| `mode` | 현재 코드 지원은 `sidecar`만. ambient 선택은 별도 CNI/ztunnel 구현 필요 |
| `namespace` | 현재 baseline은 `istio-system`만 지원. 기존 클러스터의 namespace 추정값이 아니라 신규 선언 |
| `gateway_service_type` | baseline 값 `ClusterIP` 유지. 아래 `ingress.json`을 활성화하면 생성 overlay가 ServiceLB용 `LoadBalancer`로 변경 |

`gitops/platform/istio/versions.json`은 검증한 chart 버전·SHA256·image digest 기록이다. 현재 Istio 1.30.4, Kubernetes 1.32~1.36 범위를 확인했다. `bootstrap.json.kube_version`과 연결하며 아직 K3s 실제 버전은 선택하지 않았다. [공식 지원표](https://istio.io/latest/docs/releases/supported-releases/), 확인일 2026-09-09. 실제 설치 시 지원 기간을 다시 확인한다.

`base.values.json`, `istiod.values.json`, `gateway.values.json`은 제공하는 baseline이다. `resources.requests/limits`, `replicaCount` 등을 변경하면 chart 렌더링·capacity·테스트도 다시 검토한다. version·digest·검증 코드의 잠금을 한 군데만 바꾸지 않는다. 최초 gateway에는 별도 Doppler 입력이 없다.

외부 노출은 **K3s ServiceLB**로 확정했다. [ingress.json](../../gitops/clusters/oci-a1/ingress.json)에 아래 값을 나중에 입력한다. [구조 예제](../../gitops/clusters/oci-a1/ingress.json.example)는 활성 파일이 아니며 실제 도메인으로 사용하지 않는다. `istio.json`에 이 키를 추가하지 않는다.

| `ingress.json` 키 | 입력할 값 |
| --- | --- |
| `enabled`, `reviewed` | 최초 false. 실제 namespace 소유권·메시 가입·경로 준비 검토 후 true |
| `exposure` | 확정값 `k3s-servicelb` |
| `network_reviewed` | 공인 IP/DNS·OCI/Ubuntu 80/443·포트 충돌·ServiceLB 대상 노드 점검 후 true |
| `tls_ready_reviewed` | 인증서 전달·SAN·체인·유효기간·키 일치·갱신 경로 확인 후 true. 자동 점검 flag가 아닌 수동 확인 기록 |
| `mesh_namespaces` | 이 Istio Application이 관리할 앱 namespace 목록; sidecar 가입 label과 namespace STRICT 정책 생성 |
| `routes[].name` | 고유 route 이름, 소문자 영문 시작·최대 40자 |
| `routes[].host` | 실제 외부 도메인. 소문자 DNS 이름, wildcard/URL/포트 없음 |
| `routes[].tls_secret` | `istio-system`에 준비한 TLS Secret 이름. 실제 인증서/개인키 값 금지 |
| `routes[].backend_namespace` | 위 mesh namespace 중 하나 |
| `routes[].backend_service` | 실제 앱의 HTTP ClusterIP Service 이름 |
| `routes[].backend_port` | HTTP **Service port** 정수 |
| `routes[].path_prefix` | `/` 또는 `/api` 같은 경로 접두어, rewrite 없음 |

host 및 backend Service 중복은 현재 지원하지 않는다. Gateway·VirtualService·DestinationRule은 `networking.istio.io`, mTLS 정책은 `security.istio.io`로 생성한다. Kubernetes Gateway API는 계속 비활성이다. `ingress.values.json`과 `istio/`의 리소스는 생성물이므로 손으로 수정하지 않는다.

외부 TLS 자동 발급/갱신은 cert-manager로 준비하며 DNS 업체별 연결은 남아 있다. 보유 인증서는 아래 4단계 매핑으로 인증서 키→`tls.crt`, 개인키 키→`tls.key`를 전달할 수 있으며 실제 PEM은 Doppler에만 저장한다. 자동 발급 인증서 Secret은 cert-manager, DNS 인증 자격 증명은 Doppler로 분리한다. 아직 존재하지 않는 Doppler 키 이름을 실제 소비되는 키로 가정하지 않는다.

외부 활성화 생성기는 Git의 `ansible/inventories/oci-a1/settings.json`이 유효하고 `servicelb=true`이며 K3s 기본 버전이 `bootstrap.json.kube_version`과 같은지도 검사한다. 기존 서버의 설정을 자동 변경하지 않는다. 자세한 전제·노드 확장·mTLS 범위·검증은 [외부 ingress 안내](istio-external-ingress.md)를 따른다.

생성·로컬 검사·배포 후 확인: [Istio 3단계](istio-bootstrap.md). 게이트웨이 Pod가 Ready인 것과 도메인 요청이 성공하는 것은 다르다.

runbook의 로컬 셸 변수는 `ISTIO_HELM_BINARY`=검증한 Helm 절대 경로, `ISTIO_CHART_DIR`=3개 tgz가 있는 절대 디렉터리, `K3S_KUBE_VERSION`=`bootstrap.json.kube_version`과 같은 문자열이다. 배포 후 조회의 `K3S_KUBECONFIG`=보호된 kubeconfig 경로, `K3S_CONTEXT`=그 안에서 확인한 context 이름이다. 모두 명령 입력이며 `istio.json`에 추가하는 키가 아니다. kubeconfig 내용은 Git/Doppler 참조표/로그에 복사하지 않는다.

## 4단계: Doppler 지속 동기화

Git 원본은 `gitops/clusters/oci-a1/doppler.json`이다. [예시](../../gitops/clusters/oci-a1/doppler.json.example)와 [실행 순서·제약](doppler-bootstrap.md)을 함께 읽는다. 아래는 실제 소비되는 필드다. 초기 CLI 주입(1·2단계)과 Kubernetes 지속 동기화는 별개다.

| Git JSON 키 | 넣을 값 |
| --- | --- |
| `enabled` / `reviewed` | Operator·버전·권한 검토 후 true. 기본 false |
| `sync_enabled` | Operator 설치 → 인증 bootstrap → 대상 검사 후 true. 처음에는 false |
| `auth_ready_reviewed` | 인증 Secret 준비·scope를 실제 확인한 후 true |
| `targets_ready_reviewed` | namespace 존재·Secret 소유권 충돌 없음을 확인한 후 true |
| `mappings[].name` | 고유 DopplerSecret 이름. 예 `web-tls` |
| `mappings[].project` / `.config` | 매핑이 읽는 실제 Doppler project/config 이름 |
| `mappings[].token_secret` | `doppler-auth-` 접두사의 인증 Secret 이름. namespace는 `doppler-operator-system`, data 키는 `serviceToken` 고정 |
| `mappings[].token_env` | 컨트롤러에 주입할 토큰의 Doppler 키 이름. 예 `DOPPLER_WEB_SERVICE_TOKEN` |
| `mappings[].target_namespace` | 다른 GitOps 원본이 먼저 생성한 앱 namespace. `istio-system`은 외부 TLS type만 허용 |
| `mappings[].target_secret` | 대상 Secret 이름. 외부 TLS는 `ingress.json.routes[].tls_secret`과 일치 |
| `mappings[].type` | `Opaque` 또는 `kubernetes.io/tls` |
| `mappings[].resync_seconds` | 정수 60~3600초. 예 120 |
| `mappings[].keys` | `{ "DOPPLER_KEY_NAME": "target-key" }` 키명 매핑. 전체 config 동기화·빈 매핑 금지 |

TLS 대상 키는 정확히 `tls.crt`, `tls.key`여야 한다. 예시의 `WEB_TLS_CERT`에는 PEM 인증서 체인, `WEB_TLS_KEY`에는 짝인 PEM 개인키를 **매핑 project/config의 Doppler에만** 넣는다. processor는 plain이므로 base64가 아닌 원문 PEM이다. 인증서 발급·유효성 검사는 수행하지 않는다.

`token_env`의 실제 값은 **별도 bootstrap용 Doppler config**에서 공급하는 읽기 전용 Service Token(`dp.st.…`)이다. 소비 config별 최소 scope를 사용하고 하나의 인증 Secret을 서로 다른 project/config로 공유하지 않는다. 최초 bootstrap용 Doppler 접근 인증은 클러스터 밖에서 준비한다.

로컬 실행 파일은 `.local/ansible/oci-a1/doppler-run.json`이다. [빈 예시](../../ansible/inventories/oci-a1/doppler-run.json.example)의 키를 채운다. 토큰이 아닌 실행 대상 참조다.

| run JSON 키 | 넣을 값 |
| --- | --- |
| `expected_revision` | clean checkout 및 root/operator가 반영한 같은 40자리 Git SHA |
| `kubectl` | 검증한 클라이언트 실행 파일 절대 경로 |
| `kubeconfig` | 보호된 kubeconfig 절대 경로. 내용 복사 금지 |
| `context` | 그 kubeconfig에서 확인한 정확한 context 이름 |
| `api_server` | 해당 context의 실제 HTTPS API 주소·포트 |
| `chart` | checksum 검사할 공식 Doppler 1.7.1 tgz 절대 경로 |

Ansible 입력 `doppler_python`=PyYAML을 포함한 controller Python 절대 경로, `doppler_run_config`=위 run 파일 절대 경로다. 토큰 값은 Ansible 변수로 전달하지 않는다. 생성 선언은 Git, 인증 Secret data는 최초 bootstrap, 대상 Secret data는 Operator 소유다. 자동 reload·토큰 회전·MCP 설정은 포함하지 않는다.

## TLS 자동 발급·갱신 기반

사용자는 자동 발급·갱신을 선택했다. 현재는 cert-manager 공통 설치까지 구현했으며 provider별 DNS-01·Issuer·Certificate 연결은 DNS 업체 확인 후 진행한다. 실제 값은 나중에 채운다.

| 위치 / 키 | 넣을 값 |
| --- | --- |
| `gitops/clusters/oci-a1/cert-manager.json`: `enabled` | 공통 설치 선언 활성화 시 true, 기본 false |
| 같은 파일: `reviewed` | 버전·RBAC·기존 설치 부재 검토 후 true |
| `gitops/platform/cert-manager/base.values.json` | 제공하는 ARM64·image digest·단일 A1 자원 baseline. 일상 입력으로 수정하지 않음 |
| `gitops/platform/cert-manager/versions.json` | chart v1.21.1·checksum·Helm 4.2.4. 변경 시 관련 테스트 함께 검토 |

`bootstrap.json.kube_version`은 1.33~1.36 범위를 요구한다. 위 JSON에 DNS token·도메인 등 미지원 키를 추가하지 않는다. 현재 필요한 선택은 DNS 서비스명이며, 후속 도메인·ACME 이메일·Doppler DNS 인증 키의 입력 위치는 [자동 TLS 절차](tls-automatic.md)에 구현 상태와 구분해 정리했다. 인증서 Secret은 cert-manager, DNS 인증은 Doppler 소유이며 인증서 자체를 양방향 동기화하지 않는다.

## 5단계: Wasabi — 아직 미구현

**아래도 설계 항목이며 작동하는 설정 키가 아니다.** 실제 bucket을 생성하거나 인증을 입력·조회하지 않았다. 백업 도구 선택 후 정확한 입력 파일과 키 매핑을 추가한다.

| 준비할 항목 | 위치 / 넣을 값 |
| --- | --- |
| bucket / region / endpoint / prefix | 비밀값 없는 백업 선언에 실제 Wasabi 값. endpoint는 해당 리전의 공식 HTTPS 주소 |
| access key / secret key | Doppler 백업 전용 config. 키 이름은 도구 선택 후 확정하여 참조 |
| 백업 암호화 키/암호 | 필요한 도구를 선택하면 Doppler에 보관, Git에는 키 참조만 |
| 백업 대상 | SQLite datastore, 각 PVC/local-path 경로, 앱 DB별 일관된 백업 방법 |
| 스케줄/보존 | 주기·시간대·로컬/원격 보존·lifecycle/Object Lock와 도구 prune의 관계 |
| RPO / RTO | 허용 데이터 유실 시간 / 목표 복구 시간. 사용자가 운영 요구로 결정 |
| 복구 인증 이력 | 백업 시점 K3s server token·암호화 키·Doppler 값 이력의 보호된 참조 |
| 복구 시험 | 격리 대상, 다운로드·무결성·복호화·DB/앱 복원 성공 기준 |

현재 SQLite이므로 `etcd-snapshot` S3 옵션을 대신 넣지 않는다. Wasabi는 Terraform backend나 실시간 PV가 아니다. [Wasabi 지침](../../.agents/skills/k3s-infra/references/wasabi.md).

## 6단계: 종합 검증 — 아직 미구현

실행 기록에는 Git SHA, Terraform backend/workspace·instance OCID, Ansible inventory/limit, Kubernetes kubeconfig 경로/context, Argo CD server/context·Application별 기대 revision, Doppler project/config(값 제외), 점검 URL/기대 응답, 백업 object/version·복원 시험 결과가 필요하다. 민감한 경로·결과는 보호된 기록으로 분리한다.

현재 통합 실행기용 JSON/자동 배포 명령은 없다. 기존 단계의 입력을 다시 임의 환경변수로 중복 선언하지 않는다. 각 단계 성공 후 다음 단계로 진행하고, 미입력·접속 불가·검증 실패를 성공으로 처리하지 않는다.

## 직접 수정하지 않는 생성물

- `.local/ansible/oci-a1/hosts.json`: `k3s_inventory.py`가 생성.
- `gitops/platform/argocd/accounts.values.json`: `argocd_accounts.py`가 생성.
- `gitops/clusters/oci-a1/root/`, `argocd.values.json`, 활성화 시 `istio/`, `ingress.values.json`, `doppler/`: `argocd_gitops.py`가 생성. **Git 커밋 대상**, 현재 미입력이라 활성 생성물 없음.
- `gitops/platform/doppler/install/`: `doppler_vendor.py`로 변환한 고정 upstream Git 대상. 비밀값 없음.
- `gitops/clusters/oci-a1/cert-manager/`, `root/cert-manager*.json`: 활성 입력으로 `argocd_gitops.py`가 생성하는 Git 대상. 기본 비활성.
- Kubernetes Secret data: bootstrap/선택한 동기화 주체/해당 컨트롤러가 관리. Git에 수동 복사하지 않음.

이 문서의 표는 입력 위치 안내이지 실제 값 확인·배포·인증 발급 완료 기록이 아니다.
