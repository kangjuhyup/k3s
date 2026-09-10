# Grafana 공개 도메인

`grafana.rvkang.app`은 기존 Cloudflare DNS와 ServiceLB를 통해 Istio gateway로 연결한다. 외부 TLS는 gateway에서 종료하고 `monitoring-grafana.monitoring.svc.cluster.local:80`의 기존 내부 HTTP로 전달한다. monitoring namespace의 sidecar 주입 비활성 상태를 유지하므로 이 내부 구간은 mTLS가 아니다.

공개 도메인 원본은 `gitops/clusters/oci-a1/grafana-public.values.yaml`과 `monitoring/`의 Certificate·Gateway·VirtualService·DestinationRule이다. 기존 monitoring Application이 소유하며 인증서 Ready 이후 route를 적용한다. 공유 ClusterIssuer의 dnsNames도 함께 직접 관리한다. 인증 토큰은 기존 Doppler 참조를 재사용한다.

로그인 계정은 기존 Doppler `infrastructure/prd`의 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`다. 익명 접근과 회원가입 비활성화, PVC, 대시보드, 데이터소스 설정을 유지한다. 공개 URL의 Helm 설정 변경 시 기존 Recreate 전략으로 Grafana가 잠시 재시작된다. Prometheus·Alertmanager·데이터베이스의 공개 route는 만들지 않는다.

매니페스트를 직접 편집하고 `.local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .`로 읽기 전용 검사한다. 실제 반영은 Git push 후 Argo CD가 수행한다. prune=false이므로 파일 삭제만으로 공개 route가 철거되지 않는다. 소유권·영향과 삭제 절차를 별도로 검토한다.

배포 후 HTTPS의 `/login` 응답, `/api/health`, 실제 로그인, HTTP→HTTPS 전환과 원본 서버의 인증서 SAN·신뢰 체인을 검사한다. Cloudflare 프록시 설정은 기존 값을 유지하며 원본 인증서 발급 후 `Full (strict)`를 사용할 수 있다. TLS Secret의 생성·갱신은 cert-manager, gateway의 인증서 갱신 반영은 Istio SDS가 담당한다.
