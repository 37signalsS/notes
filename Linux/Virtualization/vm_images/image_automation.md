# Образы ВМ — Автоматизация сборки и жизненного цикла

В данном файле описывается автоматизация создания, тестирования и распространения образов виртуальных машин с использованием Packer, Ansible и CI/CD. Базовые концепции образов представлены в [Основные концепции](./basic_concepts.md), а операции с qemu-img — в [Практических сценариях](./practical_scenarios.md).

## Определения

**Packer** — инструмент от HashiCorp для автоматизированного создания воспроизводимых образов ОС. Поддерживает builder `libvirt` для KVM/QEMU, provisioners (shell, ansible, file) и post-processors для конвертации/публикации.

**Golden Image (Золотой образ)** — эталонный шаблон ОС с предустановленным ПО и применёнными политиками безопасности. Используется как база для массового клонирования.

**Image Pipeline** — CI/CD пайплайн для автоматического обновления образов: сборка → тестирование → публикация → версионирование.

**Immutable Infrastructure (Неизменяемая инфраструктура)** — принцип: вместо ручного обновления работающих ВМ пересоздавайте их из нового образа. Снижает конфигурационный дрейф.

**Post-Processor** — этап в Packer, выполняемый после сборки образа: конвертация формата, загрузка в хранилище, публикация в реестр.

**Image Compliance** — проверка образа на соответствие политикам безопасности (CIS Benchmark, собственные правила) до развёртывания в продакшен.

**_serverspec/testinfra** — фреймворки инфраструктурного тестирования, используемые для верификации содержимого и конфигурации образа.

## Базовые концепции

### Архитектура пайплайна сборки образов

Автоматизированный пайплайн состоит из четырёх этапов, каждый из которых добавляет проверки и трансформации.

**Этапы пайплайна:**
```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Build     │───▶│    Test     │───▶│   Publish   │───▶│  Deploy     │
│  (Packer)   │    │ (serverspec)│    │  (Registry) │    │ (Terraform) │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
  - Установка ОС     - Пакеты          - Копирование     - Клонирование
  - Пакеты           - Сервисы         - Хэширование     - cloud-init
  - Конфигурация     - Порты           - Метаданные      - Настройка
  - Оптимизация      - Файловые права  - Подпись
```

**Минимальный пайплайн (3 этапа):**
```yaml
stages:
  - build
  - test
  - publish
```

**Полный пайплайн (5 этапов):**
```yaml
stages:
  - build
  - harden
  - test
  - publish
  - deploy
```

### Структура каталога проекта

Стандартная структура для проекта по сборке образов:

```
image-builder/
├── packer/
│   ├── base.pkr.hcl              # Базовый конфиг Packer
│   ├── variables.pkr.hcl         # Переменные
│   ├── ubuntu-24.04.pkr.hcl      # Специфичный для ОС builder
│   ├── http/
│   │   └── user-data              # Cloud-init preseed/autoinstall
│   └── scripts/
│       ├── base.sh                # Базовая настройка
│       ├── docker.sh              # Установка Docker
│       ├── harden.sh              # Hardenning CIS
│       └── cleanup.sh             # Очистка перед.snapshot
├── ansible/
│   ├── playbooks/
│   │   ├── base.yml               # Базовый плейбук
│   │   └── test.yml               # Тестовый плейбук
│   └── roles/
│       ├── common/
│       ├── docker/
│       └── security/
├── test/
│   ├── serverspec/
│   │   ├── spec_helper.rb
│   │   ├── packages_spec.rb
│   │   └── services_spec.rb
│   └── testinfra/
│       ├── test_packages.py
│       └── test_services.py
├── .gitlab-ci.yml
└── Makefile
```

### Packer: многоэтапная сборка

Packer поддерживает последовательное применение provisioners для разделения логики сборки.

