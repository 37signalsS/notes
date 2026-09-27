# Расширенное управление файрволами через Ansible

## Определения

**Firewall** — сетевой барьер, который фильтрует входящий и исходящий трафик на уровне хоста или сети. В контексте Ansible это означает автоматизацию настройки правил файрвола через модули `community.general.ufw`, `ansible.posix.firewalld`, `ansible.builtin.nftables` или `ansible.builtin.iptables`.

**Stateful firewall** — файрвол, который отслеживает состояние соединений и позволяет возвращать трафик для установленных соединений без явных правил. Примеры: `firewalld`, `ufw`.

**Stateless firewall** — файрвол, который фильтрует каждый пакет независимо от предыдущих пакетов. Пример: `iptables` без отслеживания состояний.

**Zone-based firewall** — файрвол, который группирует правила по зонам (trusted, internal, public, dmz), что упрощает управление политиками для разных интерфейсов. Подробнее о зонах см. [Firewalld: динамический межсетевой экран](../../Linux/Networking/Settings/tools/firewalld.md).

**Default deny policy** — политика по умолчанию, при которой весь трафик запрещен, если явно не разрешено правилом. Рекомендуется для production.

**DMZ (Demilitarized Zone)** — изолированная сеть между внутренней сетью и интернетом, где размещаются публичные сервисы.

**NAT (Network Address Translation)** — механизм преобразования сетевых адресов, который позволяет внутренним хостам выходить в интернет через один внешний IP.

**Port knocking** — метод защиты, при котором порты открываются только после последовательности соединений с определенными портами.

**IPS (Intrusion Prevention System)** — система предотвращения вторжений, которая анализирует трафик и блокирует подозрительные действия. В контексте файрвола — динамическое обновление правил на основе сигнатур атак.

**ipset** — механизм ядра Linux для хранения наборов IP-адресов, сетей или портов с проверкой принадлежности за O(1). Критически важен для production-окружений с большим количеством блокируемых адресов. Подробнее см. [Общие вопросы настройки межсетевых экранов в Linux](../../Linux/Networking/Settings/tools/firewall_common.md).

## Базовые концепции

### Архитектура файрвола в инфраструктуре

```
Internet
    ↓
[Edge Firewall / Load Balancer]
    ↓
[DMZ Zone]
    ├── Web servers (порты 80, 443)
    ├── Mail servers (порты 25, 465, 587)
    └── DNS servers (порт 53)
    ↓
[Internal Firewall]
    ↓
[Internal Zone]
    ├── App servers (порты 8080, 8443)
    ├── DB servers (порты 5432, 3306)
    └── Cache servers (порт 6379)
```

**Для SRE:** в продакшн-средах файрвол является первым эшелоном защиты (defense in depth). Настройка через Ansible обеспечивает:
- **Идемпотентность** — повторный запуск не ломает рабочую конфигурацию
- **Аудит** — все изменения хранятся в Git
- **Восстанавливаемость** — можно откатить любое изменение через playbook
- **Масштабируемость** — одинаковые правила применяются к сотням хостов

### Сравнение инструментов файрвола

| Инструмент | Уровень | Фронтенд | Когда использовать | Ansible модуль |
|---|---|---|---|---|
| **ufw** | Хост | Простой | Ubuntu/Debian, простые правила | `community.general.ufw` |
| **firewalld** | Хост | Средний | RHEL/CentOS/Rocky/Alma, zone-based политики | `ansible.posix.firewalld` |
| **iptables** | Хост | Сложный | Legacy, сложные правила, тонкая настройка | `ansible.builtin.iptables` |
| **nftables** | Хост | Сложный | Современный стандарт, производительность | `ansible.builtin.nftables` |
| **Cisco ASA/Palo Alto** | Сеть | Профессиональный | Сетевая инфраструктура | `cisco.asa.asa_config` и др. |

> **Важно:** Firewalld в современных дистрибутивах (RHEL 9+, Fedora 35+, Debian 12+) использует `nftables` как бэкенд. Прямое использование `iptables`-модулей может конфликтовать с firewalld. Выбирайте один инструмент и придерживайтесь его.

