# BIND: Автоматизация управления (IaC)

---

## Определения

**Infrastructure as Code (IaC)** — подход к управлению инфраструктурой, при котором конфигурация серверов, сетей и сервисов описывается в виде кода. Для BIND это означает управление конфигурацией, зонами и ключами через Ansible/Terraform/Puppet вместо ручного редактирования файлов.

**Ansible** — инструмент автоматизации без агента (agentless), использующий SSH для управления хостами. Описывает инфраструктуру через YAML-файлы (playbooks). Для BIND используется коллекция `community.general` с модулями `bind_zone` и `authorized_key`.

**Jinja2** — шаблонизатор, используемый Ansible для генерации конфигурационных файлов. Позволяет создавать параметризованные конфиги BIND, заполняя переменные из inventory.

**Групповая variables (group_vars)** — механизм Ansible для определения переменных на уровне группы хостов. Позволяет задать общие настройки DNS (TTL, NS-серверы, DC-specific параметры) для всех серверов группы.

**Rolling Update** — стратегия обновления, при которой серверы обновляются последовательно (по одному или по группам) с проверкой работоспособности после каждого шага. Критична для DNS — всегда должен быть доступен минимум один сервер.

---

## Базовые концепции

### Почему IaC для DNS критично

| Проблема ручного управления | Решение через IaC |
| :--- | :--- |
| Конфигурация drift между серверами | Единый источник правды (Git) |
| Ошибки при редактировании zone-файлов | Валидация через `named-checkzone` в playbook |
| Трудоёмкость добавления нового домена | Один YAML-файл → автоматическое развертывание |
| Сложность отката изменений | Git revert + playbook |
| Невоспроизводимость окружений | Inventory + group_vars |

### Архитектура Ansible для BIND

```text
┌──────────────────────────────────────────────┐
│               Control Node                    │
│                                               │
│  ┌──────────┐  ┌────────────┐  ┌───────────┐│
│  │inventory │  │ playbook   │  │ roles/    ││
│  │(hosts)   │  │(bind.yml)  │  │ bind/     ││
│  └────┬─────┘  └─────┬──────┘  └─────┬─────┘│
│       └───────────────┼───────────────┘       │
└───────────────────────┼──────────────────────┘
                        │ SSH
            ┌───────────┼───────────┐
            │           │           │
      ┌─────▼────┐ ┌────▼─────┐ ┌──▼────────┐
      │ ns1      │ │ ns2      │ │ ns3       │
      │(master)  │ │(slave)   │ │(slave)    │
      └──────────┘ └──────────┘ └───────────┘
```

---

## Практические сценарии

### Предусловия

```bash
# Установка Ansible
sudo apt install ansible

# Структура проекта
mkdir -p ~/bind-ansible/{inventories,roles/bind/{tasks,templates,handlers,defaults,files}}
cd ~/bind-ansible
```

### 1. Inventory (список серверов)

**Файл `inventories/production/hosts.ini`:**

```ini
[dns-master]
ns1 ansible_host=10.0.0.1 bind_role=master

[dns-slaves]
ns2 ansible_host=10.0.0.2 bind_role=slave
ns3 ansible_host=10.0.0.3 bind_role=slave

[dns:children]
dns-master
dns-slaves

[dns:vars]
ansible_user=deploy
ansible_become=yes
bind_version="9.18"
bind_domain="example.com"
bind_ns_primary="ns1.example.com"
bind_ns_secondary="ns2.example.com"
bind_ttl=3600
bind_soa_email="admin.example.com"
```

**Групповые переменные (`inventories/production/group_vars/dns.yml`):**

```yaml
---
# Общие настройки DNS
bind_zones:
  - name: example.com
    type: master
    records:
      - { name: "@", type: NS, value: "ns1.example.com." }
      - { name: "@", type: NS, value: "ns2.example.com." }
      - { name: "ns1", type: A, value: "10.0.0.1" }
      - { name: "ns2", type: A, value: "10.0.0.2" }
      - { name: "@", type: A, value: "192.0.2.1" }
      - { name: "www", type: A, value: "192.0.2.1" }
      - { name: "@", type: MX, value: "10 mail.example.com." }
      - { name: "mail", type: A, value: "192.0.2.10" }
      - { name: "_dmarc", type: TXT, value: "v=DMARC1; p=reject; rua=mailto:dmarc@example.com" }

  - name: 0.168.192.in-addr.arpa
    type: master
    records:
      - { name: "1", type: PTR, value: "ns1.example.com." }
      - { name: "2", type: PTR, value: "ns2.example.com." }
      - { name: "10", type: PTR, value: "mail.example.com." }

# TSIG ключи
bind_tsig_keys:
  - name: transfer-key
    algorithm: hmac-sha256
    secret: "{{ vault_transfer_key_secret }}"

# ACL
bind_acls:
  trusted:
    - 10.0.0.0/8
    - 192.168.0.0/16
  dns-cluster:
    - 10.0.0.1
    - 10.0.0.2
    - 10.0.0.3
```

