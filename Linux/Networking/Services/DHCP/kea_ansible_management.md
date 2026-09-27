# Kea DHCP: Управление через Ansible (IaC)

---

## Определения

**Infrastructure as Code (IaC)** — подход к управлению инфраструктурой, при котором конфигурация серверов, сетей и сервисов описывается в виде кода. Для Kea DHCP это означает управление конфигурацией, подсетями, резервированиями и hook-библиотеками через Ansible playbooks вместо ручного редактирования JSON-файлов.

**Ansible** — инструмент автоматизации без агента (agentless), использующий SSH для управления хостами. Описывает инфраструктуру через YAML-файлы (playbooks). Для Kea используется модуль `template` для генерации JSON-конфигураций и `uri` для взаимодействия с REST API.

**Idempotency (Идемпотентность)** — свойство операции, при котором повторное применение даёт тот же результат. Ansible-роли для Kea должны быть идемпотентными: повторный запуск playbook не должен перезапускать сервис без необходимости.

**Kea Control Agent (CA)** — HTTP(S)-шлюз для управления Kea через REST API. Ansible может взаимодействовать с Kea как через SSH (генерация конфигов), так и через REST API (динамические операции).

---

## Основные концепции

### Архитектура управления Kea через Ansible

```
┌─────────────────────────────────────────────────────────┐
│                    Ansible Controller                   │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Inventory   │  │  Playbooks   │  │  Roles        │  │
│  │  (hosts.ini) │  │  (kea.yml)   │  │  (kea-dhcp/)  │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                │                   │          │
└─────────┼────────────────┼───────────────────┼──────────┘
          │ SSH            │ SSH + REST API     │
          ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────┐
│                   Kea DHCP Servers                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ kea-dhcp4    │  │ kea-ctrl-    │  │ kea-dhcp6    │  │
│  │ (UDP 67/68)  │  │ agent (8000) │  │ (UDP 546/547)│  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Два подхода к управлению

| Подход | Механизм | Плюсы | Минусы |
|:--- |:--- |:--- |:--- |
| **Пush-конфигурации** | Генерация `kea-dhcp4.conf` через `template` + `systemctl restart` | Полный контроль, версионирование в Git | Требует перезапуска сервиса |
| **REST API** | Управление через `uri` + `kea-ctrl-agent` | Без перезапуска, динамические операции | Требует работающего CA, сложнее отладка |

**Рекомендация для прода:** Используйте гибридный подход — конфигурация через шаблоны (Git-контроль), динамические операции (reservations, classes) через REST API.

### Структура Ansible-роля для Kea

```
kea-dhcp/
├── defaults/
│   └── main.yml              # Переменные по умолчанию
├── files/
│   └── kea-ctrl-agent.conf   # Статический конфиг CA (опционально)
├── handlers/
│   └── main.yml              # Handlers (restart, reload)
├── meta/
│   └── main.yml              # Метаданные роли
├── tasks/
│   ├── main.yml              # Точка входа
│   ├── install.yml           # Установка пакетов
│   ├── configure.yml         # Генерация конфигурации
│   ├── hooks.yml             # Установка hook-библиотек
│   ├── firewall.yml          # Настройка фаервола
│   ├── systemd.yml           # Systemd-юниты и override
│   └── validation.yml        # Валидация и запуск
├── templates/
│   ├── kea-dhcp4.conf.j2     # Основной конфиг DHCPv4
│   ├── kea-dhcp6.conf.j2     # Конфиг DHCPv6
│   ├── kea-ctrl-agent.conf.j2 # Control Agent
│   └── kea-logging.conf.j2   # Конфигурация логирования
└── vars/
    └── main.yml              # Переменные роли
```

---

## Практические сценарии

### 1. Базовый Ansible-роль для Kea DHCP

**Структура inventory:**

```ini
# inventory/production/hosts.ini
[kea_primary]
dhcp-1 ansible_host=10.0.0.10 kea_role=primary

[kea_secondary]
dhcp-2 ansible_host=10.0.0.11 kea_role=secondary

[kea_servers:children]
kea_primary
kea_secondary

