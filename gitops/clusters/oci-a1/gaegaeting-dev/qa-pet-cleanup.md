# 승인된 dev QA 반려견 정리

이 절차는 분리 UI 검증에서 생성한 단일 테스트 반려견 삭제에만 사용한다. 기존 `deletePet` API는 실제 삭제를 수행하지 않아 일회성 SQL 작업을 명시 승인받았다. 앱 이미지·migration·Kubernetes 원하는 상태는 변경하지 않는다.

`scripts/gaegaeting_qa_pet_cleanup.mjs`를 현재 배포된 ARM64 Account/Match의 Node/DB 환경으로 stdin 실행한다. 운영자가 검토한 mode0600 입력 파일을 메모리로 읽어 `globalThis.qaCleanupInput`에 전달한다. 입력에는 environment=`gaegaeting-dev`, ownerAuthSubject, ownerProfileId, petId, expectedPetName, profileNickname 및 QA 생성/사진 삭제/프로필 보존 확인 플래그가 필요하다. 식별자·자격 증명을 Git이나 결과에 기록하지 않는다.

1. Match에서 `qaCleanupMode='feed-check'`를 실행해 소유자 feed와 target feed_item이 모두 0인지 확인한다. pet 직접 참조 컬럼은 현 Match 스키마에 없다.
2. Account에서 `verify`를 실행한다. DB의 external subject 연결은 tenant code가 아닌 `AUTH_ISSUER`를 tenant_id로 저장하므로 issuer+subject+profile을 정확히 검사한다. 행 잠금, 이름·소유자 일치, USER/PET attachment 0, 예상 외 FK 부재를 확인하고 ROLLBACK한다.
3. 승인 범위·입력 불변을 확인한 뒤 Match 검사를 다시 하고 Account `delete`를 실행한다. SERIALIZABLE 트랜잭션에서 동일 검사를 반복하고 조건부 DELETE가 정확히 1행인지 확인한다. 프로필 전체 행이 삭제 전후 동일한지 확인하고 COMMIT한다. 오류 시 ROLLBACK한다.
4. personality는 별도 연결 테이블이 아니라 `pet.personalities` text 컬럼이다. 해당 pet 행 삭제에 포함되며 별도 personality 행 삭제는 없다. pet/profile 사진이나 feed가 존재하면 작업을 중단한다.
5. 비식별 결과와 최종 앱 readiness, 기존 Pod 및 migration Job UID 보존을 기록한다. 계정·ADMIN 역할·프로필·다른 pet·production 데이터는 변경하지 않는다.

입력 identity 검증 실패를 우회하거나 broad DELETE로 변경하지 않는다. 반복 실행 시 대상 부재를 실패로 처리해 이미 삭제된 테스트 행을 다른 행으로 대체하지 않는다.
