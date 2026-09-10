# Argo CD Account Configuration Implementation Plan

**Goal:** 개인 계정과 최소 권한, 검증 후 admin 비활성화 정책을 인증 없는 코드로 준비한다.

**Spec:** 사용자가 승인한 [계정 운영 정책](../runbooks/argocd-accounts.md). 실제 계정명은 별도로 확인하며 이번 범위는 코드 준비다.

**Architecture:** 비밀값 없는 `accounts.json`을 Python 표준 라이브러리 도구가 검증하여 공식 argo-cd chart용 `accounts.values.json`을 생성한다. 생성물도 Git 검토 대상이며 단독 Kubernetes manifest로 적용하지 않는다. 기존 Argo CD 설치 Application이 향후 이 values를 소비한다. 별도의 ConfigMap 소유자를 만들지 않는다.

**Tech Stack:** Python 3.9+ 표준 라이브러리, JSON, argo-cd Helm values, unittest.

## 계약과 안전 경계

- `phase`: `bootstrap` 또는 `managed`. 기본은 bootstrap이며 `accounts`는 빈 배열이다.
- 계정 입력: `name`, `enabled`, `role`, `projects`. 역할은 `developer`/`platform-admin`이며 개발자는 지정 프로젝트의 applications/projects `get`만 허용한다.
- 사람 계정 capability는 `login`만 생성한다. disabled 계정은 정의를 남기되 RBAC 부여는 제외한다.
- `cutover.verified_admin`은 활성 개인 관리자 계정명이어야 하고 `cutover.recovery_verified`는 true여야 managed 설정을 생성한다. 이는 운영자의 검증 기록이지 로그인 자동 검증이나 적용 승인이 아니다.
- 알 수 없는 필드, 중복 JSON 키·계정, 예약 이름 admin, RBAC wildcard/CSV 주입, 잘못된 bool/role/project와 cutover는 거부한다. 오류에는 입력값을 출력하지 않는다.
- 기본 RBAC는 권한 없는 `role:authenticated`, 익명 접근은 비활성화한다. 일반 개발자에게 전역 readonly/admin·sync·override·exec·삭제 권한을 주지 않는다.
- 비밀번호·해시·토큰·Secret 생성/주입, 실제 chart 설치, 계정 발급, Kubernetes/Doppler 접근과 commit/push는 범위 밖이다.

## 구현 및 검증

- [x] `scripts/tests/test_argocd_accounts.py`에 순수 렌더링·입력 거부·CLI 검증/쓰기 테스트를 먼저 작성하고 미구현 실패를 확인한다.
- [x] `scripts/argocd_accounts.py`의 `render_values(config)`와 CLI를 구현한다. CLI는 기본 read-only 비교, 명시적 `--write`일 때만 생성 파일을 갱신한다.
- [x] `gitops/platform/argocd/accounts.json`은 bootstrap·빈 계정으로 작성하고 `accounts.values.json`을 생성한다. `.example`에는 비활성 합성 계정의 입력 형식만 둔다.
- [x] `rtk proxy python3 -m unittest discover -s scripts/tests -v`와 생성물 일치 검사를 실행한다. 가능한 경우 공식 도구의 렌더링/RBAC 검증을 추가한다.
- [x] README/runbook을 갱신하고 독립 코드 리뷰 및 문서 링크 검증 후 준비 범위와 미확정 입력을 보고한다.

순수 렌더링의 기준 예: bootstrap 빈 목록 → `configs.cm.admin.enabled`는 문자열 `true`, managed 검증 기록 없음 → `ValueError`. `render_values`가 받는 JSON에는 비밀값을 넣지 않는다.

## 검증 기록 (2026-09-08)

- 미구현 상태에서 단위 테스트 실패를 확인한 뒤 구현했고, 단위/CLI 10개와 선택적 공식 도구 2개를 합한 12개 테스트가 통과했다.
- Argo CD CLI v3.5.2로 합성 계정의 RBAC 허용/거부 12개 사례를 확인했다. Helm v4.2.4와 공식 argo-cd chart 10.8.2로 bootstrap/managed ConfigMap을 렌더링했다. 운영 설치 버전 지정이나 실제 로그인 검증은 아니다.
- 공식 도구는 임시 디렉터리에만 다운로드했고 CLI/Helm 바이너리 배포 체크섬을 확인했다. 테스트는 임시 합성 kubeconfig와 로컬 policy 파일만 사용한다.
- 생성기와 단위 테스트는 독립 읽기 전용 코드 리뷰를 받았다. 실제 계정 목록은 비어 있으며 담당자·프로젝트와 비밀값 주입 경로는 추후 확정한다.
