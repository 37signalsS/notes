# Автоматизация Proxmox VE через Ansible

**Актуально для:** Proxmox VE 9.x, community.proxmox 2.x (ansible-core ≥ 2.17, proxmoxer ≥ 2.3)

## Определения

**proxmoxer** — Python-библиотека, предоставляющая REST API обертку для Proxmox VE. Используется как бэкенд для всех модулей коллекции `community.proxmox`. Поддерживает аутентификацию по паролю (auth-тикет), API-токену и TOTP. Версия 2.x коллекции требует proxmoxer ≥ 2.3.

**community.proxmox** — Ansible-коллекция для управления Proxmox VE: KVM VM, LXC-контейнеры, хранилища, сети, SDN, кластер, HA, Ceph, firewall, ACME-сертификаты, бэкапы, пользователи/роли/ACL. Является преемником Proxmox-модулей из `community.general` (оттуда они переехали и в `community.general` остались только deprecated-переадресации).

**Proxmox Inventory Plugin** (`community.proxmox.proxmox`) — динамический inventory-плагин, получающий список VM, LXC и узлов кластера напрямую из Proxmox API. Поддерживает группировку по узлам, статусам и тегам, фильтрацию хостов, кэширование и факт-gathering конфигурации гостей.

**Connection plugins** — плагины соединения из той же коллекции, выполняющие задачи Ansible внутри гостей **без SSH**:
- `community.proxmox.proxmox_qemu_api` — выполнение команд и передача файлов в QEMU VM через QEMU Guest Agent API (требует запущенного `qemu-guest-agent` внутри гостя; Linux-гости);
- `community.proxmox.proxmox_pct_remote` — выполнение задач в LXC-контейнерах через CLI `pct` на узле по SSH.

**API Token** — механизм аутентификации Proxmox, привязанный к пользователю и имеющий собственный secret. Единственный рекомендуемый способ аутентификации для автоматизации; работает без передачи пароля и не истекает, пока токен не отозван.

## Теоретический блок

### Архитектура интеграции

```
┌──────────────────────┐       HTTPS 8006       ┌──────────────────┐
│   Ansible Control    │◄──────────────────────►│   Proxmox API    │
│   Node               │  API-Token / Password   │   (pveproxy)     │
│                      │                         └──────────────────┘
│  ┌────────────────┐  │                                │
│  │ Inventory      │  │                                │
│  │ (dynamic API)  │  │                                │
│  └────────────────┘  │                                │
│  ┌────────────────┐  │                                ▼
│  │ Playbooks      │  │              ┌──────────────────────────────────┐
│  │ (community.    │  │              │  Proxmox Cluster (node1..nodeN)  │
│  │  proxmox)      │──┼─────────────►│  VM/LXC, storage, network, HA    │
│  └────────────────┘  │   API/SSH    └──────────────────────────────────┘
│  ┌────────────────┐  │                        │            │
│  │ Connection     │  │                        ▼            ▼
│  │ plugins        │──┼──── guest agent ──►  QEMU VMs    LXC (pct)
│  └────────────────┘  │
└──────────────────────┘
```

### Три способа управления Proxmox из Ansible

1. **Через REST API (community.proxmox)** — модули вызывают Proxmox API напрямую с control node. Основной способ: управление VM/LXC, шаблонами, хранилищами, кластером, HA, Ceph, firewall. Требует `proxmoxer` на control node и сетевой доступ к порту 8006.

2. **Через SSH (shell/command)** — Ansible подключается по SSH к узлам Proxmox и выполняет CLI (`qm`, `pct`, `pvesm`, `pvecm`, `ceph`, `ha-manager`). Незаменим для операций, не закрытых API: диагностика Ceph, проверка кворума, настройка самого хоста.

3. **Через connection plugins (гости без SSH)** — задачи выполняются внутри VM/LXC через Proxmox API (QEMU Guest Agent) или через `pct` на узле. Полезно для гостей без сетевого доступа из control node или без настроенного SSH.

### Аутентификация

**Создание пользователя и API-токена на стороне Proxmox:**

```bash
# Пользователь для автоматизации (отдельный, не root@pam)
pveum user add automation@pam --comment "Ansible automation"
# → ok

# Токен: --privsep 0 — токен наследует права пользователя;
# по умолчанию (приватный токен) права задаются явно через ACL
pveum user token add automation@pam ansible --privsep 0
# → private value: <uuid-secret>   (выводится только один раз — сохранить в vault)

# Роль с минимальными правами управления гостями (альтернатива --privsep 0)
pveum role add PVEAutomation \
  --privs "VM.Audit,VM.Clone,VM.PowerMgmt,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,Sys.Audit,Sys.Syslog,Datastore.Audit,Datastore.AllocateSpace,Datastore.AllocateTemplate"
pveum acl modify / --users automation@pam --roles PVEAutomation
# → ok
```