**packer.pkr.hcl (мульти-этап):**
```hcl
packer {
  required_plugins {
    libvirt = {
      version = ">= 0.5.0"
      source  = "github.com/hashicorp/libvirt"
    }
  }
}

variable "disk_size" {
  type    = string
  default = "25G"
}

variable "ssh_username" {
  type    = string
  default = "ubuntu"
}

variable "ssh_password" {
  type      = string
  default   = "packer"
  sensitive = true
}

source "libvirt" "ubuntu" {
  domain_name = "ubuntu-template"
  vm_name     = "ubuntu-24.04-noble"

  disk_size_volumes = [var.disk_size]

  iso_urls = [
    "http://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.iso"
  ]
  iso_checksum = "sha256:xxxxxxxxxxxxxxx"

  ssh_username = var.ssh_username
  ssh_password = var.ssh_password
  ssh_timeout  = "30m"

  shutdown_command = "echo '${var.ssh_password}' | sudo -S shutdown -P now"

  libvirt_uri = "qemu:///system"
  cd_label    = "cidata"
  cd_files    = ["http/user-data", "http/meta-data"]

  # Предварительное выделение метаданных (ускоряет запись)
  disk_cache      = "none"
  disk_io         = "io_uring"
  disk_discard    = "unmap"
  disk_detect_zeroes = "unmap"
}

build {
  sources = ["source.libvirt.ubuntu"]

  # Этап 1: Базовая настройка
  provisioner "shell" {
    script          = "scripts/base.sh"
    execute_command = "echo '${var.ssh_password}' | sudo -S sh -c '{{ .Path }}'"
  }

  # Этап 2: Установка ПО через Ansible
  provisioner "ansible" {
    playbook_file    = "ansible/playbooks/base.yml"
    extra_arguments  = [
      "--extra-vars", "target=base"
    ]
    ansible_ssh_extra_args = ["-o StrictHostKeyChecking=no"]
  }

  # Этап 3: Оптимизация образа
  provisioner "shell" {
    script          = "scripts/cleanup.sh"
    execute_command = "echo '${var.ssh_password}' | sudo -S sh -c '{{ .Path }}'"
  }

  # Этап 4: Cloud-init clean для первого запуска
  provisioner "shell" {
    inline = [
      "sudo cloud-init clean --logs --seed",
      "sudo truncate -s 0 /etc/machine-id",
      "sudo rm -f /var/lib/dbus/machine-id",
      "sudo sync"
    ]
  }
}
```

### Cloud-init: типовые шаблоны для продакшена

**user-data для базового сервера:**
```yaml
#cloud-config
hostname: ${vm_name}
manage_etc_hosts: true
locale: en_US.UTF-8
timezone: UTC

users:
  - name: devops
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo, kvm
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...

  - name: ansible
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...

package_update: true
package_upgrade: true

packages:
  - qemu-guest-agent
  - open-vm-tools
  - curl
  - jq
  - htop
  - net-tools
  - acl

runcmd:
  - systemctl enable --now qemu-guest-agent
  - systemctl enable --now chrony
  - echo "PermitRootLogin prohibit-password" >> /etc/ssh/sshd_config
  - echo "PasswordAuthentication no" >> /etc/ssh/sshd_config
  - systemctl restart sshd

final_message: "Cloud-init finished after $UPTIME seconds"
```

**user-data для сервера приложений (Docker):**
```yaml
#cloud-config
hostname: ${vm_name}
manage_etc_hosts: true

users:
  - name: deploy
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo, docker
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...

package_update: true
package_upgrade: true

packages:
  - qemu-guest-agent
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
  - jq

# Установка Docker
runcmd:
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  - chmod a+r /etc/apt/keyrings/docker.gpg
  - echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
  - apt-get update
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  - systemctl enable --now docker
  - usermod -aG docker deploy
  - systemctl enable --now qemu-guest-agent

final_message: "Docker server ready after $UPTIME seconds"
```

### Тестирование образов

Образы должны тестироваться перед публикацией. Минимальный набор проверок:

**serverspec/test_packages_spec.rb:**
```ruby
require 'spec_helper'

describe 'Package installation' do
  describe package('qemu-guest-agent') do
    it { should be_installed }
  end

  describe package('curl') do
    it { should be_installed }
  end

  describe package('jq') do
    it { should be_installed }
  end
end

describe 'Services' do
  describe service('qemu-guest-agent') do
    it { should be_installed }
    it { should be_enabled }
    it { should be_running }
  end
end

describe 'Files' do
  describe file('/etc/machine-id') do
    it { should be_empty }
  end

  describe file('/etc/ssh/sshd_config') do
    its(:content) { should match(/PasswordAuthentication no/) }
  end
end
```

**testinfra/test_packages.py:**
```python
import testinfra

def test_qemu_guest_agent(host):
    pkg = host.package("qemu-guest-agent")
    assert pkg.is_installed

def test_qemu_guest_agent_running(host):
    svc = host.service("qemu-guest-agent")
    assert svc.is_running
    assert svc.is_enabled

def test_ssh_config(host):
    f = host.file("/etc/ssh/sshd_config")
    assert f.contains("PasswordAuthentication no")

def test_machine_id_empty(host):
    f = host.file("/etc/machine-id")
    assert f.content.strip() == ""
```

