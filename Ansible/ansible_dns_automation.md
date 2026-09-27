# DNS Automation: PowerDNS, BIND, CoreDNS, Knot DNS

> **См. также:** [Ansible: Модули управления DNS](./Modules/ansible_dns_modules.md) — справочник модулей (`community.general.nsupdate`, `community.dns.lookup`), операций и диагностики.

## Определения

- **DNS Automation** — автоматизация управления DNS-записями через Ansible для обеспечения консистентности между инфраструктурой и DNS-разрешениями
- **PowerDNS** — open-source authoritative DNS-сервер с REST API и поддержкой multiple backends (gsqlite3, MySQL, PostgreSQL, LMDB)
- **BIND** — классический authoritative/recursive DNS-сервер (ISC Berkeley Internet Name Domain)
- **CoreDNS** — гибкий DNS-сервер с plugin-based архитектурой, написанный на Go
- **Knot DNS** — high-performance authoritative DNS-сервер от CZ.NIC с emphasis на безопасность и скорость
- **Dynamic DNS (DDNS)** — автоматическое обновление DNS-записей через RFC 2136 (nsupdate) или API при изменении IP-адресов
- **DNS as Code** — подход, при котором DNS-записи и зоны описываются в коде и применяются через Ansible playbooks
- **DNSSEC** — расширение DNS для криптографической подписи зон и защиты от подделки ответов (RFC 4033–4035)
- **TSIG** — секретный ключ для аутентификации динамических обновлений (DDNS) и zone transfers (RFC 2845)
- **Split-horizon DNS** — разделение DNS-ответов в зависимости от источника запроса (внутренний/внешний, vlan)
- **AXFR/IXFR** — полный (AXFR) и инкрементальный (IXFR) трансфер зон между primary и secondary серверами
- **Glue Record** — A/AAAA запись, размещённая в родительской зоне для разрешения NS-серверов внутри своей зоны
- **SOA (Start of Authority)** — запись с метаданными зоны (serial, refresh, retry, expire, minimum TTL)
- **PTR Record** — обратная запись для reverse DNS (IP → имя)
- **CAA Record** — Certification Authority Authorization, ограничивает CA, которые могут выпускать сертификаты для домена

---

## Основные концепции

### Архитектура DNS automation

DNS в инфраструктуре — критичный сервис. Его downtime означает потерю доступности всех сервисов. Автоматизация через Ansible обеспечивает:

- **Консистентность** — единый источник конфигурации в Git
- **Безопасность** — TSIG-ключи и секреты хранятся в Ansible Vault
- **Воспроизводимость** — deployment воспроизводим на любом окружении
- **Откат** — Git revert + playbook для отката изменений

Архитектура automation:

```text
┌──────────────────────────────────────────────┐
│               Control Node                    │
│  Git + Vault + Inventory + Playbooks + Roles  │
└──────────────────────┬───────────────────────┘
                       │ SSH / API
           ┌───────────┼───────────┐
           │           │           │
     ┌─────▼────┐ ┌────▼─────┐ ┌──▼────────┐
     │ ns1      │ │ ns2      │ │ pdns-api  │
     │(master)  │ │(slave)   │ │(PowerDNS) │
     └──────────┘ └──────────┘ └───────────┘
```

### Authoritative vs Recursive

- **Authoritative Server** — хранит эталонные данные для конкретных зон. Отвечает только на запросы по своим зонам.
- **Recursive Server** (Resolver) — выполняет полное разрешение имён, запрашивая данные по иерархии DNS. Кэширует ответы.

### Типы DNS серверов

| Тип | Назначение | Примеры | Примечание |
| :--- | :--- | :--- | :--- |
| Authoritative | Хранение зон | BIND, PowerDNS, Knot, CoreDNS | Имеет SOA для зон |
| Recursive | Разрешение имён | Unbound, BIND recursive, PowerDNS Recursor | Кэширует ответы |
| Forwarding | Переадресация запросов | BIND forward, dnsmasq | Для split-horizon |
| Split-horizon | Разделение ответов | BIND views, CoreDNS zones | Внутренний/внешний |

### Архитектура зон

- **Primary/Master** — единственный источник правды для зоны. Разрешены динамические обновления.
- **Secondary/Slave** — получает данные через AXFR/IXFR от primary. Автоматически обновляется.
- **AXFR** — полный трансфер зоны. Используется при инициализации secondary или при больших изменениях.
- **IXFR** — инкрементальный трансфер. Передаёт только изменения, снижает нагрузку.
- **NOTIFY** — primary уведомляет secondary об изменениях через NOTIFY сообщение (RFC 1996).

### Типы записей

