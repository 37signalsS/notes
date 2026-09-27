# Настройка DNS-сервера BIND: Обзор

---

## Определения

**BIND (Berkeley Internet Name Domain)** — де-факто стандарт программного обеспечения для реализации DNS-сервера (**Domain Name System** — система доменных имён). Обеспечивает полную поддержку спецификаций протокола DNS, включая современные расширения безопасности и производительности. Разрабатывается и поддерживается организацией **ISC (Internet Systems Consortium)**.

**named (Name Daemon)** — системная служба (демон), реализующая функциональность BIND.
- В дистрибутивах на базе **RHEL (Red Hat Enterprise Linux)** служба называется `named`.
- В **Debian/Ubuntu** — `bind9`.

**Актуальные версии (2025-2026):**
*   **BIND 9.18 (LTS — Long Term Support):** стабильная ветка с долгосрочной поддержкой, ориентированная на максимальную надежность.
*   **BIND 9.20 (ESV — Extended Support Version):** современная версия с расширенным циклом обновлений, включающая оптимизации QP-trie и улучшенную поддержку сетевых протоколов нового поколения.

**AXFR (Asynchronous Full Transfer)** — полная передача содержимого зоны между серверами (RFC 5936). Используется при первоначальной синхронизации Slave или когда инкрементальная передача невозможна.

**IXFR (Incremental Zone Transfer)** — инкрементальная передача, содержащая только изменения с момента последней синхронизации (RFC 1995). Требует поддержки со стороны Master и Slave; при невозможности выполняется автоматический fallback на AXFR.

**TSIG (Transaction Signature, RFC 8945)** — механизм аутентификации сообщений DNS на основе общих секретных ключей. Защищает AXFR/IXFR и динамические обновления (RFC 2136) от подделки.

**RRSIG (Resource Record Signature)** — цифровая подпись для группы записей одного типа (RRset) в DNSSEC. Содержит временные метки начала и окончания действия, алгоритм подписи и серийный номер ключа.

**DNSKEY** — запись, содержащая открытый ключ для проверки RRSIG. Варианты: **ZSK** (Zone Signing Key, ключ подписи данных зоны) и **KSK** (Key Signing Key, ключ подписи самих ключей DNSKEY, имеет флаг SEP — Secure Entry Point).

**DS (Delegation Signer)** — хеш KSK дочерней зоны, размещенный в родительской зоне. Создает цепочку доверия (Chain of Trust) от корневых серверов до конечного домена.

**NSEC / NSEC3** — записи для подтверждения отсутствия данных. NSEC (RFC 4034) хранит имена в открытом виде; NSEC3 (RFC 5155) использует хеширование для защиты от Zone Walking (перебора всех имен в зоне).

**QNAME Minimization (RFC 7816 / RFC 9156)** — техника, при которой резолвер на каждом этапе иерархии отправляет только необходимую часть имени. При запросе `foo.bar.example.com` корень получает только запрос про `.com`, что снижает утечку данных о полном имени пользователя.

**RPZ (Response Policy Zones)** — механизм "DNS Firewall", позволяющий изменять ответы DNS-сервера или блокировать запросы к определённым доменам на основе локальных или внешних списков угроз.

**Catalog Zones (CatZ, RFC 9432)** — механизм автоматизации управления множеством зон на вторичных серверах через специальную мета-зону, передающую список зон как данные DNS.

---

## Базовые концепции

### Роли BIND в инфраструктуре

| Роль | Назначение | Ключевая конфигурация |
| :--- | :--- | :--- |
| **Авторитативный сервер** | Хранит официальные записи зоны и отвечает на запросы других серверов. | Тип зоны `master` или `slave`. |
| **Рекурсивный сервер (Резолвер)** | Выполняет полный поиск имени в иерархии DNS по запросу клиентов. | `recursion yes;` + `allow-query`. |
| **Кэширующий сервер** | Сохраняет ответы внешних серверов для ускорения повторных запросов. | Базовая роль резолвера. |
| **Перенаправляющий (Forwarder)** | Передает запросы вышестоящим серверам (например, 1.1.1.1). | `forward only;` + `forwarders { ... }`. |
| **Master (Primary)** | Первичный источник данных зоны, где файлы редактируются вручную. | `type master;` |
| **Slave (Secondary)** | Получает копию зоны с Master через трансфер (**AXFR/IXFR**). | `type slave;` + `masters { ... }`. |
| **Hidden Primary (Скрытый мастер)** | Авторитативный Master без публичного IP; доступен только для Slave-серверов. Все внешние запросы обрабатываются Slave. | `type master;` + `allow-transfer` только на IP Slave. |
| **Multi-Master** | Несколько серверов с типом `master` для одной зоны (редко, требует аккуратной работы с SOA Serial). | `type master;` на нескольких узлах. Не рекомендуется без автоматизации. |