### CI/CD пайплайн (GitLab CI)

**.gitlab-ci.yml:**
```yaml
stages:
  - build
  - test
  - publish

variables:
  PACKER_LOG: "1"
  IMAGE_NAME: "ubuntu-24.04-noble"
  IMAGE_VERSION: "${CI_COMMIT_SHORT_SHA}"

build-image:
  stage: build
  image: hashicorp/packer:latest
  before_script:
    - packer init packer/
  script:
    - packer build -color=false -on-error=abort
      -var "disk_size=25G"
      packer/ubuntu-24.04.pkr.hcl
  artifacts:
    paths:
      - output-*/
    expire_in: 1 day
  tags:
    - kvm
    - libvirt

test-image:
  stage: test
  image: python:3.11-slim
  before_script:
    - pip install testinfra pytest
    # Запуск тестовой ВМ из созданного образа
    - virsh define output-ubuntu/*.xml || true
    - virsh start ubuntu-template || true
    - sleep 60  # Ожидание cloud-init
    - TEST_IP=$(virsh domifaddr ubuntu-template | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
  script:
    - pytest test/testinfra/ --host=ssh://ubuntu@$TEST_IP --ssh-identity-file=~/.ssh/id_rsa
  after_script:
    - virsh destroy ubuntu-template || true
    - virsh undefine ubuntu-template --remove-all-storage || true
  needs:
    - build-image

publish-image:
  stage: publish
  image: alpine:latest
  before_script:
    - apk add --no-cache rsync
  script:
    - mkdir -p /images/${IMAGE_NAME}/${IMAGE_VERSION}/
    - rsync -av output-ubuntu/*.qcow2 /images/${IMAGE_NAME}/${IMAGE_VERSION}/
    - echo "${IMAGE_VERSION}" > /images/${IMAGE_NAME}/latest
    - sha256sum /images/${IMAGE_NAME}/${IMAGE_VERSION}/*.qcow2 > /images/${IMAGE_NAME}/${IMAGE_VERSION}/SHA256SUMS
  only:
    - main
    - schedules:daily
  needs:
    - test-image
```

### Версионирование и управление образами

**Стратегия именования:**
```
{os}-{version}-{variant}-{date}-{build_id}.qcow2

Примеры:
ubuntu-24.04-base-20260917-001.qcow2
ubuntu-24.04-docker-20260917-001.qcow2
ubuntu-24.04-base-20260917-001-hardened.qcow2
```

**Манифест образов:**
```json
{
  "name": "ubuntu-24.04-base",
  "version": "20260917-001",
  "base_os": "Ubuntu 24.04 LTS",
  "created": "2026-09-17T10:00:00Z",
  "build_id": "001",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "size_bytes": 2621440000,
  "format": "qcow2",
  "compat": "1.1",
  "features": {
    "cloud_init": true,
    "qemu_guest_agent": true,
    "hardened": false,
    "docker": false
  },
  "packages": [
    "qemu-guest-agent",
    "curl",
    "jq",
    "htop"
  ],
  "tested": true,
  "published": true,
  "deprecated": false
}
```

**Управление версиями через Git:**
```bash
# Тегирование образа
git tag -a v1.0.0-base -m "Base image v1.0.0"
git push origin v1.0.0-base

# Поиск изменений между версиями
git diff v1.0.0-base..v1.1.0-base -- packer/ ansible/
```

### Hardenning образов при сборке

Hardening выполняется на этапе сборки через Ansible roles или shell-скрипты.

**CIS Benchmark checks при сборке:**
```bash
#!/bin/bash
# scripts/harden.sh — CIS Benchmark Level 1 для Ubuntu 24.04

set -euo pipefail

# 1. Файловые права
chmod 600 /etc/shadow
chmod 600 /etc/gshadow
chmod 644 /etc/passwd
chmod 644 /etc/group

# 2. SSH hardening
cat >> /etc/ssh/sshd_config <<'EOF'
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
AllowGroups sudo devops
EOF

# 3. Sysctl hardening
cat > /etc/sysctl.d/99-cis.conf <<'EOF'
net.ipv4.ip_forward = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.tcp_syncookies = 1
kernel.randomize_va_space = 2
fs.suid_dumpable = 0
EOF
sysctl --system

# 4. Настройка аудита
apt-get install -y auditd audispd-plugins
cat > /etc/audit/rules.d/cis.rules <<'EOF'
-w /etc/passwd -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/ssh/sshd_config -p wa -k sshd_config
-a always,exit -F arch=b64 -S execve -C uid!=euid -F euid=0 -k priv_escalation
EOF
systemctl enable auditd

# 5. Удаление ненужных пакетов
apt-get purge -y rsh-client rsh-server telnet telnetd 2>/dev/null || true

echo "CIS Benchmark hardening completed."
```