| Тип | Назначение | Пример |
| :--- | :--- | :--- |
| A | IPv4 адрес | `web.example.com. 3600 IN A 10.0.1.10` |
| AAAA | IPv6 адрес | `web.example.com. 3600 IN AAAA 2001:db8::1` |
| CNAME | Алиас | `www.example.com. 300 IN CNAME web.example.com.` |
| MX | Почтовый сервер | `@ 3600 IN MX 10 mail.example.com.` |
| TXT | Текстовые данные | `@ 3600 IN TXT "v=spf1 include:_spf.google.com ~all"` |
| SRV | Сервисная запись | `_sip._tcp. 3600 IN SRV 10 60 5060 sip.example.com.` |
| PTR | Обратная запись | `10.1.0.10.in-addr.arpa. 3600 IN PTR web.example.com.` |
| CAA | Авторизация CA | `@ 3600 IN CAA 0 issue "letsencrypt.org"` |
| SOA | Начало полномочий | `@ 3600 IN SOA ns1.example.com. admin.example.com. ( 2024011501 3600 900 604800 3600 )` |
| NS | Сервер имён | `@ 3600 IN NS ns1.example.com.` |

### Безопасность

- **DNSSEC** — RRSIG, DNSKEY, DS, NSEC/NSEC3 записи обеспечивают целостность данных.
- **TSIG** — HMAC-SHA256 ключ для аутентификации DDNS и zone transfers.
- **ACL** — ограничение доступа к рекурсии, трансферу, динамическим обновлениям.
- **Rate Limiting** — `fetches-per-server`, `max-clients-per-query` в PowerDNS Recursor/Authoritative.
- **Query Restrictions** — `allow-query`, `allow-transfer`, `allow-update` в BIND.

### Reverse DNS

Reverse DNS (PTR) критичен для почты (SPF, DKIM, DMARC), logging, troubleshooting. Обычно делегируется регистратором на подсеть. В Ansible автоматизируется создание reverse zone и PTR записей.

### Split-horizon DNS

Разделение DNS-ответов по источнику запроса:
- Внутренние клиенты получают внутренние IP
- Внешние клиенты получают внешние IP или NXDOMAIN

Реализуется через:
- BIND views (`match-clients`)
- CoreDNS `zones` plugin
- PowerDNS `Lua` records или `Gravity`

### Ansible для DNS

Ansible обеспечивает:
- Установку и конфигурацию DNS-серверов через `ansible.builtin.apt`/`yum`/`package`
- Управление конфигурационными файлами через `ansible.builtin.template`
- Динамическое управление записями через `ansible.builtin.uri` (PowerDNS API)
- Динамические обновления через `nsupdate` (BIND, PowerDNS)
- Валидацию через `named-checkconf`, `named-checkzone`, `pdnsutil check-zone`
- Секреты через `{{ vault_* }}` переменные

---

## Предварительные требования

### Системные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| Control Node | Ansible 2.20+, Python 3.12+ | Ansible 2.21+, Python 3.12+ |
| Managed Node | Python 3.9+, OpenSSH | Python 3.11+, OpenSSH 8.0+ |
| PowerDNS Authoritative | 5.0+ (4.8 EOL) | 5.1+ |
| PowerDNS Recursor | 5.2+ | 5.4+ |
| BIND | 9.20+ (9.18 EOL) | 9.20+ |
| CoreDNS | 1.11+ | 1.14+ |
| Knot DNS | 3.5+ | 3.6+ |
| База данных (PowerDNS) | SQLite3 / MySQL 5.7 / PostgreSQL 12 | PostgreSQL 14+ / MySQL 8.0+ |

### Проверка окружения

```bash
# Проверка версий
ansible --version
# ansible [core 2.21.0]
python3 --version
# Python 3.12.4

# Проверка доступности хостов
ansible dns -i inventories/production/hosts.ini -m ping

# Проверка модулей
ansible-doc -l | grep -E 'uri|template|service|apt|yum'
```

### Структура инвентаря

```ini
# inventory.ini
[dns-master]
ns1 ansible_host=10.0.0.1 bind_role=master pdns_api_port=8081

[dns-slaves]
ns2 ansible_host=10.0.0.2 bind_role=slave
ns3 ansible_host=10.0.0.3 bind_role=slave

[dns:children]
dns-master
dns-slaves

[dns:vars]
ansible_user=deploy
ansible_become=yes
ansible_ssh_private_key_file=~/.ssh/deploy_key
bind_domain="example.com"
bind_ns_primary="ns1.example.com"
bind_ns_secondary="ns2.example.com"
bind_ttl=3600
bind_soa_email="admin.example.com"
pdns_api_key="{{ vault_pdns_api_key }}"
```

### Модули и коллекции

```bash
# Установка необходимых коллекций
ansible-galaxy collection install community.general

# Проверка установленных коллекций
ansible-galaxy collection list | grep -E 'community.general|community.dns'
```

---

## Практические сценарии

