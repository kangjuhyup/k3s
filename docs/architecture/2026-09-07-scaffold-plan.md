# Infrastructure Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for future execution of this plan. This initial documentation-only scaffold is implemented in the user-approved current directory; no worktree move or deployment is included.

**Goal:** 승인된 인프라 저장소 디렉터리 골격과 안전한 안내 파일을 생성한다.

**Architecture:** Terraform·Ansible·GitOps를 역할별로 분리한다. 공통 모듈/역할과 `oci-a1` 환경 연결을 분리하고, 환경변수·비밀값은 Doppler를 원본으로 유지한다.

**Tech Stack:** Markdown, Git ignore rules; validation with local Ruby and Git only.

**Spec:** [repository-layout.md](repository-layout.md)

## Global Constraints

- OCI A1 ARM64 1대, 4 OCPU·24GB RAM; 향후 agent 확장.
- Terraform = OCI, Ansible = K3s/호스트/bootstrap, Argo CD = Kubernetes GitOps, Doppler = 환경변수/비밀값.
- 기존 스킬 보존. 계정·IP·버전·토큰을 추측하지 않는다.
- 문서·디렉터리·제외 규칙만 생성한다. 설치·인증·apply·sync·commit·push는 이번 범위가 아니다.

## Task 1: 역할별 골격 생성과 검증

**Files:** Create `.gitignore`, `README.md`, spec에 열거한 각 leaf 디렉터리의 `README.md`, `docs/runbooks/README.md`. 설계 문서는 이 계획의 기준이며 중복된 배포 절차를 새로 작성하지 않는다.

**Interfaces:** 실제 환경 입력은 받지 않는다. 후속 구현자를 위한 경로·소유권·생성 파일 위치와 기존 스킬 참조를 제공한다.

- [x] 생성 전 검사: 승인한 경로가 없는 상태를 로컬 검사로 확인한다.
- [x] 골격 생성: 각 leaf README에 담당 범위·입출력 또는 작성할 설정·현재 미구현 상태를 적는다. 루트 README에서 전체 구조와 시작 순서를 연결한다.
- [x] 제외 규칙: `.env`, Terraform state/plan·tfvars, kubeconfig·개인키, `.local/` 및 도구 캐시를 제외한다. lockfile과 `.example` 파일, GitOps manifest는 유지한다.
- [x] 검증: 승인한 경로 존재, 전체 Markdown 상대 링크·공백, ignore 양성/음성 사례, 기존 스킬 무변경을 확인한다.
- [x] 완료 보고: 골격만 생성했으며 실행 설정·배포 검증은 미수행임을 명시한다.

검증 시 파일 내용을 공개하지 않고 오류 경로만 출력한다. `git check-ignore --no-index --quiet <path>`로 존재하지 않는 합성 경로도 검사할 수 있으므로 테스트용 비밀 파일을 만들지 않는다. ignore 검증은 이름 규칙 검증이지 비밀값 탐지나 접근 통제 검증이 아니다.

## 검증 결과

2026-09-07 로컬 검사에서 필수 경로 18개, Markdown 29개와 상대 링크 98개, 공백·개행 검사가 통과했다. Git ignore는 제외 대상 31개와 유지 대상 13개를 실제 파일 생성 없이 검사했다. 기존 스킬 12개 파일의 SHA-256이 변경 전과 같았다. Terraform·Ansible·Kubernetes·Doppler 실행 및 commit/push는 수행하지 않았다.
