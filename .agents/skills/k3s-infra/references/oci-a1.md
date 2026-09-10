# OCI Ampere A1 · ARM64

## 대상과 자원

사용자가 선택한 대상은 OCI Ampere A1 인스턴스에 직접 운영하는 K3s + Istio이며, **인스턴스는 Terraform으로 관리한다**. OKE 관리형 클러스터로 간주하지 않는다. 기존 Terraform 구성과 state를 확인하고 [Terraform 운영](terraform.md)에 따라 확장하거나 기존 인스턴스를 편입한다.

현재 사용자 지정 구성은 **A1 1대, 4 OCPU·24GB RAM**이다. 이 값을 초기 설계에 사용하고 실제 적용 전 inventory와 대조한다. 향후 A1 증설은 [노드 확장](scaling.md)을 따른다. 실제 shape(예: VM.Standard.A1.Flex), ARM64 OS 이미지, 리전·AD/FD, boot/block volume과 네트워크를 확인한다. OS 배포판, 무료 등급 여부, 추가 노드 사양은 임의로 확정하지 않는다. A1 Flex의 자원은 가변이므로 실제 할당값에서 K3s·Istio·앱·시스템 여유를 함께 산정한다. 생성 요청 시 가용 용량과 tenancy 제한을 확인하고 다른 아키텍처로 자동 대체하지 않는다. [OCI Arm-Based Compute](https://docs.oracle.com/en-us/iaas/Content/Compute/References/arm.htm)

## ARM64 배포 확인

확인된 Linux 호스트의 `uname -m`은 aarch64, Kubernetes node의 `.status.nodeInfo.architecture`는 arm64인지 확인한다. SSH 사용자명과 패키지 관리자는 선택된 OS에서 확인한다. ARM이라는 이유로 Raspberry Pi 전용 커널 패키지나 부팅 설정을 적용하지 않는다. [K3s requirements](https://docs.k3s.io/installation/requirements)

K3s 서버 바이너리와 노드용 도구는 Linux ARM64 릴리스를 선택한다. 로컬 CLI는 클라이언트의 OS/아키텍처에 맞춘다. 차트 이름이나 앱의 ARM 지원 홍보만으로 충분하다고 판단하지 않고 **배포할 정확한 tag/digest**를 확인한다.

registry manifest/index를 `docker buildx imagetools inspect` 또는 사용 가능한 registry 검사 도구로 조회하여 `linux/arm64` 이미지를 확인한다. multi-platform index digest와 amd64 전용 child digest를 구분한다. 앱뿐 아니라 initContainer, Job/CronJob, Helm hook, Istio·CNI/CSI·관측 구성요소도 포함한다. [Docker image inspection](https://docs.docker.com/reference/cli/docker/buildx/imagetools/inspect/)

자체 빌드는 `linux/arm64` 또는 필요한 multi-platform 출력을 생성하고 네이티브 모듈·빌드 중 복사한 실행 파일까지 ARM64인지 확인한다. amd64 전용 이미지는 호환 버전·대체 이미지·재빌드를 검토한다. 에뮬레이션을 운영 기본값으로 추가하지 않는다. 다른 아키텍처의 노드가 실제로 섞여 있을 때만 필요한 scheduling 제약을 검토한다.

## OCI 네트워크

VCN/subnet CIDR, route table, 인터넷·NAT·service gateway, public/private IP, NSG·security list와 OS 방화벽을 함께 확인한다. 네트워크 허용 여부는 OCI 규칙의 합성과 호스트 규칙까지 추적하며 NSG 하나만 보고 연결 가능성을 단정하지 않는다. Pod/Service CIDR은 VCN·VPN 등 연결망과 겹치지 않게 확인한다. [OCI security rules](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securityrules.htm)

관리 SSH/API는 허용된 관리 경로에서만 접근하게 한다. K3s API 6443/TCP, embedded etcd 사용 시 서버 간 2379–2380/TCP, 선택된 CNI·kubelet·Istio의 통신은 실제 토폴로지와 공식 포트 요구사항에 맞춰 제한한다. Flannel VXLAN을 쓸 때 8472/UDP는 노드 간 내부 통신으로 제한하고 인터넷에 노출하지 않는다. [K3s networking requirements](https://docs.k3s.io/installation/requirements#networking)

외부 트래픽은 Istio gateway까지의 실제 경로(OCI LB/NLB, ServiceLB 또는 별도 경로), listener/backend/health check, NSG와 포트 매핑을 확인한다. Compute 위의 자체 K3s에서 `Service type=LoadBalancer`만으로 OCI LB가 생성된다고 가정하지 않는다. OCI CCM을 도입한다면 설치 버전·IAM·기존 K3s CCM 충돌을 검토한다. 필요 없는 NodePort 범위 전체나 Istio 관리 포트를 공개하지 않는다.

## 볼륨과 복구

boot volume, 추가 block volume, mount/UUID, K3s data-dir와 local-path PV가 실제 어느 장치에 저장되는지 기록한다. 재부팅 뒤 mount가 복구되는지, 노드/볼륨 종료 시 보존 설정, 백업 위치와 복원 대상을 확인한다. 장치명만으로 format/mount 대상을 결정하지 않는다.

OCI CSI가 설치되어 있다고 가정하지 않는다. 도입 시 자체 K3s와 ARM64 지원, IAM·attachment·topology·StorageClass 조건을 확인한다. OCI 볼륨 백업의 범위·일관성·생성 시각과 애플리케이션 정합성을 검증한다. 볼륨 백업 하나를 datastore·server token·모든 PVC의 완전한 복구 수단이라고 가정하지 말고 [기존 백업 절차](maintenance.md)를 함께 적용한다. [OCI Block Volume Backups](https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumebackups.htm)

문서 확인일: 2026-09-07. 이 환경 지정만으로 OCI 리소스 생성이나 기존 클러스터 변경을 실행하지 않는다.
