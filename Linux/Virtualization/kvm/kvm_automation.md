# Автоматизация KVM: Ansible, Terraform, Packer

В данном файле описывается управление KVM-инфраструктурой как кодом (IaC) с помощью Ansible, Terraform и Packer. Базовые сценарии управления ВМ через virsh представлены в [Управление виртуальными машинами](./management.md).

## Определения

**Ansible** — инструмент автоматизации конфигураций и оркестрации. В контексте KVM используется для управления гипервизорами, развертывания ВМ, настройки сети и хранилищ через модули `community.general` и `community.libvirt`.

**Terraform** — инструмент declarative infrastructure management. Провайдер `dmacvicar/libvirt` позволяет описывать ВМ, сети, хранилища и пулы в YAML/HCL и применять изменения через `terraform apply`.

**Packer** — инструмент от HashiCorp для автоматизированного создания golden images. Поддерживает builder `libvirt` для создания qcow2/raw образов с предустановленной ОС, пакетами и конфигурацией.

**Cloud-init** — стандарт для первичной настройки ВМ при первом запуске: hostname, SSH-ключи, пакеты, скрипты. Используется для идемпотентного развертывания без ручного вмешательства.

**Golden Image (Шаблон)** — предустановленный образ ОС с базовой конфигурацией, используемый как источник для быстрого создания копий ВМ.

**Immutability (Неизменяемость)** — принцип: вместо изменения работающих ВМ пересоздавайте их из обновленного шаблона. Снижает конфигурационный дрейф.

## Базовые концепции

### Модуль community.libvirt для Ansible

Ansible управляет KVM-хостами через коллекцию `community.libvirt`, предоставляющую модули для доменов, сетей, пулов и томов.

**Основные модули:**
- `community.libvirt.virt` — управление состоянием ВМ (start, stop, suspend, destroy, undefine).
- `community.libvirt.virt_domain` — создание и настройка ВМ с полным контролем конфигурации.
- `community.libvirt.virt_network` — управление виртуальными сетями libvirt.
- `community.libvirt.virt_pool` — управление пулами хранения.
- `community.libvirt.virt_volume` — создание и удаление томов в пулах.
- `community.general virt_net` — модуль для управления сетями (устаревший, используйте `community.libvirt`).

**Установка коллекции:**
```bash
ansible-galaxy collection install community.libvirt
ansible-galaxy collection install community.general
```

**inventory.ini:**
```ini
[hypervisors]
kvm-host-01 ansible_host=192.168.1.10
kvm-host-02 ansible_host=192.168.1.11

[hypervisors:vars]
ansible_user=admin
ansible_become=yes
ansible_python_interpreter=/usr/bin/python3
```

### Провайдер libvirt для Terraform

Terraform описывает инфраструктуру декларативно: вы определяете желаемое состояние, а Terraform вычисляет и применяет изменения.

**Установка:**
```bash
terraform init
# Провайдер автоматически скачивается из Terraform Registry
```

**provider.tf:**
```hcl
terraform {
  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "~> 0.7"
    }
  }
}

provider "libvirt" {
  uri = "qemu:///system"  # Локальный KVM
  # uri = "qemu+ssh://admin@192.168.1.10/system"  # Удаленный хост
}
```

**Ресурсы провайдера:**
- `libvirt_pool` — пул хранения (dir, logical, logical_LVM).
- `libvirt_volume` — том (qcow2, raw).
- `libvirt_domain` — виртуальная машина.
- `libvirt_network` — виртуальная сеть (NAT, bridge, isolated).

### Packer Builder для libvirt

Packer создает воспроизводимые golden images через автоматизированную установку ОС.

**packer.pkr.hcl:**
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
  default = "20G"
}

source "libvirt" "ubuntu" {
  domain_name = "ubuntu-template"
  vm_name     = "ubuntu-24.04-noble"
  
  disk_size_volumes = [var.disk_size]
  
  iso_urls = [
    "http://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.iso",
    "http://mirror.example.com/ubuntu-24.04.iso"
  ]
  iso_checksum = "sha256:xxxxxxx"
  
  ssh_username = "ubuntu"
  ssh_password = "temp-password"
  ssh_timeout  = "30m"
  
  shutdown_command = "echo 'packer' | sudo -S shutdown -P now"
  
  libvirt_uri = "qemu:///system"
  
  # Cloud-init для автоматической настройки
  cd_label = "cidata"
  cd_files = ["user-data", "meta-data"]
}