### Сценарий 1: PowerDNS installation и конфигурация

Установка PowerDNS Authoritative Server с backend SQLite3 на Ubuntu 22.04/24.04.

```yaml
---
- name: PowerDNS installation and configuration
  hosts: dns_servers
  become: true
  vars:
    pdns_listen_port: 53
    pdns_api_port: 8081
    pdns_api_key: "{{ vault_pdns_api_key }}"
    pdns_backends:
      - gsqlite3
    pdns_db_path: "/var/lib/powerdns/pdns.sqlite3"
  tasks:
    - name: Install PowerDNS packages
      ansible.builtin.apt:
        name:
          - pdns-server
          - pdns-backend-gsqlite3
          - pdns-tools
        state: present
        update_cache: true

    - name: Create database directory
      ansible.builtin.file:
        path: "{{ pdns_db_path | dirname }}"
        state: directory
        owner: pdns
        group: pdns
        mode: "0750"

    - name: Configure PowerDNS
      ansible.builtin.template:
        src: templates/pdns.conf.j2
        dest: /etc/powerdns/pdns.conf
        mode: "0640"
        owner: root
        group: pdns
      notify: Restart powerdns

    - name: Enable and start PowerDNS
      ansible.builtin.systemd:
        name: pdns
        enabled: true
        state: started

    - name: Open firewall ports
      ansible.posix.firewalld:
        port: "{{ item }}"
        permanent: true
        state: enabled
      loop:
        - "53/tcp"
        - "53/udp"
        - "{{ pdns_api_port }}/tcp"

  handlers:
    - name: Restart powerdns
      ansible.builtin.systemd:
        name: pdns
        state: restarted
```

**Шаблон `templates/pdns.conf.j2`:**

```ini
# Auto-generated by Ansible
launch=gsqlite3
gsqlite3-database=/var/lib/powerdns/pdns.sqlite3

api=yes
api-key={{ pdns_api_key }}
listen-address={{ ansible_default_ipv4.address }}
port={{ pdns_listen_port }}

webserver=yes
webserver-address=127.0.0.1
webserver-port={{ pdns_api_port }}

loglevel=3
log-dns-queries=yes
```

**Запуск:**

```bash
# Проверка inventory
ansible-inventory -i inventory.ini --list

# Dry-run
ansible-playbook -i inventory.ini powerdns.yml --check

# Применение
ansible-playbook -i inventory.ini powerdns.yml
```

### Сценарий 2: Управление зонами через PowerDNS API

Создание зоны, добавление записей A, AAAA, CNAME, MX, TXT, SRV, PTR, CAA через API.

```yaml
---
- name: DNS zone management via PowerDNS API
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    pdns_api_url: "http://dns.internal:8081"
    pdns_api_key: "{{ vault_pdns_api_key }}"
    pdns_server_id: "localhost"
  tasks:
    - name: Create zone
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones"
        method: POST
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          name: "example.com."
          kind: "native"
          nameservers:
            - "ns1.example.com."
            - "ns2.example.com."
          rrsets:
            - name: "ns1.example.com."
              type: "A"
              ttl: 3600
              records:
                - content: "10.0.0.1"
                  disabled: false
            - name: "ns2.example.com."
              type: "A"
              ttl: 3600
              records:
                - content: "10.0.0.2"
                  disabled: false
        status_code: 201
      delegate_to: localhost

    - name: Add A record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "web.example.com."
              type: "A"
              ttl: 300
              changetype: "REPLACE"
              records:
                - content: "10.0.1.10"
                  disabled: false
                - content: "10.0.1.11"
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add AAAA record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "web.example.com."
              type: "AAAA"
              ttl: 300
              changetype: "REPLACE"
              records:
                - content: "2001:db8::1"
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add CNAME record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "app.example.com."
              type: "CNAME"
              ttl: 300
              changetype: "REPLACE"
              records:
                - content: "web.example.com."
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add MX record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "example.com."
              type: "MX"
              ttl: 3600
              changetype: "REPLACE"
              records:
                - content: "10 mx1.mail.example.com."
                  disabled: false
                - content: "20 mx2.mail.example.com."
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add TXT record (SPF)
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "example.com."
              type: "TXT"
              ttl: 3600
              changetype: "REPLACE"
              records:
                - content: "\"v=spf1 include:_spf.google.com ~all\""
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add SRV record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "_sip._tcp.example.com."
              type: "SRV"
              ttl: 3600
              changetype: "REPLACE"
              records:
                - content: "10 60 5060 sip.example.com."
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Add CAA record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "example.com."
              type: "CAA"
              ttl: 3600
              changetype: "REPLACE"
              records:
                - content: "0 issue \"letsencrypt.org\""
                  disabled: false
                - content: "0 issuewild \"letsencrypt.org\""
                  disabled: false
        status_code: 200
      delegate_to: localhost
```

