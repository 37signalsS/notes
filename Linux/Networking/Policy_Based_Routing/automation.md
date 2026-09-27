# Автоматизация Policy-Based Routing (PBR)

## Определения

**Автоматизация PBR** — процесс управления конфигурацией маршрутизации на основе политик через инструменты оркестрации (Ansible, Terraform, systemd-скрипты), обеспечивающий идемпотентность, версионирование и масштабируемость изменений на множестве хостов.

**Идемпотентность** — свойство playbook/scрипта приводить систему к целевому состоянию независимо от количества запусков. Повторное выполнение не нарушает существующую конфигурацию и не создает дублирующих правил.

**Декларативный подход** — описание желаемого состояния (какие правила, таблицы и маршруты должны существовать) вместо указания пошаговых команд. Инструмент сам определяет, какие изменения необходимо применить.

Теоретические основы PBR описаны в **[главном разделе (SSoT)](./index.md)**. Практические сценарии — в **[Практические сценарии PBR](./scenarios.md)**.

---

## Предпосылки

### Требования кManaged-хостам

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Python** | 3.8+ | Агент Ansible на managed-хостах |
| **iproute2** | 4.15+ | Управление `ip rule` и `ip route` |
| **nftables** | любая | Маркировка трафика (для fwmark-сценариев) |
| **systemd** | 232+ | Управление сервисами и persistent-применение |

### Требования кControl Node

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | Ядро Ansible |
| **Python** | 3.10+ | Совместимость с ansible-core |
| **SSH-ключи** | — | Доступ к managed-хостам по ключу |

---

## Основные концепции

### Почему автоматизация критична для PBR

Ручное управление PBR-правилами на нескольких серверах приводит к:

- **Configuration drift:** Правила расходятся между хостами после ручных правок.
- **Отсутствие версионирования:** Невозможно отследить, кто и когда изменил правило.
- **Риск человеческой ошибки:** Опечатка в `ip rule add` может обрушить связность.
- **Долгое восстановление:** При инциденте ручное восстановление правил занимает минуты, которые критичны.

### Модель управления PBR

```
Git-репозиторий (SSoT)
    ↓ git pull
Ansible Playbook
    ↓ idempotent execution
Managed Hosts (ip rule, ip route, sysctl, nftables)
    ↓ validation
ip route get (проверка выбора маршрута)
```

### Стратегии управления

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Синхронизация полного состояния** | Playbook задаёт конечное состояние: все правила, таблицы, маршруты. Лишнее удаляется. | Малое количество хостов, строгий контроль. |
| **Управление по ролям** | Каждая роль (web, db, monitoring) имеет набор PBR-правил. Хост получает роль → получает правила. | Средние и крупные инфраструктуры. |
| **Дополнительные правила (additive)** | Playbook только добавляет/изменяет указанные правила, не трогая остальные. | Миграция с ручного управления. |

---

## Практические сценарии

### Сценарий 1: Идемпотентная настройка PBR через Ansible

#### Структура проекта

```
pbr-automation/
├── inventory/
│   └── hosts.yml
├── group_vars/
│   └── all.yml
├── roles/
│   └── pbr/
│       ├── tasks/
│       │   └── main.yml
│       ├── templates/
│       │   ├── rt_tables.j2
│       │   └── sysctl_pbr.conf.j2
│       └── handlers/
│           └── main.yml
└── site.yml
```

#### Inventory

```yaml
# inventory/hosts.yml
all:
  children:
    web_servers:
      hosts:
        web01:
          ansible_host: 10.0.1.10
        web02:
          ansible_host: 10.0.1.11
    db_servers:
      hosts:
        db01:
          ansible_host: 10.0.2.10
  vars:
    ansible_user: admin
    ansible_become: yes
```

#### Group vars

