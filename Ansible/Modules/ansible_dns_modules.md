# Ansible: Модули управления DNS

## Определения

**Модули управления DNS** — группа инструментов Ansible для автоматизации развертывания, конфигурации и управления DNS-записями и серверами. Включает декларативные модули из `community.general` (`nsupdate`), встроенные модули (`template`, `uri`, `command`, `service`), а также специализированные модули коллекции `community.dns` для интеграции с публичными DNS-провайдерами.

**DNS-сервер** — компонент инфраструктуры, отвечающий за разрешение доменных имен в IP-адреса. В контексте Ansible автоматизируется развертывание как authoritative, так и recursive DNS-серверов (BIND, PowerDNS, CoreDNS, Knot DNS).

**Dynamic DNS (DDNS)** — механизм автоматического обновления DNS-записей при изменении IP-адресов хостов. Реализуется через RFC 2136 (`nsupdate`) или через REST API DNS-серверов.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `namespace.collection.module`. Использование FQCN является обязательным стандартом для предотвращения конфликтов имен.

**Идемпотентность** — свойство модуля, гарантирующее, что повторные запуски не приведут к изменениям, если система уже находится в целевом состоянии. Для модулей управления DNS критично при обновлении записей через `nsupdate` и `uri`.

**Zone Transfer (AXFR/IXFR)** — механизм репликации DNS-зон между primary и secondary серверами. AXFR передаёт полную зону, IXFR — только изменения.

**TSIG (Transaction SIGnature)** — механизм аутентификации динамических обновлений (DDNS) и zone transfers с использованием HMAC-ключей (RFC 2845).

**DNSSEC (DNS Security Extensions)** — расширение DNS для криптографической подписи зон и защиты от подделки ответов (RFC 4033–4035). Использует RRSIG, DNSKEY, DS, NSEC/NSEC3 записи.

**SOA (Start of Authority)** — ресурсная запись с метаданными зоны: serial, refresh, retry, expire, minimum TTL.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ | |
| **community.general** | 6.0+ | Актуальная | Содержит `nsupdate` |
| **community.dns** | 2.0+ | 4.1+ | Lookup plugins, Hetzner/HostTech модули |
| **BIND** | 9.18+ | 9.20+ | 9.18 EOL Q2 2026 |
| **PowerDNS Authoritative** | 5.0+ | 5.1+ | 4.8 EOL |
| **PowerDNS Recursor** | 5.2+ | 5.4+ | |
| **CoreDNS** | 1.11+ | 1.14+ | 1.14.7 актуальна (Aug 2026) |
| **Knot DNS** | 3.2+ | 3.5+ | 3.6.0 актуальна |
| **Python** (target) | 3.9+ | 3.12+ | |

**Установка коллекций:**
```bash
ansible-galaxy collection install community.general
ansible-galaxy collection install community.dns
```

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible-doc -l community.general | grep -E "nsupdate|bind|dns"
# → community.general.nsupdate

ansible-doc -l community.dns | head -10
# → community.dns.hetzner_dns_record
# → community.dns.hosttech_dns_record
# → community.dns.nameserver_info
# → community.dns.wait_for_txt

dig @127.0.0.1 example.com
# → 93.184.216.34
```

## Архитектура и принципы работы

DNS automation через Ansible строится на трёх уровнях:

### 1. Уровень конфигурации серверов

На этом уровне Ansible управляет:
- Установкой пакетов DNS-серверов (`bind9`, `pdns-server`, `coredns`, `knotd`)
- Развёртыванием конфигурационных файлов через `ansible.builtin.template`
- Валидацией конфигурации (`named-checkconf`, `named-checkzone`, `pdnsutil check-zone`, `knotc checkconf`)
- Управлением сервисами через `ansible.builtin.systemd`
- Настройкой firewall (`ansible.posix.firewalld`)

### 2. Уровень DNS-записей

Управление записями осуществляется двумя подходами:
- **Динамические обновления (DDNS)**: через `community.general.nsupdate` (RFC 2136) для BIND/PowerDNS
- **API-управление**: через `ansible.builtin.uri` для PowerDNS REST API или через `community.dns` модули для специализированных провайдеров
- **Статические файлы**: через `ansible.builtin.template` для zone files

### 3. Уровень безопасности

- **TSIG**: аутентификация через HMAC-ключи
- **DNSSEC**: криптографическая подпись зон
- **ACL**: ограничение доступа к рекурсии, трансферу, динамическим обновлениям

### Взаимодействие с handlers

Изменения в конфигурации DNS-серверов требуют перезагрузки или перезагрузки конфигурации. Используйте `notify` + `handler` для атомарного применения изменений:

```yaml
- name: "Развертывание конфигурации BIND"
  ansible.builtin.template:
    src: named.conf.j2
    dest: /etc/bind/named.conf
  notify: "Reload BIND"
  become: yes
