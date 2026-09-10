# CNPG Operator 설치

2026-09-10 기준 Operator와 첫 공유 PostgreSQL DB 설치를 완료했다. 백업은 사용자 요청대로 비활성화했다.

## 공유 DB 운영 상태

- namespace `databases`, Cluster `shared-postgres`, PostgreSQL `18.4-system-trixie` ARM64 이미지 digest 고정.
- 인스턴스 1개, `local-path` PVC `shared-postgres-1` 10Gi Bound. 요청 CPU 250m·메모리 512Mi, 메모리 제한 2Gi.
- `auth / prd`의 `DB_NAME`·`DB_USER`·`DB_PASSWORD`는 Doppler가 원본이다. Git에는 실제 DB·계정 이름을 넣지 않는다. 이름 변경은 기존 DB rename/migration을 자동 수행하지 않는다.
- Doppler `DB_USER`·`DB_PASSWORD` → `databases/auth-db-credentials`의 `username`·`password`, type `kubernetes.io/basic-auth`. SecretSyncReady와 원본 비밀번호 일치를 값 출력 없이 검증했다.
- 전용 read-only Service Token `k3s-auth-prd-20260910`은 90일 만료로 발급했다. 만료 전 교체가 필요하며 자동 갱신은 없다. 인증 Secret은 기존 최소 Ansible bootstrap으로 생성했다.
- 접속 주소·포트·TLS 모드는 Doppler `DB_HOST`, `DB_PORT`, `DB_SSLMODE`에서 공급한다. 외부 노출은 없다.
- 실제 TLS 인증서 검증·앱 계정 SQL 임시 테이블 트랜잭션·비관리자 권한·다른 DB 및 평문 접속 거부를 `scripts/postgresql_verify.py`로 검증했다. DB와 모든 Argo CD Application은 Healthy다.
- 검증은 DB 접속 검사이며 앱 자체 배포·영속성 재시작 시험·백업 복구 시험은 아니다. 앱 배포 시 필요한 키만 앱 namespace에 동기화하고 CNPG CA 인증서를 마운트해야 한다. `verify-full`을 낮춰 우회하지 않는다.

현재 local-path는 온라인 PVC 확장을 지원하지 않으며, 10Gi가 실제 파일시스템 사용량 상한을 강제하지도 않는다. 호스트 부트 디스크를 공유하므로 여유 공간 감시가 필요하다. 서버 손실 시 데이터를 보호할 복제본·원격 백업은 아직 없다.

## 고정 버전과 관리 원본

- CNPG 1.30.0, 공식 Helm chart 0.29.0. Kubernetes 1.34–1.36 지원 범위를 확인했다.
- 차트 SHA256: `668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f`.
- Operator 이미지 index SHA256: `a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb`; linux/arm64 manifest 존재 확인.
- 원본: `gitops/clusters/oci-a1/root/cnpg.yaml`, `cnpg/`, values: `gitops/platform/cnpg/base.values.yaml`.
- 매니페스트를 직접 편집하고 `scripts/gitops_validate.py --repo-root .`로 검사한다.
- Argo CD `cnpg` Application과 `platform-cnpg` AppProject가 관리한다. namespace는 `cnpg-system`이며 Istio 자동 주입은 비활성화했다.
- Operator 1 replica, 요청 CPU 100m·메모리 256Mi, 메모리 제한 512Mi. 관리자용 컨트롤러이므로 cluster-wide RBAC를 사용한다. 일반 사용자 역할로 권한 집계는 비활성화했다.
- webhook CA는 CNPG 소유이며 Argo CD가 덮어쓰지 않는다. Git에서 Secret data를 관리하지 않는다.

## 실제 검증

배포 revision `이력 정리 전 검증 revision`에서 CNPG/root Synced·Healthy, Operator 1/1 Running, Cluster CRD Established, webhook EndpointSlice 준비를 확인했다. Cluster 선언의 server dry-run이 성공했다. 실제 Cluster와 CNPG namespace의 PVC는 없다.

