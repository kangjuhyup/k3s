# 백업·복구, 업그레이드와 노드 유지보수

[GitOps 필수 정책](gitops.md)을 먼저 따른다. K3s 버전·호스트 설정은 Git의 Ansible 원본으로, Istio·앱의 원하는 상태는 GitOps 컨트롤러로 반영한다. 백업·복원·drain 등 일회성 작업은 Git에 기록된 playbook/runbook의 확인된 revision으로 수행한다. 복구 시 목표 Git revision과 컨트롤러 조정 재개 순서를 계획하며 데이터 백업 자체는 Git에 저장하지 않는다.

복구 대상의 [Doppler](doppler.md) config·필요한 값 이력과 클러스터 외부 인증 경로도 확인한다. Git 복원으로 Doppler 값까지 되돌아간다고 가정하지 않으며 백업 시점의 K3s token과 현재 token을 구분해 보관한다.

노드 외부 백업 사본은 [Wasabi Object Storage](wasabi.md)에 보관한다. 실제 bucket·region·endpoint·prefix와 보존 정책을 확정하고 자격 증명은 Doppler로 전달한다. 아래 backend별 일관된 백업 생성과 Wasabi 전송·원격 사본 검증을 각각 확인한다. 로컬 snapshot만 생성한 상태를 외부 백업 완료로 보고하지 않는다.

## 백업 선택

노드 수만으로 datastore를 추정하지 않는다. 실제 서버 설정과 상태에서 SQLite, embedded etcd, external datastore를 식별한다. 설정의 DB URL과 자격 증명은 출력하지 않는다.

| datastore | 백업 경로 |
| --- | --- |
| SQLite | 실제 data-dir의 `server/db/`를 일관된 시점으로 보관한다. 일반 파일 복사는 K3s를 정지한 cold backup 등 일관성이 확보된 절차를 사용한다. 서비스 정지가 승인 범위인지 확인한다. |
| 내장 etcd | 확인된 server에서 해당 버전의 `k3s etcd-snapshot save`로 snapshot을 만들고 `ls`로 저장 결과를 확인한다. |
| 외부 DB | 해당 DB의 native backup/PITR 절차를 사용한다. K3s의 etcd-snapshot으로 외부 DB를 백업하지 않는다. |