```

## Основные концепции

### Модули управления DNS-серверами

1. **`ansible.builtin.template`**: Основной инструмент управления конфигурацией DNS-серверов. Развёртывает `named.conf`, zone files, `pdns.conf`, `Corefile`, `knot.conf`.
2. **`community.general.nsupdate`**: Выполнение динамических обновлений DNS через RFC 2136. Поддерживает `server`, `zone`, `name`, `ttl`, `type`, `value`, `key_name`, `key_secret`, `state` (present/absent).
3. **`ansible.builtin.uri`**: Управление DNS через REST API (PowerDNS API).
4. **`ansible.builtin.command`**: Выполнение `rndc`, `named-checkconf`, `named-checkzone`, `pdnsutil`, `knotc` для валидации и управления.
5. **`community.dns.lookup`**: Lookup plugin для получения DNS-записей. Поддерживает все стандартные типы записей, HTTPS, SVCB.
6. **`community.dns.nameserver_info`**: Получение NS-серверов для домена.
7. **`community.dns.wait_for_txt`**: Ожидание распространения TXT-записей (полезно для ACME DNS-01 challenge).

### Сравнение подходов

| Подход | Инструмент | Идемпотентность | Применение |
| :--- | :--- | :--- | :--- |
| Конфигурация сервера | `template` | Да | BIND, PowerDNS, CoreDNS, Knot DNS |
| Динамические записи | `nsupdate` | Да | BIND, PowerDNS |
| API-управление | `uri` | Да | PowerDNS API |
| Валидация | `command` | Нет | Все серверы |
| DNS lookup | `community.dns.lookup` | Да | Все серверы |

### Типы DNS-записей

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

## Практические сценарии

### Сценарий 1: Развертывание BIND с зоной

```yaml
- name: "Установка BIND"
  ansible.builtin.package:
    name:
      - bind9
      - bind9utils
    state: present
  become: yes

- name: "Развертывание конфигурации BIND"
  ansible.builtin.template:
    src: named.conf.j2
    dest: /etc/bind/named.conf
  notify: reload bind9
  become: yes

- name: "Развертывание зоны example.com"
  ansible.builtin.template:
    src: db.example.com.j2
    dest: /etc/bind/db.example.com
  notify: reload bind9
  become: yes

- name: "Проверка конфигурации BIND"
  ansible.builtin.command: named-checkzone example.com /etc/bind/db.example.com
  register: zone_check
  changed_when: false
  failed_when: zone_check.rc != 0
```

### Сценарий 2: Динамическое обновление DNS через nsupdate

```yaml
- name: "Динамическое обновление PTR записи"
  community.general.nsupdate:
    server: "dns.internal"
    zone: "1.168.192.in-addr.arpa"
    name: "{{ inventory_hostname }}.internal"
    ttl: 300
    type: PTR
    value: "{{ new_ip }}.internal."
    key_name: "ddns-key"
    key_secret: "{{ vault_ddns_key_secret }}"
    state: present
  delegate_to: localhost
  no_log: yes
```

### Сценарий 3: Управление DNS через PowerDNS API

```yaml
- name: "Создание DNS записи через PowerDNS API"
  ansible.builtin.uri:
    url: "https://powerdns.example.com:8081/api/v1/servers/localhost/zones/example.com."
    method: PATCH
    headers:
      X-API-Key: "{{ vault_powerdns_api_key }}"
      Content-Type: "application/json"
    body_format: json
    body:
      rrsets:
        - name: "app.example.com."
          type: A
          ttl: 300
          records:
            - content: "10.0.1.10"
              disabled: false
    status_code: 204
  register: pdns_result
  no_log: yes
```

### Сценарий 4: DNS-01 ACME challenge через PowerDNS

```yaml
- name: "Add ACME challenge TXT record"
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
```

### Сценарий 5: Валидация DNS-зоны

```yaml
- name: "Проверка конфигурации BIND"
  ansible.builtin.command: named-checkconf /etc/bind/named.conf
  register: bind_check
  changed_when: false
  failed_when: bind_check.rc != 0

- name: "Проверка зоны"
  ansible.builtin.command: named-checkzone example.com /etc/bind/zones/db.example.com
  register: zone_check
  changed_when: false
  failed_when: zone_check.rc != 0

- name: "Проверка PowerDNS зоны"
  ansible.builtin.command: pdnsutil check-zone example.com
  register: pdns_check
  changed_when: false
  failed_when: pdns_check.rc != 0
