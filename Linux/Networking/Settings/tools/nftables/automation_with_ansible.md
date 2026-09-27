# nftables — автоматизация через Ansible

## Определения

**Ansible** — инструмент автоматизации конфигураций (IaC), использующий декларативные YAML- playbooks для управления инфраструктурой. Работает через SSH без установки агентов на управляемые хосты.

**Модуль `ansible.builtin.nftables`** — встроенный модуль Ansible для управления правилами nftables. Поддерживает добавление/удаление таблиц, цепочек и правил через командный интерфейс `nft`.

**Модуль `ansible.builtin.iptables`** — встроенный модуль Ansible для управления правилами iptables. Поддерживает `iptables-nft` бэкенд.

**GitOps** — подход к управлению инфраструктурой, при котором Git является единственным источником истины (SSoT). Изменения конфигураций применяются через CI/CD pipeline после code review.

**Шаблон (Template)** — Jinja2-шаблон Ansible, генерирующий конфигурационные файлы nftables на основе переменных и условий.

## Основные концепции

### Подходы к управлению nftables через Ansible

| Подход | Механизм | Преимущества | Недостатки |
|:---|:---|:---|:---|
| **Модуль `nftables`** | Добавление правил по одному | Declarative, идемпотентность | Медленно для больших конфигураций |
| **Шаблон `template`** | Генерация `/etc/nftables.conf` | Атомарная загрузка, полный контроль | Требует `nft -f` для применения |
| **Модуль `copy`** | Копирование готового файла | Простота | Нет дифференциального обновления |
| **`lineinfile`** | Вставка строк в файл | Гибкость | Неструктурированные конфигурации |

**Рекомендация:** Используйте **шаблон `template`** для полных конфигураций и **модуль `nftables`** для инкрементальных изменений.

### Идемпотентность

Ansible стремится к идемпотентности — повторный запуск playbook не должен изменять состояние системы, если конфигурация уже применена. Модуль `nftables` обеспечивает идемпотентность через проверку наличия правила перед добавлением.

### Структура проекта

```
nftables-ansible/
├── inventories/
│   ├── production/
│   │   ├── hosts.yml
│   │   └── group_vars/
│   │       ├── all.yml
│   │       ├── web_servers.yml
│   │       └── db_servers.yml
│   └── staging/
│       └── hosts.yml
├── roles/
│   └── nftables/
│       ├── tasks/
│       │   ├── main.yml
│       │   ├── install.yml
│       │   ├── configure.yml
│       │   └── validate.yml
│       ├── templates/
│       │   ├── nftables.conf.j2
│       │   └── nftables-docker.conf.j2
│       ├── handlers/
│       │   └── main.yml
│       └── defaults/
│           └── main.yml
├── playbooks/
│   ├── site.yml
│   ├── nftables_deploy.yml
│   └── nftables_rollback.yml
└── README.md
```

## Предварительные требования

### Программные требования

| Компонент | Версия | Проверка |
|:---|:---|:---|
| **Ansible** | 2.12+ | `ansible --version` |
| **Python** | 3.8+ | `python3 --version` |
| **nftables** | 1.0.0+ | `nft --version` |
| **SSH** | OpenSSH 8.0+ | `ssh -V` |
| **Права** | root/sudo | `sudo -l` |

## Практические сценарии

### 1. Роль Ansible для базовой настройки nftables

**`roles/nftables/defaults/main.yml` (переменные по умолчанию):**
```yaml
---
# Основные настройки
nftables_config_file: /etc/nftables.conf
nftables_backup_dir: /etc/nftables-backup
nftables_service_enabled: true

# Политики по умолчанию
nftables_input_policy: drop
nftables_forward_policy: drop
nftables_output_policy: accept

# Разрешенные порты
nftables_allowed_tcp_ports:
  - 22    # SSH
  - 80    # HTTP
  - 443   # HTTPS

# Разрешенные ICMP типы
nftables_allowed_icmp_types:
  - echo-request

# Дополнительные правила (нестандартные порты)
nftables_extra_rules: []

# Docker integration
nftables_docker_enabled: false
nftables_docker_filter_priority: -10
```

**`roles/nftables/templates/nftables.conf.j2`:**
```bash
#!/usr/sbin/nft -f
# Ansible managed — DO NOT EDIT MANUALLY

flush ruleset

table inet filter {
    chain input {
        type filter hook input priority {{ nftables_input_priority | default(0) }}; policy {{ nftables_input_policy }};

        # Established/related
        ct state established,related accept

        # Invalid
        ct state invalid drop

        # Loopback
        iif "lo" accept

        # ICMP
{% for icmp_type in nftables_allowed_icmp_types %}
        icmp type {{ icmp_type }} limit rate 5/second accept
{% endfor %}

        # TCP ports
{% for port in nftables_allowed_tcp_ports %}
        tcp dport {{ port }} accept
{% endfor %}

{% for rule in nftables_extra_rules %}
        {{ rule }}
{% endfor %}

        # Log drops
        log prefix "NFT_DROP: " limit rate 10/minute
    }

    chain forward {
        type filter hook forward priority 0; policy {{ nftables_forward_policy }};
    }

    chain output {
        type filter hook output priority 0; policy {{ nftables_output_policy }};
    }
}

{% if nftables_docker_enabled %}
table inet docker_filter {
    chain docker_forward {
        type filter hook forward priority {{ nftables_docker_filter_priority }}; policy accept;

        ct state established,related accept
        iifname "docker*" oifname != "docker*" drop
    }
}
{% endif %}
```

