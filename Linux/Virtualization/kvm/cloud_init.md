# Cloud-Init в KVM/libvirt: автоматизация первоначальной настройки ВМ

Данный файл описывает использование cloud-init для автоматизированного развёртывания и настройки виртуальных машин KVM/QEMU. Общие концепции автоматизации образов описаны в [Образы ВМ — Автоматизация](../vm_images/image_automation.md), а шаблоны — в [Образы ВМ — Определения](../vm_images/definitions.md).

## Определения

**Cloud-Init** — стандарт де-факто для первоначальной настройки виртуальных машин и контейнеров при первом запуске. Предоставляет механизм передачи метаданных (hostname, SSH-ключи, сетевые настройки, скрипты) через специальное устройство (NoCloud, Config Drive) или сетевой метадата-сервис (HTTP 169.254.169.254).

**NoCloud (Config Drive)** — datasource cloud-init, передающий метаданные через виртуальный диск (CD-ROM или IDE), смонтированный в гостевую ОС. Используется в KVM/libvirt, так как не требует DHCP-сервера или метадата-сервера.

**User-Data** — YAML- или скриптовый файл, содержащий инструкции для cloud-init: создание пользователей, установка пакетов, запуск скриптов, настройка сети.

**Meta-Data** — YAML-файл с базовыми метаданными ВМ: instance-id, hostname, network-конфигурация.

**Instance-ID** — уникальный идентификатор экземпляра ВМ. Cloud-init использует его для определения, была ли ВМ уже инициализирована. При повторном запуске cloud-init проверяет наличие `/var/lib/cloud/instance/<instance-id>` и пропускает стадии, если directory существует.

**Datasource** — модуль cloud-init, определяющий среду развертывания (NoCloud, EC2, GCE, OpenStack). В KVM/libvirt используется NoCloud.

**Cloud-init Stages** — последовательность выполнения: `generator` → `network` → `config` → `final`. Каждая стадия имеет собственный лог и может быть отключена.

## Базовые концепции

### Архитектура cloud-init в KVM

```
┌─────────────────────────────────────────────────────┐
│  Хост KVM (libvirt)                                 │
│  ├── cloud-init drive (IDE/CD-ROM)                  │
│  │   ├── meta-data (instance-id, hostname)          │
│  │   └── user-data (скрипты, пакеты, пользователи)  │
│  └── Виртуальная машина (QEMU/KVM)                  │
│      └── Гостевая ОС                                 │
│          ├── cloud-init (агент)                      │
│          └── /var/lib/cloud/instance/<id>/           │
└─────────────────────────────────────────────────────┘
```

### Форматы user-data

**Cloud-config (YAML):**
```yaml
#cloud-config
hostname: web-server-01
manage_etc_hosts: true

users:
  - name: deploy
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... deploy@workstation

packages:
  - nginx
  - curl
  - htop

runcmd:
  - systemctl enable --now nginx
  - echo "Hello from cloud-init" > /var/www/html/index.html

write_files:
  - path: /etc/nginx/conf.d/app.conf
    content: |
      server {
        listen 80;
        server_name _;
        root /var/www/html;
      }
    permissions: '0644'
```

**Shell script:**
```bash
#!/bin/bash
# Простой shell script для user-data
apt update && apt upgrade -y
apt install -y nginx
systemctl enable --now nginx
```

### Интеграция с libvirt/virt-install

**Способ 1: virt-install с cloud-init:**
```bash
# Скачивание cloud-image
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img

# Создание ВМ с cloud-init
virt-install \
  --name web-server-01 \
  --memory 2048 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/web-server-01.qcow2,size=20 \
  --cloud-init user-data=./user-data.yaml \
  --import \
  --os-variant ubuntu24.04 \
  --graphics none \
  --network network=bridge-net,model=virtio
```

**Способ 2: Через virt-xml (добавление cloud-init к существующей ВМ):**
```bash
# Добавление cloud-init drive
virsh attach-device web-server-01 /tmp/cloud-init-device.xml --config

# Или через virt-xml
virt-xml web-server-01 --edit --disk source.file=/var/lib/libvirt/images/cloud-init.iso,device=cdrom,target.dev=hdc
```

