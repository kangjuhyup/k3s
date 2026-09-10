# Doppler Operator GitOps

공식 Kubernetes Operator **1.7.1**을 [install/](install/kustomization.yaml)에 고정했다. 실제 설치는 하지 않았다. 환경별 [doppler.json](../../clusters/oci-a1/doppler.json)은 비활성·빈 매핑이다. [4단계 runbook](../../../docs/runbooks/doppler-bootstrap.md)과 [설정값 표](../../../docs/runbooks/configuration-inputs.md#4단계-doppler-지속-동기화)를 따른다. Doppler MCP는 런타임 동기화에 필요하지 않으며 설정하지 않았다.

## 출처와 변경

- 공식 chart: `https://helm.doppler.com/doppler-kubernetes-operator-1.7.1.tgz`
- chart SHA256: `5230eb0232d5a9d31d5a4e7303c8a002f3232717afe2a03a8cabfd3030b3e407`
- image: `docker.io/dopplerhq/kubernetes-operator:1.7.1@sha256:a29846259fb3e9a1b183adcde687e5216f768ea3693606df8266a945030d02ca`
- 공개 registry index의 `linux/arm64` 확인일: 2026-09-09. 항상 최신인 버전이라는 의미는 아니다.
- 원본: [DopplerHQ/kubernetes-operator v1.7.1](https://github.com/DopplerHQ/kubernetes-operator/tree/v1.7.1), Apache-2.0, [LICENSE](LICENSE).

공식 chart는 values가 비어 있어 image·nodeSelector·권한을 values로 조정할 수 없다. [doppler_vendor.py](../../../scripts/doppler_vendor.py)가 checksum 확인 후 지정한 두 YAML 파일을 메모리에서 읽고 JSON/Kustomization으로 변환한다. 재생성 결과를 Git으로 검토하며 Argo CD가 배포한다. 직접 Helm 설치가 아니다.

변경 사항: ARM64/Linux 배치, image digest, seccomp RuntimeDefault·capabilities drop ALL, sidecar injection disabled, CRD/namespace 삭제 보호와 sync wave. ClusterRole의 Secret 쓰기·Deployment 쓰기·OIDC token 발급 권한을 제거했다. 대상 namespace Role에서 create 및 **지정 Secret 이름만 update**를 허용한다. Secret 삭제 권한은 없다.

Kubernetes RBAC는 create를 resourceNames로 제한할 수 없어 대상 namespace 내 Secret 생성 권한은 남는다. Operator의 cluster-wide Secret 조회 권한도 남으므로 namespace 간 완전한 비밀 격리는 아니다. 관리자 Git 권한과 Kubernetes 저장 시 암호화·백업 접근 통제는 별도로 검토한다.

요청량은 1 replica, 100m CPU / 256Mi RAM이다. 같은 Application에서 CRD Established → Deployment(wave 10) → DopplerSecret(wave 20)을 적용한다. 실제 A1 부하·API 호환성·동기화는 아직 검증하지 않았다.

공식 문서: [Operator](https://docs.doppler.com/docs/kubernetes-operator), [동기화](https://docs.doppler.com/docs/doppler-k8s-operator-syncing-secrets), [보안](https://docs.doppler.com/docs/doppler-k8s-operator-security).