### Makefile для удобства разработки

```makefile
.PHONY: build test publish clean

PACKER_DIR = packer
ANSIBLE_DIR = ansible
IMAGE_NAME = ubuntu-24.04-noble
VERSION ?= $(shell date +%Y%m%d)-001

init:
	cd $(PACKER_DIR) && packer init .

build:
	cd $(PACKER_DIR) && packer build \
		-var "disk_size=25G" \
		ubuntu-24.04.pkr.hcl

test:
	pytest test/testinfra/ --host=ssh://ubuntu@$(shell virsh domifaddr $(IMAGE_NAME) | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1) \
		--ssh-identity-file=~/.ssh/id_rsa

publish:
	rsync -av output-qemu/*.qcow2 /images/$(IMAGE_NAME)/$(VERSION)/
	sha256sum /images/$(IMAGE_NAME)/$(VERSION)/*.qcow2 > /images/$(IMAGE_NAME)/$(VERSION)/SHA256SUMS

clean:
	virsh destroy $(IMAGE_NAME) || true
	virsh undefine $(IMAGE_NAME) --remove-all-storage || true
	rm -rf $(PACKER_DIR)/output-*
```

## Практические сценарии

### Сценарий 1: Сборка образа из cloud-init с нуля

Создание образа без ISO-файла, используя cloud-image и cloud-init.

```bash
# 1. Скачивание базового cloud-image
wget -q -O ubuntu-base.img \
  https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

# 2. Конвертация в qcow2 с предварительным выделением метаданных
qemu-img convert -p -O qcow2 -o preallocation=metadata \
  ubuntu-base.img ubuntu-24.04-base.qcow2

# 3. Расширение образа
qemu-img resize ubuntu-24.04-base.qcow2 +20G

# 4. Монтирование через qemu-nbd для прямого редактирования
sudo modprobe nbd max_part=8
sudo qemu-nbd --connect=/dev/nbd0 ubuntu-24.04-base.qcow2
sudo partprobe /dev/nbd0
sudo mount /dev/nbd0p1 /mnt

# 5. Добавление cloud-init конфигурации
sudo mkdir -p /mnt/var/lib/cloud/instance/
sudo tee /mnt/etc/cloud/cloud.cfg.d/99-custom.cfg <<'EOF'
hostname: template
manage_etc_hosts: true
users:
  - name: devops
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...
EOF

# 6. Очистка
sudo cloud-init clean --logs --seed --directory /mnt/var/lib/cloud/
sudo truncate -s 0 /mnt/etc/machine-id
sudo rm -f /mnt/var/lib/dbus/machine-id

# 7. Отключение
sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
```

### Сценарий 2: Тестирование образа через виртуальную машину

Запуск созданного образа и верификация его работоспособности.

```bash
#!/bin/bash
# test-image.sh — автоматизированное тестирование образа
set -euo pipefail

IMAGE="$1"
TEST_VM="test-$(date +%s)"
TEST_IP=""

# 1. Создание тестовой ВМ
virt-install \
  --name "$TEST_VM" \
  --memory 2048 --vcpus 2 \
  --disk path="/var/lib/libvirt/images/${TEST_VM}.qcow2,format=qcow2,cache=none" \
  --import \
  --os-variant ubuntu24.04 \
  --network network=default \
  --noautoconsole

# 2. Ожидание IP-адреса (макс. 120 секунд)
for i in $(seq 1 60); do
  TEST_IP=$(virsh domifaddr "$TEST_VM" 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1)
  if [ -n "$TEST_IP" ]; then
    break
  fi
  sleep 2
done

if [ -z "$TEST_IP" ]; then
  echo "FAIL: VM did not get IP address"
  virsh destroy "$TEST_VM" && virsh undefine "$TEST_VM" --remove-all-storage
  exit 1
fi

echo "TEST_VM IP: $TEST_IP"

# 3. Ожидание SSH
for i in $(seq 1 30); do
  if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 ubuntu@"$TEST_IP" "echo OK" 2>/dev/null; then
    break
  fi
  sleep 5
done

# 4. Тесты
echo "=== Test: qemu-guest-agent ==="
ssh ubuntu@"$TEST_IP" "systemctl is-active qemu-guest-agent" | grep -q active

echo "=== Test: machine-id ==="
ssh ubuntu@"$TEST_IP" "test -s /etc/machine-id" && echo "FAIL: machine-id not empty" || echo "OK"

echo "=== Test: SSH config ==="
ssh ubuntu@"$TEST_IP" "grep -q 'PasswordAuthentication no' /etc/ssh/sshd_config"

echo "=== Test: packages ==="
for pkg in curl jq htop; do
  ssh ubuntu@"$TEST_IP" "dpkg -s $pkg" > /dev/null 2>&1
  echo "  $pkg: installed"
done

echo "=== All tests passed ==="

# 5. Очистка
virsh destroy "$TEST_VM"
virsh undefine "$TEST_VM" --remove-all-storage
```