**Переменные окружения** (модули и inventory-плагин подхватывают их автоматически, аргументы модулей не требуются):

```bash
export PROXMOX_HOST="pve1.example.com"
export PROXMOX_USER="automation@pam"
export PROXMOX_TOKEN_ID="ansible"
export PROXMOX_TOKEN_SECRET="<secret>"
export PROXMOX_VALIDATE_CERTS="false"
```

Поддерживаемые переменные: `PROXMOX_HOST`, `PROXMOX_USER`, `PROXMOX_PASSWORD`, `PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET`, `PROXMOX_PORT`, `PROXMOX_OTP`, `PROXMOX_VALIDATE_CERTS`, `PROXMOX_URL` (для inventory-плагина).

**Переменные через Vault + module_defaults** — стандартный способ не дублировать аутентификацию в каждой задаче. У всех модулей коллекции есть action group `community.proxmox.proxmox`:

```yaml
# group_vars/proxmox/vars.yml
proxmox_host: "pve1.example.com"
proxmox_api_user: "automation@pam"
proxmox_api_token_id: "ansible"
proxmox_api_token_secret: "{{ vault_proxmox_token_secret }}"
```

```yaml
# Использование в play — аргументы аутентификации задаются один раз
- name: Example play
  hosts: localhost
  connection: local
  gather_facts: false
  module_defaults:
    group/community.proxmox.proxmox:
      api_host: "{{ proxmox_host }}"
      api_user: "{{ proxmox_api_user }}"
      api_token_id: "{{ proxmox_api_token_id }}"
      api_token_secret: "{{ proxmox_api_token_secret }}"
      validate_certs: false
      api_timeout: 300
  tasks:
    - community.proxmox.proxmox_node_info:
        node: node1
```

> **Важно:** дефолтный `api_timeout` равен 5 секундам — этого достаточно для чтения конфигурации, но не для клонирования или бэкапа. Для долгих операций задавайте `api_timeout` явно (сотни секунд).

### Динамический inventory

Имя файла конфигурации **обязано** заканчиваться на `.proxmox.yml` или `.proxmox.yaml` — иначе Ansible не распознает источник как Proxmox-плагин и попытается прочитать его как статический inventory.

```yaml
# inventory/pve.proxmox.yml
plugin: community.proxmox.proxmox
url: https://pve1.example.com:8006
user: automation@pam
token_id: ansible
token_secret: "{{ vault_proxmox_token_secret }}"
validate_certs: false

# Факты конфигурации гостей (proxmox_net0, proxmox_ipconfig0, proxmox_tags_parsed и др.)
want_facts: true
# ansible_host узлов кластера не трогаем — задаем сами через compose
want_proxmox_nodes_ansible_host: false

# Подключение к гостям по IP из cloud-init/сетевой конфигурации
compose:
  ansible_host: >-
    proxmox_ipconfig0.ip | default(proxmox_net0.ip)
    | default(proxmox_ip) | ipaddr('address')

# Группировка по статусу, узлу, тегам и типу гостя
keyed_groups:
  - key: proxmox_status
    prefix: status
  - key: proxmox_node
    prefix: node
  - key: proxmox_tags_parsed
    separator: ""
    prefix: tag
  - key: proxmox_vmtype
    prefix: type

# Отсев нерабочих/шаблонных гостей
filters:
  - "proxmox_status == 'running' or proxmox_status == 'stopped'"
  - "not proxmox_template"
```

Доступные факты гостя (с префиксом `proxmox_`, задается `facts_prefix`): `vmid`, `name`, `status`, `vmtype` (`qemu`/`lxc`), `node`, `tags`, `tags_parsed` (список — только при `want_facts: true`), `template`, `net0`/`ipconfig0` (словари сетевых параметров — при `want_facts: true`) и остальные параметры конфигурации гостя. Плагин также создает группу `templates` со шаблонными VM/LXC (начиная с 2.0.0).

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

[type_qemu]
web-01
db-01