[kea_servers:vars]
ansible_user=deploy
ansible_become=yes
ansible_ssh_private_key_file=~/.ssh/deploy_key
```

**Переменные роли (`defaults/main.yml`):**

```yaml
# defaults/main.yml
kea_version: "2.6"
kea_interfaces:
  - eth0

kea_subnets:
  - id: 1
    subnet: "10.0.10.0/24"
    pools:
      - "10.0.10.100 - 10.0.10.200"
    options:
      routers: "10.0.10.1"
      domain_name_servers: "10.0.0.10, 10.0.0.11"
      domain_name: "corp.example.com"
    valid_lifetime: 86400
    renew_timer: 43200
    rebind_timer: 75600

kea_reservations: []

kea_ha_enabled: false
kea_ha_mode: "hot-standby"
kea_ha_peers: []

kea_ddns_enabled: false
kea_ddns_domain: "corp.example.com"
```

**Задачи установки (`tasks/install.yml`):**

```yaml
# tasks/install.yml
- name: Установка Kea DHCP (Debian/Ubuntu)
  apt:
    name:
      - kea-dhcp4-server
      - kea-ctrl-agent
    state: present
    update_cache: yes
  when: ansible_os_family == "Debian"

- name: Установка Kea DHCP (RHEL/Rocky)
  dnf:
    name:
      - kea
      - kea-libs
      - kea-ctrl-agent
    state: present
  when: ansible_os_family == "RedHat"

- name: Создание директории для логов
  file:
    path: /var/log/kea
    state: directory
    owner: kea
    group: kea
    mode: '0755'
```

**Генерация конфигурации (`tasks/configure.yml`):**

```yaml
# tasks/configure.yml
- name: Генерация kea-dhcp4.conf
  template:
    src: kea-dhcp4.conf.j2
    dest: /etc/kea/kea-dhcp4.conf
    owner: root
    group: root
    mode: '0644'
    validate: 'kea-dhcp4 -t -c %s'
  notify: restart kea-dhcp4

- name: Генерация kea-ctrl-agent.conf
  template:
    src: kea-ctrl-agent.conf.j2
    dest: /etc/kea/kea-ctrl-agent.conf
    owner: root
    group: root
    mode: '0644'
  notify: restart kea-ctrl-agent
```

**Шаблон конфигурации (`templates/kea-dhcp4.conf.j2`):**

```json
{
    "Dhcp4": {
        "interfaces-config": {
            "interfaces": {{ kea_interfaces | to_json }},
            "dhcp-sockets": "raw"
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases4.csv",
            "lfc-interval": 3600
        },
        "valid-lifetime": {{ kea_subnets[0].valid_lifetime | default(86400) }},
        "renew-timer": {{ kea_subnets[0].renew_timer | default(43200) }},
        "rebind-timer": {{ kea_subnets[0].rebind_timer | default(75600) }},
        "authoritative": true,
        "subnet4": [
{% for subnet in kea_subnets %}
            {
                "id": {{ subnet.id }},
                "subnet": "{{ subnet.subnet }}",
                "pools": [
{% for pool in subnet.pools %}
                    {
                        "pool": "{{ pool }}"
                    }{% if not loop.last %},{% endif %}

{% endfor %}
                ],
                "option-data": [
{% if subnet.options.routers is defined %}
                    {
                        "name": "routers",
                        "data": "{{ subnet.options.routers }}"
                    },
{% endif %}
{% if subnet.options.domain_name_servers is defined %}
                    {
                        "name": "domain-name-servers",
                        "data": "{{ subnet.options.domain_name_servers }}"
                    },
{% endif %}
{% if subnet.options.domain_name is defined %}
                    {
                        "name": "domain-name",
                        "data": "{{ subnet.options.domain_name }}"
                    }
{% endif %}
                ]{% if subnet.valid_lifetime is defined %},

                "valid-lifetime": {{ subnet.valid_lifetime }}{% endif %}

            }{% if not loop.last %},{% endif %}

{% endfor %}
        ]{% if kea_reservations | length > 0 %},

        "reservations": [
{% for reservation in kea_reservations %}
            {
                "hw-address": "{{ reservation.hw_address }}",
                "ip-address": "{{ reservation.ip_address }}"{% if reservation.hostname is defined %},

                "hostname": "{{ reservation.hostname }}"{% endif %}

            }{% if not loop.last %},{% endif %}

{% endfor %}
        ]{% endif %}

    }
}
```

**Handlers (`handlers/main.yml`):**

```yaml
# handlers/main.yml
- name: restart kea-dhcp4
  systemd:
    name: kea-dhcp4
    state: restarted
    enabled: yes