### Выбор инструмента: матрица решений

| Критерий | ufw | firewalld | nftables | iptables |
|:---|:---|:---|:---|:---|
| Простота базовых правил | ✅ | △ | △ | △ |
| Zone-based политики | ❌ | ✅ | ✅ (ручная) | ❌ |
| Производительность (>10k правил) | △ | △ | ✅ | △ |
| Контейнеры (Docker/Podman) | △ | ✅ | ✅ | △ |
| Совместимость со старыми ОС | ✅ | ✅ | △ | ✅ |
| Поддержка ipset/nftables sets | ❌ | ❌ | ✅ | ✅ |

### Жизненный цикл правил файрвола

1. **Определение политики** — какие сервисы должны быть доступны, из какого источника. Документируется в desired state.
2. **Создание правил** — написание Ansible tasks для настройки правил.
3. **Валидация** — проверка правил через `--check` mode, dry-run или отдельный плейбук auditor.
4. **Применение** — применение правил на управляемых хостах с maintenance window.
5. **Мониторинг** — отслеживание блокировок, аудит правил, алерты при отклонениях.
6. **Ротация** — обновление правил при изменении инфраструктуры.

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible Core | 2.21+ | `ansible --version` |
| Python (control node) | 3.12+ | `python3 --version` |
| Python (target node) | 3.9+ | `python3 --version` |
| ufw | 0.36.2+ | `ufw --version` |
| firewalld | 1.3+ (Debian 12), 2.x+ (RHEL 9+) | `firewall-cmd --version` |
| iptables | 1.8.0+ | `iptables --version` |
| nftables | 1.0.0+ | `nft --version` |
| ansible.posix collection | 1.5+ | `ansible-galaxy collection list ansible.posix` |
| community.general collection | 8.0+ | `ansible-galaxy collection list community.general` |

### Ключевые принципы

1. **Default deny** — по умолчанию весь трафик запрещен.
2. **Least privilege** — открывайте только необходимые порты.
3. **Idempotency** — правила должны быть идемпотентными.
4. **Logging** — логируйте блокировки для аудита.
5. **Automated validation** — проверяйте правила перед применением.
6. **Change management** — все изменения проходят через review и CI/CD.
7. **IPv4/IPv6 parity** — правила должны покрывать обе версии протокола, если IPv6 активен.

## Практические сценарии

### Сценарий 1: Настройка UFW на Ubuntu

Базовая настройка UFW с allow/deny правилами для веб-сервера.

```yaml
---
- name: Настройка UFW на веб-сервере
  hosts: web_servers
  become: true
  vars:
    ufw_default_incoming: "deny"
    ufw_default_outgoing: "allow"
    ufw_routes: true

  tasks:
    - name: Установка UFW
      ansible.builtin.package:
        name: ufw
        state: present

    - name: Настройка дефолтных политик
      community.general.ufw:
        default: "{{ item }}"
        direction: "{{ 'incoming' if item == ufw_default_incoming else 'outgoing' }}"
      loop:
        - "{{ ufw_default_incoming }}"
        - "{{ ufw_default_outgoing }}"

    - name: Разрешение SSH с rate limiting
      community.general.ufw:
        rule: limit
        port: 22
        proto: tcp
        from: "10.0.0.0/8"

    - name: Разрешение HTTP
      community.general.ufw:
        rule: allow
        port: 80
        proto: tcp
        from: any

    - name: Разрешение HTTPS
      community.general.ufw:
        rule: allow
        port: 443
        proto: tcp
        from: any

    - name: Запрет порта 3306 из внешней сети
      community.general.ufw:
        rule: deny
        port: 3306
        proto: tcp
        from: any

    - name: Включение UFW
      community.general.ufw:
        state: enabled
        logging: "on"

    - name: Проверка статуса UFW
      ansible.builtin.command: ufw status verbose
      register: ufw_status
      changed_when: false
```

**Валидация:**

