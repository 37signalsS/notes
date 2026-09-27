# Автоматизация Proxmox через Ansible

## Определения

**proxmoxer** — Python-библиотека, предоставляющая REST API обертку для Proxmox VE. Используется как бэкенд для Ansible-модулей `community.proxmox`. Поддерживает аутентификацию по паролю, API-токену и OAuth2.

**community.proxmox** — коллекция Ansible-модулей для управления Proxmox VE: создание/удаление VM и LXC, управление хранилищами, сетями, кластером, бэкапами и шаблонами.

**Proxmox Inventory Plugin** — динамический inventory-плагин Ansible, получающий список VM/LXC и узлов кластера напрямую из Proxmox API. Позволяет автоматически группировать ресурсы по узлам, тегам и меткам.

**Callback Plugin (community.proxmox.callback)** — плагин обратного вызова, интегрирующий логи Ansible с Proxmox API для отображения статуса задач в веб-интерфейсе.

## Теоретический блок

### Архитектура интеграции

```
┌──────────────────────┐       HTTPS 8006       ┌──────────────────┐
│   Ansible Control    │◄──────────────────────►│   Proxmox API    │
│   Node               │  API-Token / Password   │   (pveproxy)     │
│                      │                         └──────────────────┘
│  ┌────────────────┐  │                                │
│  │ Inventory      │  │                                │
│  │ (dynamic/static)│  │                                │
│  └────────────────┘  │                                │
│  ┌────────────────┐  │                                │
│  │ Playbooks      │  │                                │
│  │ (community.    │  │                                │
│  │  proxmox)      │  │                                │
│  └────────────────┘  │                                │
└──────────────────────┘                                │
         │                                              │
         ▼                                              ▼
┌──────────────────────────────────────────────────────────┐
│  Proxmox Cluster (node1, node2, node3)                   │
│  VM/LXC management, storage, networking, backups         │
└──────────────────────────────────────────────────────────┘
```

### Два подхода к управлению Proxmox

1. **Через API (community.proxmox)** — модули работают с REST API Proxmox напрямую. Подходит для управления VM/LXC, шаблонами, хранилищами, кластером. Требует установленного `proxmoxer` на control node.

2. **Через SSH (shell/command)** — Ansible подключается по SSH к узлам Proxmox и выполняет CLI-команды (`qm`, `pct`, `pvesm`, `pvecm`). Подходит для настройки хостов, сетей, Ceph, PBS и других операций, недоступных через API.

### Аутентификация

**API-токен (рекомендуется):**
```bash
# Создание токена на стороне Proxmox
pveum useradd automation@pam --comment "Ansible automation"
pveum user token add automation@pam ansible --privsep 0
# → Token ID: automation@pam!ansible
# → Secret: <сохранить в vault>
```

**Через переменные окружения:**
```bash
export PROXMOX_TOKEN="automation@pam!ansible"
export PROXMOX_SECRET="<secret>"
export PROXMOX_HOST="pve1.example.com"
export PROXMOX_VERIFY_SSL="false"
```

**Через Vault:**
```yaml
# group_vars/all/vault.yml
proxmox_api_user: "automation@pam!ansible"
proxmox_api_password: "{{ vault_proxmox_password }}"
```

### Динамический inventory

Proxmox-плагин автоматически получает список всех VM, LXC и узлов:

```yaml
# inventory/proxmox.yml
plugin: community.proxmox.proxmox
url: https://pve1.example.com:8006
user: automation@pam!ansible
password: "{{ vault_proxmox_password }}"
want_proxmox_nodes_enabled: true
want_proxmox_nodes_availabe_only: true
validate_certs: false
compose:
  ansible_host: proxmox_net0_ip | default(proxmox_ip)
  proxmox_status: proxmox_status
keyed_groups:
  - key: proxmox_status
    prefix: status
  - key: proxmox_node
    prefix: node
  - key: proxmox_tags
    separator: "_"
    prefix: tag
  - key: proxmox_type
    prefix: type
```

**Структура inventory после импорта:**
```ini
[status_running]
web-01 ansible_host=10.0.0.10 proxmox_vmid=101 proxmox_node=node1
db-01  ansible_host=10.0.0.11 proxmox_vmid=102 proxmox_node=node1

[status_stopped]
test-01 ansible_host=10.0.0.20 proxmox_vmid=201 proxmox_node=node2

[node_node1]
web-01
db-01

[node_node2]
test-01

[tag_web]
web-01

[tag_database]
db-01
```

### Основные модули community.proxmox