### Сценарий 3: Dynamic DNS через nsupdate

Автоматическое обновление PTR записей при изменении IP адресов хостов через RFC 2136.

```yaml
---
- name: DDNS via nsupdate
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    ddns_server: "dns.internal"
    ddns_key_name: "ddns-key"
    ddns_key_secret: "{{ vault_ddns_key_secret }}"
    ddns_zone: "internal.example.com"
    ddns_ttl: 300
  tasks:
    - name: Build nsupdate commands
      ansible.builtin.set_fact:
        nsupdate_cmds: >-
          {%
            set cmds = []
          %}
          {%
            for host in groups['all']
          %}
          {%
            set hostvars_data = hostvars[host]
          %}
          {%
            if hostvars_data.ansible_host is defined and hostvars_data.dns_name is defined
          %}
          {%
            set _ = cmds.extend([
              'server ' + ddns_server,
              'key ' + ddns_key_name + ' ' + ddns_key_secret,
              'update delete ' + hostvars_data.dns_name + '.' + ddns_zone + ' A',
              'update add ' + hostvars_data.dns_name + '.' + ddns_zone + ' ' + ddns_ttl + ' A ' + hostvars_data.ansible_host,
              'send'
            ])
          %}
          {%
            endfor
          %}
          {{ cmds }}

    - name: Apply DDNS updates
      ansible.builtin.command: nsupdate -v -
      args:
        stdin: "{{ nsupdate_cmds | join('\n') }}\n"
      register: ddns_result
      changed_when: "'update' in ddns_result.stdout"

    - name: Display DDNS result
      ansible.builtin.debug:
        var: ddns_result.stdout_lines
```

### Сценарий 4: BIND automation (обзор)

Детальная автоматизация BIND (установка, конфигурация, зоны, TSIG, ACL, rolling updates, molecule tests) описана в [BIND: Автоматизация управления (IaC)](../Linux/Networking/Services/BIND/automation-iac.md).

Краткий обзор playbook для BIND:

```yaml
---
- name: Deploy BIND DNS servers
  hosts: dns
  become: yes
  roles:
    - bind

  post_tasks:
    - name: Verify DNS resolution
      ansible.builtin.command: dig @{{ inventory_hostname }} {{ bind_domain }} A +short
      register: dns_check
      changed_when: false

    - name: Fail if DNS is not working
      ansible.builtin.fail:
        msg: "DNS resolution failed on {{ inventory_hostname }}"
      when: dns_check.stdout == ""
```

### Сценарий 5: CoreDNS automation

CoreDNS используется как authoritative и recursive resolver, часто в контейнерах и bare-metal окружениях.

```yaml
---
- name: CoreDNS installation and configuration
  hosts: dns
  become: true
  vars:
    coredns_version: "1.14.6"
    coredns_config_dir: "/etc/coredns"
    coredns_bin: "/usr/local/bin/coredns"
  tasks:
    - name: Download CoreDNS binary
      ansible.builtin.get_url:
        url: "https://github.com/coredns/coredns/releases/download/v{{ coredns_version }}/coredns_{{ coredns_version }}_linux_amd64.tgz"
        dest: "/tmp/coredns.tgz"
        mode: "0644"

    - name: Extract CoreDNS binary
      ansible.builtin.unarchive:
        src: "/tmp/coredns.tgz"
        dest: "/usr/local/bin"
        remote_src: true
        mode: "0755"

    - name: Deploy Corefile
      ansible.builtin.template:
        src: Corefile.j2
        dest: "{{ coredns_config_dir }}/Corefile"
        mode: "0644"
        owner: root
        group: root
      notify: Restart coredns

    - name: Create systemd service
      ansible.builtin.copy:
        content: |
          [Unit]
          Description=CoreDNS
          After=network.target

          [Service]
          ExecStart={{ coredns_bin }} -conf {{ coredns_config_dir }}/Corefile
          Restart=always
          LimitNOFILE=65536

          [Install]
          WantedBy=multi-user.target
        dest: /etc/systemd/system/coredns.service
        mode: "0644"
      notify: Restart coredns

    - name: Enable and start CoreDNS
      ansible.builtin.systemd:
        name: coredns
        enabled: true
        state: started

  handlers:
    - name: Restart coredns
      ansible.builtin.systemd:
        name: coredns
        state: restarted
```

**Шаблон `Corefile.j2`:**

```
. {
    log
    errors
    cache 3600
    forward . 8.8.8.8 8.8.4.4
}

example.com {
    file /etc/coredns/db.example.com
    log
}
```

### Сценарий 6: Knot DNS automation

Knot DNS — authoritative сервер с emphasis на безопасность, скорость и DNSSEC.