build {
  sources = ["source.libvirt.ubuntu"]
  
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo apt-get install -y qemu-guest-agent open-vm-tools",
      "sudo systemctl enable qemu-guest-agent",
      "sudo cloud-init clean --logs --seed",
      "sudo truncate -s 0 /etc/machine-id",
      "sudo rm /var/lib/dbus/machine-id"
    ]
  }
  
  provisioner "ansible" {
    playbook_file = "ansible/provision.yml"
    extra_arguments = [
      "--extra-vars", "role=base"
    ]
  }
}
```

### Cloud-init: первичная настройка ВМ

Cloud-init позволяет автоматизировать настройку ВМ при первом запуске без ручного вмешательства.

**user-data (cloud-init):**
```yaml
#cloud-config
hostname: web-server-01
manage_etc_hosts: true

users:
  - name: devops
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo, libvirt, kvm
    ssh_authorized_keys:
      - ssh-rsa AAAA...

packages:
  - qemu-guest-agent
  - open-vm-tools
  - curl
  - jq

runcmd:
  - systemctl enable --now qemu-guest-agent
  - echo "KVM host: $(hostname)" > /etc/motd

final_message: "Cloud-init finished after $UPTIME seconds"
```

**meta-data:**
```yaml
instance-id: web-server-01
local-hostname: web-server-01
```

## Практические сценарии

### Сценарий 1: Ansible — автоматическое создание ВМ

Полный плейбук для создания ВМ из готового образа через Ansible.

**playbook-create-vm.yml:**
```yaml
---
- name: Deploy KVM Virtual Machines
  hosts: hypervisors
  become: yes
  vars:
    vm_name: web-server-01
    vm_memory: 4096  # MiB
    vm_vcpus: 2
    vm_disk_size: 20  # GiB
    vm_image: /var/lib/libvirt/images/ubuntu-24.04.qcow2
    vm_network: default
    vm_cloud_init: /tmp/user-data.yaml

  tasks:
    - name: Ensure libvirt is running
      ansible.builtin.systemd:
        name: libvirtd
        state: started
        enabled: yes

    - name: Ensure default storage pool is active
      community.libvirt.virt_pool:
        name: default
        state: active
        autostart: yes

    - name: Create VM disk from template
      community.libvirt.virt_volume:
        name: "{{ vm_name }}.qcow2"
        pool: default
        vol: "{{ vm_name }}.qcow2"
        size: "{{ vm_disk_size }}GiB"
        format: qcow2
        state: present

    - name: Clone template disk
      ansible.builtin.command: >
        virt-clone
        --original ubuntu-24.04
        --name {{ vm_name }}
        --file /var/lib/libvirt/images/{{ vm_name }}.qcow2
      register: clone_result
      changed_when: "'successfully cloned' in clone_result.stdout"
      failed_when: clone_result.rc != 0 and 'already exists' not in clone_result.stderr

    - name: Define VM from XML template
      community.libvirt.virt:
        name: "{{ vm_name }}"
        command: define
        xml: "{{ lookup('template', 'vm-template.xml.j2') }}"

    - name: Start VM
      community.libvirt.virt:
        name: "{{ vm_name }}"
        command: start

    - name: Wait for VM to be ready
      ansible.builtin.wait_for:
        timeout: 30

    - name: Get VM IP address
      community.libvirt.virt:
        name: "{{ vm_name }}"
        command: query-vnc
      register: vm_vnc

    - name: Display VNC connection
      ansible.builtin.debug:
        msg: "VNC: {{ vm_vnc.port }}"
```

**templates/vm-template.xml.j2:**
```xml
<domain type='kvm'>
  <name>{{ vm_name }}</name>
  <memory unit='MiB'>{{ vm_memory }}</memory>
  <vcpu placement='static'>{{ vm_vcpus }}</vcpu>
  <os>
    <type arch='x86_64' machine='q35'>hvm</type>
    <boot dev='hd'/>
  </os>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='none' io='native'/>
      <source file='/var/lib/libvirt/images/{{ vm_name }}.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='{{ vm_network_type | default("network") }}'>
      <source network='{{ vm_network }}'/>
      <model type='virtio'/>
    </interface>
    <graphics type='vnc' port='-1' autoport='yes'/>
  </devices>
