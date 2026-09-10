# 환경별 값과 Git 선언 분리

IP·OCI 리소스 ID·배치·이름·계정 이메일은 사용자 지정 `.env`에서 주입한다.
추후 Doppler로 옮겨도 동일한 환경변수 이름을 사용한다. `.env.example`은 새 입력
이름만 제공한다. 기존 `.env`를 예제로 덮어쓰지 않는다. Git 이력은 아직 정리하지 않았다.

Git의 `ansible/inventories/oci-a1/settings.json`과
`terraform/environments/oci-a1/nodes.inputs.json`에는 구조와 `{"$env":"이름"}`
참조를 저장한다. JSON 타입이 필요한 목록은 `{"$env_json":"A1_NSG_IDS_JSON"}`로
참조한다. 누락·빈 값·잘못된 JSON은 실패하며 값을 로그에 표시하지 않는다.
CIDR·버전·사양 등 일반 설계값은 Git에 유지한다.

OCI 자동 태그 이메일은 삭제 시 실제 태그 변경을 유발할 수 있으므로
`A1_CREATED_BY`로 이동하여 기존 값을 보존한다.

## 생성 및 검증

저장소 루트에서 신뢰하는 `.env`만 읽는다. 출력 디렉터리는 기존 `.local`을 사용한다.
생성 파일은 `0600`이며 Git에서 제외된다.

```sh
set -a
source .env
set +a
.local/os-cleanup-venv/bin/python scripts/k3s_inventory.py \
  --input ansible/inventories/oci-a1/settings.json \
  --output .local/ansible/oci-a1/hosts.json --write
.local/os-cleanup-venv/bin/python scripts/k3s_inventory.py \
  --input terraform/environments/oci-a1/nodes.inputs.json --format json \
  --output .local/terraform/oci-a1/nodes.tfvars.json --write
.local/bin/terraform -chdir=terraform/environments/oci-a1 plan \
  -input=false -detailed-exitcode \
  -var-file=../../../.local/terraform/oci-a1/nodes.tfvars.json \
  -var-file=../../../.local/terraform/oci-a1/metadata.tfvars.json
```

`--write`를 빼면 기존 생성물과 비교만 한다. Terraform apply는 별도 요청 시에만 한다.
Argo CD 준비 등 원본 설정을 읽는 로컬 도구에도 같은 환경변수를 주입한다.
생성물·state·plan 로그를 공개하거나 `git add -f`로 추가하지 않는다.
reset/cleanup은 별도 승인과 명시적 환경 입력을 요구하며 이 작업에서 실행하지 않는다.

2026-09-10 검증: 생성 inventory와 Terraform 입력은 분리 전과 동일하다.
기존 state를 사용하는 실제 Terraform plan은 exit 0(변경 없음), 기본 회귀 테스트
30개와 관련 Ansible 구문 검증이 통과했다. `.env`·생성물은 `0600`이며,
현재 업로드 대상에서 이동한 실제 값은 발견되지 않았다. 과거 Git 이력은 별도다.