```yaml
# group_vars/all.yml
pbr_tables:
  - id: 100
    name: isp1_table
  - id: 200
    name: isp2_table
  - id: 300
    name: mgmt_table

pbr_rules:
  # Source-based routing для ISP1
  - from: "192.168.1.0/24"
    table: isp1_table
    priority: 100
  # Source-based routing для ISP2
  - from: "192.168.2.0/24"
    table: isp2_table
    priority: 200
  # Management-трафик через выделенный канал
  - from: "10.0.100.0/24"
    table: mgmt_table
    priority: 50

pbr_routes:
  - table: isp1_table
    to: "default"
    via: "192.168.1.1"
    dev: eth0
  - table: isp2_table
    to: "default"
    via: "192.168.2.1"
    dev: eth1
  - table: mgmt_table
    to: "default"
    via: "10.0.100.1"
    dev: eth2

pbr_sysctl:
  net.ipv4.conf.all.rp_filter: 2
  net.ipv4.conf.default.rp_filter: 2
```

#### Роль Ansible

```yaml
# roles/pbr/tasks/main.yml
---
- name: Ensure iproute2 installed
  ansible.builtin.package:
    name: iproute2
    state: present

- name: Ensure nftables installed
  ansible.builtin.package:
    name: nftables
    state: present

- name: Deploy /etc/iproute2/rt_tables
  ansible.builtin.template:
    src: rt_tables.j2
    dest: /etc/iproute2/rt_tables
    owner: root
    group: root
    mode: "0644"
  notify: restore pbr rules

- name: Deploy sysctl PBR configuration
  ansible.builtin.template:
    src: sysctl_pbr.conf.j2
    dest: /etc/sysctl.d/99-pbr.conf
    owner: root
    group: root
    mode: "0644"
  notify: apply sysctl

- name: Remove conflicting ip rules
  ansible.builtin.command:
    cmd: "ip rule del priority {{ item.priority }}"
  loop: "{{ pbr_rules }}"
  register: rule_del_result
  failed_when: rule_del_result.rc not in [0, 2]

- name: Add PBR rules
  ansible.builtin.command:
    cmd: >-
      ip rule add
      from {{ item.from }}
      table {{ item.table }}
      priority {{ item.priority }}
  loop: "{{ pbr_rules }}"
  register: rule_add_result
  changed_when: "'RTNETLINK' not in rule_add_result.stderr"

- name: Ensure routes in PBR tables
  ansible.builtin.command:
    cmd: >-
      ip route replace
      {{ item.to }}
      via {{ item.via }}
      dev {{ item.dev }}
      table {{ item.table }}
  loop: "{{ pbr_routes }}"

- name: Validate PBR rules
  ansible.builtin.command:
    cmd: ip rule show
  register: pbr_rules_show
  changed_when: false

- name: Validate PBR routes
  ansible.builtin.command:
    cmd: "ip route show table {{ item.name }}"
  loop: "{{ pbr_tables }}"
  register: pbr_routes_show
  changed_when: false

- name: Validate route selection for each rule
  ansible.builtin.command:
    cmd: "ip route get 8.8.8.8 from {{ item.from }}"
  loop: "{{ pbr_rules }}"
  register: route_get_result
  changed_when: false
  failed_when: "'{{ item.table }}' not in route_get_result.stdout"
```

#### Шаблоны

```jinja2
{# templates/rt_tables.j2 #}
#
# /etc/iproute2/rt_tables — managed by Ansible
#
# numeric  name
#
255    local
254    main
253    default
0      unspec
{% for table in pbr_tables %}
{{ table.id }}    {{ table.name }}
{% endfor %}
```

```jinja2
{# templates/sysctl_pbr.conf.j2 #}
# PBR sysctl configuration — managed by Ansible
{% for key, value in pbr_sysctl.items() %}
{{ key }} = {{ value }}
{% endfor %}
```

#### Обработчики

```yaml
# roles/pbr/handlers/main.yml
---
- name: apply sysctl
  ansible.builtin.command:
    cmd: sysctl --system

- name: restore pbr rules
  ansible.builtin.command:
    cmd: ip rule restore < /etc/ip_rules_v4.conf
  ignore_errors: yes
```

#### Playbook

```yaml
# site.yml
---
- name: Configure Policy-Based Routing
  hosts: all
  roles:
    - pbr
```

#### Запуск и валидация

```bash
# Dry-run (check mode)
ansible-playbook -i inventory/hosts.yml site.yml --check --diff

# Применение
ansible-playbook -i inventory/hosts.yml site.yml

# Валидация на конкретном хосте
ansible web01 -m shell -a "ip rule show"
ansible web01 -m shell -a "ip route get 8.8.8.8 from 192.168.1.50"
```

