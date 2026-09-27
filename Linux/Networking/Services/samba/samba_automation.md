# Samba: Автоматизация (Ansible)

## Определения

**Ansible Role** — структурированный набор задач (tasks), обработчиков (handlers), переменных и шаблонов для повторного использования. Позволяет кодировать инфраструктуру (IaC) и обеспечивать единообразие развёртывания.

**Ansible Galaxy** — публичный реестр ролей и коллекций. Содержит готовые модули для Samba, PostgreSQL, Apache и других сервисов.

**Idempotency (Идемпотентность)** — свойство playbook'а давать одинаковый результат при повторном выполнении. Критично для production: повторный запуск не должен ломать рабочую конфигурацию.

**Handler** — задача, выполняемая только при наличии `notify` от других задач. Обычно используется для перезапуска сервисов после изменения конфигурации.

**Vault** — механизм шифрования секретов в Ansible. Позволяет хранить пароли, ключи и токены в репозитории в зашифрованном виде.

**Template (Jinja2)** — шаблон для генерации конфигурационных файлов. Позволяет параметризовать настройки для разных окружений (dev/staging/prod).

**Variable Precedence** — иерархия приоритетов переменных в Ansible (defaults → inventory → playbook → extra vars). Позволяет переопределять настройки для конкретных хостов.

## Базовые концепции

### Структура Ansible-роли для Samba

```
ansible-role-samba/
├── defaults/
│   └── main.yml          # Значения по умолчанию
├── vars/
│   └── main.yml          # Переменные (более высокий приоритет)
├── tasks/
│   └── main.yml          # Основные задачи
├── handlers/
│   └── main.yml          # Обработчики (restart smbd)
├── templates/
│   ├── smb.conf.j2       # Шаблон конфигурации
│   └── fail2ban-samba.conf.j2
├── files/
│   └── samba-audit.conf  # Статические файлы
├── meta/
│   └── main.yml          # Метаданные роли
├── molecule/
│   └── default/
│       └── converge.yml  # Тестирование через Molecule
└── README.md
```

### Ключевые модули Ansible для Samba

| Модуль | Назначение | Пример |
| :--- | :--- | :--- |
| `ansible.builtin.package` | Установка пакетов | `name: samba` |
| `ansible.builtin.template` | Генерация smb.conf | `src: smb.conf.j2` |
| `ansible.builtin.service` | Управление сервисами | `name: smbd, state: started` |
| `ansible.builtin.lineinfile` | Изменение строк в файлах | `regexp: ^workgroup` |
| `ansible.builtin.user` | Управление пользователями | `name: smbuser` |
| `ansible.builtin.group` | Управление группами | `name: shareusers` |
| `ansible.posix.acl` | Управление ACL | `path: /srv/samba` |
| `ansible.builtin.copy` | Копирование файлов | `src: smb.conf` |
| `ansible.builtin.blockinfile` | Блоковая вставка | `block: \| ...` |

## Практические сценарии

### 1. Defaults (переменные по умолчанию)

```yaml
# defaults/main.yml
---
# Основные настройки
samba_workgroup: WORKGROUP
samba_security: user
samba_server_min_protocol: SMB3_11
samba_server_smb_encrypt: required

# Настройки шар
samba_shares:
  - name: data
    path: /srv/samba/data
    valid_users: "@shareusers"
    writable: yes
    browsable: yes
    vfs_objects: acl_xattr

# Пользователи для шар
samba_users:
  - name: smbuser
    groups: shareusers

# Сетевые настройки
samba_interfaces: "eth1"
samba_hosts_allow: "192.168.1.0/24"
samba_hosts_deny: "0.0.0.0/0"

# Безопасность
samba_ntlm_auth: ntlmv2-only
samba_restrict_anonymous: 2
samba_map_to_guest: Never

# Логирование
samba_log_level: 2
samba_max_log_size: 10240

# Мониторинг
samba_enable_metrics: true
```

### 2. Tasks (основные задачи)

