# 애플리케이션 배포 원본

앱별 디렉터리에 재사용 가능한 배포 원본을 둔다. [auth](auth/kustomization.yaml)는 API·UI·워커·마이그레이션 Job·Service·UI 설정을 관리한다.

OCI 리소스 예산·HPA·공개 도메인·Doppler 주입은 [auth 환경 구성](../clusters/oci-a1/auth/kustomization.yaml)에 둔다. 환경 Kustomization이 앱 원본을 참조하고 리소스와 공개 URL을 패치한다. 앱 원본만 직접 배포하지 않는다.

환경별 연결·namespace·배치 설정은 [clusters/oci-a1](../clusters/oci-a1/README.md)에서 관리한다. 이미지와 chart 버전을 추적 가능한 값으로 고정하고 정확한 이미지의 ARM64 지원을 검증한다.

런타임 환경변수·비밀값은 Doppler에서 공급하고 Git에는 필요한 Secret 참조만 둔다. 배포·rollback은 Argo CD가 Git 원본으로 수행한다. 단일 노드에서 실행 가능한 replica·배치 조건과 증설 후 분산 조건을 구분한다.
