# 사진 등록 Slack 알림 릴리즈

애플리케이션 core/v1.0.8과 PR #158의 main squash 커밋을 사용한다. `release-images.json`의 Account serving image만 해당 커밋과 검증된 manifest digest로 갱신한다. 기존 migrationImages와 완료된 migration Job은 유지한다.

실제 배포 대상은 기존 gaegaeting-dev namespace와 test 공개 서비스다. 최신 인프라 main이 선택한 Doppler gaegaeting/stg의 SLACK_WEBHOOK_URL을 Account runtime Secret에만 전달한다. Webhook URL은 Doppler에서 관리하고 Git과 검증 기록에 복사하지 않는다.

USER/PET 사진이 새로 PENDING으로 저장된 요청만 알림을 보낸다. 알림에는 요청자·대상 ID와 사진 번호를 담으며 사진이나 다운로드 URL은 담지 않는다. 중복 완료 요청은 재전송하지 않는다. 전송 실패는 사진 등록을 되돌리지 않으며 자동 재시도는 없다.

Argo CD의 Git revision, Synced/Healthy, Account Ready와 runtime secret 값 일치를 확인한다. 기존 synthetic QA fixture에서 비어 있는 사진 슬롯만 사용해 USER/PET 업로드·제출·중복 완료와 Slack 성공 로그를 검사한 뒤 새로 만든 사진을 API로 삭제한다. 기존 사진 행을 보존하고 개인별 ID·인증·서명 URL은 기록하지 않는다.

DB/API schema 변경이 없으므로 새 migration은 실행하지 않는다. 문제 발생 시 Git에서 Account image와 이 키 전달 변경을 검증된 이전 선언으로 되돌리고 Argo CD로 반영한다. Git revert는 Doppler 원본 값을 복원하지 않는다.

최종 집계 증거는 `slack-photo-verification.json`에 기록한다.