### Сценарий 3: Пакетная сборка нескольких образов

Сборка набора образов для разных ролей из одного проекта.

```bash
#!/bin/bash
# build-all.sh — пакетная сборка образов
set -euo pipefail

ROLES=("base" "docker" "k8s-node" "db-server")
DISK_SIZE="25G"

for role in "${ROLES[@]}"; do
  echo "=== Building: $role ==="
  
  packer build \
    -var "disk_size=$DISK_SIZE" \
    -var "role=$role" \
    -only="libvirt.${role}" \
    packer/ubuntu-24.04.pkr.hcl
  
  # Публикация в пул libvirt
  IMAGE_PATH=$(ls output-${role}/*.qcow2 | head -1)
  virt-install --name "test-${role}" \
    --disk path="$IMAGE_PATH",format=qcow2 \
    --import --noautoconsole --print-xml > /dev/null
  
  echo "=== Completed: $role ==="
done

echo "=== All builds completed ==="
```

### Сценарий 4: Обновление существующего образа без пересборки

Применение изменений к готовому образу через libguestfs.

```bash
# 1. Обновление пакетов внутри образа
virt-customize -a ubuntu-24.04-base.qcow2 \
  --update \
  --install nginx,curl,vim \
  --ssh-inject root:file:/root/.ssh/id_rsa.pub \
  --selinux-relabel

# 2. Применение Ansible playbook к образу
virt-customize -a ubuntu-24.04-base.qcow2 \
  --run-command "ansible-pull -U https://git.example.com/ansible/playbook.yml"

# 3. Оптимизация размера
virt-sparsify --compress ubuntu-24.04-base.qcow2 ubuntu-24.04-base-optimized.qcow2

# 4. Верификация
qemu-img info --output=json ubuntu-24.04-base-optimized.qcow2 | \
  jq '{virtual_size: .virtual-size, actual_size: .actual-size}'
```

### Сценарий 5: Миграция образов между серверами

Копирование образов с проверкой целостности.

```bash
#!/bin/bash
# migrate-image.sh — безопасная миграция образа
set -euo pipefail

SOURCE_HOST="$1"
DEST_HOST="$2"
IMAGE_PATH="$3"

# 1. Проверка размера
echo "Source image info:"
ssh "$SOURCE_HOST" "qemu-img info --output=json $IMAGE_PATH" | \
  jq '{virtual_size: .virtual-size, actual_size: .actual-size}'

# 2. Копирование с rsync и проверкой
rsync -avz --progress \
  "$SOURCE_HOST:$IMAGE_PATH" \
  "$DEST_HOST:$(dirname $IMAGE_PATH)/"

# 3. Верификация на целевом хосте
echo "Verifying on destination..."
ssh "$DEST_HOST" "qemu-img check $IMAGE_PATH"

# 4. Сравнение хэшей
SOURCE_HASH=$(ssh "$SOURCE_HOST" "sha256sum $IMAGE_PATH" | awk '{print $1}')
DEST_HASH=$(ssh "$DEST_HOST" "sha256sum $IMAGE_PATH" | awk '{print $1}')

if [ "$SOURCE_HASH" = "$DEST_HASH" ]; then
  echo "OK: Image integrity verified (SHA256 match)"
else
  echo "FAIL: Hash mismatch!"
  exit 1
fi
```

### Сценарий 6: Откат к предыдущей версии образа

Восстановление предыдущей версии при проблемах с обновлённым образом.