[tag_web]
web-01
```

Кэширование inventory, сопоставление с NetBox/Consul и сравнение плагинов — в [Динамический инвентарь в Ansible](../Ansible/dynamic_inventory.md).

### Основные модули и плагины коллекции

| Модуль / плагин | Назначение |
|--------|-----------|
| `community.proxmox.proxmox_kvm` | Управление KVM VM: создание, клонирование, изменение, удаление, power-состояния |
| `community.proxmox.proxmox` | Управление LXC-контейнерами: создание, клонирование шаблонов, изменение, удаление (в `community.general` назывался `proxmox_lxc`) |
| `community.proxmox.proxmox_vm_info` | Информация о KVM VM |
| `community.proxmox.proxmox_node_info` | Информация об узлах кластера |
| `community.proxmox.proxmox_storage` / `proxmox_storage_info` / `proxmox_storage_contents_info` | Управление хранилищами и их содержимым |
| `community.proxmox.proxmox_template` | Шаблоны ОС (vztmpl/iso), загрузка через pveam |
| `community.proxmox.proxmox_snap` / `proxmox_snap_info` | Снапшоты гостей |
| `community.proxmox.proxmox_backup` / `proxmox_backup_info` / `proxmox_backup_schedule` | Запуск бэкапа, просмотр и изменение расписаний (jobs.cfg) |
| `community.proxmox.proxmox_firewall` / `proxmox_cluster_firewall_options` / `proxmox_node_firewall_options` | Правила и опции firewall |
| `community.proxmox.proxmox_cluster` / `proxmox_cluster_status_info` / `proxmox_cluster_join_info` | Создание кластера, статус, данные для join |
| `community.proxmox.proxmox_cluster_ha_groups` / `proxmox_cluster_ha_resources` / `proxmox_cluster_ha_rules` | HA-группы, ресурсы и правила |
| `community.proxmox.proxmox_ceph_osd` / `proxmox_ceph_pool` / `proxmox_ceph_mon` / `proxmox_ceph_mgr` / `proxmox_ceph_mds` | Управление Ceph-кластером PVE |
| `community.proxmox.proxmox_pool` / `proxmox_pool_member` | Пулы и их участники (в 2.x `members` — список) |
| `community.proxmox.proxmox_user` / `proxmox_group` / `proxmox_role` / `proxmox_access_acl` | Пользователи, группы, роли, ACL |
| `community.proxmox.proxmox_zone` / `proxmox_vnet` / `proxmox_subnet` | SDN: зоны, виртуальные сети, подсети |
| `community.proxmox.proxmox_node_network` | Сетевые интерфейсы узла (замена ручного `/etc/network/interfaces`) |
| `community.proxmox.proxmox_acme_certificate` / `proxmox_acme_account` | ACME SSL-сертификаты узлов |
| `community.proxmox.proxmox_tasks_info` | Статус задач PVE (UPID) |
| `community.proxmox.proxmox` (inventory) | Динамический inventory |
| `community.proxmox.proxmox_qemu_api` (connection) | Задачи в QEMU VM через Guest Agent, без SSH |
| `community.proxmox.proxmox_pct_remote` (connection) | Задачи в LXC через `pct`, без SSH в контейнер |

## Предварительные требования

```bash
# ansible-core ≥ 2.17
ansible --version
# → ansible [core 2.17.x]

# Коллекция
ansible-galaxy collection install community.proxmox
# → starting galaxy collection install process
# → successfully installed community.proxmox-2.x.y

# Зависимости на control node
pip3 install 'proxmoxer>=2.3' requests
# проверка
python3 -c "import proxmoxer; print(proxmoxer.__version__)"
# → 2.3.0
```

Проверка доступности API с control node перед написанием playbooks:

```bash
curl -sk -H "Authorization: PVEAPIToken=automation@pam!ansible=<SECRET>" \
  https://pve1.example.com:8006/api2/json/version
