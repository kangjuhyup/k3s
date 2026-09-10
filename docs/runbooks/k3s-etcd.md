# Embedded etcd 전환과 control-plane 증설

가까운 시일 내 control-plane 증설을 위해 `settings.json`은 `datastore=etcd`, `bootstrap_server=a1-server-1`을 사용한다. 첫 server는 `cluster-init`, 추가 server는 `server=<endpoint>`로 가입한다. server별 공통 CIDR·DNS·암호화·번들 컴포넌트 설정은 동일하게 렌더링된다. 가입 노드 추가만으로 기존 server의 설치 fingerprint가 달라지지 않는다.

## 현재 SQLite 서버 전환

`migrate-sqlite-to-etcd.yml`은 단일 관리 노드에서만 실행된다. 기존 SQLite 설치와 원하는 etcd 설정 간에 버전·토큰·주소 등 다른 차이가 있으면 거부한다. 기존 bootstrap token이 controller 환경에 필요하며, 값은 출력하지 않는다.

순서: 기존 fingerprint와 파일 검증 → API·단일 노드 확인 → K3s 정지 → root 전용 로컬 cold backup → `cluster-init` 설정 → 시작 → etcd TLS health·Ready·동일 Node UID 확인 → 새 fingerprint 기록.

백업은 `/var/backups/k3s-migrations`에 한 번만 보관한다. Wasabi 연동이나 주기적 백업을 대신하지 않는다. 전환 도중 실패하면 API·DB 상태를 조사하며 자동 삭제·롤백하지 않는다. 성공한 재실행은 인증·state 검증만 하고 서비스를 다시 시작하지 않는다. 기존 reset playbook으로 전환을 우회하지 않는다.

저장소 고정 Ansible 환경에서 inventory를 다시 생성한 뒤 `ansible/`에서 실행한다.

```sh
ansible-playbook -i ../.local/ansible/oci-a1/hosts.json playbooks/migrate-sqlite-to-etcd.yml
ansible-playbook -i ../.local/ansible/oci-a1/hosts.json playbooks/verify-cluster.yml
```

## 추가 control-plane

1. 실제 추가 인스턴스를 Terraform 관리에 편입하고, 기존 server 키를 유지한 채 `nodes`에 `role=server`를 추가한다. 현재 Terraform은 기존 인스턴스 편입 전용이며 자동 신규 VM 생성 기능은 없다.
2. `bootstrap_server`는 변경하지 않는다. 공통 endpoint는 우선 기존 server 내부 주소다. 완전한 HA 접근 경로는 별도의 고정 DNS/LB 설계가 필요하며 임의 endpoint를 생성하지 않는다.
3. OCI NSG/보안 목록과 라우팅에서 server 간 TCP 2379/2380, 노드의 API TCP 6443 및 사용 중인 CNI·kubelet 통신을 검토한다. etcd/VXLAN을 인터넷에 개방하지 않는다. `prepare-etcd-peers.yml`은 UFW만 관리하며 OCI 규칙을 대신하지 않는다.
4. 기존 server의 `/var/lib/rancher/k3s/server/token`에서 보호된 경로로 확보한 secure server token을 `K3S_SERVER_JOIN_TOKEN`(또는 지정한 `token_env.server_join`)으로 공급한다. `K3S_AGENT_TOKEN`을 server 가입에 사용하지 않는다.
5. 갱신한 inventory로 모든 server에 `prepare-etcd-peers.yml`을 적용하고, 새 server만 `join-servers.yml --limit <새-server>`로 한 대씩 가입시킨다. bootstrap에는 가입 play가 실행되지 않는다.
6. 각 server의 etcd health·Ready와 전체 노드 검증을 수행한다. 2대는 장애 허용이 없는 과도기이므로 3대 구성을 완료한다. local-path 데이터와 앱 replica의 HA는 별도 구성이다.

공식 근거: [K3s embedded etcd와 SQLite 전환](https://docs.k3s.io/datastore/ha-embedded), [네트워크 요구사항](https://docs.k3s.io/installation/requirements). Wasabi 백업·Argo CD·Istio 설치는 별도 작업이다.
## 적용 기록 — 2026-09-10

`a1-server-1`의 K3s v1.36.4+k3s1을 SQLite에서 embedded etcd로 전환했다.
원래 노드 UID를 전환 전 SQLite 백업과 대조하여 유지됨을 확인했다.
etcd health, API readiness, Node Ready, 시스템 Pod 3개 및 DNS 응답이 정상이다.
최종 migration/verify 재실행은 `changed=0`, `failed=0`; 로컬 테스트 25개가 통과했다.
초기 검증의 포트 및 응답 Content-Type 처리 오류는 수정 후 검증 전용 복구로 완료했다.
전환 전 백업은 노드의 `/var/backups/k3s-migrations/`에 root 전용으로 보관했다.
Wasabi 업로드는 아직 미구성이며 현재 단일 etcd 서버는 HA 구성이 아니다.

## 검증 단계만 실패한 경우

전환은 끝났지만 완료 마커 기록 전 검증이 실패했다면 원인을 먼저 진단한다.
`migration_finalize_only=true`와 백업에서 독립적으로 확인한
`migration_original_node_uid`를 전달하면 서비스 재시작 없이 원하는 etcd
설정·바이너리·토큰·상태·기존 마커를 검사하고, 원래 노드 UID와 일치할 때만
완료 마커를 기록한다. 일반 재실행은 불완전 전환을 계속 거부한다.
HTTP 상태 검사는 현재 K3s의 로컬 2382 포트를 사용한다.