```bash
#!/bin/bash
# rollback-image.sh — откат к предыдущей версии
set -euo pipefail

IMAGE_NAME="ubuntu-24.04-base"
CURRENT_VERSION=$(cat /images/$IMAGE_NAME/latest)
PREVIOUS_VERSION=$(ls -1d /images/$IMAGE_NAME/*/ | sort -V | sed -n '$p' | xargs basename)

echo "Current: $CURRENT_VERSION"
echo "Rollback to: $PREVIOUS_VERSION"

# 1. Проверка существования предыдущей версии
if [ ! -d "/images/$IMAGE_NAME/$PREVIOUS_VERSION" ]; then
  echo "ERROR: Previous version not found"
  exit 1
fi

# 2. Верификация хэшей
cd "/images/$IMAGE_NAME/$PREVIOUS_VERSION"
sha256sum -c SHA256SUMS

# 3. Обновление latest
echo "$PREVIOUS_VERSION" > "/images/$IMAGE_NAME/latest"

# 4. Оповещение
echo "Rollback completed: $CURRENT_VERSION -> $PREVIOUS_VERSION"
```

## Мульти-архитектурные образы (ARM64/AMD64)

Сборка образов для нескольких архитектур — стандарт 2025–2026 годов. Встречаются среды на Apple Silicon (M1–M4), AWS Graviton и классических x86_64 серверах.

### Packer + QEMU: кросс-сборка ARM64

Packer собирает образ через QEMU-эмуляцию целевой архитектуры. Для ARM64 required плагин `qemu` с указанием `guest_os_type` и эмулятора `qemu-system-aarch64`.

**packer-arm64.pkr.hcl:**
```hcl
packer {
  required_plugins {
    qemu = {
      version = ">= 1.0.0"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

variable "arch" {
  type    = string
  default = "aarch64"
}

source "qemu" "ubuntu-arm64" {
  vm_name      = "ubuntu-24.04-arm64"
  accelerator  = "tcg"
  cpus         = 2
  memory       = 2048
  disk_size    = "25G"
  format       = "qcow2"

  iso_urls = [
    "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img"
  ]
  iso_checksum = "sha256:xxxxxxxxxxxxxxx"

  ssh_username = "ubuntu"
  ssh_password = "packer"
  ssh_timeout  = "30m"

  shutdown_command = "echo 'packer' | sudo -S shutdown -P now"

  # Эмуляция ARM64 через TCG
  qemuargs = [
    ["-cpu", "cortex-a72"],
    ["-machine", "virt,gic-version=3"]
  ]

  cd_label    = "cidata"
  cd_files    = ["http/user-data", "http/meta-data"]
}

build {
  sources = ["source.qemu.ubuntu-arm64"]

  provisioner "ansible" {
    playbook_file = "ansible/playbooks/base.yml"
  }

  provisioner "shell" {
    inline = [
      "sudo cloud-init clean --logs --seed",
      "sudo truncate -s 0 /etc/machine-id"
    ]
  }
}
```

**Параллельная сборка нескольких архитектур:**
```bash
#!/bin/bash
# build-multiarch.sh — параллельная сборка AMD64 и ARM64
set -euo pipefail

ARCHS=("amd64" "aarch64")

for arch in "${ARCHS[@]}"; do
  echo "=== Building: $arch ==="
  packer build \
    -var "arch=$arch" \
    -only="qemu.*" \
    "packer/ubuntu-24.04-${arch}.pkr.hcl" &
done

wait
echo "=== All architectures built ==="
```

**Верификация архитектуры образа:**
```bash
# Проверка архитектуры ОС внутри образа (через virt-inspector)
virt-inspector -a ubuntu-24.04-arm64.qcow2 --format=json | \
  jq '.operating_system.arch'
# → "aarch64"

# Или через монтирование
sudo qemu-nbd --connect=/dev/nbd0 ubuntu-24.04-arm64.qcow2
sudo mount /dev/nbd0p1 /mnt
file /mnt/boot/vmlinuz-*
# → Linux kernel ARM64 aarch64 boot Image
sudo umount /mnt && sudo qemu-nbd --disconnect /dev/nbd0
```

### VM-образы vs контейнеры: различия мульти-архитектурной сборки

| Критерий | Docker (buildx) | VM (Packer + QEMU) |
| :--- | :--- | :--- |
| **Метод** | Эмуляция QEMU в контейнере | Эмуляция TCG в QEMU |
| **Скорость** | Быстрая (BuildKit кэш) | Медленная (полная эмуляция) |
| **Рекомендация** | Кросс-компиляция | Нативные раннеры или QEMU |
| **Формат результата** | OCI-индекс (multi-arch manifest) | Отдельные qcow2 файлы |