```bash
# Проверка статуса UFW
ufw status verbose
# → Status: active
# → Default: deny (incoming), allow (outgoing), disabled (routed)
# → 22/tcp (v6) LIMIT IN 10.0.0.0/8
# → 80/tcp ALLOW IN Anywhere
# → 443/tcp ALLOW IN Anywhere
# → 3306/tcp DENY IN Anywhere

# Проверка правил
iptables -L -n -v
# → показывает правила iptables, созданные UFW

# Проверка блокировки
ufw deny 23/tcp
ufw status
# → 23/tcp DENY IN Anywhere
```

### Сценарий 2: Настройка Firewalld на RHEL

Настройка firewalld с zones, services, rich rules и IP sets.

```yaml
---
- name: Настройка Firewalld на RHEL
  hosts: rhel_servers
  become: true
  vars:
    firewalld_default_zone: "public"
    firewalld_zones:
      - name: "public"
        services:
          - ssh
          - http
          - https
        ports:
          - "8080/tcp"
        masquerade: no
      - name: "internal"
        services:
          - ssh
          - mysql
        sources:
          - "10.0.0.0/8"

  tasks:
    - name: Установка Firewalld
      ansible.builtin.package:
        name: firewalld
        state: present

    - name: Запуск и включение Firewalld
      ansible.builtin.systemd:
        name: firewalld
        state: started
        enabled: yes

    - name: Настройка зон
      ansible.posix.firewalld:
        zone: "{{ item.name }}"
        state: enabled
        services: "{{ item.services }}"
        ports: "{{ item.ports }}"
        masquerade: "{{ item.masquerade }}"
        source: "{{ item.sources | default(omit) }}"
      loop: "{{ firewalld_zones }}"

    - name: Установка дефолтной зоны
      ansible.posix.firewalld:
        state: enabled
        zone: "{{ firewalld_default_zone }}"
        immediate: yes
        permanent: yes

    - name: Добавление rich rules для ограничения SSH
      ansible.posix.firewalld:
        zone: public
        rich_rule: "rule family=ipv4 source address=10.0.0.0/8 port port=22 protocol=tcp accept"
        permanent: yes
        immediate: yes
        state: enabled

    - name: Проверка статуса Firewalld
      ansible.builtin.command: firewall-cmd --list-all-zones
      register: firewalld_status
      changed_when: false
```

**Валидация:**

```bash
# Проверка статуса firewalld
firewall-cmd --list-all-zones
# → public (active)
# → services: ssh, http, https
# → ports: 8080/tcp

# Проверка зон
firewall-cmd --zone=internal --list-all
# → services: ssh, mysql
# → sources: 10.0.0.0/8

# Проверка rich rules
firewall-cmd --zone=public --list-rich-rules
# → rule family=ipv4 source address=10.0.0.0/8 port port=22 protocol=tcp accept
```

### Сценарий 3: Кроссплатформенная роль файрвола

Абстракция для управления файрволом на разных ОС через единый интерфейс.

```yaml
---
- name: Применение файрвола через кроссплатформенную роль
  hosts: all
  become: true
  vars:
    firewall_allowed_tcp_ports:
      - 22
      - 443
    firewall_allowed_udp_ports:
      - 53
    firewall_trusted_networks:
      - "10.0.0.0/8"
      - "192.168.1.0/24"

  tasks:
    - name: Настройка UFW (Debian/Ubuntu)
      community.general.ufw:
        rule: allow
        port: "{{ item }}"
        proto: tcp
      loop: "{{ firewall_allowed_tcp_ports }}"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Настройка Firewalld (RHEL/Rocky/Alma)
      ansible.posix.firewalld:
        service: "{{ item }}"
        permanent: yes
        state: enabled
        immediate: yes
      loop: "{{ firewall_allowed_tcp_ports | map('extract', {'22':'ssh','443':'https'}) | list }}"
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Разрешение доверенных сетей в UFW
      community.general.ufw:
        rule: allow
        from: "{{ item }}"
      loop: "{{ firewall_trusted_networks }}"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Разрешение доверенных сетей в Firewalld
      ansible.posix.firewalld:
        zone: internal
        source: "{{ item }}"
        permanent: yes
        state: enabled
      loop: "{{ firewall_trusted_networks }}"
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Проверка правил файрвола
      ansible.builtin.command: "{{ 'ufw status verbose' if ansible_facts['os_family'] == 'Debian' else 'firewall-cmd --list-all-zones' }}"
      register: firewall_status
      changed_when: false
```

