# 4단계: Doppler 지속 동기화

2026-09-10 기준 Operator 설치까지 완료했다. `이력 정리 전 검증 revision`를 Git에 반영하고 Argo CD로 배포했으며 `doppler`/root Application의 Synced·Healthy, Operator Pod 1/1 Running, CRD Established를 확인했다. 공식 1.7.1 차트와 저장소 고정 manifest 비교가 통과했고 관련 테스트는 12개 통과·선택 의존성 검사 1개 생략이다.

이후 `auth / prd`의 DB 계정 연동을 완료했다. `sync_enabled=true`이며 `auth-postgres` 매핑이 `databases/auth-db-credentials`로 동기화된다. 읽기 전용 토큰은 최소 Ansible bootstrap으로 공급했고 SecretSyncReady 및 원본 비밀번호 일치를 검증했다. `.env` 이전은 하지 않았다. Wasabi 백업은 비활성 상태를 유지한다. 상세 현재 상태는 [공유 PostgreSQL](cnpg-bootstrap.md)을 따른다.

후속 실행 시 **앞 단계의 실제 성공을 확인한 후** 진행한다. root의 여러 자식 Application에 붙은 sync-wave만으로 준비 완료를 보장하지 않는다.

## 소유권

| 대상 | 원본 / 반영 주체 |
| --- | --- |
| Operator·CRD·RBAC·DopplerSecret | Git / Argo CD `platform-doppler` |
| 인증 Secret | 보호된 운영자/CI 입력 / Git의 최소 Ansible bootstrap, 최초 create만 |
| 앱 설정·외부 TLS Secret data | Doppler project/config / Doppler Operator |
| 앱 env 반영·Pod 재배포 | 앱 Git Pod template 변경 / Argo CD |
| Istio 내부 CA·Argo CD 초기 Secret | 기존 컨트롤러/bootstrap 소유권 유지, 동기화 제외 |

보유 인증서 `kubernetes.io/tls`와 일반 `Opaque` 전달을 지원한다. 인증서 발급·자동 갱신, 토큰 회전, 앱 Deployment, Argo CD 개인 비밀번호 발급까지 구현한 것은 아니다. 버전·권한·리소스 사용량은 [Operator 출처와 변경](../../gitops/platform/doppler/README.md)을 따른다.

## 1. 값 없는 설정·로컬 검사