## Хранение и распространение образов (реестры)

### Типы хранилищ для VM-образов

| Тип | Инструмент | Преимущества | Сценарий |
| :--- | :--- | :--- | :--- |
| **Локальный пул** | libvirt storage pool | Простота, скорость | Одиночный хост |
| **NFS** | nfs-utils | Общее хранилище | Кластер из 2–5 хостов |
| **Ceph RBD** | librbd | Масштабируемость, HA | Кластеры >5 хостов |
| **HTTP-реестр** | Apache/Nginx + SHA256 | Простая дистрибуция | CI/CD, публичные образы |
| **Harbor** | Harbor (OCI) | RBAC, сканирование, webhook | Enterprise-среды |

### Хранение через NFS с versioning

```bash
# 1. Настройка NFS-сервера (хост)
cat >> /etc/exports <<'EOF'
/images  192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
EOF
exportfs -ra

# 2. Монтирование на KVM-хостах
sudo mount -t nfs nfs-server:/images /var/lib/libvirt/images

# 3. Автоматическое монтирование при загрузке
echo "nfs-server:/images /var/lib/libvirt/images nfs defaults,_netdev 0 0" | \
  sudo tee -a /etc/fstab
```

### HTTP-реестр с версионированием

```bash
# Структура каталога
/var/www/images/
├── ubuntu-24.04-base/
│   ├── latest                          # symlink на текущую версию
│   ├── 20260917-001/
│   │   ├── ubuntu-24.04-base.qcow2
│   │   ├── SHA256SUMS
│   │   └── manifest.json
│   └── 20260915-001/
│       ├── ubuntu-24.04-base.qcow2
│       └── SHA256SUMS
└── ubuntu-24.04-docker/
    └── ...

# Загрузка образа с проверкой
VERSION=$(curl -s http://nfs-server/images/ubuntu-24.04-base/latest)
wget "http://nfs-server/images/ubuntu-24.04-base/${VERSION}/ubuntu-24.04-base.qcow2"
sha256sum -c "http://nfs-server/images/ubuntu-24.04-base/${VERSION}/SHA256SUMS"
```

### Хранение в Harbor (OCI-режим)

Harbor поддерживает произвольные OCI-артефакты, включая VM-образы. Преимущества: RBAC, webhooks, сканирование на CVE, immutable tags.

```bash
# Загрузка qcow2 как OCI-артефакт через ORAS
oras push harbor.example.com/vm-images/ubuntu-24.04:latest \
  ubuntu-24.04-base.qcow2:application/vnd.vm.image.v1

# Проверка
oras manifest fetch harbor.example.com/vm-images/ubuntu-24.04:latest | jq .
```

## Стратегии обновления и патчинга образов

### Методы обновления

| Метод | Время простоя | Сложность | Риск | Сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **Rebuild (Packer)** | 0 (неизменяемые) | Средняя | Низкий | Рекомендуется для продакшена |
| **virt-customize** | 0 (офлайн) | Низкая | Средний | Точечные обновления |
| **Ручное обновление** | Высокое | Низкая | Высокий | Только для dev/test |

### Rebuild: полная пересборка (рекомендуется)

```yaml
# .gitlab-ci.yml — автоматический rebuild при обновлении базовой ОС
stages:
  - build
  - test
  - publish

rebuild-base:
  stage: build
  image: hashicorp/packer:latest
  script:
    - packer build -var "timestamp=$(date +%Y%m%d)" packer/ubuntu-24.04.pkr.hcl
  rules:
    # Триггер по расписанию (еженедельно)
    - if: $CI_PIPELINE_SOURCE == "schedule"
    # Ручной запуск
    - when: manual
  artifacts:
    paths:
      - output-ubuntu/
    expire_in: 7 days

test-image:
  stage: test
  needs: [rebuild-base]
  script:
    - ./scripts/test-image.sh output-ubuntu/*.qcow2
  allow_failure: false

publish-image:
  stage: publish
  needs: [test-image]
  only: [main]
  script:
    - VERSION=$(date +%Y%m%d)-${CI_COMMIT_SHORT_SHA}
    - mkdir -p /images/ubuntu-24.04/${VERSION}/
    - cp output-ubuntu/*.qcow2 /images/ubuntu-24.04/${VERSION}/
    - sha256sum /images/ubuntu-24.04/${VERSION}/*.qcow2 > /images/ubuntu-24.04/${VERSION}/SHA256SUMS
    - echo "$VERSION" > /images/ubuntu-24.04/latest
```