| Модуль | Назначение |
|--------|-----------|
| `community.proxmox.proxmox_vm` | Управление KVM VM (создание, изменение, удаление) |
| `community.proxmox.proxmox_pool_member` | Добавление/удаление ресурсов в пулы |
| `community.proxmox.proxmox_storage_contents_info` | Просмотр содержимого хранилищ |
| `community.proxmox.proxmox_storage_iso` | Загрузка ISO-образов |
| `community.proxmox.proxmox_kvm` | Управление KVM VM (legacy, используется proxmox_vm) |
| `community.proxmox.proxmox_lxc` | Управление LXC контейнерами |
| `community.proxmox.proxmox_nodes_info` | Получение информации об узлах |
| `community.proxmox.proxmox_vm_info` | Получение информации о VM |
| `community.proxmox.proxmox_firewall` | Управление правилами firewall |
| `community.proxmox.proxmox_cluster` | Управление кластером |

## Практические сценарии

### Сценарий 1: Массовое создание VM из шаблона

```yaml
---
# playbooks/deploy_vms.yml
- name: Deploy VMs from template
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    template_id: 9001
    target_storage: local-lvm
    vm_nodes:
      - name: web-01
        id: 101
        ip: 10.0.0.10/24
        gateway: 10.0.0.1
        cores: 2
        memory: 4096
        node: node1
      - name: web-02
        id: 102
        ip: 10.0.0.11/24
        gateway: 10.0.0.1
        cores: 2
        memory: 4096
        node: node1
      - name: db-01
        id: 103
        ip: 10.0.0.20/24
        gateway: 10.0.0.1
        cores: 4
        memory: 8192
        node: node2

  tasks:
    - name: Clone VMs from template
      community.proxmox.proxmox_vm:
        api_host: "{{ proxmox_host }}"
        api_user: "{{ proxmox_api_user }}"
        api_password: "{{ proxmox_api_password }}"
        validate_certs: false
        node: "{{ item.node }}"
        vmid: "{{ item.id }}"
        name: "{{ item.name }}"
        clone: "{{ template_id }}"
        full: true
        storage: "{{ target_storage }}"
        cores: "{{ item.cores }}"
        memory: "{{ item.memory }}"
        net:
          virtio: "bridge=vmbr0"
      loop: "{{ vm_nodes }}"
      loop_control:
        label: "{{ item.name }}"

    - name: Configure Cloud-Init for each VM
      community.proxmox.proxmox_vm:
        api_host: "{{ proxmox_host }}"
        api_user: "{{ proxmox_api_user }}"
        api_password: "{{ proxmox_api_password }}"
        validate_certs: false
        node: "{{ item.node }}"
        vmid: "{{ item.id }}"
        ipconfig: "ip={{ item.ip }},gw={{ item.gateway }}"
        sshkeys: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"
      loop: "{{ vm_nodes }}"

    - name: Start VMs
      community.proxmox.proxmox_vm:
        api_host: "{{ proxmox_host }}"
        api_user: "{{ proxmox_api_user }}"
        api_password: "{{ proxmox_api_password }}"
        validate_certs: false
        node: "{{ item.node }}"
        vmid: "{{ item.id }}"
        state: started
      loop: "{{ vm_nodes }}"
```

**Запуск:**
```bash
ansible-playbook -i inventory/proxmox.yml playbooks/deploy_vms.yml \
  --extra-vars "proxmox_host=pve1.example.com"
```

### Сценарий 2: Массовое обновление пакетов на VM/LXC

```yaml
---
# playbooks/update_proxmox_guests.yml
- name: Update packages on all Proxmox guests
  hosts: "status_running:!tag_test"
  become: true
  serial: 1
  max_fail_percentage: 10

  pre_tasks:
    - name: Check if reboot is required
      ansible.builtin.stat:
        path: /var/run/reboot-required
      register: reboot_required

  tasks:
    - name: Update apt cache
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

    - name: Upgrade all packages
      ansible.builtin.apt:
        upgrade: dist
        autoremove: true
        purge: true
      when: ansible_os_family == "Debian"

    - name: Gather package facts
      ansible.builtin.package_facts:

    - name: Check for held packages
      ansible.builtin.command: dpkg --get-selections
      register: held_packages
      changed_when: false

    - name: Display held packages
      ansible.builtin.debug:
        msg: "{{ held_packages.stdout_lines | select('search', 'hold') | list }}"

  post_tasks:
    - name: Reboot if required
      ansible.builtin.reboot:
        reboot_timeout: 300
      when: reboot_required.stat.exists
```

### Сценарий 3: Настройка бэкапов через vzdump