---

### Сценарий 2: PBR-правила по ролям (role-based)

Разные типы хостов получают разные PBR-конфигурации:

```yaml
# group_vars/web_servers.yml
pbr_rules:
  - from: "10.0.1.0/24"
    table: isp1_table
    priority: 100
  - from: "10.0.2.0/24"
    table: isp2_table
    priority: 200

# group_vars/db_servers.yml
pbr_rules:
  - from: "10.0.2.0/24"
    table: isp_direct
    priority: 100
  # Базы данных не используют балансировку — только прямой канал
```

```bash
# Применение только для web-серверов
ansible-playbook -i inventory/hosts.yml site.yml --limit web_servers
```

---

### Сценарий 3: Безопасное изменение PBR в production (canary)

Пошаговое применение с проверкой на каждом этапе:

```yaml
# site.yml — canary-режим
---
- name: Canary PBR deployment
  hosts: all
  serial: 1  # По одному хосту за раз
  max_fail_percentage: 0  # Любой сбой → остановка

  pre_tasks:
    - name: Backup current rules
      ansible.builtin.shell:
        cmd: "ip rule save > /tmp/pbr_backup_$(date +%s).rules"
      register: backup_result

    - name: Backup current routes
      ansible.builtin.shell:
        cmd: ip route show table all > /tmp/pbr_routes_$(date +%s).txt

  roles:
    - pbr

  post_tasks:
    - name: Verify connectivity
      ansible.builtin.command:
        cmd: ping -c 3 -W 2 8.8.8.8
      register: ping_result
      until: ping_result.rc == 0
      retries: 3
      delay: 1

    - name: Verify PBR rule is active
      ansible.builtin.command:
        cmd: "ip route get 8.8.8.8 from {{ pbr_rules[0].from }}"
      register: route_check
      failed_when: "'{{ pbr_rules[0].table }}' not in route_check.stdout"

    - name: Rollback on failure
      ansible.builtin.shell:
        cmd: ip rule restore < /tmp/pbr_backup_*.rules
      when: ping_result.rc != 0 or route_check.rc != 0
```

---

### Сценарий 4: Ansible + sysctl для PBR-хостов

Управление параметрами ядра, критичными для PBR:

```yaml
# roles/pbr/tasks/sysctl.yml
---
- name: Deploy PBR sysctl parameters
  ansible.posix.sysctl:
    name: "{{ item.key }}"
    value: "{{ item.value }}"
    sysctl_file: /etc/sysctl.d/99-pbr.conf
    reload: yes
  loop:
    - { key: "net.ipv4.conf.all.rp_filter", value: "2" }
    - { key: "net.ipv4.conf.default.rp_filter", value: "2" }
    - { key: "net.ipv4.ip_forward", value: "1" }
    - { key: "net.ipv4.conf.all.accept_redirects", value: "0" }
    - { key: "net.ipv4.fib_multipath_hash_policy", value: "1" }
    - { key: "net.netfilter.nf_conntrack_max", value: "1048576" }
```

---

### Сценарий 5: Управление nftables-маркировкой через Ansible

Для сценариев, требующих `fwmark`:

```yaml
# roles/pbr/tasks/nftables_marking.yml
---
- name: Deploy nftables PBR marking rules
  ansible.builtin.copy:
    dest: /etc/nftables.d/pbr-marking.nft
    owner: root
    group: root
    mode: "0640"
    content: |
      # PBR marking rules — managed by Ansible
      table inet filter {
          chain prerouting {
              type filter hook prerouting priority mangle; policy accept;
              # Mark HTTPS traffic for ISP1
              tcp dport 443 meta mark set 0x1
              # Mark SSH for management table
              tcp dport 22 meta mark set 0x2
          }
      }
  notify: reload nftables

- name: Ensure nftables includes /etc/nftables.d/
  ansible.builtin.lineinfile:
    path: /etc/nftables.conf
    insertbefore: "^include"
    line: "include \"/etc/nftables.d/*.nft\""
  notify: reload nftables
```

```yaml
# roles/pbr/handlers/main.yml (дополнение)
- name: reload nftables
  ansible.builtin.systemd:
    name: nftables
    state: reloaded
```