**`roles/nftables/tasks/main.yml`:**
```yaml
---
- name: Установка nftables
  ansible.builtin.package:
    name: nftables
    state: present
  tags: install

- name: Копирование конфигурации
  ansible.builtin.template:
    src: nftables.conf.j2
    dest: "{{ nftables_config_file }}"
    owner: root
    group: root
    mode: '0600'
    validate: 'nft --check -f %s'
  notify: Restart nftables
  tags: configure

- name: Включение и запуск службы
  ansible.builtin.systemd:
    name: nftables
    enabled: "{{ nftables_service_enabled }}"
    state: started
  tags: configure

- name: Проверка правил
  ansible.builtin.command: nft list ruleset
  register: nft_ruleset
  changed_when: false
  tags: validate
```

**`roles/nftables/handlers/main.yml`:**
```yaml
---
- name: Restart nftables
  ansible.builtin.systemd:
    name: nftables
    state: restarted
```

### 2. Использование модуля `nftables` для инкрементальных правил

```yaml
---
- name: Добавление правила для Redis
  ansible.builtin.nftables:
    table: inet filter
    chain: input
    rule: "tcp dport 6379 ip saddr 10.0.0.0/8 accept"
    state: present

- name: Блокировка IP-адреса
  ansible.builtin.nftables:
    table: inet filter
    chain: input
    rule: "ip saddr 203.0.113.5 drop"
    state: present

- name: Удаление правила
  ansible.builtin.nftables:
    table: inet filter
    chain: input
    rule: "ip saddr 203.0.113.5 drop"
    state: absent
```

### 3. Динамические sets через Ansible

**Шаблон для sets с таймаутом:**
```jinja2
{# roles/nftables/templates/dynamic_sets.conf.j2 #}

table inet filter {
{% for set_name, set_config in nftables_dynamic_sets.items() %}
    set {{ set_name }} {
        type {{ set_config.type }}
        flags {{ set_config.flags | default('dynamic, timeout') }}
        timeout {{ set_config.timeout | default('1h') }}
    }
{% endfor %}

    chain input {
        type filter hook input priority 0; policy drop;

{% for set_name in nftables_dynamic_sets %}
        ip saddr @{{ set_name }} drop
{% endfor %}
    }
}
```

**Переменные (`group_vars/web_servers.yml`):**
```yaml
nftables_dynamic_sets:
  ssh_bruteforce:
    type: ipv4_addr
    timeout: 1h
  http_flood:
    type: ipv4_addr
    timeout: 30m
  blocked_ips:
    type: ipv4_addr
    flags: interval
```

### 4. GitOps-подход с CI/CD

**`.gitlab-ci.yml` (пример):**
```yaml
stages:
  - lint
  - test
  - deploy

lint:
  stage: lint
  script:
    - nft --check -f roles/nftables/templates/nftables.conf.j2
    - ansible-lint playbooks/

test:
  stage: test
  script:
    - ansible-playbook -i inventories/staging playbooks/nftables_deploy.yml --check
  only:
    - merge_requests

deploy_staging:
  stage: deploy
  script:
    - ansible-playbook -i inventories/staging playbooks/nftables_deploy.yml
  only:
    - main

deploy_production:
  stage: deploy
  script:
    - ansible-playbook -i inventories/production playbooks/nftables_deploy.yml
  only:
    - tags
  when: manual
  environment:
    name: production
```

### 5. Inventory для групп серверов

**`inventories/production/hosts.yml`:**
```yaml
---
all:
  children:
    web_servers:
      hosts:
        web01.example.com:
          nftables_allowed_tcp_ports: [22, 80, 443]
          nftables_extra_rules:
            - "tcp dport 8080 ip saddr 10.0.0.0/8 accept"
        web02.example.com:
          nftables_allowed_tcp_ports: [22, 80, 443]

    db_servers:
      hosts:
        db01.example.com:
          nftables_allowed_tcp_ports: [22, 5432]
          nftables_extra_rules:
            - "ip saddr 10.0.1.0/24 tcp dport 5432 accept"

    docker_hosts:
      hosts:
        docker01.example.com:
          nftables_docker_enabled: true
          nftables_allowed_tcp_ports: [22, 80, 443, 2376]

  vars:
    ansible_user: deploy
    ansible_become: true
```

### 6. Безопасное обновление с откатом