### Механизмы управления и безопасности

*   **ACL (Access Control Lists):** Именованные списки **IP (Internet Protocol)** адресов для ограничения доступа к рекурсии, трансферу зон или динамическому обновлению записей (RFC 2136).
*   **Views (Представления):** Реализация **Split-horizon DNS**. Позволяет отдавать разные ответы (например, внутренние и публичные IP) в зависимости от IP-адреса источника запроса.
*   **rndc (Remote Name Daemon Control):** Утилита для безопасного управления демоном `named` (перезагрузка зон, очистка кэша, статистика) без перезапуска всей службы.
*   **RPZ (Response Policy Zones):** "DNS Firewall", позволяющий блокировать доступ к вредоносным доменам или перенаправлять запросы на основе репутационных списков.
*   **Catalog Zones (CatZ):** Современный механизм управления множеством зон, позволяющий автоматически создавать/удалять зоны на вторичных серверах через специальную мета-зону.

### Логирование и журналирование

BIND поддерживает гибкую настройку логирования через каналы (channels) и категории (categories). Рекомендуется разделять логи запросов, ошибок и трансферов зон:

```conf
logging {
    channel "query_log" {
        file "/var/log/named/query.log" versions 3 size 10m;
        severity info;
        print-time yes;
    };
    channel "error_log" {
        file "/var/log/named/error.log" versions 3 size 10m;
        severity warning;
        print-time yes;
    };
    category "queries" { "query_log"; };
    category "default" { "error_log"; };
};
```

При использовании **systemd-journald** логи автоматически собираются через `journalctl -u named` или `journalctl -u bind9`.

### Современные технологии и производительность

*   **QP-trie (Quaternary Prefix Trie):** Высокопроизводительная структура данных для кэша и зон, значительно ускоряющая поиск и снижающая потребление RAM/CPU.
*   **DoH/DoT (DNS over HTTPS / DNS over TLS):** Шифрование трафика между клиентом и сервером для защиты от перехвата и подмены данных.
*   **DNSSEC (Domain Name System Security Extensions):** Обеспечение подлинности ответов DNS через криптографические подписи. В современных версиях автоматизировано через `dnssec-policy`.
*   **Stale Cache:** BIND 9.18+ может продолжать отдавать устаревшие записи из кэша при недоступности авторитативного сервера (`stale-cache-enable yes;`), повышая отказоустойчивость разрешения.

---

## Практические сценарии

### Версии BIND и совместимость

| Версия | Тип | До EOL | Ключевые особенности |
| :--- | :--- | :--- | :--- |
| **BIND 9.16** | LTS | 2024 (EOL) | Последняя версия без DoH-сервера, namespace `isc-` для метрик |
| **BIND 9.18** | LTS | 2026+ | DoH/XoT сервер, `dnssec-policy`, inline-signing, stale-cache, QP-trie |
| **BIND 9.20** | ESV | 2027+ | Оптимизации производительности, улучшенная поддержка TFO, DNS64/NAT64 |

**Рекомендация:** используйте **BIND 9.18+** (LTS). Все примеры в данном разделе написаны для BIND 9.18/9.20. При использовании 9.16 — опции DoH/XoT недоступны.

### Структура конфигурации BIND

#### Файловая иерархия (Debian / Ubuntu)

