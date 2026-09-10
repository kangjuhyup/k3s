# 애플리케이션 배포 원본

실제 앱이 추가되면 앱별 디렉터리에 재사용 가능한 chart/manifest·values 참조를 둔다. 현재 샘플 앱이나 배포 가능한 파일은 없다.

환경별 연결·namespace·배치 설정은 [clusters/oci-a1](../clusters/oci-a1/README.md)에서 관리한다. 이미지와 chart 버전을 추적 가능한 값으로 고정하고 정확한 이미지의 ARM64 지원을 검증한다.

런타임 환경변수·비밀값은 Doppler에서 공급하고 Git에는 필요한 Secret 참조만 둔다. 배포·rollback은 Argo CD가 Git 원본으로 수행한다. 단일 노드에서 실행 가능한 replica·배치 조건과 증설 후 분산 조건을 구분한다.