```yaml
# tasks/main.yml
---
- name: Install Samba packages
  ansible.builtin.package:
    name:
      - samba
      - samba-common-bin
      - smbclient
      - winbind
      - libnss-winbind
      - libpam-winbind
    state: present
  tags: install

- name: Create share groups
  ansible.builtin.group:
    name: "{{ item }}"
    state: present
  loop: "{{ samba_share_groups | default([]) }}"

- name: Create share users
  ansible.builtin.user:
    name: "{{ item.name }}"
    groups: "{{ item.groups | default(omit) }}"
    shell: /usr/sbin/nologin
    create_home: no
    state: present
  loop: "{{ samba_users }}"

- name: Add users to Samba database
  community.general.smbpasswd:
    name: "{{ item.name }}"
    state: present
  loop: "{{ samba_users }}"
  notify: Restart smbd

- name: Create share directories
  ansible.builtin.file:
    path: "{{ item.path }}"
    state: directory
    owner: root
    group: root
    mode: '0770'
  loop: "{{ samba_shares }}"

- name: Deploy smb.conf
  ansible.builtin.template:
    src: smb.conf.j2
    dest: /etc/samba/smb.conf
    owner: root
    group: root
    mode: '0644'
    validate: testparm -s %s
  notify: Restart smbd
  tags: config

- name: Deploy fail2ban config
  ansible.builtin.template:
    src: fail2ban-samba.conf.j2
    dest: /etc/fail2ban/filter.d/samba.conf
    owner: root
    group: root
    mode: '0644'
  notify: Restart fail2ban
  tags: security

- name: Deploy jail config
  ansible.builtin.template:
    src: fail2ban-jail-samba.conf.j2
    dest: /etc/fail2ban/jail.d/samba.conf
    owner: root
    group: root
    mode: '0644'
  notify: Restart fail2ban
  tags: security

- name: Enable and start services
  ansible.builtin.service:
    name: "{{ item }}"
    state: started
    enabled: yes
  loop:
    - smbd
    - winbind

- name: Disable nmbd (not needed in modern networks)
  ansible.builtin.service:
    name: nmbd
    state: stopped
    enabled: no

- name: Deploy metrics collector
  ansible.builtin.copy:
    src: samba_metrics.sh
    dest: /usr/local/bin/samba_metrics.sh
    owner: root
    group: root
    mode: '0755'
  when: samba_enable_metrics | bool
  tags: monitoring
```

### 3. Handlers (обработчики)

```yaml
# handlers/main.yml
---
- name: Restart smbd
  ansible.builtin.service:
    name: smbd
    state: restarted

- name: Restart winbind
  ansible.builtin.service:
    name: winbind
    state: restarted

- name: Restart fail2ban
  ansible.builtin.service:
    name: fail2ban
    state: restarted
```

### 4. Шаблон smb.conf

```jinja2
{# templates/smb.conf.j2 #}
# {{ ansible_managed }}

[global]
   workgroup = {{ samba_workgroup }}
   security = {{ samba_security }}
   server min protocol = {{ samba_server_min_protocol }}
   server smb encrypt = {{ samba_server_smb_encrypt }}

   # Безопасность
   ntlm auth = {{ samba_ntlm_auth }}
   restrict anonymous = {{ samba_restrict_anonymous }}
   map to guest = {{ samba_map_to_guest }}
   lanman auth = no

   # Сеть
   bind interfaces only = yes
   interfaces = {{ samba_interfaces }}
   hosts allow = {{ samba_hosts_allow }}
   hosts deny = {{ samba_hosts_deny }}
   smb ports = 445

   # Логирование
   log level = {{ samba_log_level }}
   max log size = {{ samba_max_log_size }}

   # Производительность
   aio read size = 1
   aio write size = 1
   socket options = TCP_NODELAY IPTOS_LOWDELAY

{% for share in samba_shares %}
[{{ share.name }}]
   path = {{ share.path }}
   valid users = {{ share.valid_users }}
   writable = {{ share.writable | default('yes') }}
   browsable = {{ share.browsable | default('yes') }}
{% if share.vfs_objects is defined %}
   vfs objects = {{ share.vfs_objects }}
{% endif %}
   create mask = 0660
   directory mask = 0770
{% endfor %}
```

### 5. Inventory для Samba-кластера

```yaml
# inventory/samba.yml
---
all:
  children:
    samba_cluster:
      hosts:
        samba1:
          ansible_host: 192.168.1.10
          ctdb_node_address: 10.0.1.10
          samba_vip: 192.168.1.100
        samba2:
          ansible_host: 192.168.1.11
          ctdb_node_address: 10.0.1.11
          samba_vip: 192.168.1.101
        samba3:
          ansible_host: 192.168.1.12
          ctdb_node_address: 10.0.1.12
          samba_vip: 192.168.1.102
      vars:
        ansible_user: deploy
        ansible_become: yes
        samba_workgroup: EXAMPLE
        samba_security: ads
```

### 6. Playbook для развёртывания кластера

```yaml
# deploy_samba_cluster.yml
---
- name: Deploy Samba Cluster
  hosts: samba_cluster
  become: yes
  roles:
    - role: common
    - role: samba
    - role: ctdb
    - role: monitoring

  pre_tasks:
    - name: Wait for SSH
      ansible.builtin.wait_for_connection:
        timeout: 60

  post_tasks:
    - name: Verify Samba is running
      ansible.builtin.command: smbstatus
      register: smbstatus_result
      changed_when: false
      failed_when: smbstatus_result.rc not in [0, 1]
```