# → {"data":{"version":"9.2",...}}
```

## Практические сценарии

### Сценарий 1: Массовое создание VM из шаблона с Cloud-Init

```yaml
---
# playbooks/deploy_vms.yml
- name: Deploy VMs from template
  hosts: localhost
  connection: local
  gather_facts: false
  module_defaults:
    group/community.proxmox.proxmox:
      api_host: "{{ proxmox_host }}"
      api_user: "{{ proxmox_api_user }}"
      api_token_id: "{{ proxmox_api_token_id }}"
      api_token_secret: "{{ proxmox_api_token_secret }}"
      validate_certs: false
      api_timeout: 300
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
      community.proxmox.proxmox_kvm:
        node: "{{ item.node }}"
        clone: "{{ template_id }}"
        newid: "{{ item.id }}"
        name: "{{ item.name }}"
        full: true
        storage: "{{ target_storage }}"
        cores: "{{ item.cores }}"
        memory: "{{ item.memory }}"
        net:
          net0: "virtio,bridge=vmbr0"
      loop: "{{ vm_nodes }}"
      loop_control:
        label: "{{ item.name }}"

    - name: Configure Cloud-Init for each VM
      community.proxmox.proxmox_kvm:
        node: "{{ item.node }}"
        vmid: "{{ item.id }}"
        update: true
        ipconfig:
          ipconfig0: "ip={{ item.ip }},gw={{ item.gateway }}"
        nameservers:
          - 10.0.0.53
        ciuser: ubuntu
        # PVE API ожидает URL-encoded значение публичного ключа
        sshkeys: "{{ lookup('file', '~/.ssh/id_ed25519.pub') | urlencode }}"
      loop: "{{ vm_nodes }}"
      loop_control:
        label: "{{ item.name }}"

    - name: Start VMs
      community.proxmox.proxmox_kvm:
        node: "{{ item.node }}"
        vmid: "{{ item.id }}"
        state: started
      loop: "{{ vm_nodes }}"
      loop_control:
        label: "{{ item.name }}"
```

**Запуск и проверка:**

```bash
ansible-playbook -i inventory/pve.proxmox.yml playbooks/deploy_vms.yml

# Проверка на узле
qm status 101
# → status: running
qm config 101 | grep -E "ipconfig0|sshkeys"
# → ipconfig0: ip=10.0.0.10/24,gw=10.0.0.1
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

    - name: Check for held packages
      ansible.builtin.command: dpkg --get-selections
      register: held_packages
      changed_when: false

    - name: Display held packages
      ansible.builtin.debug:
        msg: "{{ held_packages.stdout_lines | select('search', 'hold') | list }}"

    - name: Check if reboot is required
      ansible.builtin.shell: |
        set -o pipefail
        # Ubuntu создаёт /var/run/reboot-required; Debian — нет
        [ -e /var/run/reboot-required ] && exit 0
        # Debian/PVE: запущенное ядро больше не установлено в системе
        dpkg -l 'linux-image-*' 2>/dev/null \
          | awk '/^ii/ {print $2}' \
          | grep -qx "linux-image-$(uname -r)" || exit 0
        exit 1
      args:
        executable: /bin/bash
      register: reboot_check
      changed_when: false
      failed_when: false

    - name: Reboot if required
      ansible.builtin.reboot:
        reboot_timeout: 300
      when: reboot_check.rc == 0
```

Хост-паттерн `status_running:!tag_test` использует группы из inventory-плагина: обновляются все запущенные гости, кроме помеченных тегом `test`. `serial: 1` обеспечивает обновление по одному гостю.

### Сценарий 3: Резервное копирование — глобальные настройки и расписание

Глобальные дефолты vzdump хранятся в `/etc/vzdump.conf` (формат `ключ: значение`). Периодические задания **не** описываются этим файлом — они создаются в Datacenter → Backup или через API `/cluster/backup` и попадают в кластерный конфиг `/etc/pve/jobs.cfg`, который исполняет демон `pvescheduler`. Отдельного «сервиса vzdump» не существует — перезапускать нечего, `pvescheduler` читает конфигурацию на лету.

```yaml
---
# playbooks/configure_backups.yml
- name: Configure Proxmox backups
  hosts: proxmox_nodes[0]
  become: true
  vars:
    backup_storage: "pbs"
    retention: "keep-last=7,keep-daily=7,keep-weekly=4,keep-monthly=6"

  tasks:
    - name: Set vzdump global defaults
      ansible.builtin.blockinfile:
        path: /etc/vzdump.conf
        marker: "# {mark} ANSIBLE MANAGED"
        block: |
          storage: {{ backup_storage }}
          mode: snapshot
          compress: zstd
          mailto: admin@example.com

    - name: Ensure scheduled backup job exists
      ansible.builtin.blockinfile:
        path: /etc/pve/jobs.cfg
        marker: "# {mark} ANSIBLE MANAGED JOB daily-all"
        block: |
          vzdump: daily-all
              all 1
              compress zstd
              mailto admin@example.com
              mode snapshot
              node {{ inventory_hostname }}
              storage {{ backup_storage }}
              schedule sun..sat 01:00
              prune-backups: {{ retention }}
              repeat-missed 1