```yaml
---
- name: Knot DNS installation and configuration
  hosts: dns
  become: true
  vars:
    knot_version: "3.5"
    knot_conf_dir: "/etc/knot"
    knot_zone_dir: "/var/lib/knot/zones"
    knot_key_dir: "{{ knot_conf_dir }}/keys"
  tasks:
    - name: Install Knot DNS
      ansible.builtin.apt:
        name:
          - knotd
          - knot-utils
          - keymgr
        state: present
        update_cache: true

    - name: Create directories
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
        owner: knot
        group: knot
        mode: "0750"
      loop:
        - "{{ knot_zone_dir }}"
        - "{{ knot_key_dir }}"

    - name: Deploy knot.conf
      ansible.builtin.template:
        src: knot.conf.j2
        dest: "{{ knot_conf_dir }}/knot.conf"
        mode: "0640"
        owner: root
        group: knot
      notify: Reload knot

    - name: Deploy zone file
      ansible.builtin.template:
        src: zone.example.com.j2
        dest: "{{ knot_zone_dir }}/example.com.zone"
        mode: "0640"
        owner: knot
        group: knot
      notify: Reload knot

    - name: Enable and start Knot
      ansible.builtin.systemd:
        name: knot
        enabled: true
        state: started

  handlers:
    - name: Reload knot
      ansible.builtin.systemd:
        name: knot
        state: reloaded
```

**Шаблон `knot.conf.j2`:**

```
server:
    listen: 10.0.0.1@53
    listen: 10.0.0.1@53#tcp
    user: knot:knot
    pidfile: /run/knot/knot.pid

zone:
    storage: {{ knot_zone_dir }}
    file: {{ knot_zone_dir }}/{{ item.name }}.zone
    master:
      - 10.0.0.1
    acl:
      - id: xfr-out
        address: 10.0.0.2
        action: transfer
      - id: xfr-out
        address: 10.0.0.3
        action: transfer
    notify:
      - 10.0.0.2
      - 10.0.0.3
```

### Сценарий 7: Split-horizon DNS

Разделение DNS-ответов для внутренних и внешних клиентов.

**BIND approach (views):**

```yaml
---
- name: Deploy split-horizon BIND
  hosts: dns
  become: yes
  vars:
    bind_internal_net: "10.0.0.0/8"
    bind_external_net: "0.0.0.0/0"
    bind_internal_ttl: 300
    bind_external_ttl: 3600
  tasks:
    - name: Deploy named.conf with views
      ansible.builtin.template:
        src: named.conf.views.j2
        dest: /etc/bind/named.conf.views
        mode: "0644"
        owner: root
        group: bind
        validate: "named-checkconf %s"
      notify: Reload bind
```

**Шаблон `named.conf.views.j2`:**

```
view "internal" {
    match-clients { {{ bind_internal_net }}; };
    recursion yes;
    allow-query { any; };

    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.internal";
        allow-transfer { key "transfer-key"; };
        also-notify { 10.0.0.2; };
    };
};

view "external" {
    match-clients { any; };
    recursion no;
    allow-query { any; };

    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.external";
        allow-transfer { key "transfer-key"; };
    };
};
```

**CoreDNS approach (split zones):**

```
internal.example.com {
    hosts {
        10.0.1.10 web.internal
        10.0.1.20 api.internal
    }
}

external.example.com {
    file /etc/coredns/db.example.com
}
```

### Сценарий 8: Reverse DNS

Автоматизация PTR записей для reverse DNS.

```yaml
---
- name: Deploy reverse DNS zone
  hosts: dns
  become: yes
  vars:
    reverse_zone: "1.168.192.in-addr.arpa"
    reverse_network: "192.168.1.0/24"
  tasks:
    - name: Generate PTR records from inventory
      ansible.builtin.set_fact:
        ptr_records: >-
          {%
            set records = []
          %}
          {%
            for host in groups['all']
          %}
          {%
            set h = hostvars[host]
          %}
          {%
            if h.ansible_host is defined and h.ansible_host.startswith('192.168.1.')
          %}
          {%
            set octet = h.ansible_host.split('.')[3]
          %}
          {%
            set _ = records.append({
              'name': octet,
              'type': 'PTR',
              'value': h.inventory_hostname + '.example.com.'
            })
          %}
          {%
            endif
          %}
          {%
            endfor
          %}
          {{ records }}

    - name: Deploy reverse zone file
      ansible.builtin.template:
        src: reverse.zone.j2
        dest: /etc/bind/zones/{{ reverse_zone }}
        mode: "0644"
        owner: bind
        group: bind
        validate: "named-checkzone {{ reverse_zone }} %s"
      notify: Reload bind
```

**Шаблон `reverse.zone.j2`:**

