# OCI 공통 모듈

환경에서 재사용할 OCI 리소스 모듈을 둔다. 현재는 구현된 모듈이 없다.

모듈은 명시적 입력을 받고 필요한 비밀값 없는 outputs를 제공한다. backend·환경별 계정 선택은 [환경 root](../environments/oci-a1/README.md)가 담당한다. 네트워크·노드·볼륨 모듈의 실제 경계는 기존 OCI 관리 범위를 확인한 뒤 정한다.

모듈에서 K3s를 설치하거나 Helm/Kubernetes provider로 앱을 배포하지 않는다. 호스트 작업은 Ansible, Kubernetes 배포는 Argo CD 소유다. 단일 환경용 상수를 모듈 내부에 고정하지 않는다.
