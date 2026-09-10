# 운영 절차 진입점

현재는 [기존 A1 Terraform 편입](terraform-adoption.md)의 준비·검토 절차가 있다. 실제 편입은 수행하지 않았다. 다른 운영 작업의 일반 안전 원칙은 기존 스킬을 재사용하고, 실제 대상·명령·복구 시점이 확정되면 작업별 절차를 작성한다.

처음 입력할 때는 [단계별 설정값 안내](configuration-inputs.md)에서 파일·키·값·Doppler 위치를 확인한다.

| 작업 | 현재 참고 지침 |
| --- | --- |
| 최초 설치·Argo CD bootstrap | [K3s 1단계](../../ansible/README.md), [Argo CD 2단계](argocd-bootstrap.md), [GitOps](../../.agents/skills/k3s-infra/references/gitops.md) |
| Istio GitOps baseline | [Istio 3단계](istio-bootstrap.md): CRD/istiod/gateway 준비 순서, 내부 ClusterIP 기본값 |
| ServiceLB 외부 노출·TLS·내부 mTLS | [외부 ingress 확장](istio-external-ingress.md): 입력 gate·도메인/경로·인증서 참조·앱 namespace STRICT |
| TLS 자동 발급·갱신 기반 | [자동 TLS](tls-automatic.md): cert-manager 공통 설치 코드, DNS 업체별 발급 연결은 미구현 |
| Argo CD 계정·권한·admin 비활성화 | [개인 계정 운영](argocd-accounts.md): 초기 admin → 개발자별 계정, Git RBAC·Doppler 비밀값 |
| 기존 A1 편입·agent 증설 | [편입 runbook](terraform-adoption.md), [Terraform](../../.agents/skills/k3s-infra/references/terraform.md), [노드 확장](../../.agents/skills/k3s-infra/references/scaling.md) |
| 기존 A1 유지·OS부터 새로 구축 | [OS 재구축 runbook](os-rebuild.md): 편입과 교체 분리, 이전 볼륨 보존, 신규 설치 |
| 장애 진단 | [진단](../../.agents/skills/k3s-infra/references/diagnostics.md), [Istio](../../.agents/skills/k3s-infra/references/istio.md) |
| 백업·복구·업그레이드·노드 유지보수 | [유지보수](../../.agents/skills/k3s-infra/references/maintenance.md) |
| Wasabi 외부 사본·전송 검증·보존·원격 복구 | [Wasabi 백업](../../.agents/skills/k3s-infra/references/wasabi.md) |
| Doppler 설치·최소 인증·키 매핑·조회 검사 | [Doppler 4단계](doppler-bootstrap.md): 값 없는 선언·생성 Secret 소유권·실행 gate |
| 값 교체·Doppler 장애·복구 인증 | [Doppler](../../.agents/skills/k3s-infra/references/doppler.md) |

환경별 절차에는 대상 context/inventory, 필요한 권한·입력 참조, Git revision·Doppler 이력, 서비스 영향, 단계별 성공/중단 기준, 복구 방법을 명시한다. 실제 비밀값·백업 내용을 문서에 붙여 넣지 않는다. 운영 절차 문서가 존재한다는 사실을 실행·복구 시험 완료로 보고하지 않는다.