</domain>
```

**Запуск:**
```bash
ansible-playbook -i inventory.ini playbook-create-vm.yml
```

### Сценарий 2: Ansible — управление состоянием ВМ

Управление 生命周期 ВМ: запуск, остановка, перезагрузка, удаление.

**playbook-manage-vm.yml:**
```yaml
---
- name: Manage KVM Virtual Machines
  hosts: hypervisors
  become: yes
  vars:
    action: start  # start | stop | restart | destroy | undefine
    vm_list:
      - web-server-01
      - web-server-02
      - db-server-01

  tasks:
    - name: "{{ action }} VMs"
      community.libvirt.virt:
        name: "{{ item }}"
        state: "{{ action }}"
      loop: "{{ vm_list }}"
      register: result

    - name: Report results
      ansible.builtin.debug:
        msg: "{{ item.item }}: {{ item.changed }}"
      loop: "{{ result.results }}"
```

**playbook-vm-info.yml:**
```yaml
---
- name: Gather KVM VM Information
  hosts: hypervisors
  become: yes

  tasks:
    - name: List all VMs
      community.libvirt.virt:
        command: list_vms
      register: vm_list

    - name: Display VM list
      ansible.builtin.debug:
        var: vm_list.list_vms

    - name: Get detailed info for each running VM
      community.libvirt.virt:
        name: "{{ item }}"
        command: info
      loop: "{{ vm_list.list_vms }}"
      register: vm_info

    - name: Display VM details
      ansible.builtin.debug:
        msg: >
          {{ item.item }}: 
          state={{ item.info.state }},
          mem={{ item.info.memory }}KB,
          vcpus={{ item.info.vcpus }}
      loop: "{{ vm_info.results }}"
```

### Сценарий 3: Terraform — создание ВМ

Declarative определение ВМ через Terraform с использованием libvirt-провайдера.

**main.tf:**
```hcl
# Пул хранения
resource "libvirt_pool" "default" {
  name = "default"
  type = "dir"
  path = "/var/lib/libvirt/images"
}

# Виртуальная сеть
resource "libvirt_network" "default" {
  name      = "default"
  mode      = "nat"
  domain    = "kvm.local"
  autostart = true

  dhcp {
    enabled = true
  }

  # DNS
  dns {
    enabled = true
  }

  addresses = ["192.168.122.0/24"]
}

# Базовый образ (backing store)
resource "libvirt_volume" "ubuntu_base" {
  name   = "ubuntu-24.04-noble.qcow2"
  pool   = libvirt_pool.default.name
  source = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
  format = "qcow2"
}

# Том для ВМ (clone base)
resource "libvirt_volume" "vm_disk" {
  name           = "web-server-01.qcow2"
  pool           = libvirt_pool.default.name
  base_volume_id = libvirt_volume.ubuntu_base.id
  format         = "qcow2"
  size           = 20 * 1024 * 1024 * 1024  # 20 GB
}

# Cloud-init
resource "libvirt_cloudinit_disk" "cloudinit" {
  name           = "cloudinit.iso"
  pool           = libvirt_pool.default.name
  user_data      = data.template_file.user_data.rendered
  meta_data      = data.template_file.meta_data.rendered
}

data "template_file" "user_data" {
  template = file("${path.module}/cloud-init/user-data")
}

data "template_file" "meta_data" {
  template = file("${path.module}/cloud-init/meta-data")
}

# Виртуальная машина
resource "libvirt_domain" "web_server" {
  name   = "web-server-01"
  memory = 4096
  vcpu   = 2

  cloudinit = libvirt_cloudinit_disk.cloudinit.id

  network_interface {
    network_name = libvirt_network.default.name
  }

  disk {
    volume_id = libvirt_volume.vm_disk.id
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }

  graphics {
    type        = "vnc"
    port        = "-1"
    autoport    = "yes"
    listen_type = "address"
    listen_address = "0.0.0.0"
  }

  # Параметры производительности
  cpu {
    mode = "host-passthrough"
  }

  # Автозапуск
  autostart = true
}

