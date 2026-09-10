# Argo CD 공개 도메인

`argo.rvkang.app`을 Argo CD에 연결한다. [매니페스트](../../gitops/clusters/oci-a1/argocd-ingress/)를 직접 관리한다. 공개 도메인·공개 URL은 Git에 기록할 수 있으며 API 토큰·서버 IP·개인키는 Doppler 관리 대상이다.

## 연결과 소유권

Cloudflare DNS → OCI 공인 경로의 443 → K3s ServiceLB → Istio SNI 라우팅 → `argocd-server.argocd.svc.cluster.local:443` 순서다. Istio는 TLS를 그대로 전달하고 Argo CD가 HTTPS를 종료한다. HTTP 80은 HTTPS로 리다이렉트한다. `server.insecure=false`를 유지하며 Argo CD namespace에 sidecar 주입이나 STRICT mTLS를 추가하지 않는다. DestinationRule의 `DISABLE`은 Istio가 TLS를 추가로 감싸지 않는다는 뜻이며, 전달되는 Argo CD HTTPS를 평문으로 바꾸지 않는다.

- `argocd` Application: 기존 설치와 공개 URL 설정을 소유한다.
- `istio` Application: 기존 gateway Service의 ServiceLB overlay를 소유한다. 일반 앱 라우팅과 독립적이며 80/443만 노출한다.
- `cert-manager` Application: 고정된 controller·CRD 설치를 소유한다.
- `doppler` Application: `infrastructure/prd`의 `CLOUDFLARE_DNS_API_TOKEN_`을 `cert-manager/cloudflare-dns-api-token` Secret의 `api-token` 키로 전달한다.
- `argocd-ingress` Application: ClusterIssuer → Certificate → Gateway/VirtualService/DestinationRule을 wave 0/10/20으로 적용한다. 기존 Argo CD 3.5.2의 cert-manager health 검사로 최초 인증서 Ready 이후 라우팅을 적용한다. 다른 Application 사이의 wave만으로 controller/webhook 준비를 보장하지 않으므로 초기 API 미준비 오류는 준비 후 재동기화한다.

cert-manager가 `argocd/argocd-server-tls`를 생성·갱신하고 Argo CD가 변경을 자동으로 읽는다. Doppler는 이 TLS Secret을 관리하지 않는다. ACME 계정 키는 cert-manager가 생성하며 개인 이메일은 설정하지 않는다. ClusterIssuer의 DNS solver는 해당 호스트만 선택한다. 이 선택은 다른 사용자의 Certificate 생성 권한을 제한하는 인가 정책이 아니므로 ClusterIssuer·Certificate 생성 권한은 관리자 범위로 관리한다.

인증서 health는 최초 라우팅 적용 순서를 제어한다. 이후 인증서가 만료되어도 이미 적용된 route를 자동으로 제거하지 않는다. 갱신 실패·만료 감시와 실제 TLS 검증은 운영 시 별도로 확인한다.

## Cloudflare와 Doppler 준비

1. Cloudflare의 `rvkang.app` zone이 활성 상태인지 확인한다.
2. 해당 zone에만 `Zone / DNS / Edit`, `Zone / Zone / Read` 권한을 가진 API Token을 만든다. 토큰 값은 Doppler `infrastructure/prd`의 `CLOUDFLARE_DNS_API_TOKEN_`에 저장한다(현재 등록된 키 이름은 끝에 밑줄이 있다). 채팅·Git·명령 인자에 넣지 않는다.
3. Cloudflare에 `A`, 이름 `argo`, 내용은 확인된 OCI 공인 IPv4 주소를 설정한다. 초기 연결은 **DNS only**로 검증한다. IPv6 연결을 별도로 구성하지 않았다면 AAAA를 추가하지 않는다. DNS 레코드 생성은 cert-manager가 수행하지 않는다. cert-manager는 인증용 TXT 레코드만 관리한다.
4. OCI 네트워크와 호스트 방화벽의 80/443 허용, ServiceLB 포트 점유를 확인한다. 이 변경은 OCI 방화벽을 수정하지 않는다.
5. Git 변경을 반영한 뒤 cert-manager·Doppler·Istio·Argo CD와 `argocd-ingress`의 기대 revision 및 상태를 확인한다. 인증서 발급 전에는 연결 완료로 간주하지 않는다.

Cloudflare 프록시를 켜면 `Full (strict)`를 사용한다. CLI는 `argocd login argo.rvkang.app --grpc-web`을 사용할 수 있다. 네이티브 gRPC 사용 시 Cloudflare의 gRPC 설정·HTTP/2 경로를 별도로 검증한다. DNS only에서는 Argo CD에 직접 TLS 연결한다.

## 로컬 생성과 검증

저장소에서 확인한 Python 3.9+와 PyYAML, Helm v4.2.4 및 고정 chart archive를 사용한다. 현재 로컬 환경은 `.local/os-cleanup-venv/bin/python`(3.12.9), `.local/downloads/darwin-arm64/helm`(v4.2.4)이다.

```sh
.local/os-cleanup-venv/bin/python scripts/gitops_validate.py --repo-root .
```

`test_argocd_ingress.py`는 정확한 SNI·backend·TLS 유지, 인증서 소유권·적용 순서, 잘못된 입력 및 누락된 의존성, ServiceLB 공유를 검사한다. `HELM_TEST_BINARY`, `CERT_MANAGER_TEST_CHART`, `ISTIO_TEST_CHART_DIR`, `ARGOCD_TEST_CHART`에 로컬 고정 파일을 지정하면 실제 차트와 CRD 검사도 실행한다.

```sh
.local/os-cleanup-venv/bin/python -m unittest discover -s scripts/tests -p 'test_argocd_ingress.py' -v
```

실제 배포 후 TLS 검증을 끄지 않고 `curl -I https://argo.rvkang.app`과 로그인, HTTP→HTTPS 전환을 확인한다. 기존 port-forward 복구 경로는 유지한다. 파일 삭제나 source 연결 해제는 기존 공개 리소스의 철거 절차가 아니다.

이 작업에서 로컬 GitOps 선언을 준비했다. DNS 변경·토큰 발급/저장·Git push·실클러스터 동기화·인증서 발급 검증은 수행하지 않았다.

근거: [Argo CD TLS와 자동 재로딩](https://argo-cd.readthedocs.io/en/stable/operator-manual/tls/), [Cloudflare DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/), [Istio TLS passthrough](https://istio.io/latest/docs/tasks/traffic-management/ingress/ingress-sni-passthrough/), [Cloudflare Full (strict)](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/).