```yaml
---
# playbooks/configure_backups.yml
- name: Configure Proxmox backups
  hosts: proxmox_nodes
  become: true
  vars:
    backup_storage: "pbs"
    backup_schedule: "daily"
    retention:
      keep_last: 7
      keep_daily: 7
      keep_weekly: 4
      keep_monthly: 6

  tasks:
    - name: Ensure backup job exists for all VMs
      ansible.builtin.lineinfile:
        path: /etc/vzdump.conf
        regexp: "^backup: .*"
        line: "backup: all,storage {{ backup_storage }},mode snapshot,compress zstd,mailto admin@example.com"
        state: present
      notify: restart-vzdump

    - name: Configure retention policy
      ansible.builtin.blockinfile:
        path: /etc/vzdump.conf
        marker: "# {mark} RETENTION MANAGED BY ANSIBLE"
        block: |
          retention: keep-last {{ retention.keep_last }},keep-daily {{ retention.keep_daily }},keep-weekly {{ retention.keep_weekly }},keep-monthly {{ retention.keep_monthly }}
      notify: restart-vzdump

  handlers:
    - name: restart-vzdump
      ansible.builtin.systemd:
        name: vzdump
        state: restarted
```

### Сценарий 4: Настройка узлов кластера через SSH

```yaml
---
# playbooks/setup_proxmox_nodes.yml
- name: Configure Proxmox nodes
  hosts: proxmox_nodes
  become: true
  vars:
    ntp_servers:
      - 0.pool.ntp.org
      - 1.pool.ntp.org
      - 2.pool.ntp.org

  tasks:
    - name: Disable enterprise repository
      ansible.builtin.lineinfile:
        path: /etc/apt/sources.list.d/pve-enterprise.sources
        regexp: "^#?Enabled:"
        line: "Enabled: false"
      when: ansible_distribution == "Debian"

    - name: Add no-subscription repository
      ansible.builtin.copy:
        dest: /etc/apt/sources.list.d/proxmox.sources
        content: |
          Types: deb
          URIs: http://download.proxmox.com/debian/pve
          Suites: trixie
          Components: pve-no-subscription
          Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg

    - name: Configure NTP via chrony
      ansible.builtin.template:
        src: templates/chrony.conf.j2
        dest: /etc/chrony/chrony.conf
        owner: root
        group: root
        mode: "0644"
      notify: restart-chrony

    - name: Enable chrony
      ansible.builtin.systemd:
        name: chrony
        enabled: true
        state: started

    - name: Set sysctl parameters for production
      ansible.posix.sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        sysctl_set: true
        state: present
        reload: true
      loop:
        - { key: "net.core.somaxconn", value: "65535" }
        - { key: "net.ipv4.tcp_max_syn_backlog", value: "65535" }
        - { key: "net.ipv4.ip_forward", value: "1" }
        - { key: "net.bridge.bridge-nf-call-iptables", value: "1" }
        - { key: "fs.file-max", value: "2097152" }

    - name: Configure SSH hardening
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: "{{ item.regexp }}"
        line: "{{ item.line }}"
      loop:
        - { regexp: "^#?PermitRootLogin", line: "PermitRootLogin prohibit-password" }
        - { regexp: "^#?PasswordAuthentication", line: "PasswordAuthentication no" }
        - { regexp: "^#?X11Forwarding", line: "X11Forwarding no" }
        - { regexp: "^#?MaxAuthTries", line: "MaxAuthTries 3" }
      notify: restart-ssh

    - name: Install essential packages
      ansible.builtin.apt:
        name:
          - htop
          - iotop
          - iftop
          - nethogs
          - tmux
          - vim
          - curl
          - wget
          - jq
        state: present
        update_cache: true

  handlers:
    - name: restart-chrony
      ansible.builtin.systemd:
        name: chrony
        state: restarted

    - name: restart-ssh
      ansible.builtin.systemd:
        name: ssh
        state: restarted
```

### Сценарий 5: Снапшоты VM перед обновлением

```yaml
---
# playbooks/snapshot_before_upgrade.yml
- name: Create snapshots before upgrade
  hosts: "status_running"
  gather_facts: false
  vars:
    snapshot_name: "pre-upgrade-{{ lookup('pipe', 'date +%Y%m%d-%H%M') }}"

  tasks:
    - name: Create snapshot via proxmoxer
      community.general.proxmox_snap:
        api_host: "{{ proxmox_host }}"
        api_user: "{{ proxmox_api_user }}"
        api_password: "{{ proxmox_api_password }}"
        validate_certs: false
        node: "{{ proxmox_node }}"
        vmid: "{{ proxmox_vmid }}"
        snapname: "{{ snapshot_name }}"
        description: "Snapshot before upgrade {{ lookup('pipe', 'date') }}"
        state: present
```