```text
/etc/bind/
├── named.conf                  # Корневой include (родитель для остальных)
├── named.conf.options          # Глобальные опции (ACL, форвардеры, порты, DNSSEC)
├── named.conf.local            # Зоны (Master/Slave), Views, ключи
├── named.conf.default-zones    # Стандартные зоны (root, localhost, broadcast)
├── rndc.key                    # Ключ для rndc (автогенерация)
├── keys/                       # TSIG-ключи
│   ├── transfer.key
│   └── rndc.key
└── zones/                      # Файлы зон
    ├── db.example.com
    ├── db.10.0.0
    └── db.rpz.example.com
```

#### Debian / Ubuntu

| Файл | Назначение |
| :--- | :--- |
| `/etc/bind/named.conf` | Главный файл (корневой include). |
| `/etc/bind/named.conf.options` | Глобальные опции: ACL, форвардеры, параметры безопасности, прослушиваемые порты, statistics-channels, logging. |
| `/etc/bind/named.conf.local` | Объявление пользовательских зон (Master/Slave), Views, TSIG-ключи. |
| `/etc/bind/named.conf.default-zones` | Стандартные зоны (root-серверы, localhost, широковещательные адреса). |
| `/etc/bind/zones/` | Стандартная директория для хранения файлов описания зон (zone files). |

#### RHEL / CentOS / Fedora

| Файл | Назначение |
| :--- | :--- |
| `/etc/named.conf` | Главный файл конфигурации (в RHEL-family часто объединён в один файл). |
| `/etc/named.rfc1912.zones` | Стандартные зоны (localhost, широковещательные адреса). |
| `/var/named/` | Директория для файлов зон (Master/Slave). |
| `/var/named/data/` | Директория для сессий, кэша, статистики. |
| `/var/named/dynamic/` | Директория для динамически обновляемых зон и журналов (journal). |

### Компоненты и этапы настройки

1.  **[Установка и запуск](./installation.md):** Развёртывание пакетов, настройка автозапуска и первичная проверка.
2.  **[Настройка Master-сервера](./master_server_local_zone.md):** Создание авторитативной зоны и наполнение её ресурсными записями.
3.  **[Настройка Slave-сервера](./slave_server_configuration.md):** Конфигурация репликации и механизмов оповещения (NOTIFY).
4.  **[Обратные зоны (Reverse Zones)](./reverse_zone_configuration.md):** Настройка PTR-записей для резолвинга IP в имена.
5.  **[Сервер перенаправления (Forwarding)](./forwarding_server.md):** Оптимизация внешних запросов через кэширующий прокси.
6.  **[Продвинутые возможности](./advanced_topics.md):** Детальный разбор Views, DNSSEC-policy, CatZ, RPZ, ECS, RRL, DDoS-защита.
7.  **[Диагностика и отладка](./troubleshooting.md):** Использование `named-checkconf`, `named-checkzone` и анализ журналов системы.
8.  **[Отказоустойчивый кластер Master-Slave](./high-availability-cluster.md):** Пошаговая настройка отказоустойчивой пары с синхронизацией времени.
9.  **[DoT/DoH сервер](./dot-doh-server.md):** Настройка DNS over TLS и DNS over HTTPS на стороне сервера.
10. **[Логирование и мониторинг](./logging-and-monitoring.md):** Настройка логов, Prometheus-метрик, Grafana-дашбордов.
11. **[Автоматизация (IaC)](./automation-iac.md):** Управление BIND через Ansible.
12. **[TSIG-ключи](./tsig-key-management.md):** Ротация ключей и автоматизация.
13. **[Реагирование на инциденты](./incident-response.md):** Live-отладка и postmortem.

### Минимальные рабочие конфигурации

#### Авторитативный Master-сервер (Debian/Ubuntu)

**`/etc/bind/named.conf.options`:**
```conf
options {
    directory "/var/cache/bind";
    listen-on port 53 { any; };
    allow-query { any; };
    recursion no;
    allow-transfer { 10.0.8.51; };  # IP Slave-сервера
    version "none";
    dnssec-validation auto;
    max-cache-size 256m;
};
```

**`/etc/bind/named.conf.local`:**
```conf
zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com";
    allow-transfer { 10.0.8.51; };
};

zone "8.10.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/db.10.8";
};
```

#### Авторитативный Slave-сервер (Debian/Ubuntu)