**Способ 3: Генерация ISO вручную:**
```bash
# Создание директории для метаданных
mkdir -p /tmp/cloud-init/{meta-data,user-data}

# meta-data
cat > /tmp/cloud-init/meta-data/meta-data << 'EOF'
instance-id: web-server-01
local-hostname: web-server-01
EOF

# user-data
cat > /tmp/cloud-init/user-data/user-data << 'EOF'
#cloud-config
hostname: web-server-01
users:
  - name: ubuntu
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... ubuntu@workstation
EOF

# Генерация ISO
mkisofs -output /var/lib/libvirt/images/cloud-init.iso \
  -volid cidata -joliet -rock \
  /tmp/cloud-init/user-data/user-data \
  /tmp/cloud-init/meta-data/meta-data
```

### Проверка состояния cloud-init внутри ВМ

```bash
# Статус выполнения
cloud-init status
# → status: done

# Детальный статус
cloud-init status --long
# → instance-id: web-server-01
# → datasource: NoCloud
# → last_update: Tue Sep 17 12:00:00 2026

# Логи cloud-init
cat /var/log/cloud-init.log
cat /var/log/cloud-init-output.log

# Повторный запуск (сброс состояния)
sudo cloud-init clean --logs --seed
```

### Повторное использование образов (Clone/Template)

При клонировании ВМ с cloud-init необходимо сбросить instance-id:

```bash
# Очистка cloud-init перед клонированием
virsh domclone web-server-01 web-server-02

# Внутри новой ВМ:
sudo cloud-init clean --logs --seed

# Или через XML: изменить instance-id
virsh edit web-server-02
# Внутри <os><initrd> или cloud-init section:
# Изменить instance-id на уникальный
```

## Практические сценарии

### Сценарий 1: Массовое развёртывание серверов

Создание 10 одинаковых веб-серверов с автоматической настройкой:

```bash
#!/bin/bash
# deploy-web-servers.sh — массовое развертывание ВМ
set -euo pipefail

COUNT=${1:-10}
BASE_IMAGE="/var/lib/libvirt/images/ubuntu-22.04.qcow2"
TEMPLATE_XML="/etc/libvirt/qemu/web-template.xml"

for i in $(seq 1 $COUNT); do
  VM_NAME="web-$(printf '%02d' $i)"
  VM_IP="192.168.122.$((10 + i))"
  
  # Клонирование образа
  qemu-img create -f qcow2 -b "$BASE_IMAGE" -F qcow2 \
    "/var/lib/libvirt/images/${VM_NAME}.qcow2"
  
  # Генерация user-data
  cat > "/tmp/user-data-${VM_NAME}.yaml" <<EOF
#cloud-config
hostname: ${VM_NAME}
manage_etc_hosts: true
users:
  - name: deploy
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... deploy@workstation
packages:
  - nginx
  - prometheus-node-exporter
runcmd:
  - systemctl enable --now nginx
  - systemctl enable --now prometheus-node-exporter
EOF

  # Создание cloud-init ISO
  mkisofs -output "/var/lib/libvirt/images/${VM_NAME}-cloud-init.iso" \
    -volid cidata -joliet -rock \
    /tmp/user-data-${VM_NAME}.yaml /tmp/meta-data
  
  # Создание ВМ
  virt-install \
    --name "$VM_NAME" \
    --memory 2048 --vcpus 2 \
    --disk path="/var/lib/libvirt/images/${VM_NAME}.qcow2",format=qcow2 \
    --disk path="/var/lib/libvirt/images/${VM_NAME}-cloud-init.iso",device=cdrom \
    --import --noautoconsole \
    --os-variant ubuntu22.04 \
    --network network=prod-net,model=virtio

  echo "Deployed: $VM_NAME (IP: $VM_IP)"
done
```

### Сценарий 2: Настройка сети через cloud-init (netplan)