output "vm_ip" {
  value = libvirt_domain.web_server.network_interface.0.addresses.0
}
```

**Запуск:**
```bash
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### Сценарий 4: Terraform — масштабирование ВМ через count

Создание нескольких однотипных ВМ через `count`.

**variables.tf:**
```hcl
variable "worker_count" {
  description = "Number of worker VMs"
  type        = number
  default     = 3
}

variable "worker_memory" {
  description = "Memory per worker in MiB"
  type        = number
  default     = 4096
}

variable "worker_vcpus" {
  description = "vCPUs per worker"
  type        = number
  default     = 2
}
```

**main.tf (workers):**
```hcl
resource "libvirt_volume" "worker" {
  count          = var.worker_count
  name           = "worker-${format("%02d", count.index + 1)}.qcow2"
  pool           = libvirt_pool.default.name
  base_volume_id = libvirt_volume.ubuntu_base.id
  format         = "qcow2"
  size           = 20 * 1024 * 1024 * 1024
}

resource "libvirt_domain" "worker" {
  count  = var.worker_count
  name   = "worker-${format("%02d", count.index + 1)}"
  memory = var.worker_memory
  vcpu   = var.worker_vcpus

  network_interface {
    network_name = libvirt_network.default.name
  }

  disk {
    volume_id = libvirt_volume.worker[count.index].id
  }
}

output "worker_ips" {
  value = libvirt_domain.worker[*].network_interface.0.addresses.0
}
```

### Сценарий 5: Packer — создание golden image

Автоматизированное создание оптимизированного образа для ВМ.

**Создание образа:**
```bash
# Инициализация
packer init packer.pkr.hcl

# Сборка
packer build -var "disk_size=25G" packer.pkr.hcl

# Результат: /var/lib/libvirt/images/ubuntu-24.04-noble.qcow2
```

**Использование образа в Terraform:**
```hcl
resource "libvirt_volume" "vm_disk" {
  name           = "app-server.qcow2"
  pool           = libvirt_pool.default.name
  base_volume_id = libvirt_volume.golden_image.id  # Packer-created image
  format         = "qcow2"
  size           = 30 * 1024 * 1024 * 1024
}
```

### Сценарий 6: Ansible + Packer — CI/CD пайплайн

Интеграция Packer и Ansible в GitLab CI для автоматического обновления golden images.

**.gitlab-ci.yml:**
```yaml
stages:
  - build
  - test
  - publish

variables:
  PACKER_LOG: "1"
  PACKER_CACHE_DIR: "$CI_PROJECT_DIR/.packer_cache"

build-golden-image:
  stage: build
  image: hashicorp/packer:latest
  script:
    - packer init packer.pkr.hcl
    - packer build -color=false -on-error=abort packer.pkr.hcl
  artifacts:
    paths:
      - output-*/
    expire_in: 1 day
  only:
    - main
    - schedules:daily

test-image:
  stage: test
  image: python:3.11
  script:
    - pip install ansible
    - ansible-galaxy collection install community.libvirt community.general
    # Запуск тестовой ВМ из созданного образа
    - ansible-playbook -i inventory.ini test-vm.yml
    # Проверка установленных пакетов
    - ansible all -i inventory.ini -m shell -a "systemctl is-active qemu-guest-agent"
    - ansible all -i inventory.ini -m shell -a "test -f /etc/machine-id && echo OK"
  needs:
    - build-golden-image

publish-image:
  stage: publish
  image: curlimages/curl:latest
  script:
    # Копирование образа в shared storage
    - curl -X PUT -T output-qemu/ubuntu-24.04-noble.qcow2 $NFS_SERVER/golden-images/
    # Обновление манифеста в Git
    - git config user.email "ci@example.com"
    - git config user.name "CI Bot"
    - echo "${CI_COMMIT_SHA}" > golden-image.sha
    - git add golden-image.sha
    - git commit -m "Update golden image: ${CI_COMMIT_SHORT_SHA}"
    - git push https://oauth2:${GIT_TOKEN}@gitlab.example.com/group/project.git
  only:
    - main
  needs:
    - test-image
```

### Сценарий 7: Terraform — управление сетями и хранилищами