**`/etc/bind/named.conf.options`:**
```conf
options {
    directory "/var/cache/bind";
    listen-on port 53 { any; };
    allow-query { any; };
    recursion no;
    version "none";
    dnssec-validation auto;
};
```

**`/etc/bind/named.conf.local`:**
```conf
zone "example.com" {
    type slave;
    masters { 10.0.8.50; };  # IP Master-сервера
    file "/var/cache/bind/db.example.com";
};

zone "8.10.in-addr.arpa" {
    type slave;
    masters { 10.0.8.50; };
    file "/var/cache/bind/db.10.8";
};
```

### Управление службой и rndc

#### Systemd-юниты

```bash
# Debian/Ubuntu
sudo systemctl status bind9
sudo systemctl restart bind9
sudo systemctl enable --now bind9

# RHEL/CentOS/Fedora
sudo systemctl status named
sudo systemctl restart named
sudo systemctl enable --now named
```

#### Генерация ключа rndc

По умолчанию в Debian/Ubuntu ключ `rndc` создаётся автоматически. В RHEL-family требуется ручное создание:

```bash
# 1. Создание ключевого файла
sudo rndc-confgen -a -k /etc/rndc.key
# → /etc/rndc.key

# 2. Проверка подключения
sudo rndc status
# → version: 9.18.x ...
```

#### Основные команды rndc

| Команда | Описание |
| :--- | :--- |
| `sudo rndc reload` | Полная перезагрузка конфигурации и всех зон. |
| `sudo rndc flush` | Очистка всего кэша резолвера. |
| `sudo rndc status` | Вывод статистики и времени работы сервера. |
| `sudo rndc querylog` | Включение/выключение записи всех входящих запросов в системный журнал. |
| `sudo rndc reconfig` | Перечитывание только конфигов (без проверки файлов зон). |
| `sudo rndc freeze <zone>` | Приостановка динамических обновлений зоны (для резервного копирования). |
| `sudo rndc thaw <zone>` | Возобновление динамических обновлений. |

### Резервное копирование зон

Авторитативные зоны BIND представляют собой обычные текстовые файлы. Для резервного копирования достаточно копирования файлов зон и конфигурации:

```bash
# 1. Остановка динамических обновлений (если зоны динамические)
sudo rndc freeze example.com

# 2. Резервное копирование
sudo tar czf /backup/bind-zones-$(date +%Y%m%d).tar.gz \
    /etc/bind/ \
    /var/lib/bind/

# 3. Возобновление обновлений
sudo rndc thaw example.com

# 4. Проверка целостности резервной копии
sudo named-checkzone example.com /backup/bind-zones-$(date +%Y%m%d).tar.gz
```

Для Slave-серверов файлы зон хранятся в кэше (`/var/cache/bind/` или `/var/named/data/`); их резервное копирование менее критично, так как зоны автоматически реплицируются с Master.

### Мониторинг через Statistics Channel

BIND предоставляет встроенный **Statistics Channel** (порт 8053 по умолчанию) для сбора метрик без сторонних агентов:

**Включение в `named.conf.options`:**
```conf
statistics-channels {
    inet 127.0.0.1 port 8053 allow { 127.0.0.1; };
};
```

**Проверка:**
```bash
curl http://127.0.0.1:8053/  # → JSON со статистикой
curl http://127.0.0.1:8053/json  # → расширенная статистика
```

Ключевые метрики для SRE: `resolver.queries.recursivetotal`, `resolver.queries.queriesperetz`, `server.queries.tcp`, `server.queries.udp`, `zone.requests`, `server.rcodes` (распределение RCODE), размер кэша (`resolver.cache.memory`), количество активных TCP-соединений.

### Производительность и масштабирование

**Основные параметры настройки в `options`:**

```conf
options {
    # TCP: количество клиентских соединений
    tcp-clients 100;

    # UDP: размер буфера на прием
    udp-receive-buffer 4m;

    # Ограничение размера кэша (защита от memory exhaustion)
    max-cache-size 512m;
    max-cache-ttl 3600;
    max-ncache-ttl 600;

    # Предвыборка (prefetch) популярных записей
    prefetch 2 90;

    # Отдача устаревших записей при недоступности источника
    stale-cache-enable yes;
    stale-answer-ttl 30;
};
```