```

`/etc/pve/jobs.cfg` — общий кластерный файл (configfs), поэтому playbook выполняется только на одном узле (`proxmox_nodes[0]`). Секция задачи содержит обязательный заголовок `vzdump: <id>` и отступленные параметры; `prune-backups` задает retention на уровне задачи (переопределяет настройки хранилища).

Проверка:

```bash
cat /etc/pve/jobs.cfg
# → vzdump: daily-all
#     all 1
#     schedule sun..sat 01:00
#     ...

pvesh get /cluster/backup
# → [{"id":"daily-all","schedule":"sun..sat 01:00",...}]
```

Привязка отдельных VM к уже существующей задаче бэкапа — модулем `proxmox_backup_schedule`:

```yaml
    - name: Ensure VMs are present in the daily backup job
      community.proxmox.proxmox_backup_schedule:
        backup_id: daily-all
        vm_id: "{{ item }}"
        state: present
      loop:
        - 101
        - 102
        - 103
```

Концепции PBS, дедупликации и хранения — в [Proxmox Backup Server](./proxmox_backup_server.md).

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
        # ip_forward и bridge-nf-call-iptables — дефолты PVE; фиксируем,
        # чтобы значение не потерялось после правок вручную
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

Hardening SSH перед перезапуском убедитесь, что SSH-ключ control node уже добавлен в `~/.ssh/authorized_keys` на узлах, иначе доступ по паролю будет потерян.

### Сценарий 5: Снапшоты VM перед обновлением

```yaml
---
# playbooks/snapshot_before_upgrade.yml
- name: Create snapshots before upgrade
  hosts: "status_running"
  gather_facts: false
  module_defaults:
    group/community.proxmox.proxmox:
      api_host: "{{ proxmox_host }}"
      api_user: "{{ proxmox_api_user }}"
      api_token_id: "{{ proxmox_api_token_id }}"
      api_token_secret: "{{ proxmox_api_token_secret }}"
      validate_certs: false
  vars:
    snapshot_name: "pre-upgrade-{{ lookup('pipe', 'date +%Y%m%d-%H%M') }}"

  tasks:
    - name: Create snapshot via proxmoxer
      community.proxmox.proxmox_snap:
        node: "{{ proxmox_node }}"
        vmid: "{{ proxmox_vmid }}"
        snapname: "{{ snapshot_name }}"
        description: "Snapshot before upgrade {{ lookup('pipe', 'date') }}"
        state: present
```

Откат — тот же модуль с `state: absent` для удаления или GUI/CLI `qm rollback` / `pct rollback` для возврата состояния. Снапшоты независимы от резервных копий: они защищают от проблем с обновлением гостя, но не от потери хранилища.

### Сценарий 6: Проверка здоровья Ceph через SSH

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
        msg: "Ceph cluster is {{ ceph_health.health.status }} (ожидается HEALTH_OK) — требуется внимание."
      when: ceph_health.health.status != "HEALTH_OK"

    - name: Get OSD summary
      ansible.builtin.command: ceph osd stat
      register: osd_stat
      changed_when: false

    - name: Display OSD status
      ansible.builtin.debug:
        msg: "{{ osd_stat.stdout }}"

    - name: Get PG summary
      ansible.builtin.command: ceph pg stat
      register: pg_stat
      changed_when: false

    - name: Display PG summary
      ansible.builtin.debug:
        msg: "{{ pg_stat.stdout }}"
```