### Сценарий 4: Настройка nftables с атомарными транзакциями

Настройка nftables через шаблон с атомарной валидацией. Подробнее о модуле и подходах см. [nftables — автоматизация через Ansible](../../Linux/Networking/Settings/tools/nftables/automation_with_ansible.md).

```yaml
---
- name: Настройка nftables с атомарной валидацией
  hosts: all
  become: true
  vars:
    nftables_conf: "/etc/nftables.conf"
    nftables_backup_dir: "/etc/nftables-backup"

  tasks:
    - name: Установка nftables
      ansible.builtin.package:
        name: nftables
        state: present

    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ nftables_backup_dir }}"
        state: directory
        mode: '0700'

    - name: Бэкап текущей конфигурации nftables
      ansible.builtin.command: nft list ruleset
      register: current_nftables_rules
      changed_when: false

    - name: Сохранение бэкапа
      ansible.builtin.copy:
        content: "{{ current_nftables_rules.stdout }}"
        dest: "{{ nftables_backup_dir }}/ruleset-{{ ansible_date_time.date }}.nft"
        mode: '0600'
      when: current_nftables_rules.stdout | length > 0

    - name: Настройка nftables.conf
      ansible.builtin.copy:
        dest: "{{ nftables_conf }}"
        content: |
          #!/usr/sbin/nft -f
          # Ansible managed — DO NOT EDIT MANUALLY

          flush ruleset

          table inet filter {
            chain input {
              type filter hook input priority 0; policy drop;
              iif lo accept
              tcp dport { 22, 443 } ip saddr { 10.0.0.0/8, 192.168.1.0/24 } accept
              tcp dport { 80, 443 } accept
              ct state established,related accept
              icmp type echo-request accept
            }

            chain forward {
              type filter hook forward priority 0; policy drop;
            }

            chain output {
              type filter hook output priority 0; policy accept;
            }
          }
        mode: '0644'
      notify: Reload nftables

    - name: Включение и запуск nftables
      ansible.builtin.systemd:
        name: nftables
        state: started
        enabled: yes

    - name: Проверка статуса nftables
      ansible.builtin.command: nft list ruleset
      register: nft_status
      changed_when: false

  handlers:
    - name: Reload nftables
      ansible.builtin.systemd:
        name: nftables
        state: reloaded
```

**Валидация:**

```bash
# Проверка правил nftables
nft list ruleset
# → table inet filter {
# →   chain input {
# →     type filter hook input priority 0; policy drop;
# →     iif lo accept
# →     tcp dport { 22, 443 } ip saddr { 10.0.0.0/8, 192.168.1.0/24 } accept
# →     tcp dport { 80, 443 } accept
# →     ct state established,related accept
# →     icmp type echo-request accept
# →   }
# → }

# Проверка статуса сервиса
systemctl status nftables
# → active (running)

# Dry-run проверка конфигурации
nft -cf /etc/nftables.conf
# → (без вывода — ошибок нет)
```

### Сценарий 5: Интеграция с ipset для больших списков блокировок

Использование `ipset` (для iptables) или nftables `sets` для эффективного управления большими списками IP-адресов. Обычно применяется для блокировки ботнетов, гео-блокировки или allowlist.

