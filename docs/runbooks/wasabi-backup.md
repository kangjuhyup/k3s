# Wasabi 백업 설정

현재 `ansible/inventories/oci-a1/settings.json`의 `backup.enabled`는 `false`다.
이 상태에서는 로컬 자동 etcd 스냅샷과 Wasabi 업로드가 모두 꺼진다.
접속 키를 서버에 설치하지 않으며 기존 스냅샷·버킷 객체를 삭제하지 않는다.
`.env`는 현재 사용자가 지정한 임시 주입 원본이며 Doppler 연동은 아직 미구성이다.

2026-09-10 `0eb7688` 적용 완료: 자동 스냅샷 비활성·S3 비활성·서버에
Wasabi 키 파일 없음 확인. 재실행은 `changed=0`, `failed=0`이며
etcd/API/시스템 Pod/DNS 정상, 회귀 테스트 28개 통과.
실제 Wasabi 업로드·재다운로드·복원은 실행하지 않았다.

## 나중에 활성화

먼저 버킷/prefix 권한, 백업 시점 server token의 클러스터 외부 보관,
최소 저장 기간 과금·Object Lock·보존 정책을 확인한다. etcd 스냅샷은 PVC 데이터를
포함하지 않는다. 실행 전 원격 보존 삭제 범위도 검토한다.

`backup`을 아래 구조로 바꾸되 값은 실제 정책으로 확정한다. 아래는 예시이며
현재 설정에 적용된 주기·경로·보존 정책이 아니다. 보존값의 단위는 **일이 아니라 개수**다.
cron 시간대는 서버 시간대다.

```json
{
  "enabled": true,
  "endpoint": "s3.ap-northeast-1.wasabisys.com",
  "region": "ap-northeast-1",
  "bucket": "replace-with-reviewed-bucket",
  "folder": "k3s/reviewed-cluster/etcd",
  "schedule": "0 0,6,12,18 * * *",
  "local_retention": 28,
  "remote_retention": 360
}
```

비밀값은 이 JSON에 넣지 않는다. `WASABI_ACCESS_KEY_ID`,
`WASABI_SECRET_ACCESS_KEY`를 Ansible 프로세스에 주입한다.
활성화한 경우에만 서버 root 전용 `/etc/rancher/k3s/wasabi.env`로 전달된다.
`.env`의 bucket/region/endpoint 값은 검토한 비밀값 없는 설정과 일치시킨다.

inventory를 다시 생성한 후 `ansible/`에서 실행한다.

```sh
../.local/os-cleanup-venv/bin/ansible-playbook \
  -i ../.local/ansible/oci-a1/hosts.json playbooks/configure-backup.yml \
  -e '{"previous_backup":{"enabled":false}}'
```

`previous_backup`은 실제 변경 전 정책이다. 최초 정책 도입 때만 생략한다.
이미 원하는 상태이면 재시작하지 않는다. 변경 시 한 서버씩 재시작하므로
단일 컨트롤플레인의 API 중단 시간을 고려한다. 변경 도중 실패하면 원인을
확인하고 복구하며, 완료 마커나 데이터 파일을 임의 삭제하지 않는다.

다시 끌 때는 이전 활성 정책을 `previous_backup`으로 전달하고 원하는 설정을
`{"enabled":false}`로 바꾼다. 기존 키 파일과 스냅샷은 삭제하지 않지만
서비스의 credential 파일 참조와 S3 업로드는 해제된다.

활성화 후에는 새 스냅샷 생성·Wasabi 업로드·재다운로드 checksum 확인과
격리 복원 시험을 별도로 수행한다. 비활성 구성 검증을 실제 백업 성공으로
간주하지 않는다. [K3s 공식 스냅샷 문서](https://docs.k3s.io/cli/etcd-snapshot)