```dns
$TTL 3600
@   IN  SOA  ns1.example.com. admin.example.com. (
        2024011501  ; Serial
        3600        ; Refresh
        900         ; Retry
        1209600     ; Expire
        3600        ; Minimum TTL
        )

@           IN  NS   ns1.example.com.
@           IN  NS   ns2.example.com.
{% for record in ptr_records %}
{{ record.name }}  IN  PTR  {{ record.value }}
{% endfor %}
```

### Сценарий 9: DNSSEC signing

Подпись зоны DNSSEC через BIND.

```yaml
---
- name: DNSSEC signing with BIND
  hosts: dns-master
  become: yes
  vars:
    bind_dnssec: true
    bind_key_directory: "/etc/bind/keys"
  tasks:
    - name: Create key directory
      ansible.builtin.file:
        path: "{{ bind_key_directory }}"
        state: directory
        owner: bind
        group: bind
        mode: "0750"

    - name: Generate KSK
      ansible.builtin.command: >
        dnssec-keygen -a RSASHA256 -b 2048 -n ZONE -r /dev/urandom example.com
      args:
        chdir: "{{ bind_key_directory }}"
        creates: "{{ bind_key_directory }}/Kexample.com.*.key"

    - name: Generate ZSK
      ansible.builtin.command: >
        dnssec-keygen -a RSASHA256 -b 1024 -n ZONE -r /dev/urandom example.com
      args:
        chdir: "{{ bind_key_directory }}"
        creates: "{{ bind_key_directory }}/Kexample.com.*.key"

    - name: Sign zone
      ansible.builtin.command: >
        dnssec-signzone -S -o example.com db.example.com
      args:
        chdir: "{{ bind_key_directory }}"
        creates: "{{ bind_key_directory }}/db.example.com.signed"

    - name: Deploy signed zone
      ansible.builtin.copy:
        src: "{{ bind_key_directory }}/db.example.com.signed"
        dest: /etc/bind/zones/db.example.com.signed
        mode: "0644"
        owner: bind
        group: bind
```

### Сценарий 10: Disaster Recovery (backup/restore)

Резервное копирование и восстановление зон.

```yaml
---
- name: DNS backup
  hosts: dns-master
  become: yes
  vars:
    backup_dir: "/var/backups/dns"
    backup_retention: 7
  tasks:
    - name: Create backup directory
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        owner: root
        group: root
        mode: "0750"

    - name: Backup BIND zone files
      ansible.builtin.archive:
        path: /etc/bind/zones/
        dest: "{{ backup_dir }}/bind-zones-{{ ansible_date_time.iso8601_basic }}.tar.gz"
        format: gz

    - name: Backup PowerDNS database
      ansible.builtin.command: >
        sqlite3 /var/lib/powerdns/pdns.sqlite3 .dump > {{ backup_dir }}/pdns-{{ ansible_date_time.iso8601_basic }}.sql
      args:
        creates: "{{ backup_dir }}/pdns-{{ ansible_date_time.iso8601_basic }}.sql"

    - name: Remove old backups
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "*.tar.gz,*.sql"
        age: "{{ backup_retention }}d"
      register: old_backups

    - name: Delete old backups
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"
```

### Сценарий 11: ACME DNS-01