[입력 표](configuration-inputs.md#4단계-doppler-지속-동기화)에 따라 `gitops/clusters/oci-a1/doppler.json`의 실제 이름·참조를 채운다. 처음에는 `enabled=true`, `reviewed=true`, **`sync_enabled=false`**이며 매핑을 미리 적는다. 두 readiness 검토 flag는 아직 false다. 기존 `bootstrap.json`의 Git 주소·branch·Kubernetes 버전도 검토한다.

아래는 저장소 루트에서 실행한다. `DOPPLER_PYTHON`은 PyYAML을 포함한 controller Python 절대 경로, `DOPPLER_CHART`는 공식 1.7.1 tgz 절대 경로다. `ansible/requirements.txt` 환경에 필요한 의존성이 있다.

```bash
rtk proxy "$DOPPLER_PYTHON" scripts/doppler_vendor.py \
  --repo-root . --chart "$DOPPLER_CHART"
rtk proxy "$DOPPLER_PYTHON" scripts/argocd_gitops.py --repo-root . --write
rtk proxy "$DOPPLER_PYTHON" scripts/argocd_gitops.py --repo-root .
```

생성 `root/doppler*.json`, `doppler/`는 Git 대상이다. `install/` 재생성은 출처·checksum·image를 함께 검토하는 버전 갱신 때만 `doppler_vendor.py --write`로 한다. 생성 파일을 직접 편집하지 않는다.

## 2. Operator 설치 인계와 대상 확인

별도 승인된 Git 반영 경로를 사용한 뒤 root 및 `doppler` Application의 같은 기대 Git SHA, Synced/Healthy, operation Succeeded와 Operator Deployment Ready를 확인한다. 이 단계에서는 아직 Doppler를 호출하거나 대상 Secret을 생성하지 않는다.

대상 namespace는 **지정한 다른 GitOps 원본에서 먼저 생성**되어야 한다. Doppler는 앱 namespace를 소유하지 않는다. TLS 목적지 `istio-system`은 Istio baseline이 만든다. 현재 ingress가 만드는 앱 namespace보다 앞서 앱 Secret이 필요하면 앱 GitOps namespace 원본을 별도로 확정한다. Secret 준비를 위해 ingress를 먼저 공개하지 않는다.

기존 Secret 이름·type·소유권을 검사한다. 공식 Operator는 기존 data를 덮어쓸 수 있다. 아래 bootstrap은 대상이 없거나 동일 DopplerSecret 소유인지 확인하지만, 검사 후 다른 관리자가 같은 이름을 생성하는 경쟁까지 막는 admission 정책은 아니다.

## 3. 최소 인증 Ansible bootstrap

클러스터 밖의 보호된 운영자/CI 인증을 먼저 준비한다. 소비 project/config별 **읽기 전용 Service Token**을 확보하여 별도 bootstrap용 Doppler config에서 매핑의 `token_env` 이름으로 공급한다. 소비 config의 토큰을 그 config 자체에서만 꺼낼 수 있게 만들지 않는다. 토큰 형식 검사는 실제 scope·만료·권한 검증이 아니다.

[빈 run 예시](../../ansible/inventories/oci-a1/doppler-run.json.example)를 참고해 `.local/ansible/oci-a1/doppler-run.json`을 준비한다. 실제 kubeconfig는 제한된 권한으로 보관한다. `expected_revision`은 커밋된 코드·생성물과 실제 root/operator가 읽은 **동일한 40자리 Git SHA**다. 현재처럼 untracked 저장소이면 실행이 차단된다.

다음은 승인된 실제 구축 때만 사용하는 예시다. `DOPPLER_BOOTSTRAP_PROJECT`/`DOPPLER_BOOTSTRAP_CONFIG`는 인증 토큰을 보관한 실제 이름, `DOPPLER_RUN_CONFIG`는 run JSON 절대 경로, `ANSIBLE_PLAYBOOK`은 고정 Ansible 바이너리 절대 경로다. 설치한 CLI의 `run --help`에서 옵션·fallback 정책을 확인하고 오래된 fallback으로 최초 인증 검증을 대체하지 않는다.

```bash
rtk proxy doppler run --project "$DOPPLER_BOOTSTRAP_PROJECT" \
  --config "$DOPPLER_BOOTSTRAP_CONFIG" -- \
  "$ANSIBLE_PLAYBOOK" -i localhost, ansible/playbooks/bootstrap-doppler-auth.yml \
  -e "doppler_python=$DOPPLER_PYTHON" \
  -e "doppler_run_config=$DOPPLER_RUN_CONFIG"
```

localhost만 사용하며 SSH 대신 명시한 kubeconfig/context/API 주소로 접근한다. check mode·미입력·dirty Git·생성물 불일치·다른 API·TLS 검증 해제 시 중단한다. 기본 최초 bootstrap은 sync 비활성 상태에서만 실행한다. 이미 운영 중인 클러스터에 config를 추가할 때는 `doppler_token_env`에 Git 매핑의 환경변수 **이름**을 명시한다. 이 경로는 해당 config만 선택하고 기존 다른 config의 전달 상태, 기대 Git revision과 sync 성공을 검사한 뒤 인증 Secret만 create한다. 신규 config의 인증 전 Degraded 상태만 이 단계에서 허용하며 기존 토큰은 덮어쓰지 않는다. 토큰은 환경에서 읽어 메모리/stdin으로 전달하고 `no_log: true`, `diff: false`를 적용한다. 하위 kubectl에 전체 Doppler 환경을 전달하지 않는다. 값은 셸 인자·Ansible `-e`·Git·로그에 넣지 않는다.

같은 소유권·같은 토큰이면 재실행 시 쓰기 0회다. 다른 토큰/Secret을 갱신·삭제하지 않는다. 여러 create 중 통신이 끊기면 부분 생성될 수 있고, 동일 입력 재실행으로 생성된 인증을 보존한다. 장애 조사 시에도 전체 Secret 덤프나 토큰 포함 debug를 켜지 않는다.

## 4. 지속 동기화 활성화·조회 검증

인증과 대상 준비를 확인한 뒤 `auth_ready_reviewed=true`, `targets_ready_reviewed=true`, `sync_enabled=true`로 Git 원본을 변경하고 생성기를 다시 실행한다. 검토·반영된 Git을 Argo CD가 조정하며 대상 쓰기 Role과 DopplerSecret을 만든다. run JSON의 `expected_revision`을 새로 반영된 SHA로 갱신한다.

다음은 **조회만** 수행하며 Doppler 토큰 주입이 필요 없다.

```bash
rtk proxy "$DOPPLER_PYTHON" scripts/doppler_runtime.py verify \
  --repo-root . --run-config "$DOPPLER_RUN_CONFIG"
```

검사: 같은 revision의 root/operator Application, 선언 spec, SecretSyncReady, 대상 type/소유권, 필수 키의 비어 있지 않은 전달 결과. 값·해시는 출력하지 않는다.

**제한:** Operator 1.7.1 condition은 observedGeneration을 기록하지 않는다. Healthy만으로 변경 직후 최신 값 수신을 보장하지 않으며 lastTransitionTime도 마지막 polling 시각이 아니다. 결과는 `freshness_verified=false`다. Doppler 변경 이력과 비밀값을 노출하지 않는 앱 기능 검사를 별도로 연결한다. TLS PEM 형식·키 일치·SAN·체인·만료·SDS·외부 handshake도 별도 검사이며 `tls_validity_verified=false`다.

## TLS 연결과 앱 반영

보유 인증서는 Doppler의 `WEB_TLS_CERT → tls.crt`, `WEB_TLS_KEY → tls.key`처럼 매핑한다. 실제 PEM은 매핑의 project/config에만 보관한다. processor는 `plain`이므로 base64 문자열이 아닌 원문 PEM이다. `target_namespace=istio-system`, `target_secret=ingress.json.routes[].tls_secret`로 맞춘다. 실제 유효성·SDS 검증 전 ingress의 `tls_ready_reviewed`를 켜지 않는다.

자동 발급 컨트롤러를 채택하면 그 인증서 Secret을 Doppler가 동시에 관리하지 않는다. DNS API 인증만 Doppler로 공급하는 등 소유권을 별도로 설계한다. 외부 인증서는 자동 발급·갱신을 선택했으며 [cert-manager 공통 설치](tls-automatic.md)까지 준비했다. DNS 업체별 issuer 연결은 아직 남아 있다.

Opaque는 지정 키만 요청하지만 upstream이 `DOPPLER_*` 메타데이터를 추가할 수 있다. 앱은 가급적 필요한 키를 `secretKeyRef`로 명시한다. 파일 소비는 앱 reload 지원을 확인한다. Secret 변경만으로 기존 프로세스의 env가 바뀌지 않는다.

Deployment update 권한은 제거했으므로 `secrets.doppler.com/reload: "true"`를 사용하지 않는다. 잘못된 annotation은 권한 오류/Degraded가 되며 직접 rollout restart로 우회하지 않는다. Git Pod template 변경을 Argo CD가 반영한다.

## 변경·복구 경계

- `prune=false`는 중지가 아니다. 기존 동기화 제거·전체 비활성화·대상/source 변경은 생성기가 차단한다. 명시적인 폐기/소유권 이전 절차 없이 파일만 지우면 기존 writer가 계속 실행될 수 있다.
- 인증 playbook은 최초 sync 전 전용이다. 활성 연동의 새 토큰 추가·회전은 기존 연동을 보존하는 별도 create-only 교체 절차를 구현·검토해야 한다. sync_enabled를 되돌려 우회하지 않는다.
- Git revert는 Doppler 값 복원이 아니다. 장애 시 Secret 삭제·빈 값 덮어쓰기·임의 `.env` 대체를 하지 않는다. 외부 복구 인증을 보존한다.
- 로컬 검사·ARM64 index 확인은 실제 reconcile·앱 소비·TLS 개통 완료가 아니다.

공식 근거: [Service Tokens](https://docs.doppler.com/docs/service-tokens), [CLI](https://docs.doppler.com/docs/cli), [Secret 동기화](https://docs.doppler.com/docs/doppler-k8s-operator-syncing-secrets), [고정 버전 controller](https://github.com/DopplerHQ/kubernetes-operator/tree/v1.7.1/controllers).