### 2. Role: установка BIND

**Файл `roles/bind/defaults/main.yml`:**

```yaml
---
bind_packages:
  - bind9
  - bind9utils
  - bind9-dnsutils

bind_service_name: named
bind_config_dir: /etc/bind
bind_zone_dir: /var/lib/bind
bind_log_dir: /var/log/named
bind_user: bind
bind_group: bind
```

**Файл `roles/bind/tasks/main.yml`:**

```yaml
---
- name: Install BIND packages
  apt:
    name: "{{ bind_packages }}"
    state: present
    update_cache: yes
  tags: [install]

- name: Create directories
  file:
    path: "{{ item }}"
    state: directory
    owner: "{{ bind_user }}"
    group: "{{ bind_group }}"
    mode: "0750"
  loop:
    - "{{ bind_log_dir }}"
    - "{{ bind_zone_dir }}"
    - "{{ bind_config_dir }}/zones"
    - "{{ bind_config_dir }}/keys"
  tags: [config]

- name: Deploy named.conf.options
  template:
    src: named.conf.options.j2
    dest: "{{ bind_config_dir }}/named.conf.options"
    owner: root
    group: "{{ bind_group }}"
    mode: "0644"
    validate: "named-checkconf %s"
  notify: Reload BIND
  tags: [config]

- name: Deploy named.conf.local
  template:
    src: named.conf.local.j2
    dest: "{{ bind_config_dir }}/named.conf.local"
    owner: root
    group: "{{ bind_group }}"
    mode: "0644"
    validate: "named-checkconf %s"
  notify: Reload BIND
  tags: [config]

- name: Deploy zone files
  template:
    src: zone.db.j2
    dest: "{{ bind_zone_dir }}/db.{{ item.name }}"
    owner: "{{ bind_user }}"
    group: "{{ bind_group }}"
    mode: "0644"
    validate: "named-checkzone {{ item.name }} %s"
  loop: "{{ bind_zones }}"
  notify: Reload BIND
  tags: [zones]

- name: Deploy TSIG keys
  template:
    src: tsig.key.j2
    dest: "{{ bind_config_dir }}/keys/{{ item.name }}.key"
    owner: root
    group: "{{ bind_group }}"
    mode: "0640"
  loop: "{{ bind_tsig_keys }}"
  notify: Reload BIND
  tags: [security]

- name: Ensure BIND is started and enabled
  service:
    name: "{{ bind_service_name }}"
    state: started
    enabled: yes
  tags: [service]
```

**Файл `roles/bind/handlers/main.yml`:**

```yaml
---
- name: Reload BIND
  service:
    name: "{{ bind_service_name }}"
    state: reloaded

- name: Restart BIND
  service:
    name: "{{ bind_service_name }}"
    state: restarted
```

### 3. Шаблоны

**Шаблон `roles/bind/templates/named.conf.options.j2`:**

```conf
// Auto-generated by Ansible. Do not edit manually.
options {
    directory "{{ bind_zone_dir }}";

    listen-on port 53 { any; };
    listen-on-v6 port 53 { any; };

    recursion {{ bind_recursion | default('yes') }};
    allow-query { {{ bind_allow_query | default('any') }} };

    forwarders {
{% for fwd in bind_forwarders | default([]) %}
        {{ fwd }};
{% endfor %}
    };

    dnssec-validation auto;
    version "{{ bind_version_string | default('none') }}";

    max-cache-size {{ bind_max_cache_size | default('256m') }};
    max-cache-ttl {{ bind_max_cache_ttl | default('3600') }};

    // Statistics channel
    statistics-channels {
        inet 127.0.0.1 port 8080 allow { 127.0.0.1; };
    };

    // Logging
    logging {
        channel "query_log" {
            file "{{ bind_log_dir }}/query.log" versions 5 size 50m;
            severity info;
            print-time yes;
        };
        category queries { "query_log"; };
    };
};
```