Автоматизация выдачи сертификатов через DNS-01 challenge (Let's Encrypt).

```yaml
---
- name: ACME DNS-01 challenge via PowerDNS
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    acme_domain: "example.com"
    acme_challenge: "_acme-challenge.example.com"
    acme_token: "{{ vault_acme_token }}"
    pdns_api_url: "http://dns.internal:8081"
    pdns_api_key: "{{ vault_pdns_api_key }}"
    pdns_server_id: "localhost"
  tasks:
    - name: Add ACME challenge TXT record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/{{ acme_domain }}."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "{{ acme_challenge }}."
              type: "TXT"
              ttl: 60
              changetype: "REPLACE"
              records:
                - content: "\"{{ acme_token }}\""
                  disabled: false
        status_code: 200
      delegate_to: localhost

    - name: Wait for propagation
      ansible.builtin.pause:
        seconds: 15

    - name: Request certificate via certbot
      ansible.builtin.command: >
        certbot certonly --dns-route53 --dns-route53-propagation-seconds 15
        -d {{ acme_domain }} --agree-tos --email admin@example.com --non-interactive
      register: certbot_result
      changed_when: "'Congratulations' in certbot_result.stdout"

    - name: Remove ACME challenge record
      ansible.builtin.uri:
        url: "{{ pdns_api_url }}/api/v1/servers/{{ pdns_server_id }}/zones/{{ acme_domain }}."
        method: PATCH
        headers:
          X-API-Key: "{{ pdns_api_key }}"
          Content-Type: "application/json"
        body_format: json
        body:
          rrsets:
            - name: "{{ acme_challenge }}."
              type: "TXT"
              ttl: 60
              changetype: "DELETE"
              records:
                - content: "\"{{ acme_token }}\""
                  disabled: false
        status_code: 200
      delegate_to: localhost
```

### Сценарий 12: Monitoring и health checks

Проверка доступности DNS через Ansible.

```yaml
---
- name: DNS health check
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    dns_servers:
      - "10.0.0.1"
      - "10.0.0.2"
      - "10.0.0.3"
    dns_check_domain: "example.com"
    dns_check_type: "A"
  tasks:
    - name: Check DNS resolution
      ansible.builtin.command: dig +short +timeout=5 @{{ item }} {{ dns_check_domain }} {{ dns_check_type }}
      register: dig_result
      loop: "{{ dns_servers }}"
      ignore_errors: true
      changed_when: false

    - name: Report results
      ansible.builtin.debug:
        msg: "{{ item.item }} -> {{ item.stdout | default('FAILED') }}"
      loop: "{{ dig_result.results }}"

    - name: Fail if any server failed
      ansible.builtin.fail:
        msg: "DNS check failed on {{ item.item }}"
      when: item.stdout == ""
      loop: "{{ dig_result.results }}"
```

---

## Операции и команды

### Директивы управления деплоем

| Директива | Назначение | Пример |
| :--- | :--- | :--- |
| `serial` | Ограничивает количество хостов в батче | `serial: "25%"` |
| `max_fail_percentage` | Максимальный процент ошибок в батче | `max_fail_percentage: 10` |
| `strategy` | Алгоритм планирования (linear/free) | `strategy: linear` |
| `any_errors_fatal` | Прерывает выполнение при любой ошибке | `any_errors_fatal: true` |
| `ignore_unreachable` | Пропускает недоступные хосты | `ignore_unreachable: true` |
| `throttle` | Ограничивает количество параллельных задач | `throttle: 5` |
| `async/poll` | Длинные операции без ожидания | `async: 3600; poll: 0` |
| `delegate_to` | Выполнение задачи на control node | `delegate_to: localhost` |
| `run_once` | Выполнение один раз для всего плейбука | `run_once: true` |
| `meta: clear_host_errors` | Сброс ошибок хостов перед повторным запуском | `meta: clear_host_errors` |
| `pre_tasks/post_tasks` | Задачи до/после основных | `pre_tasks`, `post_tasks` |

### Полезные команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `dig` | Проверка DNS | `dig @10.0.0.1 example.com A +short` |
| `nslookup` | Проверка DNS (Windows/Linux) | `nslookup web.example.com 10.0.0.1` |
| `host` | Простая проверка DNS | `host -t A web.example.com` |
| `rndc` | Управление BIND | `rndc notify example.com` |
| `rndc retransfer` | Принудительный трансфер | `rndc retransfer example.com` |
| `nsupdate` | Динамическое обновление DNS | `nsupdate -k key.name` |
| `pdnsutil` | Управление PowerDNS | `pdnsutil list-zone example.com` |
| `pdns_control` | Управление PowerDNS daemon | `pdns_control cycle-graceful` |
| `named-checkconf` | Валидация BIND конфига | `named-checkconf /etc/bind/named.conf` |
| `named-checkzone` | Валидация BIND зоны | `named-checkzone example.com /etc/bind/zones/db.example.com` |
| `kdig` | DNS диагностика (Knot) | `kdig @10.0.0.1 example.com A` |
| `knotc` | Управление Knot DNS | `knotc zone-check example.com` |
| `keymgr` | Управление DNSSEC ключами Knot | `keymgr generate example.com` |
| `pdnsutil check-zone` | Валидация зоны PowerDNS | `pdnsutil check-zone example.com` |

---

## Диагностика

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `SERVFAIL` | Ошибка конфигурации, DNSSEC validation failed, недоступен upstream | Проверить `journalctl -u pdns/named`, `dig +dnssec`, проверить DNSSEC chain |
| `NXDOMAIN` | Запись или зона не существуют | Проверить `dig`, `named-checkzone`, наличие зоны на authoritative сервере |
| `REFUSED` | Сервер не отвечает на запрос (ACL) | Проверить `allow-query`, `firewalld`, `named-checkconf` |
| Zone transfer failed | Неверный TSIG ключ, ACL, serial mismatch | Проверить `allow-transfer`, TSIG ключи, `rndc notify`, `dig AXFR` |
| `nsupdate update failed` | Неверный TSIG ключ, сервер недоступен | Проверить `key` directive, `allow-update`, сетевое подключение |
| High latency / timeout | Сетевые проблемы, overload, slow queries | Проверить `dig +time=5`, `top`, `netstat`, `journalctl` |
| DNSSEC validation failed | RRSIG expired, missing DS, key rollover | Проверить `dig +dnssec +multi`, DS запись у регистратора, срок действия ключей |
| AXFR/IXFR не работает | Serial не увеличивается, NOTIFY не отправляется | Увеличить serial, `rndc notify`, проверить `also-notify` |
| Slave не синхронизируется | Master недоступен, ACL запрещает трансфер | Проверить `masters` directive, TSIG, сеть |

### Диагностические команды

```bash
# Проверка доступности хостов перед деплоем
ansible dns -i inventory.ini -m ping

# Просмотр фактов для проверки готовности
ansible dns -i inventory.ini -m setup | grep ansible_host

# Проверка запущенных сервисов
ansible dns -i inventory.ini -m service_facts

# Проверка DNS-разрешения с конкретного сервера
ansible dns-master -i inventory.ini -m command -a "dig +short +timeout=5 example.com A"

# Проверка конфигурации BIND
ansible dns-master -i inventory.ini -m command -a "named-checkconf /etc/bind/named.conf"

# Проверка зоны BIND
ansible dns-master -i inventory.ini -m command -a "named-checkzone example.com /etc/bind/zones/db.example.com"

# Проверка конфигурации Knot
ansible dns -i inventory.ini -m command -a "knotc checkconf"

# Проверка статуса Knot
ansible dns -i inventory.ini -m command -a "knotc status"

# Проверка PowerDNS API
ansible localhost -i inventory.ini -m uri -a "url=http://dns.internal:8081/api/v1/servers/localhost/zones method=GET headers=X-API-Key:{{ vault_pdns_api_key }}"

# Проверка логов
ansible dns -i inventory.ini -m command -a "journalctl -u pdns/named -n 100 --no-pager"

# Проверка zone transfer
ansible dns -i inventory.ini -m command -a "dig @10.0.0.1 example.com AXFR +noauth | head -20"
```

---

## Лучшие практики

- **Централизованное хранение конфигурации** — все изменения DNS проходят через Git + playbook. Никаких ручных редактирований на production.
- **Атомарные изменения** — обновляйте одну зону/запись за один playbook run. Сложные изменения разбивайте на stages с проверкой.
- **Rolling updates** — обновляйте secondary-серверы раньше primary. Всегда должен быть доступен минимум один authoritative сервер.
- **Валидация перед деплоем** — используйте `named-checkconf`, `named-checkzone`, `pdnsutil check-zone` в каждом playbook.
- **Splittable TTL** — используйте низкие TTL (60–300s) для записей, которые могут меняться часто (LB, failover). Для статичных записей TTL 3600–86400.
- **DNSSEC** — подписывайте все зоны. Используйте KSK/ZSK split. Следите за сроками действия ключей.
- **TSIG** — используйте разные TSIG ключи для DDNS, zone transfer, NOTIFY. Ротируйте ключи регулярно.
- **Backup** — резервное копирование зон (BIND: zone files; PowerDNS: database dump) перед каждым изменением.
- **Мониторинг** — настройте алерты на `SERVFAIL`, `NXDOMAIN`, latency, zone transfer failures.
- **Disaster Recovery** — тестируйте восстановление из backup на dev-окружении. Документируйте процедуру.
- **ACL и Rate Limiting** — ограничьте рекурсию внутренней сетью, ограничьте zone transfers только secondary серверами.
- **HashiCorp Vault** — храните TSIG ключи, API ключи, vault пароли в Vault. Не храните секреты в Git.
- **Тестирование** — используйте Molecule + Docker для тестирования ролей перед продом.
- **Разделение окружений** — отдельные inventory, зоны, credentials для dev/staging/prod.
- **Split-horizon** — используйте views (BIND) или separate zones (CoreDNS) для разделения внутреннего/внешнего DNS.
- **Reverse DNS** — автоматизируйте PTR записи. Без reverse DNS многие сервисы (почта, logging) работают некорректно.
- **Метрики** — экспортируйте метрики DNS (Prometheus) для мониторинга query rates, cache hit ratio, error rates.

---

## Дополнительная информация

### Связанные разделы

- [BIND: Автоматизация управления (IaC)](../Linux/Networking/Services/BIND/automation-iac.md) — детальная автоматизация BIND через Ansible roles
- [DNS в CI/CD: автоматическая верификация и smoke-тесты](../Linux/Diagnostics/Networking/dns/dns_ci_cd_integration.md) — DNS проверки в pipeline
- [ansible_network_automation.md](ansible_network_automation.md) — DNS для сетевого оборудования

### Стандарты и RFC

- RFC 1035 — базовый стандарт DNS
- RFC 2136 — Dynamic DNS updates (nsupdate)
- RFC 2845 — TSIG
- RFC 4033–4035 — DNSSEC
- RFC 1996 — DNS NOTIFY
- RFC 2782 — SRV records
- RFC 4408 — SPF
- RFC 6376 — DKIM
- RFC 7489 — DMARC
- RFC 8659 — CAA records
