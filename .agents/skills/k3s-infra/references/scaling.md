# A1 단일 노드에서 확장

## 확정된 초기 구성과 확장 경로

사용자는 현재 OCI A1 ARM64 **1대, 4 OCPU·24GB RAM**을 사용하며 추후 A1 노드 증설을 원한다. 이 문서는 설계·운영 기준이다. 실클러스터 설치 여부나 현재 datastore가 확인되었다는 뜻은 아니다.

| 단계 | 구성 | 목적과 한계 |
| --- | --- | --- |
| 초기 | A1 server 1대에 control plane·Istio·앱 배치 | 단일 노드로 시작한다. 노드 장애 시 전체 서비스에 영향이 있다. |
| 처리 용량 확장 | 기존 server 1대 + 필요한 수의 A1 agents | agent에 워크로드를 분산한다. control plane의 단일 장애 지점은 남는다. |
| HA가 별도로 필요할 때 | 내장 etcd 기준 server 3대 이상 홀수 구성 + 선택적 agents | quorum과 API 접근 경로를 함께 구성한다. 앱·스토리지의 HA는 별도로 검증한다. |

단순 노드 추가 요청은 처리 용량 확장을 기본안으로 삼는다. server 장애에도 관리 기능을 유지해야 한다는 요구가 있으면 HA 경로를 선택한다. server 노드도 워크로드를 실행할 수 있다. [K3s architecture](https://docs.k3s.io/architecture)

## datastore 결정

현재 datastore를 먼저 확인하고 유지한다. SQLite 단일 server에도 agent를 추가할 수 있으므로 워커 증설만을 위해 DB를 전환하지 않는다. 아직 설치하지 않았고 HA 요구가 없다면 SQLite가 단순한 초기 선택이다.

향후 내장 etcd HA가 확정된 신규 설치라면 첫 server부터 `cluster-init` 기반 단일 멤버 etcd로 시작하는 선택을 검토할 수 있다. 단일 멤버 etcd 자체는 HA가 아니다. 기존 SQLite에서 server를 늘리려면 백업·복구 계획을 마련한 뒤 해당 버전의 공식 SQLite→etcd 전환 절차를 적용한다. agent 추가와 이 전환은 별도 작업이다.

내장 etcd server 2대는 1대 장애를 견디지 못한다. HA 전환은 총 3대 및 quorum 건강성을 목표로 하고 과도기 작업 순서를 계획한다. 외부 datastore를 실제 사용하는 환경은 해당 DB의 HA·server 추가 조건을 따른다. [Embedded etcd HA와 기존 클러스터 전환](https://docs.k3s.io/datastore/ha-embedded)

## 처음부터 분리할 구성

- 공통 설정: 고정 K3s 버전, CNI·Pod/Service CIDR, DNS, Istio 설치 모드/버전, 서버 공통 flags, secret 참조.
- 노드별 inventory: 안정적인 노드 식별자, server/agent 역할, OCI 인스턴스 참조, private IP/SSH 대상, shape·OCPU/RAM, 볼륨, labels/taints. 초기 노드만 4 OCPU·24GB로 확정하고 추가 노드 자원은 입력값으로 둔다.
- 가입 endpoint: 노드에서 접근 가능한 안정적인 DNS 이름 또는 관리되는 주소와 TLS SAN을 계획한다. 단일 server 단계는 해당 server로 연결하고, HA 전환 시 건강성 검사되는 API/등록용 endpoint를 검토한다. 실제 도메인·주소는 임의로 만들지 않는다. API 6443과 Istio 사용자 트래픽 80/443 경로를 분리한다. [고정 등록 주소와 LB](https://docs.k3s.io/datastore/cluster-loadbalancer)
- 구성 관리: OCI 인스턴스는 Terraform의 안정적인 노드 키 기반 map과 `for_each`로 관리한다. K3s는 [Ansible](ansible.md)의 공통·server·agent role을 재사용하며 Terraform의 비밀값 없는 출력을 inventory로 연결한다. agent 항목 추가 시 기존 server·볼륨의 교체/삭제가 없는지 plan을 확인하고, Ansible 실행은 새 agent 설치·가입 범위로 제한한다. 기존 인스턴스 편입과 state 관리는 [Terraform 운영](terraform.md)을 따른다.

## 단일 노드에서도 실행 가능한 배치

초기 server를 control-plane 전용 NoSchedule로 막지 않는다. 이미 존재하는 taint는 목적을 확인하고 앱의 toleration 또는 배치를 조정한다. 4 OCPU·24GB 전부를 앱 requests로 배정하지 말고 OS·K3s·datastore·Istio·스토리지 및 관측 구성요소의 실측 사용량과 여유를 반영한다.

단일 노드에서 여러 노드를 강제하는 anti-affinity·topology spread와 과도한 replica 요구가 Pending을 만들지 않게 한다. 서비스별 최소 replica와 완화 가능한 배치 조건을 사용하고, 증설 후 노드 분산·replica·PDB를 함께 조정한다. replica 여러 개가 같은 노드에 있다는 사실을 노드 장애 내성으로 표현하지 않는다. PDB가 단일 replica의 drain을 막을 수 있으므로 유지보수 중단 허용 범위를 정한다.

노드 추가만으로 기존 Pod가 자동 재분산된다고 기대하지 않는다. 새 용량 검증 후 필요하면 Git의 배치·replica·Pod template 선언을 변경하고 GitOps 컨트롤러로 반영한다. 직접 rollout restart/scale로 우회하지 않는다. 일회성 유지보수는 [GitOps 운영 경계](gitops.md)를 따른다. Istio gateway도 replica뿐 아니라 다른 노드 배치와 실제 LB backend/health check가 연결되는지 확인한다.

## 데이터와 증설 검증

local-path PV의 데이터는 기존 노드에 남는다. agent 증설은 PV 복제나 자동 이동을 제공하지 않는다. 무상태 앱은 분산하고 상태 저장 앱은 PV node affinity를 존중한다. 이동이 필요하면 지원되는 볼륨 재연결·복원 또는 별도 스토리지 설계를 통해 데이터 일관성을 검증한다. 증설 대비만을 이유로 분산 스토리지를 설치하지 않는다.

실제 agent 추가 시 기존 노드를 재설치하지 않고 ARM64 OS/이미지, 지원 버전, 노드 이름, 안전한 join token 참조, private 경로·NSG·방화벽을 확인해 가입시킨다. 이후 Node Ready/allocatable, CNI의 노드 간 통신, DNS·Service/EndpointSlice, Istio의 해당 모드 구성요소 및 proxy 연결, storage topology를 검증한다. 요청에 포함된 테스트 워크로드로 새 노드의 실행과 기존 서비스 무영향을 확인한 뒤 분산 배치를 진행한다.

백업·drain·server 유지보수는 [유지보수 지침](maintenance.md)을 따른다. 문서 확인일: 2026-09-07.