**Шаблон `roles/bind/templates/named.conf.local.j2`:**

```conf
// Auto-generated by Ansible. Do not edit manually.

{% for acl_name, acl_entries in bind_acls.items() %}
acl "{{ acl_name }}" {
{% for entry in acl_entries %}
    {{ entry }};
{% endfor %}
};
{% endfor %}

{% for key in bind_tsig_keys %}
key "{{ key.name }}" {
    algorithm {{ key.algorithm }};
    secret "{{ key.secret }}";
};
{% endfor %}

{% for zone in bind_zones %}
zone "{{ zone.name }}" {
    type {{ zone.type | default('master') }};
    file "{{ bind_zone_dir }}/db.{{ zone.name }}";

{% if zone.type | default('master') == 'master' %}
    allow-transfer { key "transfer-key"; };
    also-notify {
{% for slave in groups['dns-slaves'] | default([]) %}
        {{ hostvars[slave]['ansible_host'] }};
{% endfor %}
    };
{% elif zone.type | default('master') == 'slave' %}
    masters {
{% for master in groups['dns-master'] | default([]) %}
        {{ hostvars[master]['ansible_host'] }} key "transfer-key";
{% endfor %}
    };
{% endif %}

{% if zone.dnssec | default(false) %}
    auto-dnssec maintain;
    inline-signing yes;
    key-directory "{{ bind_config_dir }}/keys";
{% endif %}
};
{% endfor %}
```

**Шаблон `roles/bind/templates/zone.db.j2`:**

```dns
; Zone file for {{ item.name }}
; Generated by Ansible — {{ ansible_date_time.iso8601 }}

$TTL {{ bind_ttl | default(3600) }}
@   IN  SOA {{ bind_ns_primary }}. {{ bind_soa_email }}. (
        {{ item.serial | default(ansible_date_time.epoch) }}  ; Serial
        3600        ; Refresh
        900         ; Retry
        1209600     ; Expire
        {{ bind_ttl | default(3600) }}  ; Negative TTL
)

{% for record in item.records %}
{{ record.name }}  IN  {{ record.type }}  {{ record.value }}
{% endfor %}
```

### 4. Playbook для развёртывания

**Файл `bind.yml`:**

```yaml
---
- name: Deploy and configure BIND DNS servers
  hosts: dns
  become: yes
  roles:
    - bind

  post_tasks:
    - name: Verify DNS resolution
      dig:
        server: "127.0.0.1"
        name: "{{ bind_domain }}"
        type: A
      register: dns_check
      ignore_errors: yes

    - name: Display DNS check result
      debug:
        msg: "DNS resolution {{ 'OK' if dns_check.succeeded else 'FAILED' }}"

    - name: Fail if DNS is not working
      fail:
        msg: "DNS resolution failed on {{ inventory_hostname }}"
      when: not dns_check.succeeded
```

**Запуск:**

```bash
# Проверка inventory
ansible-inventory -i inventories/production/hosts.ini --list

# Dry-run
ansible-playbook -i inventories/production/hosts.ini bind.yml --check

# Применение
ansible-playbook -i inventories/production/hosts.ini bind.yml

# Только на master
ansible-playbook -i inventories/production/hosts.ini bind.yml --limit dns-master

# С тегами
ansible-playbook -i inventories/production/hosts.ini bind.yml --tags zones
```

### 5. Добавление нового домена

**Шаг 1: Добавить зону в group_vars:**

```yaml
bind_zones:
  # ... существующие зоны ...
  - name: newdomain.com
    type: master
    records:
      - { name: "@", type: NS, value: "ns1.example.com." }
      - { name: "@", type: NS, value: "ns2.example.com." }
      - { name: "@", type: A, value: "192.0.2.50" }
      - { name: "www", type: A, value: "192.0.2.50" }
      - { name: "@", type: MX, value: "10 mail.newdomain.com." }
```

**Шаг 2: Запустить playbook:**

```bash
ansible-playbook -i inventories/production/hosts.ini bind.yml --tags zones
```

**Шаг 3: Обновить NS-записи у регистратора:**

```bash
# На регистраторе добавить:
# newdomain.com.  NS  ns1.example.com.
# newdomain.com.  NS  ns2.example.com.
```