```yaml
---
- name: Настройка ipset для блокировки нежелательных подсетей
  hosts: all
  become: true
  vars:
    blocked_networks:
      - "203.0.113.0/24"
      - "198.51.100.0/24"
    allowed_networks:
      - "10.0.0.0/8"

  tasks:
    - name: Установка ipset
      ansible.builtin.package:
        name: ipset
        state: present

    - name: Создание набора для блокируемых подсетей
      ansible.builtin.command: ipset create blocked_nets hash:net
      register: ipset_create
      changed_when: false
      failed_when: ipset_create.rc != 0 and 'already exists' not in ipset_create.stderr

    - name: Добавление подсетей в набор блокировки
      ansible.builtin.command: ipset add blocked_nets {{ item }}
      loop: "{{ blocked_networks }}"

    - name: Правило iptables с использованием ipset
      ansible.builtin.iptables:
        chain: INPUT
        source: "{{ item }}"
        jump: DROP
        state: present
      loop: "{{ blocked_networks }}"

    - name: Сохранение правил ipset
      ansible.builtin.command: ipset save > /etc/ipset.conf
      changed_when: true
```

**Альтернатива: nftables sets (рекомендуется для RHEL 9+, Debian 12+):**

```yaml
---
- name: Настройка nftables sets
  hosts: all
  become: true
  vars:
    blocked_ips:
      - "203.0.113.10"
      - "198.51.100.20"

  tasks:
    - name: Добавление IP в nftables set
      ansible.builtin.nftables:
        table: inet filter
        chain: input
        set: blackhole
        type: ipv4_addr
        elements: "{{ blocked_ips }}"
        state: present

    - name: Блокировка трафика из набора
      ansible.builtin.nftables:
        table: inet filter
        chain: input
        rule: "ip saddr @blackhole drop"
        state: present
```

### Сценарий 6: Rate limiting и защита от brute-force

Ограничение количества соединений для защиты от brute-force атак на SSH и других сервисов. Подробнее о rate limiting см. [Общие вопросы настройки межсетевых экранов в Linux](../../Linux/Networking/Settings/tools/firewall_common.md).

```yaml
---
- name: Rate limiting для SSH
  hosts: all
  become: true
  vars:
    ssh_rate_limit: "6/min"

  tasks:
    - name: Ограничение SSH через UFW (limit)
      community.general.ufw:
        rule: limit
        port: 22
        proto: tcp
        from: any
      when: ansible_facts['os_family'] == 'Debian'

    - name: Ограничение SSH через nftables (connlimit)
      ansible.builtin.nftables:
        table: inet filter
        chain: input
        rule: "tcp dport 22 ct state new limit rate {{ ssh_rate_limit }} accept"
        state: present
      when: ansible_facts['os_family'] == 'RedHat'
```

### Сценарий 7: Мониторинг и аудит правил файрвола

Настройка централизованного сбора логов блокировок файрвола для SIEM и мониторинга.

```yaml
---
- name: Настройка аудита файрвола
  hosts: all
  become: true
  vars:
    firewall_log_drop_packets: true
    syslog_server: "10.0.1.10:514"

  tasks:
    - name: Включение логирования UFW
      community.general.ufw:
        logging: "on"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Включение логирования Firewalld
      ansible.posix.firewalld:
        zone: public
        log_denied: all
        permanent: yes
        state: enabled
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Настройка rsyslog для пересылки логов файрвола
      ansible.builtin.copy:
        dest: /etc/rsyslog.d/firewall.conf
        content: |
          :msg, contains, "UFW" action(type="omfwd" target="{{ syslog_server }}" protocol="udp")
          :msg, contains, "DROP" action(type="omfwd" target="{{ syslog_server }}" protocol="udp")
        mode: '0644'
      notify: Restart rsyslog

    - name: Создание Prometheus exporter конфигурации
      ansible.builtin.template:
        src: firewall_exporter.yml.j2
        dest: /etc/firewall_exporter/config.yml
        mode: '0640'
      when: firewall_metrics_enabled | default(false)

  handlers:
    - name: Restart rsyslog
      ansible.builtin.systemd:
        name: rsyslog
        state: restarted
```

### Сценарий 8: Обнаружение дрейфа конфигурации файрвола

