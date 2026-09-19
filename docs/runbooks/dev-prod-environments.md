# 공유 Auth의 개발 Tenant와 서비스 운영 승격

[개발·운영 경계](../architecture/2026-09-19-dev-prod-isolation.md)에 따라 Auth 서버는 하나를 유지한다. 별도 개발 Auth 도메인·namespace·DB·Redis 계정을 만들지 않는다. 다른 서비스의 개발·운영 데이터는 공유 PostgreSQL·Redis 안에서 논리적으로 분리한다.

## 개발 Tenant 구성

1. 기존 `https://auth.rvkang.app`의 관리자 UI에서 Tenants 화면을 연다. 먼저 기존 Tenant 목록을 확인해 개발 Tenant가 이미 있으면 용도와 설정을 확인한다.
2. 없으면 개발용임을 구분할 수 있는 Code와 Name으로 Tenant를 생성한다. Code는 소문자·숫자·하이픈을 사용하며 생성 후 변경하지 않는 식별자다. 기존 운영 Tenant를 변경하거나 개발용으로 전환하지 않는다.
3. 개발 Tenant를 명시적으로 선택하고 개발 서비스용 OIDC Client와 테스트 사용자를 등록한다. 해당 앱의 client 유형·grant·PKCE·개발 callback 및 logout URL을 확인해 등록한다. 운영 Client나 비밀값을 복사하지 않는다.
4. 테스트에 필요한 사용자·role·permission·정책·외부 IdP 연결은 개발 Tenant 범위에 둔다. 가입·MFA·전화번호 인증 정책은 QA 요구에 맞춰 지정하며 운영 정책을 자동 변경하지 않는다.
5. 개발 서비스 Doppler config에 개발 Tenant의 issuer·Client ID와 필요한 경우 Client secret을 전달한다. 실제 환경변수 이름은 소비 앱 계약을 따른다. public client에 client secret을 넣지 않는다.

관리 API는 소스 기준 `POST /admin/tenants`이며 `code`, `name`을 필수로 받는다. 기존 관리자 인증과 command 경로를 사용한다. 직접 DB INSERT나 인프라 migration Job으로 우회하지 않는다. 개발 Tenant 생성은 아래 실행 기록에서 확인한다. Client 등록은 아직 수행하지 않았다.

## 연결 주소

두 환경의 호스트는 `auth.rvkang.app`으로 동일하고 Tenant 경로가 다르다.

```text
Issuer:    https://auth.rvkang.app/t/{tenantCode}/oidc
Discovery: https://auth.rvkang.app/t/{tenantCode}/oidc/.well-known/openid-configuration
```

서비스마다 정확한 issuer의 discovery를 읽어 authorization·token·JWKS endpoint를 사용한다. 운영 서비스는 기존 운영 Tenant issuer를 유지한다. 개발 서비스에 Auth 서버의 Doppler `auth/prd` 토큰, DB/Redis 계정 또는 관리자 비밀번호를 전달하지 않는다.

## QA 확인

- 개발 Client로 개발 사용자의 로그인·토큰 발급·갱신·로그아웃이 정상 동작한다.
- 개발 토큰은 운영 서비스에서 issuer/audience 검증으로 거부되며, 운영 토큰도 개발 서비스에서 거부된다.
- 다른 Tenant의 Client·사용자·권한·정책을 Tenant 범위 API에서 읽거나 수정할 수 없다. 전역 관리자 권한과 일반 사용자 권한은 구분해 확인한다.
- Client callback·logout URL이 각 환경에 맞고, 개발에서 운영 callback을 사용할 수 없다.
- 개발 로그인·정책 변경·로그아웃이 운영 Tenant의 세션과 정책에 영향을 주지 않는지 확인한다.
- 운영 로그인과 기존 인증 연동이 유지된다.

이는 실제 배포 버전에서 수행할 검증 목록이다. 로컬 소스에 Tenant 기능이 있다는 사실만으로 운영 격리가 검증되었다고 보고하지 않는다. 단일 Auth 프로세스·저장소·장애와 부하는 공유한다.

## 일반 서비스 배포와 승격

1. 해당 서비스의 개발·운영 워크로드와 Doppler config를 나눈다.
2. 공유 PostgreSQL에는 개발 논리 DB·전용 계정을 두고, 공유 Redis에는 `dev`가 포함된 개발 접두사와 전용 ACL을 설정한다. 실제 DB명·계정·접두사는 Doppler에서 관리한다.
3. 개발 서비스의 인증은 개발 Tenant issuer에 연결한다.
4. 빌드한 image digest를 개발에 고정하고 실행 중 버전·Git revision·QA 결과를 기록한다.
5. QA를 통과한 동일 digest를 운영 배포 설정에 반영한다. 운영은 운영 DB·Redis 설정과 운영 Tenant issuer를 사용한다.
6. 검토된 Git 변경을 Argo CD가 반영한 뒤 운영 기능을 검증한다. 이미지 rollback은 DB schema나 데이터를 복구하지 않는다.

이 흐름은 Auth 소비 서비스의 승격 절차다. Auth 자체는 한 버전을 공유하므로 개발 Tenant만으로 Auth 서버 버전별 QA·승격을 구현했다고 표현하지 않는다. 현재 다른 서비스의 overlay·빌드 CI·승격 자동화는 구성하지 않았다.

## 이번 변경 상태

- 앞서 추가한 별도 개발 Auth 배포 구성과 전용 데이터 분리 도구를 제거했다.
- 기존 운영 Auth·DB·Redis·도메인의 Git 선언을 유지한다.
- 기존 관리자 API로 개발 Tenant를 생성하고 단건 조회 및 OIDC discovery의 issuer를 검증했다.
- 생성 요청의 가입 정책이 실제 조회에 반영되지 않아 Tenant 정책 API로 초대 전용을 설정하고 다시 조회해 확인했다. 다른 Tenant는 변경하지 않았다.
- Tenant 생성 작업에서는 Client·테스트 사용자 생성, 교차 Tenant 접근 차단 QA, Doppler·DNS 변경은 수행하지 않았다.
- 후속 버전 갱신으로 공유 Auth `v0.2.1`을 배포했다. 관리자 로그인과 개발 Tenant의 초대 전용 정책·OIDC issuer를 재확인했다.
- 기존 운영 배포 절차는 [Auth GitOps 배포](auth-public-domain.md)를 따른다.