datastore와 함께 **백업 시점의 server token**, K3s 설정, 필요한 암호화 키·secret 복구 수단을 보호된 저장소에 보관한다. 기본 token 경로는 `/var/lib/rancher/k3s/server/token`이다. 실제 data-dir와 token 설정을 확인한다. [K3s Backup and Restore](https://docs.k3s.io/datastore/backup-restore)

클러스터 datastore 백업에 PVC 내용이 포함된다고 가정하지 않는다. PV의 실제 backend/path/node affinity를 조사하고 local-path, CSI, 외부 DB 각각의 데이터 백업을 별도로 수행한다. 애플리케이션 쓰기 정지 또는 DB-native backup으로 일관성을 확보한다. K3s 서비스를 멈춰도 기존 컨테이너가 계속 실행될 수 있다.

백업 완료 보고에는 다음 필드를 포함한다: 대상·K3s 버전, datastore 종류, 생성 시각, 저장 위치, token 보관 확인, PV/앱 데이터 포함 범위, checksum/읽기 검증, 노드 외부 사본, 복구 시험 여부. 비밀값은 제외한다. 파일 존재만 확인했다면 복구 가능성을 검증했다고 쓰지 않는다.

## 복원

복원 요청에서 먼저 복구할 시점, 대상 클러스터/노드, 덮어쓸 데이터, RPO/RTO와 복구 후 앱 데이터 정합성을 구체화한다. 실운영 데이터 덮어쓰기 권한이 확인되기 전에는 진단·복구 계획·격리 환경 준비까지 수행한다.

내장 etcd 복원은 서버 정지와 membership reset을 포함한다. 지정 snapshot, 해당 token, 실제 data-dir, 복구 버전 및 다른 server의 재가입 순서를 확인하고 [공식 snapshot 복원 절차](https://docs.k3s.io/cli/etcd-snapshot#restoring-snapshots)를 현재 버전에 맞춰 적용한다. `--cluster-reset`만 실행하면 snapshot 복원이 아니다. peer DB 정리 전 정확한 경로와 보존 사본을 확인한다.

S3 자격 증명이 Kubernetes Secret에만 있으면 API가 내려간 복원 시 읽을 수 없다. 클러스터 외부에서 접근할 수 있는 보호된 복구 수단을 미리 확보한다. S3 설정이 켜진 환경에서 로컬 snapshot 복원 시 `--etcd-s3=false` 필요 여부를 확인한다. token 값, S3 자격 증명, snapshot 내용은 대화나 셸 인자에 노출하지 않는다. 복원 명령에는 확인된 snapshot 파일 경로를 전달할 수 있다.

SQLite/외부 DB는 각 backend의 복원 절차를 따른다. 격리된 복원 시험에서 nodes, API, controllers, PVC mount, 애플리케이션 읽기·쓰기와 데이터 시점을 확인한다. 확인되지 않은 항목을 남기고 실운영 성공으로 확대 해석하지 않는다.

## K3s 업그레이드

현재 버전 → 목표 버전, 지원되는 중간 minor 경로, 릴리스 노트, CNI/CSI/Istio/Gateway API CRD 호환성을 확인한다. Istio 관련 검증은 [Istio 운영](istio.md)을 따른다. 업그레이드 직전 datastore·token·앱 데이터 백업과 복구 경로를 확보한다. 설치 스크립트를 다시 실행할 때 기존 환경 변수/인자를 누락하면 설정이 사라질 수 있으므로 원래 설치 방식과 옵션을 보존한다.

서버를 한 대씩 먼저 업그레이드하고 각 단계의 건강성을 확인한 뒤 agents를 진행한다. minor 버전을 건너뛰지 않는다. 설치 스크립트는 자동 drain하지 않는다. drain 필요성은 워크로드 가용성과 노드 유지보수 범위로 판단한다. [Manual Upgrades](https://docs.k3s.io/upgrades/manual)

내장 etcd는 voting member 수와 endpoint health로 quorum 여유를 계산한다. 3 voting member 중 1개가 unavailable이면 남은 2개 중 하나를 정지할 수 없다. Node NotReady만으로 etcd member가 죽었다고 단정하지도 않는다. 멤버 건강성·복구 여유가 불명확하면 다음 서버의 재시작을 보류하고 기존 장애를 먼저 조사한다. 단일 서버의 API 중단 가능성은 작업 영향에 포함한다.

노드별 API readiness, etcd 건강성, Node Ready, 핵심 controller와 대상 워크로드의 회복을 확인한다. timeout, 신규 오류, quorum 저하가 발생하면 진행을 멈춘다. 창이 닫힌다는 이유로 모든 서버를 동시에 재시작하지 않는다.

다운그레이드는 단순 바이너리 교체로 일반화하지 않는다. 버전별 datastore 호환성과 백업 시점을 확인하고 [Rolling Back K3s](https://docs.k3s.io/upgrades/roll-back)에 맞춰 복구 계획을 세운다. 오래된 백업으로 되돌리면 이후 변경과 데이터가 유실될 수 있다.

## drain과 노드 제거

대상 노드의 워크로드, PDB, replica, 대체 노드 capacity, DaemonSet/static Pod, emptyDir, local-path PV와 node affinity를 확인한다. 퇴거 불가능한 Pod의 이유를 먼저 설명한다. `--force`, `--disable-eviction`, `--delete-emptydir-data`를 기본 옵션으로 넣지 않는다.

필요한 유지보수에 한해 cordon → 허용된 eviction/drain → 노드 작업 → Ready 및 워크로드 검증 → uncordon 순서로 진행한다. 작업 전부터 cordon된 노드는 임의로 uncordon하지 않는다. 영구 제거는 데이터 이전과 server/etcd membership 영향을 검토한다. Kubernetes Node 삭제, K3s uninstall, 호스트 데이터 삭제를 같은 작업으로 취급하지 않는다.

문서 확인일: 2026-09-07. 복원 및 업그레이드 실행 시 버전별 공식 절차를 다시 확인한다.