### Сценарий 6: Управление Ceph через SSH

```yaml
---
# playbooks/ceph_health_check.yml
- name: Check Ceph cluster health
  hosts: proxmox_nodes[0]
  become: true
  gather_facts: false
  tasks:
    - name: Get Ceph status
      ansible.builtin.command: ceph -s --format json
      register: ceph_status
      changed_when: false

    - name: Parse Ceph status
      ansible.builtin.set_fact:
        ceph_health: "{{ ceph_status.stdout | from_json }}"

    - name: Display health
      ansible.builtin.debug:
        msg: "Ceph health: {{ ceph_health.health.status }}"

    - name: Alert if degraded
      ansible.builtin.fail:
        msg: "Ceph cluster is {{ ceph_health.health.status }}! Immediate attention required."
      when: ceph_health.health.status != "HEALTH_OK"

    - name: Check OSD tree
      ansible.builtin.command: ceph osd tree --format json
      register: osd_tree
      changed_when: false

    - name: Display OSD status
      ansible.builtin.debug:
        msg: "OSDs up: {{ (osd_tree.stdout | from_json).nodes | selectattr('type', 'equalto', 'host') | map(attribute='status') | select('equalto', 'up') | list | length }}"

    - name: Check PG status
      ansible.builtin.command: ceph pg stat --format json
      register: pg_stat
      changed_when: false

    - name: Display PG summary
      ansible.builtin.debug:
        msg: "PGs: {{ (pg_stat.stdout | from_json).pg_summary }}"
```

### Сценарий 7: Rolling update кластера

```yaml
---
# playbooks/rolling_update_cluster.yml
- name: Rolling update of Proxmox cluster
  hosts: proxmox_nodes
  become: true
  serial: 1
  max_fail_percentage: 0
  order: sorted

  pre_tasks:
    - name: Check if this is the last node
      ansible.builtin.set_fact:
        is_last_node: "{{ inventory_hostname == ansible_play_hosts[-1] }}"

    - name: Get node status
      ansible.builtin.command: pveversion -v
      register: pveversion_output
      changed_when: false

    - name: Display current version
      ansible.builtin.debug:
        msg: "{{ pveversion_output.stdout_lines }}"

  tasks:
    - name: Migrate VMs off this node
      ansible.builtin.shell: |
        for vmid in $(qm list --node {{ inventory_hostname }} | awk 'NR>1 && $3=="running" {print $1}'); do
          target_node=$(pvesh get /cluster/resources --type vm | jq -r ".[] | select(.vmid==$vmid) | .node" | head -1)
          if [ "$target_node" != "{{ inventory_hostname }}" ]; then
            qm migrate "$vmid" "$target_node" --online 1
          fi
        done
      when: not is_last_node
      ignore_errors: true

    - name: Enable maintenance mode
      ansible.builtin.command: ha-manager crm-command node-maintenance enable {{ inventory_hostname }}
      ignore_errors: true

    - name: Update packages
      ansible.builtin.apt:
        update_cache: true
        upgrade: dist
        autoremove: true

    - name: Check if reboot required
      ansible.builtin.stat:
        path: /var/run/reboot-required
      register: reboot_required

    - name: Reboot node
      ansible.builtin.reboot:
        reboot_timeout: 600
      when: reboot_required.stat.exists

    - name: Wait for node to come back
      ansible.builtin.wait_for_connection:
        delay: 30
        timeout: 300

    - name: Verify cluster status
      ansible.builtin.command: pvecm status
      register: cluster_status
      changed_when: false

    - name: Display cluster status
      ansible.builtin.debug:
        msg: "{{ cluster_status.stdout_lines }}"

    - name: Disable maintenance mode
      ansible.builtin.command: ha-manager crm-command node-maintenance disable {{ inventory_hostname }}
      ignore_errors: true

  post_tasks:
    - name: Final cluster health check
      ansible.builtin.command: pvecm status
      register: final_status
      changed_when: false
      run_once: true

    - name: Verify quorum
      ansible.builtin.assert:
        that:
          - "'Quorate: Yes' in final_status.stdout"
        fail_msg: "Cluster lost quorum after update!"
        success_msg: "Cluster quorum is healthy"
```

### Сценарий 8: Управление через pvesh (shell модуль)