### Точечное обновление через virt-customize

```bash
# 1. Копирование текущего образа (бэкап)
cp /images/ubuntu-24.04/current.qcow2 /images/ubuntu-24.04/pre-patch.qcow2

# 2. Применение исправлений
virt-customize -a /images/ubuntu-24.04/current.qcow2 \
  --update \
  --install nginx \
  --run-command "systemctl enable nginx" \
  --selinux-relabel

# 3. Верификация
qemu-img check /images/ubuntu-24.04/current.qcow2

# 4. Тестирование (запуск тестовой ВМ)
virt-install --name test-patch --import \
  --disk path=/images/ubuntu-24.04/current.qcow2,format=qcow2 \
  --os-variant ubuntu24.04 --noautoconsole

# 5. После успешного теста — обновление latest
echo "patched-$(date +%Y%m%d)" > /images/ubuntu-24.04/latest
```

### Cadence обновлений

| Тип обновления | Частота | Метод | Кто владелец |
| :--- | :--- | :--- | :--- |
| **Security patches** | Ежемесячно | Rebuild (Packer) | SRE/Security |
| **Base OS updates** | Еженедельно | Rebuild (Packer) | DevOps |
| **Application updates** | По событию | virt-customize или rebuild | Dev team |
| **Emergency CVE** | Вне графика | virt-customize + rebuild | SRE |

## Жизненный цикл Golden Image (lifecycle)

### Этапы жизненного цикла

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│  Build  │───▶│  Test   │───▶│ Publish │───▶│ Deploy  │───▶│ Retire  │
│ (Packer)│    │(serverspec)│  │(Registry)│   │(Ansible)│    │(удаление)│
└─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
    │              │              │              │              │
    ▼              ▼              ▼              ▼              ▼
 Версия        Тесты         Подпись        Клонирование    Архив/удаление
 Changelog     Pass/Fail     SHA256/cosign  cloud-init      Документация
```

### Владелец и ответственность

| Роль | Ответственность | SLA |
| :--- | :--- | :--- |
| **DevOps/SRE** | Сборка, тестирование, публикация | Обновление в течение 7 дней после CVE |
| **Security** | Сканирование, compliance, подпись | Блокировка CRITICAL CVE в течение 24ч |
| **Dev team** | Запрос на установку ПО, тестирование | Верификация в течение 3 дней |
| **Management** | Утверждение политики устаревания | Ревю квартально |

### Политика устаревания (retention)

```bash
#!/bin/bash
# retention-policy.sh — удаление старых версий образов
set -euo pipefail

IMAGES_DIR="/images"
KEEP_WEEKLY=4    # Хранить 4 последних еженедельных
KEEP_MONTHLY=6   # Хранить 6 последних месячных
RETENTION_DAYS=90

# Удаление еженедельных версий старше $KEEP_WEEKLY
find "$IMAGES_DIR" -maxdepth 2 -mindepth 2 -type d -name "20*" | \
  sort -r | tail -n +$((KEEP_WEEKLY + 1)) | \
  xargs -I {} rm -rf {}

# Удаление файлов старше RETENTION_DAYS
find "$IMAGES_DIR" -name "*.qcow2" -mtime +${RETENTION_DAYS} -delete

echo "Retention policy applied: keep ${KEEP_WEEKLY} weekly, ${KEEP_MONTHLY} monthly"
```

## Дополнительная информация

- [Образы ВМ — Определения](./definitions.md) — глоссарий терминов.
- [Образы ВМ — Основные концепции](./basic_concepts.md) — форматы и стратегии хранилища.
- [Автоматизация KVM: Ansible, Terraform, Packer](../kvm/kvm_automation.md) — управление ВМ через Ansible/Terraform.
- [Деплой образов в продакшен](./production_deployment.md) — развертывание и тюнинг при развёртывании.
- [Конвертация и миграция образов](./vm_image_conversion.md) — конвертация форматов, валидация.
- [Оптимизация и безопасность образов](./vm_image_optimization.md) — размер, подпись, staging.
- [Compliance и сканирование](./vm_image_compliance.md) — политики, SBOM, CIS.
- [Бэкап и DR](./vm_image_backup_dr.md) — RPO/RTO, стратегии восстановления.