- name: restart kea-ctrl-agent
  systemd:
    name: kea-ctrl-agent
    state: restarted
    enabled: yes

- name: reload kea-dhcp4
  systemd:
    name: kea-dhcp4
    state: reloaded
```

### 2. Управление резервированиями через REST API

**Задачи для динамического управления (`tasks/reservations.yml`):**

```yaml
# tasks/reservations.yml
- name: Добавление резервирования через REST API
  uri:
    url: "http://{{ ansible_host }}:8000/"
    method: POST
    body_format: json
    body:
      command: "lease4-add"
      arguments:
        ip-address: "{{ item.ip_address }}"
        hw-address: "{{ item.hw_address }}"
        hostname: "{{ item.hostname | default(omit) }}"
        valid-lft: "{{ item.valid_lft | default(86400) }}"
        subnet-id: "{{ item.subnet_id | default(1) }}"
    headers:
      Content-Type: "application/json"
    user: "{{ kea_ca_user | default('admin') }}"
    password: "{{ kea_ca_password }}"
    force_basic_auth: yes
  loop: "{{ kea_reservations }}"
  loop_control:
    label: "{{ item.hw_address }} -> {{ item.ip_address }}"
  register: result
  changed_when: result.json.arguments result == 0

- name: Удаление резервирования
  uri:
    url: "http://{{ ansible_host }}:8000/"
    method: POST
    body_format: json
    body:
      command: "lease4-del"
      arguments:
        ip-address: "{{ item.ip_address }}"
    headers:
      Content-Type: "application/json"
    user: "{{ kea_ca_user | default('admin') }}"
    password: "{{ kea_ca_password }}"
    force_basic_auth: yes
  loop: "{{ kea_reservations_to_remove | default([]) }}"
  when: kea_reservations_to_remove is defined
```

### 3. Управление классами клиентов через API

```yaml
# tasks/client_classes.yml
- name: Добавление client-класса
  uri:
    url: "http://{{ ansible_host }}:8000/"
    method: POST
    body_format: json
    body:
      command: "class-add"
      arguments:
        client-classes:
          - name: "{{ item.name }}"
            test: "{{ item.test }}"
            option-data: "{{ item.options | default([]) }}"
    headers:
      Content-Type: "application/json"
    user: "{{ kea_ca_user | default('admin') }}"
    password: "{{ kea_ca_password }}"
    force_basic_auth: yes
  loop: "{{ kea_client_classes | default([]) }}"

# Пример переменных:
# kea_client_classes:
#   - name: "voip-phones"
#     test: "option[60].text == 'Polycom'"
#     options:
#       - name: "routers"
#         data: "10.0.10.10"
```

### 4. Настройка фаервола

```yaml
# tasks/firewall.yml
- name: Открытие портов DHCP (Debian/Ubuntu)
  ufw:
    rule: allow
    port: "{{ item.port }}"
    proto: "{{ item.proto }}"
    comment: "{{ item.comment }}"
  loop:
    - { port: "67", proto: "udp", comment: "DHCPv4 Server" }
    - { port: "68", proto: "udp", comment: "DHCPv4 Client" }
    - { port: "8000", proto: "tcp", comment: "Kea Control Agent" }
  when: ansible_os_family == "Debian"

- name: Открытие портов DHCP (RHEL/Rocky)
  firewalld:
    port: "{{ item.port }}/{{ item.proto }}"
    permanent: yes
    state: enabled
  loop:
    - { port: "67", proto: "udp" }
    - { port: "68", proto: "udp" }
    - { port: "8000", proto: "tcp" }
  when: ansible_os_family == "RedHat"
  notify: reload firewalld
```

### 5. Валидация и health check

```yaml
# tasks/validation.yml
- name: Проверка синтаксиса конфигурации
  command: kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
  register: kea_syntax_check
  changed_when: false
  failed_when: kea_syntax_check.rc != 0