```yaml
#cloud-config
# Статическая конфигурация сети (Ubuntu/Debian)
network:
  version: 2
  ethernets:
    eth0:
      addresses:
        - 192.168.122.10/24
      gateway4: 192.168.122.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 1.1.1.1
      routes:
        - to: 10.0.0.0/8
          via: 192.168.122.254
```

### Сценарий 3: Автоматическая установка пакетов и настройка сервисов

```yaml
#cloud-config
package_update: true
package_upgrade: true
packages:
  - nginx
  - postgresql-14
  - redis-server
  - certbot
  - python3-certbot-nginx

write_files:
  - path: /etc/nginx/sites-available/default
    content: |
      server {
          listen 80;
          server_name _;
          location / {
              proxy_pass http://127.0.0.1:3000;
              proxy_set_header Host $host;
              proxy_set_header X-Real-IP $remote_addr;
          }
      }
    permissions: '0644'

runcmd:
  - systemctl enable --now nginx
  - systemctl enable --now postgresql
  - systemctl enable --now redis-server
  - certbot --nginx -d example.com --non-interactive --agree-tos -m admin@example.com
```

### Сценарий 4: Настройка swap через cloud-init

```yaml
#cloud-config
# Включение swap (1 GB)
swap:
  filename: /swapfile
  size: 1g
  maxsize: 2g

# Или через runcmd:
runcmd:
  - fallocate -l 1G /swapfile
  - chmod 600 /swapfile
  - mkswap /swapfile
  - swapon /swapfile
  - echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### Сценарий 5: Cloud-init для CentOS/RHEL

```yaml
#cloud-config
# CentOS/RHEL cloud-init
system_info:
  default_user:
    name: centos
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash

packages:
  - nginx
  - firewalld

runcmd:
  - systemctl enable --now nginx
  - firewall-cmd --permanent --add-service=http
  - firewall-cmd --reload
```

### Сценарий 6: Диагностика проблем cloud-init

```bash
# Проблема: cloud-init не выполняется
# 1. Проверка datasource
sudo cloud-init status --long
# → datasource: None (означает, что cloud-init drive не найден)

# 2. Проверка device в XML
virsh dumpxml web-server-01 | grep -A5 "cloud-init\|cdrom\|ide"
# → Должен быть IDE device с cloud-init ISO

# 3. Проверка логов
sudo cat /var/log/cloud-init.log | grep -i "error\|warn\|no cloud"
# → "No cloud-init data found" — ISO не смонтирован или пуст

# 4. Решение: пересоздать cloud-init drive
sudo cloud-init clean --logs --seed
sudo reboot

# Проблема: hostname не применяется
# Причина: instance-id уже существует
# Решение:
sudo cloud-init clean --logs --seed
sudo reboot
```

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **cloud-init не запускается** | No cloud-init data found | Проверить наличие cloud-init drive в XML, переISO |
| **Hostname не применяется** | Instance-id уже существует | `cloud-init clean --logs --seed` + reboot |
| **SSH-ключи не добавлены** | Ошибка в формате YAML | Проверить user-data на валидность YAML |
| **Пакеты не устанавливаются** | Нет доступа к репозиторию | Проверить DNS, прокси, firewall в guest |
| **Сеть не настраивается** | Netplan конфликтует с cloud-init | Удалить `/etc/netplan/50-cloud-init.yaml` |
| **Повторный запуск cloud-init** | Нет `clean --seed` | Выполнить `cloud-init clean --logs --seed` |

## Дополнительная информация

- [Образы ВМ — Автоматизация](../vm_images/image_automation.md) — Packer, serverspec, CI/CD.
- [Образы ВМ — Определения](../vm_images/definitions.md) — шаблоны, cloud-init drive.
- [Автоматизация KVM](./kvm_automation.md) — Ansible, Terraform, Packer.
- [Управление виртуальными машинами](./management.md) — `virt-install`, `virsh`.
- [Cloud-init: официальная документация](https://cloudinit.readthedocs.io/) — ссылка на документацию.
