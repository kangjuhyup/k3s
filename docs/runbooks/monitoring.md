# 모니터링 운영

Argo CD `monitoring` Application이 kube-prometheus-stack 90.0.0을 관리한다.
원본은 `gitops/platform/monitoring/base.values.json`, 설치 단계는
`gitops/clusters/oci-a1/monitoring.json`이다. 생성은 기존
`scripts/argocd_gitops.py --repo-root . --write`를 사용한다.

## 비밀값과 설치 순서

`infrastructure / prd`의 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`,
`SLACK_WEBHOOK_URL`을 Doppler Operator가 각각 `grafana-admin`,
`alertmanager-slack` Secret에 주입한다. 웹훅은 Alertmanager의 `api_url_file`로
읽으며 토큰이나 실제 URL을 Git에 넣지 않는다. 봇·앱 토큰은 사용하지 않는다.

최초에는 `enabled: false`로 namespace만 먼저 생성한다. Doppler 동기화와
필수 키를 값 출력 없이 확인한 뒤 두 플래그를 true로 변경하고 Git에 반영한다.
스택 활성화 이후 false로 되돌리는 것은 제거 절차가 아니며 생성기가 거부한다.

## 용량과 수집 범위

- Prometheus: 메모리 최대 2Gi, 보존 7일 또는 8GB 중 먼저 도달하는 한도, PVC 10Gi.
- Alertmanager: 메모리 최대 256Mi, PVC 1Gi, 복구 알림 포함 Slack 전달.
- Grafana: 본체 메모리 최대 512Mi, sidecar 각각 128Mi, PVC 1Gi.
- 노드·Kubernetes 워크로드·API·kubelet 및 CNPG 기본 메트릭을 수집한다.
- Redis master/replica 수집기는 각각 최대 64Mi이며 기존 probe 계정 권한은
  PING/INFO로 한정된다. 운영용 client 인증서로 mTLS를 검증하고 관리 비밀번호·CA 개인키는
  전달하지 않는다. CONFIG/키 탐색은 비활성이고 인증·복제 연결·메모리 알림을 둔다.
  인증서 교체 시 Redis 서버뿐 아니라 수집기의 Pod template도 Git으로 갱신해
  재시작하고 수집 성공을 재검증한다. 자동 Secret reload는 구성하지 않았다.
- Redis 인증서 만료 자동 경보·자동 갱신은 아직 포함하지 않는다. 기존 Redis
  runbook의 PKI 검사와 갱신 절차를 계속 따른다.
- K3s 별도 노출 설정이 필요한 etcd/controller-manager/scheduler/proxy 수집은 비활성이다.

local-path PVC는 같은 노드의 디스크를 사용한다. 요청 용량은 디스크 쿼터가
아니므로 호스트 디스크 사용량도 확인한다. PVC 보존은 노드 장애 대비 백업이
아니다. Wasabi 백업은 비활성 상태를 유지한다. 단일 노드 중단 시 이 스택도
함께 중단되므로 외부 dead-man 감시를 대신하지 않는다.

## 접속과 확인

확인된 kubeconfig/context를 사용한다. 모든 서비스는 ClusterIP이며 Ingress는 없다.

```sh
kubectl --kubeconfig "$KUBECONFIG" --context "$K3S_CONTEXT" -n monitoring get pods,pvc
kubectl --kubeconfig "$KUBECONFIG" --context "$K3S_CONTEXT" -n monitoring port-forward svc/monitoring-grafana 3000:80
```

브라우저에서 localhost의 3000번 포트로 접속한다. 로그인 값은 Doppler에서
확인하며 대화·스크린샷·명령 인자로 공유하지 않는다. Grafana의 관리 계정은
최초 DB 초기화 시 반영되므로 Doppler 값 변경만으로 기존 로그인 비밀번호가
회전하지 않는다. 교체 시 Grafana의 지원되는 계정 변경 절차를 별도로 수행한다.

Prometheus Targets에서 실제 수집 성공을, Alertmanager에서는 알림 전달 성공을
검증한다. `Watchdog`, `InfoInhibitor`는 Slack 전송하지 않는다. 원복은 Git의
검증된 설정으로 되돌려 수행하고 PVC 삭제나 직접 Helm 설치로 우회하지 않는다.

`scripts/monitoring_verify.py --run-config <보호된 런타임 설정 경로>`는 기존
Doppler/Redis 검증과 같은 kubectl·kubeconfig·context·api_server 설정을 사용한다.
수집 대상, 필수 메트릭, Grafana 인증·익명 접근 거부·대시보드·데이터소스,
Prometheus에서 Alertmanager로의 Watchdog 전달을 검증한다.
`--send-test-alert`는 실제 Slack 테스트 알림 1건을 발생시키며 전송 성공 카운터를
확인한 후 해제한다. 이 옵션은 알림 전송이 승인된 경우에만 사용한다.