Статус здоровья берется из JSON (`health.status` — `HEALTH_OK` / `HEALTH_WARN` / `HEALTH_DEGRADED`), а OSD и PG выводятся человекочитаемым однострочным статусом `ceph osd stat` / `ceph pg stat` — его стабильнее парсить, чем вложенные структуры `pgmap`.

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

    - name: Get node version
      ansible.builtin.command: pveversion
      register: pveversion_output
      changed_when: false

    - name: Display current version
      ansible.builtin.debug:
        msg: "{{ pveversion_output.stdout_lines[0] }}"

  tasks:
    - name: Migrate running VMs off this node
      ansible.builtin.shell: |
        set -o pipefail
        for vmid in $(qm list | awk 'NR>1 && $3=="running" {print $1}'); do
          target=$(pvesh get /cluster/resources --type vm --output-format json \
            | jq -r --argjson id "$vmid" \
              '.[] | select(.vmid == $id) | .node' \
            | grep -v "^{{ inventory_hostname }}$" | head -1)
          if [ -n "$target" ]; then
            qm migrate "$vmid" "$target" --online 1
          fi
        done
      args:
        executable: /bin/bash
      when: not is_last_node
      changed_when: false

    - name: Enable maintenance mode
      ansible.builtin.command: >
        ha-manager crm-command node-maintenance enable {{ inventory_hostname }}
      when: not is_last_node
      register: maintenance_enabled
      failed_when: false
      changed_when: maintenance_enabled.rc == 0

    - name: Wait until no HA services remain on this node
      ansible.builtin.shell: >
        ha-manager status
        | grep -cE "service .*\({{ inventory_hostname }}," || true
      register: ha_left
      changed_when: false
      failed_when: false
      until: ha_left.stdout | trim | int == 0
      retries: 30
      delay: 10
      when: not is_last_node

    - name: Update packages
      ansible.builtin.apt:
        update_cache: true
        upgrade: dist
        autoremove: true

    - name: Check if reboot is required
      ansible.builtin.shell: |
        set -o pipefail
        # PVE основан на Debian: /var/run/reboot-required не создаётся,
        # проверяем, что запущенное ядро установлено в системе
        dpkg -l 'linux-image-*' 2>/dev/null \
          | awk '/^ii/ {print $2}' \
          | grep -qx "linux-image-$(uname -r)" || exit 0
        exit 1
      args:
        executable: /bin/bash
      register: reboot_check
      changed_when: false
      failed_when: false

    - name: Reboot node
      ansible.builtin.reboot:
        reboot_timeout: 600
      when: reboot_check.rc == 0

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
      ansible.builtin.command: >
        ha-manager crm-command node-maintenance disable {{ inventory_hostname }}
      when: not is_last_node
      failed_when: false

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

`ha-manager crm-command node-maintenance enable <node>` переводит узел в режим обслуживания: HA-ресурсы уезжают на другие узлы, а после `disable` возвращаются обратно. Режим обслуживания **не сбрасывается при перезагрузке** — отключать его обязательно. На последнем узлу миграция и maintenance mode пропускаются (некуда мигрировать), но кластерный кворум при 2+ узлах сохраняется.

Полная процедура мажорного обновления PVE — в [Обновление систем Proxmox](./proxmox_updates.md), HA-механики — в [Кластеризация и High Availability](./proxmox_cluster.md).

### Сценарий 8: Управление через CLI (shell модуль)

```yaml
---
# playbooks/proxmox_api_via_shell.yml
- name: Advanced Proxmox management via CLI
  hosts: proxmox_nodes[0]
  become: true
  gather_facts: false

  tasks:
    - name: List all VMs on this node
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

    - name: Get cluster resources as JSON
      ansible.builtin.command: >
        pvesh get /cluster/resources --type vm --output-format json
      register: resources
      changed_when: false

    - name: Create backup of all VMs on this node
      ansible.builtin.shell: |
        set -o pipefail
        for vmid in $(qm list | awk 'NR>1 {print $1}'); do
          vzdump "$vmid" --mode snapshot --storage pbs --compress zstd \
            --mailto admin@example.com
        done
      args:
        executable: /bin/bash
      async: 3600
      poll: 60
      register: backup_result

    - name: Check backup results
      ansible.builtin.debug:
        var: backup_result.stdout_lines
      when: backup_result is defined
```

`qm list` работает только с локальным узлом (опций выбора узла у команды нет) — для обзора всего кластера используйте `pvesh get /cluster/resources`.

### Сценарий 9: Управление гостями без SSH через QEMU Guest Agent

```yaml
---
# playbooks/manage_guests_via_agent.yml
- name: Manage guests via QEMU guest agent (no SSH)
  hosts: localhost
  connection: community.proxmox.proxmox_qemu_api
  gather_facts: true
  vars:
    proxmox_api_host: "{{ proxmox_host }}"
    proxmox_api_token_id: "{{ proxmox_api_token_id }}"
    proxmox_api_token_secret: "{{ proxmox_api_token_secret }}"
    proxmox_node: node1
    proxmox_vmid: 101
    proxmox_validate_certs: false

  tasks:
    - name: Ensure curl is installed
      ansible.builtin.apt:
        name: curl
        state: present

    - name: Copy application config
      ansible.builtin.copy:
        src: files/app.conf
        dest: /etc/app/app.conf
        mode: "0644"

    - name: Restart application
      ansible.builtin.systemd:
        name: app
        state: restarted
```

Требования: запущенный `qemu-guest-agent` в госте и привилегии API-токена на операции guest agent — на PVE 9 это `VM.GuestAgent.Unrestricted` (команды) и `VM.GuestAgent.FileRead` / `VM.GuestAgent.FileWrite` (файлы); на PVE 8 достаточно `VM.Monitor`. Для Windows-гостей плагин не работает. Передача файлов ограничена ~45000 байт за вызов API — большие файлы плагин разбивает автоматически. В inventory-хостах можно задать `ansible_connection: community.proxmox.proxmox_qemu_api` вместе с `proxmox_vmid` / `proxmox_node` — тогда гости из Proxmox inventory управляются тем же способом.

