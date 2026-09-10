# Grafana 공개 도메인

`grafana.rvkang.app`은 기존 Cloudflare DNS와 ServiceLB를 통해 Istio gateway로 연결한다. 외부 TLS는 gateway에서 종료하고 `monitoring-grafana.monitoring.svc.cluster.local:80`의 기존 내부 HTTP로 전달한다. monitoring namespace의 sidecar 주입 비활성 상태를 유지하므로 이 내부 구간은 mTLS가 아니다.

[monitoring.json](../../gitops/clusters/oci-a1/monitoring.json)의 `public_host`가 공개 도메인 원본이다. [생성기](../../scripts/monitoring_gitops.py)는 공개 URL·보안 쿠키용 Helm overlay와 Certificate·Gateway·VirtualService·DestinationRule을 생성한다. 기존 `monitoring` Application이 이 리소스를 관리하고 Certificate Ready 이후 route를 적용한다. `argocd-cloudflare` ClusterIssuer는 Argo CD와 Grafana의 정확한 호스트만 DNS-01 solver 대상으로 선택한다. 인증 토큰은 기존 Doppler 참조를 재사용한다.

로그인 계정은 기존 Doppler `infrastructure/prd`의 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`다. 익명 접근과 회원가입 비활성화, PVC, 대시보드, 데이터소스 설정을 유지한다. 공개 URL의 Helm 설정 변경 시 기존 Recreate 전략으로 Grafana가 잠시 재시작된다. Prometheus·Alertmanager·데이터베이스의 공개 route는 만들지 않는다.

로컬 생성/검사: `python scripts/argocd_gitops.py --repo-root . --write` 후 같은 명령에서 `--write`를 빼고 검사한다. `test_monitoring_gitops.py`와 `test_argocd_ingress.py`는 공개 호스트·인증서·라우팅·공유 issuer와 기존 동작을 검사한다. 실제 반영은 Git push 후 Argo CD가 수행한다. `public_host`를 지우는 것만으로 공개 route를 철거할 수 없으며 기존 생성 리소스가 사라지는 변경은 생성기에서 차단한다.

배포 후 HTTPS의 `/login` 응답, `/api/health`, 실제 로그인, HTTP→HTTPS 전환과 원본 서버의 인증서 SAN·신뢰 체인을 검사한다. Cloudflare 프록시 설정은 기존 값을 유지하며 원본 인증서 발급 후 `Full (strict)`를 사용할 수 있다. TLS Secret의 생성·갱신은 cert-manager, gateway의 인증서 갱신 반영은 Istio SDS가 담당한다.