Автоматическая проверка соответствия правил desired state. Подробнее о дрейфе см. [Ansible: Обнаружение дрейфа](./ansible_configuration_drift.md).

```yaml
---
- name: Проверка дрейфа конфигурации файрвола
  hosts: all
  gather_facts: yes
  tasks:
    - name: Проверка статуса UFW
      ansible.builtin.service:
        name: ufw
        state: started
        enabled: yes
      check_mode: yes
      register: ufw_drift
      when: ansible_facts['os_family'] == 'Debian'

    - name: Проверка статуса Firewalld
      ansible.builtin.service:
        name: firewalld
        state: started
        enabled: yes
      check_mode: yes
      register: firewalld_drift
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Проверка портов в UFW
      community.general.ufw:
        rule: allow
        port: "{{ item }}"
        proto: tcp
      check_mode: yes
      register: ufw_port_drift
      loop: "{{ expected_tcp_ports }}"
      when: ansible_facts['os_family'] == 'Debian'

    - name: Проверка сервисов в Firewalld
      ansible.posix.firewalld:
        service: "{{ item }}"
        permanent: yes
        state: enabled
      check_mode: yes
      register: firewalld_service_drift
      loop: "{{ expected_services }}"
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Отчет о дрейфе
      ansible.builtin.debug:
        msg: |
          Drift Report for {{ inventory_hostname }}:
          UFW Active: {{ 'DRIFT DETECTED' if ufw_drift.changed else 'OK' }}
          Firewalld Active: {{ 'DRIFT DETECTED' if firewalld_drift.changed else 'OK' }}
          UFW Ports Drift: {{ ufw_port_drift.results | map(attribute='changed') | select('equalto', true) | list | length }} issues
```

## Операции и команды

### Основные команды для управления файрволом

| Команда | Назначение | Пример |
|---|---|---|
| `ufw allow <port>` | Разрешить порт в UFW | `ufw allow 22/tcp` |
| `ufw deny <port>` | Запретить порт в UFW | `ufw deny 3306/tcp` |
| `ufw enable` | Включить UFW | `ufw enable` |
| `firewall-cmd --zone=<zone> --add-service=<service>` | Добавить сервис в зону | `firewall-cmd --zone=public --add-service=http` |
| `firewall-cmd --list-all` | Показать все правила | `firewall-cmd --list-all-zones` |
| `iptables -L -n -v` | Показать правила iptables | `iptables -L -n -v` |
| `iptables-save` | Сохранить правила iptables | `iptables-save > /etc/iptables/rules.v4` |
| `nft list ruleset` | Показать правила nftables | `nft list ruleset` |

### Команды для проверки файрвола

| Команда | Назначение | Пример |
|---|---|---|
| `ufw status` | Проверка статуса UFW | `ufw status verbose` |
| `firewall-cmd --state` | Проверка статуса firewalld | `firewall-cmd --state` |
| `iptables -S` | Показать правила iptables в формате команд | `iptables -S` |
| `nft list ruleset` | Показать правила nftables | `nft list ruleset` |
| `nc -zv <host> <port>` | Проверка открытого порта | `nc -zv web1 80` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `UFW: Unable to find rule` | Правило не существует или неверный синтаксис | Проверьте `ufw status`, добавьте правило заново |
| `Firewalld: Permission denied` | Недостаточно прав | Запустите с `sudo` или через become |
| `iptables: No chain/target/match by that name` | Цепочка или правило не существует | Создайте цепочку заново или проверьте синтаксис |
| `Порт закрыт, но должен быть открыт` | Правило применено к неверной цепочке/интерфейсу | Проверьте `iptables -L -n -v`, убедитесь в правильности правила |
| `Firewalld: Zone not found` | Зона не существует | Создайте зону или используйте существующую |
| `Rollback правил файрвола заблокировал доступ` | Откат удалил критичные правила | Всегда оставляйте maintenance window, тестируйте rollback |
| `nftables: syntax error` | Ошибка в конфигурации | Проверьте синтаксис через `nft -c` (dry-run) |
| `iptables-persistent не сохраняет правила` | Пакет не установлен или сервис не запущен | Установите `iptables-persistent`, проверьте `systemctl status netfilter-persistent` |
| `Конфликт firewalld и iptables` | Оба инструмента пытаются управлять Netfilter | Отключите один из них: `systemctl disable --now firewalld` |
| `UFW не применяет IPv6 правила` | IPv6 отключен в `/etc/default/ufw` | Установите `IPV6=yes` в `/etc/default/ufw` |