### 6. Rolling Update (обновление без даунтайма)

**Стратегия:**
1. Обновить slave-серверы (один за другим)
2. Проверить синхронизацию
3. Обновить master-сервер
4. Проверить доступность DNS

```bash
# Шаг 1: Обновить slaves
ansible-playbook -i inventories/production/hosts.ini bind.yml --limit dns-slaves

# Шаг 2: Проверить трансфер
dig @ns2.example.com example.com AXFR +noauth | head -5

# Шаг 3: Обновить master
ansible-playbook -i inventories/production/hosts.ini bind.yml --limit dns-master

# Шаг 4: Финальная проверка
for ns in ns1 ns2 ns3; do
  echo "=== $ns ==="
  dig @$ns.example.com example.com +short
done
```

### 7. Тестирование через Molecule (для role)

```bash
# Установка Molecule
pip install molecule molecule-docker

# Создание теста
molecule init scenario --driver-name docker

# Тестирование role
molecule test

# Локальное тестирование
molecule converge
molecule verify
```

**Файл `molecule/default/molecule.yml`:**

```yaml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: ns1
    image: ubuntu:22.04
    privileged: yes
    command: /lib/systemd/systemd
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:ro
    pre_build_image: no
provisioner:
  name: ansible
  inventory:
    group_vars:
      dns:
        bind_zones:
          - name: test.local
            type: master
            records:
              - { name: "@", type: A, value: "192.0.2.1" }
```

---

## Типичные ошибки и их решение

### Ansible не может подключиться по SSH

**Симптом:** `Failed to connect to the host via ssh: Permission denied (publickey)`

**Решение:**

```bash
# 1. Проверка SSH-ключа
ssh -i ~/.ssh/id_rsa deploy@10.0.0.1 "echo ok"

# 2. Настройка в inventory
[dns:vars]
ansible_user=deploy
ansible_ssh_private_key_file=~/.ssh/deploy_key
ansible_become=yes
ansible_become_method=sudo
```

### named-checkconf в шаблоне падает

**Симптом:** `error: /etc/bind/named.conf.options:15: unknown option 'statistics-channels'`

**Причина:** Шаблон генерирует синтаксис, несовместимый с версией BIND.

**Решение:**

```yaml
# Добавить условие в шаблон
{% if bind_statistics_channel | default(true) %}
    statistics-channels {
        inet 127.0.0.1 port 8080 allow { 127.0.0.1; };
    };
{% endif %}
```

### Зоны не синхронизируются после обновления

**Симптом:** Slave-сервер не получает обновления зоны.

**Решение:**

```bash
# 1. Проверка NOTIFY
sudo rndc notify example.com

# 2. Проверка логов
journalctl -u named -n 50 | grep -i "transfer\|notify"

# 3. Ручная синхронизация
sudo rndc retransfer example.com
```

---

## Лучшие практики

*   **Храните конфигурацию в Git** — все изменения DNS проходят через PR + review.
*   **Используйте vault для секретов** — TSIG-ключи, пароли хранятся в Ansible Vault или HashiCorp Vault.
*   **Валидируйте перед деплоем** — `named-checkconf` и `named-checkzone` в каждом playbook.
*   **Тестируйте в dev-окружении** — Molecule + Docker для тестирования role перед продом.
*   **Rolling updates** — обновляйте slave-серверы раньше master, чтобы не прерывать доступность.
*   **Используйте tags** — `--tags zones` для обновления только зон, `--tags config` для конфигов.
*   **Логируйте изменения** — Git commit message = история изменений DNS.
*   **Документируйте inventory** — кто отвечает за какой домен, какие TTL, какие requirements.

---

## Дополнительная информация

### Инструментарий

- **Ansible:** Автоматизация без агента (SSH).
- **Molecule:** Тестирование Ansible-ролей.
- **HashiCorp Vault:** Управление секретами (TSIG-ключи, пароли).
- **Git:** Версионирование конфигурации.

### Связанные разделы

*   [BIND: Обзор](./overview.md) — архитектура и роли серверов.
*   [BIND: Master сервер](./master_server_local_zone.md) — настройка зон.
*   [BIND: Slave сервер](./slave_server_configuration.md) — трансферы зон.
*   [BIND: TSIG-ключи](./tsig-key-management.md) — ротация ключей.
*   [Ansible: Identity Management](../../../Ansible/ansible-identity-management.md) — модули Ansible.
