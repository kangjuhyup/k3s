# 애플리케이션 배포 원본

앱 배포 소스는 공통 원본과 환경별 설정으로 구분한다.

```text
apps/
├── base/   # auth, gaegaeting, redisinsight, vote 공통 워크로드
├── dev/    # gaegaeting, vote 개발 환경
└── prod/   # auth, redisinsight 운영 환경
```

`base/<app>`에는 Deployment·Service·migration Job 등 앱 원본을 둔다.
`dev/<app>`과 `prod/<app>`은 해당 base를 참조하고 환경별 replica·리소스 예산·앱 설정을 패치한다. 현재 사용하는 환경만 선언하며, base를 직접 배포하지 않는다.

[clusters/oci-a1](../clusters/oci-a1/README.md)는 환경 overlay를 참조하고 클러스터의 namespace·Doppler 전달·DB 준비·Ingress·인증서·정책을 연결한다. Argo CD Application의 기존 경로와 리소스 소속은 유지한다. 따라서 폴더 이동만으로 워크로드를 다시 생성하지 않는다.

- [Auth 운영](prod/auth/kustomization.yaml)
- [Gaegaeting 개발](dev/gaegaeting/kustomization.yaml)
- [Vote 개발](dev/vote/kustomization.yaml)
- [RedisInsight 운영](prod/redisinsight/kustomization.yaml)

Kafka·PostgreSQL·Redis는 공용 인프라로 별도 관리한다. 환경별 실제 값과 비밀값은 Doppler에서 공급하고 Git에는 필요한 Secret 참조만 둔다. 배포·rollback은 Git 변경을 Argo CD가 반영하는 방식으로 수행한다.