- name: Проверка статуса сервиса
  systemd:
    name: kea-dhcp4
    state: started
    enabled: yes
  register: kea_service_status

- name: Проверка REST API
  uri:
    url: "http://{{ ansible_host }}:8000/"
    method: GET
    return_content: yes
  register: kea_api_response
  failed_when: kea_api_response.status != 200

- name: Прослушивание порта DHCP
  wait_for:
    port: 67
    proto: udp
    timeout: 10
  delegate_to: "{{ ansible_host }}"
```

### 6. Плейбук полного развёртывания

```yaml
# playbooks/kea-dhcp-deploy.yml
---
- name: Развёртывание Kea DHCP Server
  hosts: kea_servers
  become: yes
  vars_files:
    - ../vars/kea_config.yml
    - ../vars/kea_vault.yml  # Ansible Vault для секретов

  pre_tasks:
    - name: Проверка текущего состояния
      uri:
        url: "http://{{ ansible_host }}:8000/"
        method: GET
        return_content: yes
      register: kea_current_state
      ignore_errors: yes
      run_once: yes

  roles:
    - role: kea-dhcp
      tags: ['install', 'configure']

  post_tasks:
    - name: Финальная проверка
      include_tasks: tasks/validation.yml

  handlers:
    - include_tasks: handlers/main.yml
```

### 7. Rolling Update без простоя

```yaml
# playbooks/kea-rolling-update.yml
---
- name: Rolling Update Kea DHCP (без простоя)
  hosts: kea_servers
  serial: 1  # По одному серверу за раз
  max_fail_percentage: 0
  become: yes

  pre_tasks:
    - name: Проверка HA-статуса
      uri:
        url: "http://{{ ansible_host }}:8000/"
        method: POST
        body_format: json
        body:
          command: "statistic-get"
          args:
            name: "ha-state"
      register: ha_status
      when: kea_ha_enabled
      run_once: yes

    - name: Вывод HA-статуса
      debug:
        msg: "HA State: {{ ha_status.json.arguments['ha-state'] | default('N/A') }}"
      when: kea_ha_enabled

  tasks:
    - name: Обновление конфигурации
      template:
        src: kea-dhcp4.conf.j2
        dest: /etc/kea/kea-dhcp4.conf
        validate: 'kea-dhcp4 -t -c %s'
      notify: restart kea-dhcp4

  post_tasks:
    - name: Ожидание восстановления сервиса
      wait_for:
        port: 67
        proto: udp
        timeout: 30

    - name: Проверка выдачи адресов
      uri:
        url: "http://{{ ansible_host }}:8000/"
        method: POST
        body_format: json
        body:
          command: "statistic-get"
          args:
            name: "subnet[1].assigned-addresses"
      register: lease_count
```

---

## Дополнительная информация

### ansible-vault для секретов

```bash
# Шифрование пароля Kea CA
ansible-vault encrypt_string 'strong_password' --name 'kea_ca_password'

# Запуск playbook с vault
ansible-playbook playbooks/kea-dhcp-deploy.yml --ask-vault-pass

# Или с файлом паролей
ansible-playbook playbooks/kea-dhcp-deploy.yml --vault-password-file=.vault_pass
```

### Тестирование роли (Molecule)

```bash
# Установка Molecule
pip install molecule molecule-docker

# Инициализация
molecule init scenario default -d docker

# Тестирование
molecule test

# Проверка idempotency
molecule converge
molecule idempotence
```

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полная конфигурация Kea.
- **[Kea DHCP: Миграция с ISC](./kea_dhcp_migration.md)** — пошаговая миграция.
- **[Kea DHCP: Production Operations](./kea_production_operations.md)** — day-2 ops, мониторинг, troubleshooting.
- **[Kea DHCP: Безопасность и Hardening](./kea_security_hardening.md)** — TLS, SELinux, firewall.
- **[Kea DHCP: Docker/Podman](./kea_docker_deployment.md)** — контейнерное развертывание.
- **[Kea DHCP Documentation](https://kea.readthedocs.io/)** — официальная документация.
