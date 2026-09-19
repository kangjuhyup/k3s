# 단일 서버의 개발·운영 분리와 공유 Auth

사용자는 PostgreSQL·Redis 인스턴스를 공유하고 개발 데이터에 `dev` 명칭을 붙여 논리적으로 분리하며, 개발 QA를 통과한 서비스 버전을 운영에 반영하도록 요청했다. Auth는 별도 개발 서버를 만들지 않고 기존 서버에서 Tenant만 구분한다.

## 확정한 경계

| 항목 | 개발 | 운영 |
| --- | --- | --- |
| 일반 서비스 배포 | 서비스별 개발 워크로드 | 서비스별 운영 워크로드 |
| 일반 서비스 PostgreSQL | 개발 논리 DB·전용 계정, 이름에 `dev` 포함 | 기존 운영 논리 DB·전용 계정 |
| 일반 서비스 Redis | 개발 키 접두사·전용 ACL 계정 | 운영 키 접두사·전용 ACL 계정 |
| Auth 서버·도메인 | 기존 `https://auth.rvkang.app` 공유 | 기존 `https://auth.rvkang.app` |
| Auth 데이터 저장소 | 기존 Auth DB·Redis 공유, 애플리케이션 Tenant 경계 사용 | 동일 |
| Auth Tenant | 개발 전용 Tenant | 기존 운영 Tenant 유지 |
| OIDC Client·사용자·정책 | 개발 Tenant에 별도 등록 | 운영 Tenant의 기존 리소스 유지 |

Auth의 Kubernetes namespace·Application·Doppler config는 기존 `auth`, `auth / prd`를 유지한다. 개발 서비스가 Auth에 연결하기 위해 Auth 서버의 DB 계정·Redis 계정·내부 암호화 키를 받을 필요는 없다. 개발 서비스에는 해당 Tenant의 issuer와 OIDC Client 설정만 공급한다.

## Tenant 연결 계약

현재 Auth 소스의 `service/src/infrastructure/oidc-provider/oidc-provider.module.ts`와 `docs/docs/concepts/tenant/overview.md`에서 확인한 issuer 형식은 다음과 같다.

```text
https://auth.rvkang.app/t/{tenantCode}/oidc
https://auth.rvkang.app/t/{tenantCode}/oidc/.well-known/openid-configuration
```

`{tenantCode}`는 실제 Tenant code로 치환한다. 개발임을 알 수 있는 code를 사용하되 실제 생성된 code·id·client credential은 소비 서비스의 Doppler 설정으로 전달한다. 코드·문서에 실제 credential을 기록하지 않는다.

개발과 운영의 Client ID·redirect URI·사용자·권한·정책을 각각 등록한다. 각 서비스는 자기 환경의 정확한 issuer와 Client audience를 검증한다. 같은 호스트라는 이유로 두 Tenant의 토큰을 함께 허용하지 않는다. UI에서 Tenant를 선택하는 것만으로 데이터 격리가 검증된 것으로 간주하지 않는다.

## QA와 승격

일반 서비스는 이미지를 한 번 빌드하고 개발 환경에 digest로 고정해 QA한 뒤, 같은 digest를 운영 배포 설정에 반영한다. 개발 서비스는 개발 Tenant, 운영 서비스는 운영 Tenant에 연결한다. 승격할 때 개발 사용자·토큰·DB 데이터를 운영으로 복사하지 않는다.

Auth 서버 코드와 DB migration은 하나이므로 Tenant별로 서로 다른 Auth 버전을 실행할 수 없다. 개발 Tenant는 인증 연동·정책·Client 설정 QA를 위한 경계다. Auth 자체의 코드 변경을 먼저 별도 버전으로 QA해야 하는 경우에는 임시 검증 환경이 별도로 필요하다. 이번 구성은 Auth를 공유한다는 사용자 선택을 따른다.

## 구현 상태와 범위

앞서 작성했던 별도 Auth 개발 namespace·도메인·Application·Doppler `auth/dev` 매핑·개발 DB/Redis 계정·인증서 도구·Auth 이미지 승격 도구는 로컬에서 제거했다. 모두 미배포 상태였으며 기존 운영 선언으로 복구했다. 실제 클러스터나 Doppler 리소스를 삭제한 것이 아니다.

이 저장소에 현재 배포 원본이 있는 업무 앱은 Auth다. 다른 서비스에 대한 개발/운영 overlay·CI·승격 구현은 해당 서비스의 배포 원본과 이미지 저장소를 확인한 뒤 진행한다. 일반 서비스의 논리 데이터 분리 요구는 유지하지만, Auth 전용 분리 코드를 다른 서비스 구현으로 간주하지 않는다.

Tenant 생성과 Client 등록은 Auth 관리 기능을 사용하는 운영 데이터 변경이다. Kubernetes manifest나 직접 SQL로 Tenant를 생성하지 않는다. 개발 Tenant 생성·조회 및 OIDC discovery는 확인했다. Client 등록과 배포된 Auth 버전의 교차 Tenant 격리 검증은 아직 수행하지 않았다. [설정과 검증 절차](../runbooks/dev-prod-environments.md)를 따른다.