**`playbooks/nftables_rollback.yml`:**
```yaml
---
- name: Откат nftables на предыдущую конфигурацию
  hosts: all
  become: true
  vars:
    backup_file: "/etc/nftables-backup/{{ inventory_hostname }}.conf"

  tasks:
    - name: Проверка наличия бэкапа
      ansible.builtin.stat:
        path: "{{ backup_file }}"
      register: backup_stat

    - name: Восстановление из бэкапа
      ansible.builtin.command: "nft -f {{ backup_file }}"
      when: backup_stat.stat.exists
      notify: Restart nftables

    - name: Отсутствие бэкапа
      ansible.builtin.debug:
        msg: "Бэкап не найден: {{ backup_file }}"
      when: not backup_stat.stat.exists
```

### 7. Rollback через systemd-run (5 минут)

**`playbooks/nftables_deploy.yml`:**
```yaml
---
- name: Безопасный деплой nftables
  hosts: all
  become: true
  tasks:
    - name: Создание бэкапа
      ansible.builtin.command: >
        nft list ruleset >
        /etc/nftables-backup/{{ inventory_hostname }}-{{ ansible_date_time.iso8601_basic }}.conf
      register: backup_result

    - name: Копирование конфигурации
      ansible.builtin.template:
        src: nftables.conf.j2
        dest: /etc/nftables.conf
        validate: 'nft --check -f %s'

    - name: Применение правил
      ansible.builtin.command: nft -f /etc/nftables.conf

    - name: Планирование отката через 5 минут
      ansible.builtin.command: >
        bash -c 'echo "nft flush ruleset && nft -f /etc/nftables-backup/{{ inventory_hostname }}-latest.conf" |
        at now + 5 minutes'
      when: rollback_enabled | default(true)
```

### 8. Тестирование перед деплоем

**`playbooks/nftables_validate.yml`:**
```yaml
---
- name: Валидация nftables конфигурации
  hosts: all
  become: true
  tasks:
    - name: Синтаксическая проверка
      ansible.builtin.command: nft --check -f /etc/nftables.conf
      register: syntax_check
      failed_when: syntax_check.rc != 0

    - name: Проверка SSH-доступа
      ansible.builtin.wait_for:
        port: 22
        host: "{{ inventory_hostname }}"
        timeout: 5
      delegate_to: localhost

    - name: Проверка счетчиков
      ansible.builtin.command: nft list chain inet filter input
      register: nft_input
      changed_when: false

    - name: Вывод правил
      ansible.builtin.debug:
        var: nft_input.stdout_lines
```

## Валидация результатов

### Проверка через Ansible

```bash
# Запуск playbook с проверкой
ansible-playbook -i inventories/production playbooks/nftables_deploy.yml --check

# Просмотр изменений (dry-run)
ansible-playbook -i inventories/production playbooks/nftables_deploy.yml --diff

# Применение
ansible-playbook -i inventories/production playbooks/nftables_deploy.yml
```

### Проверка на хосте

```bash
# Просмотр правил
sudo nft list ruleset

# Проверка статуса службы
sudo systemctl status nftables

# Проверка SSH-доступа (из другого терминала)
ssh deploy@server.example.com echo OK
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Ansible не может подключиться** | SSH timeout, нет sudo | Проверьте `ansible_user`, `ansible_become` |
| **Правила не применяются** | Ошибка синтаксиса в шаблоне | Используйте `validate: 'nft --check -f %s'` |
| **SSH обрывается после деплоя** | Нет правила для SSH | Добавьте `tcp dport 22 accept` в шаблон |
| **Правила дублируются** | Нет идемпотентности | Используйте `state: present` в модуле `nftables` |
| **Бэкап не создается** | Нет прав на запись | Проверьте `ansible_become: true` |
| **nft: command not found** | nftables не установлен | Добавьте таску установки в роль |

## Best Practices

1. **Используйте шаблоны** вместо `nft add rule` — это обеспечивает атомарность и идемпотентность.

2. **Всегда включайте `validate`** — `validate: 'nft --check -f %s'` предотвратит применение некорректных конфигураций.

3. **Создавайте бэкапы** перед каждым деплоем — храните в `/etc/nftables-backup/`.

4. **Используйте roles** — инкапсулируйте логику nftables в переиспользуемую роль.

5. **Тестируйте в staging** — прогоняйте playbook на staging перед production.

6. **Версионируйте в Git** — Git является SSoT для конфигураций nftables.

7. **Используйте групповые переменные** — настраивайте правила per-group, а не per-host.

8. **Включайте rollback** — автоматический откат через `at` или `systemd-run` спасает при потерянном SSH.

## См. также

- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — синтаксис и структура.
- **[nftables — практические сценарии](./practical_scenarios.md)** — безопасная настройка на удалённом сервере.
- **[Ansible](../../../../../../Ansible/ansible_basics.md)** — основы Ansible.
- **[Ansible Modules: Service & System](../../../../../../Ansible/Modules/ansible_service_and_system_config_modules.md)** — модули управления системой.