### 7. Playbook для обновления конфигурации

```yaml
# update_samba_config.yml
---
- name: Update Samba Configuration
  hosts: samba_cluster
  become: yes
  serial: 1  # По одному узлу для zero-downtime
  tasks:
    - name: Deploy new smb.conf
      ansible.builtin.template:
        src: smb.conf.j2
        dest: /etc/samba/smb.conf
        validate: testparm -s %s
      notify: Reload smbd

  handlers:
    - name: Reload smbd
      ansible.builtin.service:
        name: smbd
        state: reloaded
```

### 8. Molecule для тестирования роли

```yaml
# molecule/default/converge.yml
---
- name: Converge
  hosts: all
  become: yes
  roles:
    - role: ansible-role-samba

- name: Verify
  hosts: all
  tasks:
    - name: Check smbd is running
      ansible.builtin.service_facts:
      register: service_facts

    - name: Assert smbd is active
      ansible.builtin.assert:
        that:
          - "'smbd.service' in ansible_facts.services"
          - "ansible_facts.services['smbd.service'].state == 'running'"

    - name: Check share is accessible
      ansible.builtin.command: smbclient -L localhost -N
      register: smbclient_result
      changed_when: false
      failed_when: smbclient_result.rc != 0
```

### 9. Playbook для управления пользователями

```yaml
# manage_samba_users.yml
---
- name: Manage Samba Users
  hosts: samba
  become: yes
  vars_prompt:
    - name: username
      prompt: "Username"
      private: no
    - name: user_state
      prompt: "State (present/absent)"
      default: present
      private: no

  tasks:
    - name: Create system user
      ansible.builtin.user:
        name: "{{ username }}"
        shell: /usr/sbin/nologin
        create_home: no
        state: "{{ user_state }}"

    - name: Add/remove Samba user
      community.general.smbpasswd:
        name: "{{ username }}"
        state: "{{ user_state }}"

    - name: Add user to share group
      ansible.builtin.user:
        name: "{{ username }}"
        groups: shareusers
        append: yes
      when: user_state == "present"
```

### 10. Playbook для бэкапа конфигурации

```yaml
# backup_samba_config.yml
---
- name: Backup Samba Configuration
  hosts: samba
  become: yes
  vars:
    backup_dir: "/backup/samba/{{ ansible_date_time.date }}"

  tasks:
    - name: Create backup directory
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'

    - name: Backup smb.conf
      ansible.builtin.copy:
        src: /etc/samba/smb.conf
        dest: "{{ backup_dir }}/smb.conf"
        remote_src: yes

    - name: Backup secrets.tdb
      ansible.builtin.copy:
        src: /var/lib/samba/private/secrets.tdb
        dest: "{{ backup_dir }}/secrets.tdb"
        remote_src: yes

    - name: Backup idmap.ldb
      ansible.builtin.copy:
        src: /var/lib/samba/private/idmap.ldb
        dest: "{{ backup_dir }}/idmap.ldb"
        remote_src: yes

    - name: Keep only last 7 backups
      ansible.builtin.shell: |
        find /backup/samba -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
      changed_when: true
```

## Мониторинг и диагностика

### Проверка роли перед запуском

```bash
# Синтаксис playbook
ansible-playbook deploy_samba.yml --syntax-check

# Проверка inventory
ansible-inventory --list

# Dry-run (check mode)
ansible-playbook deploy_samba.yml --check --diff

# Запуск с ограничением по хостам
ansible-playbook deploy_samba.yml --limit samba1
```

### Отладка при ошибках

```bash
# Verbose режим
ansible-playbook deploy_samba.yml -vvv

# Остановка на ошибке
ansible-playbook deploy_samba.yml --step

# Запуск конкретного тега
ansible-playbook deploy_samba.yml --tags config
```

## Типовые ошибки автоматизации

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `FAILED! => {'msg': '...is not defined'}` | Переменная не определена | Проверьте defaults/main.yml |
| `Permission denied` | Нет `become: yes` | Добавьте `become: yes` |
| `testparm: error` | Невалидный smb.conf | Проверьте шаблон Jinja2 |
| Handler не перезапускает | Нет `notify` | Убедитесь, что задача имеет `notify` |

## Дополнительная информация

- [Настройка сервера](./samba_setup.md) — ручная настройка.
- [Безопасность и VFS](./samba_security.md) — hardening.

## См. также

- [Ansible: Введение](../../../Ansible/ansible_introduction.md) — основы Ansible.
- [Ansible Roles](../../../Ansible/ansible_roles.md) — структура ролей.
- [Ansible Vault](../../../Ansible/Vault/basics.md) — управление секретами.
- [Molecule](../../../Ansible/ansible_testing_with_molecule.md) — тестирование ролей.