## Рекомендации

### Best Practices

1. **Default deny** — по умолчанию весь трафик запрещен.
2. **Least privilege** — открывайте только необходимые порты.
3. **Logging** — логируйте блокировки для аудита.
4. **Automated validation** — проверяйте правила перед применением.
5. **Documentation** — документируйте каждое правило с обоснованием.
6. **Regular review** — регулярно пересматривайте правила, удаляйте устаревшие.
7. **Change management** — все изменения правил должны проходить через change management.
8. **IPv4/IPv6 parity** — убедитесь, что правила покрывают обе версии протокола.
9. **ipset для больших списков** — используйте `ipset`/nftables sets для списков >100 адресов.
10. **Testing in staging** — всегда тестируйте изменения в staging перед production.

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| UFW статус | `ufw status verbose` | Active, правильные политики |
| Firewalld статус | `firewall-cmd --list-all-zones` | Правила в нужных зонах |
| iptables правила | `iptables -L -n -v` | Правила применены |
| nftables правила | `nft list ruleset` | Правила применены |
| Проверка порта | `nc -zv <host> <port>` | Порт открыт/закрыт согласно правилам |
| Логи блокировок | `journalctl -u ufw` или `firewall-cmd --get-log-denied` | Логи присутствуют |
| IPv6 правила | `ip6tables -L -n -v` или `nft list ruleset family inet` | Правила применены для IPv6 |
| Persistence | `systemctl status nftables` / `iptables-save` | Правила сохраняются после перезагрузки |

## Дополнительная информация

### Смотрите также

- **[UFW — Uncomplicated Firewall](../../Linux/Networking/Settings/tools/ufw.md)** — теория и практика UFW.
- **[Firewalld: динамический межсетевой экран](../../Linux/Networking/Settings/tools/firewalld.md)** — zones, policies, rich rules.
- **[nftables — автоматизация через Ansible](../../Linux/Networking/Settings/tools/nftables/automation_with_ansible.md)** — продвинутые паттерны автоматизации nftables.
- **[Общие вопросы настройки межсетевых экранов в Linux](../../Linux/Networking/Settings/tools/firewall_common.md)** — conntrack, flowtables, ipset.
- **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)** — hardening файрвола, аудит.
- **[Ansible: Обнаружение дрейфа](./ansible_configuration_drift.md)** — проверка соответствия правил desired state.

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Потеря доступа при настройке файрвола | Открыт только порт 22, правило применено неверно | Используйте console access или VNC для восстановления |
| Слишком много правил | Файрвол работает медленно | Используйте ipset/nftables sets для больших списков IP |
| Откат правил файрвола | Критичные правила удалены | Всегда тестируйте rollback на staging, сохраняйте бэкапы |
| Конфликтующие правила | Неожиданное поведение файрвола | Используйте `iptables -L -n -v` для диагностики |
| Правила не сохраняются после перезагрузки | Нет persistence | Установите `iptables-persistent` или настройте firewalld/nftables service |
| Конфликт firewalld и iptables | Оба инструмента управляют Netfilter | Выберите один: для firewalld отключите iptables-service |
| IPv6 не фильтруется | Правила только для IPv4 | Добавьте правила для IPv6 или используйте `inet` семейство в nftables |
| Правила не применяются в Docker-среде | Docker перезаписывает iptables | Настройте `DOCKER-USER` chain или отключите iptables управление в Docker |
| SSH обрывается после деплоя правил | Правило для SSH не добавлено или имеет неправильный порядок | Используйте `insert` вместо `append`, проверяйте порядок цепочек |