```yaml
---
# playbooks/proxmox_api_via_shell.yml
- name: Advanced Proxmox management via CLI
  hosts: proxmox_nodes[0]
  become: true
  gather_facts: false

  tasks:
    - name: List all VMs
      ansible.builtin.command: qm list
      register: vm_list
      changed_when: false

    - name: Display VMs
      ansible.builtin.debug:
        var: vm_list.stdout_lines

    - name: Get storage status
      ansible.builtin.command: pvesm status
      register: storage_status
      changed_when: false

    - name: Display storage
      ansible.builtin.debug:
        var: storage_status.stdout_lines

    - name: Create backup of all VMs
      ansible.builtin.shell: |
        for vmid in $(qm list --active | awk 'NR>1 {print $1}'); do
          vzdump "$vmid" --mode snapshot --storage pbs --compress zstd --mailto admin@example.com
        done
      async: 3600
      poll: 60
      register: backup_result

    - name: Check backup results
      ansible.builtin.debug:
        var: backup_result.stdout_lines
      when: backup_result is defined
```

## Диагностика и устранение неполадок

### Ошибка аутентификации

```
Failed to connect to host via ssh: ssh: connect to host pve1 port 22: Connection refused
```

**Причины:**
- SSH-сервис не запущен на узле Proxmox
- Firewall блокирует порт 22
- Неверный hostname/IP

**Решение:**
```bash
# Проверка SSH на узле
systemctl status ssh
# Проверка firewall
pve-firewall status
# Добавление правила
pve-firewall add --rule in --source 10.0.0.0/24 --proto tcp --dport 22 --action ACCEPT
```

### Ошибка API-токена

```
401 Unauthorized
```

**Проверка:**
```bash
# Тест токена через curl
curl -k -H "Authorization: PVEAPIToken=automation@pam!ansible=<SECRET>" \
  https://pve1:8006/api2/json/nodes

# Проверка прав токена
pveum user token list automation@pam
```

### Proxmoxer не установлен

```
module_proxmoxer = import_module('proxmoxer')
ModuleNotFoundError: No module named 'proxmoxer'
```

**Решение:**
```bash
pip3 install proxmoxer requests
# или
ansible-galaxy collection install community.proxmox
```

### VM не создается через API

**Проверка свободного места:**
```bash
pvesm status
# → Убедитесь, что на целевом хранилище достаточно места
```

**Проверка доступности шаблона:**
```bash
qm config 9001 | grep template
# → template: 1 (шаблон должен быть сконвертирован)
```

## Лучшие практики

1. **API-токен вместо пароля**: Создайте отдельного пользователя `automation@pam` с минимальными правами (PVEAuditor или кастомные роли). Никогда не используйте `root@pam` в playbooks.

2. **Хранение секретов**: Используйте Ansible Vault для паролей и токенов. Не храните секреты в открытом виде в inventory или group_vars.

3. **Serial update**: При обновлении кластера используйте `serial: 1` для обновления по одному узлу. Убедитесь, что кворум сохраняется.

4. **Idempotency**: Используйте модули `community.proxmox.*` вместо `shell` для идемпотентных операций. Модули проверяют текущее состояние перед изменением.

5. **Pre-flight checks**: Всегда проверяйте доступность хранилища, кворум и версии PVE перед mass-операциями.

6. **Тестирование**: Запускайте playbooks с `--check --diff` перед реальным применением. Используйте `--limit` для тестирования на одном узле.

7. **Логирование**: Настройте callback plugin для интеграции с Proxmox API и central logging.

8. **Роли**: Создайте Ansible-роли для типовых операций: setup-node, manage-vm, configure-backups, rolling-update.

## Граничные случаи

- **Смешанные версии PVE**: При обновлении кластера с PVE 8 на PVE 9 ansible-задачи могут завершиться ошибкой из-за несовместимости CLI. Обновляйте по одному узлу и проверяйте версию через `pveversion`.

- **Live Migration через API**: Требует shared storage. При попытке миграции VM с локальным хранилищем ошибка `no shared storage` — используйте холодную миграцию.

- **LXC через API**: Модуль `community.proxmox.proxmox_lxc` требует указания `ostemplate` при создании. Убедитесь, что шаблон скачан: `pveam download local debian-12-standard_12.0-1_amd64.tar.zst`.

- **Firewall Proxmox**: По умолчанию API доступен только с доверенных сетей. Добавьте правило для Ansible control node в Datacenter → Firewall → Options → IP Whitelist.

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Ansible — Введение](../Ansible/ansible_introduction.md)
- [Ansible — Модули](../Ansible/Modules/ansible_modules_overview.md)
- [Ansible — Динамический inventory](../Ansible/dynamic_inventory.md)
- [Ansible — OS Hardening](../Ansible/ansible-os-hardening.md)
- [Обновление систем Proxmox](./proxmox_updates.md)