**Рекомендации по ресурсам:**
- **RAM:** 1 GB минимум для авторитативного сервера; +1 GB на каждые 1 млн записей в зонах; +2 GB для кэша резолвера на 1 млн запросов/день.
- **CPU:** BIND predominantly single-threaded на запрос; `tcp-clients` и `recursive-clients` распределяются по потокам, но пиковые нагрузки требуют быстрых ядер.
- **Disk:** Используйте SSD для высоконагруженных Slave-серверов с частыми IXFR; зоны хранятся в текстовом или raw-формате (`masterfile-format raw;` ускоряет загрузку).

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`SERVFAIL`** | Ошибка в конфигурации зоны, невалидный Serial, таймаут вышестоящих серверов. | `named-checkzone`, проверка `journalctl -u named`, `dig` с флагом `+cd` для обхода DNSSEC. |
| **`REFUSED`** | Запрос отклонён ACL (разделённый DNS, закрытая рекурсия). | Проверка `allow-query`, `allow-recursion`, `match-clients` в Views. |
| **Порт 53 занят** | Конфликт с `systemd-resolved`, другим DNS-сервером или неверные права на порт <1024. | `ss -ulnp | grep :53`, отключение конфликтующей службы. |
| **Служба не стартует после `reload`** | Синтаксическая ошибка в конфиге или файле зоны, отсутствие прав на файл. | `named-checkconf /etc/bind/named.conf`, `named-checkzone`. |
| **Slave не получает зону** | Ошибка TSIG, закрытый `allow-transfer` на Master, несовпадение `keys`. | `dig @master example.com AXFR`, проверка `masters { ... key "xxx"; }`. |
| **Высокое потребление памяти** | Неограниченный кэш, утечка в QP-trie, DDoS-атака (Water Torture). | `max-cache-size`, `rate-limit`, анализ логов на аномалии. |
| **«Зона не обновляется»** | Slave сравнивает Serial; на Master Serial не увеличен, или Slave кэширует старую версию. | `rndc refresh example.com`, проверка формата Serial (YYYYMMDDNN). |

---

## Дополнительная информация

### Расширенные функции

*   **[DoT/DoH сервер](./dot-doh-server.md)** — настройка DNS over TLS и DNS over HTTPS на стороне сервера.
*   **[Логирование и мониторинг](./logging-and-monitoring.md)** — настройка логов, Prometheus-метрик, Grafana-дашбордов.
*   **[Автоматизация (IaC)](./automation-iac.md)** — управление BIND через Ansible.
*   **[TSIG-ключи](./tsig-key-management.md)** — ротация ключей и автоматизация.
*   **[Реагирование на инциденты](./incident-response.md)** — live-отладка и postmortem.
*   **[Продвинутые возможности](./advanced_topics.md)** — Views, DNSSEC-policy, CatZ, RPZ, ECS, RRL.
*   **[Troubleshooting](./troubleshooting.md)** — диагностика ошибок.
*   **[HA-кластер](./high-availability-cluster.md)** — отказоустойчивость.

### Связанные разделы

*   **[Протокол DNS](../../../../Networking/Protocols/DNS/dns.md)** — фундаментальные принципы работы системы.
*   **[Зоны DNS и SOA](../../../../Networking/Protocols/DNS/dns_zones.md)** — иерархия и управление записью Start of Authority.
*   **[DNS-записи](../../../../Networking/Protocols/DNS/dns_records.md)** — описание типов A, MX, CNAME, TXT, SRV.
*   **[Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md)** — DNSSEC, DoT/DoH/DoQ, TSIG, XoT, защита от атак.
*   **[Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md)** — архитектура мониторинга, Blackbox Exporter, алертинг.
*   **[Миграция DNS](../../../../Networking/Protocols/DNS/dns_migration.md)** — перенос DNS-сервисов.
*   **[Диагностика сетевых служб DNS](../../../Diagnostics/Networking/dns/overview.md)** — работа с утилитами `dig`, `host`, `nslookup`.
*   [Официальная документация ISC BIND 9](https://bind9.readthedocs.io/)