Declarative настройка виртуальных сетей и пулов хранилища.

**networks.tf:**
```hcl
# NAT-сеть для development
resource "libvirt_network" "dev" {
  name      = "dev-net"
  mode      = "nat"
  autostart = true
  domain    = "dev.local"
  addresses = ["192.168.100.0/24"]

  dhcp {
    enabled = true
    range {
      start = "192.168.100.100"
      end   = "192.168.100.200"
    }
  }

  dns {
    enabled = true
    hosts {
      hostname = "dev-db-01"
      ip       = "192.168.100.10"
    }
  }
}

# Isolated-сеть для тестирования
resource "libvirt_network" "isolated" {
  name      = "isolated-net"
  mode      = "isolated"
  autostart = true
  addresses = ["10.0.0.0/24"]
}

# Bridge-сеть для production
resource "libvirt_network" "production" {
  name      = "production"
  mode      = "bridge"
  autostart = true
  bridge    = "br0"
}
```

**pools.tf:**
```hcl
resource "libvirt_pool" "fast_ssd" {
  name = "ssd-storage"
  type = "logical"
  
  # LVM-группа для быстрого хранилища
  target {
    path = "/dev/vg_ssd"
  }
}

resource "libvirt_pool" "cold_hdd" {
  name = "hdd-storage"
  type = "dir"
  path = "/mnt/hdd-storage/vms"
}
```

### Сценарий 8: Ansible — миграция ВМ между хостами

Автоматизация live migration ВМ между KVM-хостами.

**playbook-migrate-vm.yml:**
```yaml
---
- name: Migrate KVM VM between hypervisors
  hosts: localhost
  become: yes
  vars:
    vm_name: web-server-01
    source_host: kvm-host-01
    dest_host: kvm-host-02
    migration_type: live  # live | offline

  tasks:
    - name: Check VM is running on source
      ansible.builtin.command: >
        virsh -c qemu+ssh://{{ source_host }}/system domstate {{ vm_name }}
      register: vm_state
      changed_when: false

    - name: Fail if VM not running
      ansible.builtin.fail:
        msg: "VM {{ vm_name }} is not running on {{ source_host }}"
      when: vm_state.stdout != "running"

    - name: Perform live migration
      ansible.builtin.command: >
        virsh -c qemu+ssh://{{ source_host }}/system 
        migrate --live --persistent --verbose 
        {{ vm_name }} qemu+ssh://{{ dest_host }}/system
      register: migration_result
      when: migration_type == "live"

    - name: Perform offline migration
      block:
        - name: Stop VM on source
          community.libvirt.virt:
            name: "{{ vm_name }}"
            uri: "qemu+ssh://{{ source_host }}/system"
            command: shutdown

        - name: Wait for VM to stop
          ansible.builtin.wait_for:
            timeout: 60

        - name: Start migration
          ansible.builtin.command: >
            virsh -c qemu+ssh://{{ source_host }}/system 
            migrate --persistent --verbose 
            {{ vm_name }} qemu+ssh://{{ dest_host }}/system
          register: migration_result
      when: migration_type == "offline"

    - name: Verify VM on destination
      ansible.builtin.command: >
        virsh -c qemu+ssh://{{ dest_host }}/system domstate {{ vm_name }}
      register: dest_state
      changed_when: false

    - name: Report result
      ansible.builtin.debug:
        msg: >
          Migration {{ migration_type }} completed.
          VM {{ vm_name }} is now {{ dest_state.stdout }} on {{ dest_host }}.
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — теория KVM/QEMU/libvirt.
- [Управление виртуальными машинами](./management.md) — virsh, жизненный цикл ВМ.
- [Ansible: Введение](../../Ansible/ansible_introduction.md) — основы Ansible.
- [Ansible Collections](../../Ansible/ansible_collections_deep_dive.md) — создание и управление коллекциями.
- [Terraform: Обзор IaC](../../Concepts/iac_overview.md) — основы Infrastructure as Code.
- [Cloud-init](../vm_images/basic_concepts.md) — автоматизация настройки ВМ.
- [CI/CD: Deployment Strategies](../../CI-CD/Deployment_Strategies/traditional_infrastructure.md) — стратегии развертывания.