```

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
# → ns1.example.com | SUCCESS => {
# →     "ansible_facts": {...},
# →     "changed": false
# → }

# Просмотр фактов для проверки готовности
ansible dns -i inventory.ini -m setup | grep ansible_host
# → ns1.example.com | SUCCESS | ansible_host=10.0.0.1

# Проверка запущенных сервисов
ansible dns -i inventory.ini -m service_facts
# → ns1.example.com | SUCCESS => {
# →     "services": {
# →         "named": {"state": "running", "status": "enabled"},
# →         "pdns": {"state": "running", "status": "enabled"}
# →     }
# → }

# Проверка DNS-разрешения с конкретного сервера
ansible dns-master -i inventory.ini -m command -a "dig +short +timeout=5 example.com A"
# → ns1.example.com | SUCCESS | "93.184.216.34"

# Проверка конфигурации BIND
ansible dns-master -i inventory.ini -m command -a "named-checkconf /etc/bind/named.conf"
# → ns1.example.com | SUCCESS | rc=0

# Проверка зоны BIND
ansible dns-master -i inventory.ini -m command -a "named-checkzone example.com /etc/bind/zones/db.example.com"
# → ns1.example.com | SUCCESS | zone example.com/IN: loaded serial 2024011501
# →     OK

# Проверка конфигурации Knot
ansible dns -i inventory.ini -m command -a "knotc checkconf"
# → ns1.example.com | SUCCESS | rc=0

# Проверка статуса Knot
ansible dns -i inventory.ini -m command -a "knotc status"
# → ns1.example.com | SUCCESS | server: version 3.6.0, uptime: 3d12h

# Проверка PowerDNS API
ansible localhost -i inventory.ini -m uri -a "url=http://dns.internal:8081/api/v1/servers/localhost/zones method=GET headers=X-API-Key:{{ vault_pdns_api_key }}"
# → localhost | SUCCESS => {
# →     "zones": [
# →         {"id": "example.com.", "name": "example.com.", "type": "Native"}
# →     ]
# → }

# Проверка логов
ansible dns -i inventory.ini -m command -a "journalctl -u pdns/named -n 100 --no-pager"
# → ns1.example.com | SUCCESS | ... (логи сервиса)

# Проверка zone transfer
ansible dns -i inventory.ini -m command -a "dig @10.0.0.1 example.com AXFR +noauth"
# → ns1.example.com | SUCCESS | ... (полный вывод зоны)
```

## Рекомендации

1. **Централизованное хранение конфигурации** — все изменения DNS проходят через Git + playbook. Никаких ручных редактирований на production.
2. **Атомарные изменения** — обновляйте одну зону/запись за один playbook run. Сложные изменения разбивайте на stages с проверкой.
3. **Rolling updates** — обновляйте secondary-серверы раньше primary. Всегда должен быть доступен минимум один authoritative сервер.
4. **Валидация перед деплоем** — используйте `named-checkconf`, `named-checkzone`, `pdnsutil check-zone` в каждом playbook.
5. **Splittable TTL** — используйте низкие TTL (60–300s) для записей, которые могут меняться часто (LB, failover). Для статичных записей TTL 3600–86400.
6. **DNSSEC** — подписывайте все зоны. Используйте KSK/ZSK split. Следите за сроками действия ключей.
7. **TSIG** — используйте разные TSIG ключи для DDNS, zone transfer, NOTIFY. Ротируйте ключи регулярно.
8. **Backup** — резервное копирование зон (BIND: zone files; PowerDNS: database dump) перед каждым изменением.
9. **Мониторинг** — настройте алерты на `SERVFAIL`, `NXDOMAIN`, latency, zone transfer failures.
10. **Disaster Recovery** — тестируйте восстановление из backup на dev-окружении. Документируйте процедуру.
11. **ACL и Rate Limiting** — ограничьте рекурсию внутренней сетью, ограничьте zone transfers только secondary серверами.
12. **HashiCorp Vault** — храните TSIG ключи, API ключи, vault пароли в Vault. Не храните секреты в Git.
13. **Тестирование** — используйте Molecule + Docker для тестирования ролей перед продом.
14. **Разделение окружений** — отдельные inventory, зоны, credentials для dev/staging/prod.
15. **Split-horizon** — используйте views (BIND) или separate zones (CoreDNS) для разделения внутреннего/внешнего DNS.
16. **Reverse DNS** — автоматизируйте PTR записи. Без reverse DNS многие сервисы (почта, logging) работают некорректно.

## Дополнительная информация

- **[Ansible nsupdate](https://docs.ansible.com/ansible/latest/collections/community/general/nsupdate_module.html)** — документация модуля `nsupdate`.
- **[Ansible community.dns](https://docs.ansible.com/ansible/latest/collections/community/dns/index.html)** — документация коллекции `community.dns`.
- **[BIND Documentation](https://bind9.readthedocs.io/)** — официальная документация BIND.
- **[PowerDNS Documentation](https://doc.powerdns.com/)** — документация PowerDNS.
- **[CoreDNS Documentation](https://coredns.io/docs/)** — документация CoreDNS.
- **[RFC 2136](https://datatracker.ietf.org/doc/html/rfc2136)** — Dynamic DNS Updates.