## Диагностика и устранение неполадок

### Ошибка SSH-подключения к узлу

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
# Проверка/компиляция правил
pve-firewall compile
```

Правила PVE firewall добавляются не CLI-командой (у `pve-firewall` есть только `start`/`stop`/`restart`/`status`/`compile`/`simulate`), а файлами конфигурации или API:

```bash
# /etc/pve/firewall/host.fw (или cluster.fw — общий для кластера)
cat >> /etc/pve/firewall/host.fw <<'EOF'
[RULES]
IN ACCEPT -p tcp -source 10.0.0.0/24 -dport 22
EOF
pve-firewall restart
```

Либо модулем `community.proxmox.proxmox_firewall` / через GUI Datacenter → Firewall. Подробнее — в [Продвинутый Firewall в Proxmox VE](./proxmox_firewall_advanced.md).

### Ошибка API-токена

```
401 Unauthorized
```

**Проверка:**

```bash
# Тест токена через curl
curl -sk -H "Authorization: PVEAPIToken=automation@pam!ansible=<SECRET>" \
  https://pve1:8006/api2/json/nodes
# → {"data":[...]} — токен работает

# Список токенов пользователя
pveum user token list automation@pam
# Проверка прав токена (приватный токен требует явного ACL)
pveum acl view / --user automation@pam
```

Типовые причины: неверный формат `user@realm!tokenname` в `api_token_id`, отозванный secret, приватный токен без выданных прав (создавайте с `--privsep 0` или выдавайте роль через `pveum acl modify`).

### Proxmoxer не установлен или устарел

```
module_proxmoxer = import_module('proxmoxer')
ModuleNotFoundError: No module named 'proxmoxer'
```

**Решение:**

```bash
pip3 install 'proxmoxer>=2.3' requests
```

Убедитесь, что пакет установлен в тот же интерпретатор/окружение, из которого запускается `ansible` (venv, pipx, Execution Environment).

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

### Задача клонирования падает по таймауту

```
Timeout waiting for task ... : UPID:pve1:...
```

Дефолтный `api_timeout` модулей — 5 секунд. Клонирование, бэкап и миграция выполняются дольше: задайте `api_timeout: 300` (и более) через `module_defaults` или в задаче.

### Конфигурация кластера недоступна: /etc/pve не записывается

```
Failed to add entry to list 'vms' - error writing to file '/etc/pve/qemu-server/101.conf'
```

**Причины:** потеря кворума кластера (`pvecm status` → `Quorate: No`), заблокированный ресурс (lock), остановленный `pve-cluster`.

**Решение:**

```bash
pvecm status
# При распаде кластера — восстановление кворума:
# pvecm delnode <отказавший_узел>   (см. proxmox_cluster.md)
systemctl status pve-cluster
```

### --check не предсказывает изменения

Модули `community.proxmox.proxmox` и `proxmox_kvm` не поддерживают check mode (атрибут `check_mode: none`) — при запуске с `--check` такие задачи пропускаются. Тестируйте через `--limit` на одном госте/узле и dry-run на уровне shell-задач; для идемпотентных правок конфигурации узлов (`lineinfile`, `template`, `sysctl`) `--check` работает штатно.

### Дубликат VMID при параллельном развертывании

```
VM 101 already exists on node 'node1'
```

При конкурентных запусках playbook'ов явный `newid` конфликтует. Варианты: не задавать `newid` (модуль сам возьмет следующий свободный ID), сериализовать развертывание, выделять диапазоны VMID разным pipeline'ам.

## Лучшие практики

1. **API-токен вместо пароля**: отдельный пользователь `automation@pam` с минимальной ролью (`PVEAuditor` для чтения/inventory, кастомная роль — для управления). Никогда не используйте `root@pam` в playbooks. Приватные токены (`--privsep` вкл.) требуют явной выдачи прав через ACL.

2. **Хранение секретов**: Ansible Vault для secret'ов токенов; переменные с секретами помечайте `no_log: true` в задачах, где они передаются. Не храните секреты в открытом виде в inventory.

3. **module_defaults через action group**: аутентификация и `api_timeout` задаются один раз на play через `group/community.proxmox.proxmox`, а не в каждой задаче.

4. **Serial update**: при обновлении гостей и узлов — `serial: 1` и контроль кворума/HA перед продолжением.

5. **Idempotency**: модули `community.proxmox.*` вместо `shell` — они проверяют состояние перед изменением. Учтите: `proxmox_kvm` с `update: true` может отчитываться об изменении даже без реальных правок (см. граничные случаи).

6. **Pre-flight checks**: перед массовыми операциями — `pvecm status` (кворум), `pvesm status` (хранилища), `pveversion` (одинаковые версии узлов).

7. **Тестирование**: тегирование задач и `--limit` на одном узле/госте; `--check` применим не ко всем модулям (см. диагностику). Для разработки ролей — Molecule: [Тестирование Ansible с Molecule](../Ansible/ansible_testing_with_molecule.md).

8. **Теги гостей как источник группировки**: теги PVE (`tags` в модулях) становятся inventory-группами `tag_*` через `proxmox_tags_parsed` — единый механизм декларативной принадлежности гостя к сервису.

9. **Логирование**: стандартные callback-плагины Ansible (jsonfile, syslog, плагины мониторинга) — в [Callback-плагины Ansible](../Ansible/ansible-callback-plugins.md). В самой коллекции `community.proxmox` callback-плагинов нет; задачи PVE также пишутся в `/var/log/pve/` и journal.

10. **Роли и коллекции**: типовые операции оформляйте в Ansible-роли (`setup-node`, `manage-vm`, `configure-backups`, `rolling-update`); версионируйте коллекцию через `requirements.yml`.

## Граничные случаи

- **Смешанные версии PVE**: при обновлении кластера с PVE 8 на PVE 9 задачи могут падать из-за несовместимости CLI/конфигурации. Обновляйте по одному узлу, проверяйте версию через `pveversion`. Репозитории PVE 8 — `bookworm`, PVE 9 — `trixie` (формат `.sources`).

- **Live Migration через API**: требует shared storage (NFS/Ceph) либо configured replication. При миграции VM с локальным хранилищем ошибка `no shared storage` — используйте холодную миграцию (`--online 0`).

- **LXC через API**: модуль `community.proxmox.proxmox` требует `ostemplate` при создании. Убедитесь, что шаблон скачан: `pveam download local debian-12-standard_12.0-1_amd64.tar.zst`, либо скачайте его модулем `proxmox_template`.

- **Firewall Proxmox**: по умолчанию порт 8006 не ограничен списком доверенных сетей — API открыт всем, кому доступна сеть к узлу. Ограничьте доступ правилом host/cluster firewall (файлы `.fw` или модуль `proxmox_firewall`) до начала автоматизации.

- **`update: true` и идемпотентность**: `proxmox_kvm` с `update: true` может всегда отчитываться `changed=true`, даже если конфигурация гостя не изменилась (известная особенность модуля). Не используйте этот флаг как триггер для смежных обработчиков.

- **Linked vs full clone**: для шаблонов модуль по умолчанию стремится к linked clone; `full: true` + `storage` обязателен для full clone. Linked clone требует хранилища с поддержкой backing files и шаблона на том же хранилище.

- **Guest agent**: connection plugin `proxmox_qemu_api` и module parameter `agent` требуют запущенного `qemu-guest-agent` в госте; до первой установки агента SSH-доступ остаётся единственным способом доставки пакета.

- **Имя файла inventory**: источник Proxmox не активируется, если файл не заканчивается на `.proxmox.yml`/`.proxmox.yaml` — при прямом указании `-i inventories/pve.proxmox.yml` это особенно легко пропустить.

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [REST API Proxmox VE](./proxmox_rest_api.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Шаблоны ВМ и Cloud-Init в Proxmox VE](./proxmox_vm_templates.md)
- [Proxmox Backup Server (PBS)](./proxmox_backup_server.md)
- [Обновление систем Proxmox](./proxmox_updates.md)
- [Безопасность и Hardening Proxmox VE](./proxmox_security.md)
- [Мониторинг Proxmox через Prometheus и Grafana](./proxmox_monitoring.md)
- [Proxmox Service Discovery](./proxmox_service_discovery.md)
- [Ansible — Введение](../Ansible/ansible_introduction.md)
- [Динамический инвентарь в Ansible](../Ansible/dynamic_inventory.md)
- [Ansible — Коллекции](../Ansible/ansible_collections_deep_dive.md)
- [Ansible — module_defaults](../Ansible/ansible_module_defaults.md)
- [Ansible — OS Hardening](../Ansible/ansible-os-hardening.md)
