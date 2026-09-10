# Wasabi 외부 백업 사본

## 확정 범위와 필수 입력

노드 외부 백업 사본의 목적지는 **Wasabi Object Storage**다. A1 내부 사본만으로 백업 완료를 보고하지 않는다. Wasabi는 이 단계에서 백업 목적지이며 Kubernetes PV·DB의 실시간 저장소나 Terraform state backend로 확정한 것이 아니다. 버킷/IAM·lifecycle 생성·변경 또는 실제 업로드도 별도 작업 범위를 확인한다.

실제 실행 전에 계정·bucket·region·S3 endpoint·환경/클러스터별 prefix, 백업 주기·보존 기간·목표 RPO/RTO, 백업 도구·버전, Doppler project/config·키 참조, 암호화·복구 경로를 확인한다. 이름·주소·보존 일수를 추측하지 않는다. endpoint는 해당 Wasabi 리전의 공식 값을 쓰고 HTTPS와 인증서 검증을 유지한다. S3 호환성을 이유로 AWS endpoint·region 기본값을 그대로 사용하지 않는다. [Wasabi 리전별 endpoint](https://docs.wasabi.com/docs/service-urls-for-wasabis-storage-regions)

## 백업 종류와 소유권

| 대상 | 생성·전송 경로 |
| --- | --- |
| K3s SQLite | [유지보수](maintenance.md)의 일관된 백업 절차로 생성한 뒤 선택한 도구로 Wasabi에 전송한다. 실행 중인 DB 파일의 단순 복사를 기본으로 삼지 않는다. |
| K3s embedded etcd | 실제 사용 중일 때만 K3s의 S3 호환 snapshot 기능을 검토한다. endpoint·region·bucket·folder와 로컬/원격 보존 옵션을 고정 버전에 맞춰 검증한다. |
| PVC/local-path·앱 DB | 데이터 종류에 맞는 파일 백업 또는 DB-native backup을 별도로 생성하고 Wasabi에 전송한다. datastore snapshot이 PVC 내용을 포함한다고 가정하지 않는다. |
| token·암호화 키·복구 메타데이터 | 백업 시점의 K3s token과 필요한 키를 복구할 수 있게 Doppler의 보호된 보관 방식과 연결한다. Wasabi 사본에는 비밀값 대신 복구 참조를 기록하고, 키 사본이 필요하면 별도 암호화·접근 통제를 적용한다. |

Wasabi를 쓰기 위해 SQLite를 etcd로 전환하지 않는다. K3s는 etcd snapshot에 대해 S3 호환 저장소 업로드·복원을 지원하며 SQLite나 앱 데이터는 다른 백업 절차가 필요하다. [K3s S3 snapshot](https://docs.k3s.io/cli/etcd-snapshot#s3-compatible-object-store-support)

호스트 백업 작업·스케줄은 Git의 Ansible 원본에서 관리한다. Kubernetes 백업 Job/CronJob·연동 도구를 채택한다면 선언은 Git과 Argo CD가 관리한다. 스케줄러를 중복 구성하지 않고 전송 도구·ARM64 이미지·재시도·동시 실행 정책은 실제 구현 때 확정한다. 이번 선택만으로 특정 백업 도구를 설치하지 않는다.

## 자격 증명과 데이터 보호

- Wasabi access key·secret key 및 백업 도구가 요구하는 암호화 비밀번호는 [Doppler](doppler.md)에서 필요한 실행 환경으로만 전달한다. 명령 인자·Git·로그·Terraform outputs에 값을 넣지 않는다. 백업 계정은 지정 bucket/prefix와 실제 전송·검증에 필요한 권한으로 제한하고 bucket 관리자 권한을 기본 부여하지 않는다.
- K3s의 S3 config Secret을 사용한다면 Doppler 연동이 생성한 Secret을 참조한다. 실제 버전의 옵션 우선순위를 확인하며 다른 S3 flags와 섞어 Secret이 무시되지 않게 한다. 클러스터 API가 내려간 복원 시 그 Secret을 읽을 수 없으므로 클러스터 밖의 Doppler 인증·보호된 다운로드 경로를 준비한다.
- 백업은 Kubernetes Secret·앱 개인정보를 포함할 수 있다. 전송 TLS, 저장 시 암호화와 필요 시 클라이언트 측 암호화를 검토하고 복호화 키는 동일 버킷의 유일한 사본으로 두지 않는다. 압축은 암호화가 아니다. 원본·임시 archive·다운로드 복원 파일도 제한된 권한과 명시적 정리 절차를 적용한다.

## 보존·삭제·실패 정책

로컬 보존, 원격 보존, bucket lifecycle·versioning·Object Lock을 함께 검토한다. 백업 도구의 prune과 보존 잠금이 충돌할 때 잠금을 해제하거나 광범위한 삭제 권한으로 우회하지 않는다. Object Lock·보존 기간 변경은 삭제 가능성과 복구 운영에 영향을 주므로 임의 활성화하지 않는다. [Wasabi 불변 보관](https://docs.wasabi.com/docs/en/immutability-compliance-and-object-locking)

Wasabi의 최소 저장 기간 과금은 실제 보존 잠금과 다르다. 짧은 주기로 삭제·덮어쓰기해도 과금이 남을 수 있으므로 계정 계약과 최소 저장 기간을 확인한 뒤 lifecycle·prune 정책을 정한다. 특정 보존 일수를 모든 계정의 무료 삭제 기준으로 간주하지 않는다. [최소 저장 기간 정책](https://docs.wasabi.com/docs/how-does-wasabis-minimum-storage-duration-policy-work)

전송 실패 시 성공 처리하거나 마지막 정상 사본을 삭제하지 않는다. 중복 실행·실패 재시도는 제한하고 로컬 용량 부족과 원격 백업 지연을 알린다. 새 사본의 무결성이 확인되기 전 오래된 유일한 정상 사본을 정리하지 않는다. 접속 시험을 위해 기존 데이터를 덮어쓰지 않으며 테스트 객체 생성·삭제도 승인된 prefix와 범위에서만 수행한다.

## 완료 검증과 복구

보고할 항목은 대상·datastore/도구 버전, 데이터 시점·백업 시각, bucket/prefix·object key와 필요 시 version ID, 크기·도구 검증 checksum, 전송 결과, token/키 복구 참조 확인, 복구 시험 여부다. S3 ETag를 모든 객체의 MD5로 단정하지 않는다.

Wasabi에서 사본을 다시 읽어 무결성·복호화 가능성을 확인하고 격리 환경에서 [복원 절차](maintenance.md)를 시험한다. 객체 목록에 보인다는 사실이나 upload 명령 성공만으로 복구 가능성을 보장하지 않는다. 앱 데이터 시점·Git revision·Doppler 값 이력과 Argo CD 재조정 순서를 맞춘다. 원격 전송·다운로드·실제 복원 중 무엇을 수행하지 않았는지 구분해 보고한다.

문서 확인일: 2026-09-07. 이 지침 반영 자체는 Wasabi 연결·버킷 생성·업로드·삭제·복원 작업이 아니다.