Python 3.12.9·Helm 4.2.4로 CNPG 테스트 4개 통과. 전체 테스트 103개 중 76개 통과·선택 의존성 검사 27개 생략. 공식 chart checksum과 렌더링 리소스의 AppProject 허용 범위도 검사했다.

## 후속 앱 추가 및 분리

1. 추가 앱마다 DB·계정·Doppler config를 분리한다. 인프라 `.env`는 이전하지 않는다.
2. 추가 DB·역할 생성 시 실제 이름이 공개 Database/DatabaseRole 선언에 들어가지 않도록 Secret 기반 실행 경로를 검토한다. pg_hba는 Secret의 이름 파일을 참조한다. 기존 bootstrap initdb를 재실행하지 않는다.
3. 최초 인증 bootstrap은 현재 sync 활성 상태에서 재실행할 수 없다. 추가 토큰·교체는 기존 Secret을 보존하는 별도 절차를 먼저 구현·검증한다.
4. 나중에 물리 분리할 앱은 별도 Cluster·PVC로 데이터를 이전하고 그 앱의 접속 설정만 전환한다. 주소 변경은 데이터 이전을 대체하지 않는다.

Wasabi 백업은 사용자 요청대로 비활성화 상태를 유지한다. 백업 활성화·복구 검증 전에는 데이터 보호가 완료되었다고 간주하지 않는다. 노드 증설과 DB 복제본 증설은 별개다.

## DB 이름의 비공개 관리

`auth-db-private` Secret은 Doppler의 DB_NAME·DB_USER와 비공개 초기화 SQL을 받는다. DB 이름·사용자명은 `/projected/identity`의 파일로 마운트하고 pg_hba에서 파일을 참조한다. 계정 비밀번호는 기존 basic-auth Secret을 유지한다. 앱명·Doppler project/config·Secret 리소스 이름은 비밀값이 아닌 참조로 Git에 남는다.

기존 Cluster의 `/spec/bootstrap`은 Argo CD의 `RespectIgnoreDifferences`로 보존한다. CNPG가 기존 앱 계정·비밀번호 연결을 계속 관리하도록 하기 위함이며, Kubernetes API에는 과거 초기화 이름이 남는다. 공개 Git에서 제거하는 것과 클러스터 관리자에게도 숨기는 것은 다르다.

새 Cluster의 Git 초기화 선언은 기본 `postgres` DB·계정을 지정하고 `postInitSQLRefs`로 private SQL Secret만 참조한다. SQL은 `scripts/postgresql_private_bootstrap.py --project <project> --config <config> --write`로 Doppler에 준비한다. Git에는 SQL 생성 코드만 남으며 실제 SQL·비밀번호는 출력하지 않는다. SQL은 준비 시점의 스냅샷이므로 **신규 생성·복구 전에 현재 원본에서 다시 준비**해야 한다. 실행 권한이 있는 SQL Secret은 관리자만 변경하도록 보호한다. CNPG debug 로그에 SQL이 기록될 수 있으므로 debug 로그를 활성화하지 않는다.

현재 전환은 기존 DB 유지·접속 검증과 신규 선언의 server dry-run까지 검증했다. 별도 신규 Cluster 생성·초기화 전체 실행과 복구 시험은 수행하지 않았다. 기존 bootstrap을 재실행하거나 PVC를 지우면서 시험하지 않는다.

## 변경과 복구

직접 Helm 설치·kubectl apply 대신 Git 변경을 Argo CD가 반영한다. prune=false이므로 파일 삭제만으로 기존 Operator가 제거되지 않는다. Operator 제거·CRD 삭제는 DB 리소스에 영향을 줄 수 있어 별도 검토가 필요하다. Git revert는 DB 데이터 복원이 아니다.

공식 근거: [지원 범위](https://cloudnative-pg.io/docs/1.30/supported_releases/), [공식 차트](https://github.com/cloudnative-pg/charts), [DB bootstrap](https://cloudnative-pg.io/docs/1.30/bootstrap/).