---

## Диагностика и устранение неисправностей

### Типичные проблемы при автоматизации

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Playbook падает с "Permission denied"** | Нет `become: yes` или нет SSH-ключа с sudo | Добавить `ansible_become: yes` в inventory или group_vars |
| **Правила дублируются после второго запуска** | Не идемпотентное добавление (`ip rule add` без проверки) | Использовать `ip rule del` перед добавлением или `ip rule replace` (если поддерживается) |
| **Маршруты не применяются** | Таблица не создана в `/etc/iproute2/rt_tables` | Убедиться, что шаблон `rt_tables.j2` deployed до добавления маршрутов |
| **sysctl не применяется после reboot** | Файл в `/etc/sysctl.d/` не включён в обработку | Проверить `sysctl --system` и порядок файлов |
| **Playbook apply, но правила не изменились** | Managed host уже в целевом состоянии (идемпотентность) | Это нормальное поведение. Проверить `--diff` для просмотра изменений |
| **Разные результаты на разных хостах** | Разная версия ядра или iproute2 | Добавить проверку версий в pre_tasks |

### Валидация после применения

```bash
# 1. Проверка наличия всех правил
ip rule show | grep -E "100:|200:|300:"
# → Должны присутствовать все правила из pbr_rules

# 2. Проверка маршрутов в таблицах
for table in isp1_table isp2_table mgmt_table; do
  echo "=== $table ==="
  ip route show table $table
done

# 3. Эмуляция выбора маршрута
ip route get 8.8.8.8 from 192.168.1.50
# → Должен показать isp1_table

# 4. Проверка sysctl
sysctl net.ipv4.conf.all.rp_filter
# → net.ipv4.conf.all.rp_filter = 2

# 5. Проверка nftables
nft list chain inet filter prerouting
# → Должны присутствовать правила маркировки
```

---

## Лучшие практики

1. **Версионируйте PBR-конфигурацию:** Храните roles, group_vars и inventory в Git.
2. **Используйте `--check --diff` перед apply:** Dry-run покажет, что изменится без реального применения.
3. **Идемпотентность обязательна:** Всегда проверяйте существование перед добавлением (`ip rule del` перед `ip rule add`, или проверка через `ip rule show | grep`).
4. **Применяйте по одному хосту (canary):** Используйте `serial: 1` и `max_fail_percentage: 0`.
5. **Бэкап перед изменением:** Сохраняйте текущие правила: `ip rule save > /tmp/backup.rules`.
6. **Валидируйте после каждого изменения:** Проверяйте `ip route get` для каждого нового правила.
7. **Документируйте переменные:** В `group_vars` указывайте комментарии к каждому правилу (зачем оно нужно).
8. **Тестируйте в staging:** Запускайте playbook на test-хостах перед production.
9. **Используйте Ansible Vault для секретов:** Если PBR-правила зависят от VPN-ключей или паролей — храните их в Vault.
10. **Мониторьте drift:** Периодически запускайте `--check` для обнаружения ручных изменений.

---

## Дополнительная информация

### Сравнение Ansible и ручного управления

| Критерий | Ручное управление | Ansible |
| :--- | :--- | :--- |
| **Скорость применения** | Быстро на 1 хосте | Быстро на 100+ хостах |
| **Риск ошибок** | Высокий (опечатки) | Низкий (идемпотентность) |
| **Версионирование** | Нет | Git |
| **Откат** | Ручной, медленный | Автоматический (handler) |
| **Документация** | В голове администратора | В коде (inventory, vars) |
| **Аудит** | Невозможен | `ansible-lint`, git log |

### Связанные документы

- **[Policy-Based Routing (PBR) — Обзор](./index.md)** — архитектура и база данных правил RPDB.
- **[Администрирование PBR](./administration.md)** — методы отладки, мониторинг и персистентность.
- **[Практические сценарии PBR](./scenarios.md)** — типовые конфигурации (Dual-ISP, VPN-split, ECMP).
- **[Ansible — сетевая автоматизация](../../../Ansible/ansible_network_automation.md)** — автоматизация сетевого оборудования.
- **[sysctl: сетевые параметры ядра](../../Networking/Settings/sysctl_network.md)** — параметры ядра для persistent-конфигурации.
