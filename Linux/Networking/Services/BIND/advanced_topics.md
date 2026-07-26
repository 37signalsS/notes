# BIND: Расширенные возможности

## Определения

**Views (Представления)** — механизм в **BIND (Berkeley Internet Name Domain)**, позволяющий серверу предоставлять разные наборы данных (зон или параметров) в зависимости от источника **DNS (Domain Name System — система доменных имён)** запроса (например, **IP (Internet Protocol)** адреса клиента).

**ACL (Access Control List — список управления доступом)** — именованный список IP-адресов, сетей или ключей, используемый для разграничения доступа к функциям сервера (рекурсии, трансферу зон, динамическим обновлениям).

**RPZ (Response Policy Zones — зоны политик ответа)** — механизм ("DNS Firewall"), позволяющий изменять ответы DNS-сервера или блокировать запросы к определённым доменам на основе локальных или внешних списков угроз.

## Базовые концепции

### Сценарии использования Views

| Сценарий | Описание |
|----------|----------|
| **Split-horizon DNS** | Разделение сетевого пространства: внутренние клиенты получают локальные адреса ресурсов, внешние — публичные. |
| **Геораспределение (Geo-DNS)** | Направление клиентов на ближайшие серверы или **CDN (Content Delivery Network — сеть доставки контента)** узлы на основе их местоположения. |
| **Изоляция сред** | Создание раздельных пространств имён для разработки, тестирования и промышленной эксплуатации на одном сервере. |

### Стандартные ACL

BIND имеет несколько предопределённых списков доступа, которые можно использовать в конфигурации:

*   `any` — разрешает доступ всем источникам.
*   `none` — запрещает доступ всем.
*   `localhost` — разрешает доступ только с IP-адресов локальных интерфейсов сервера.
*   `localnets` — разрешает доступ из всех сетей, к которым напрямую подключён сервер (на основе масок интерфейсов).

### Архитектурные стандарты

**RFC 9704 (Request for Comments 9704)** — актуальный документ (2025), описывающий современные архитектурные подходы к реализации **Split-horizon DNS** и методы минимизации утечки внутренней информации.

## Практические сценарии

### 1. Настройка Split-horizon DNS (Views)

Механизм требует, чтобы при использовании `view` **все** зоны были описаны внутри блоков представлений.

**Конфигурация в `/etc/bind/named.conf.local`:**

```conf
acl "internal-clients" {
    192.168.0.0/24;
    127.0.0.1;
};

view "internal" {
    match-clients { internal-clients; };
    recursion yes;

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.internal";
    };

    include "/etc/bind/named.conf.default-zones";
};

view "external" {
    match-clients { any; };
    recursion no; // Запрет рекурсии для внешних клиентов для защиты от DDoS

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.external";
    };
};
```

### 2. Автоматизация DNSSEC (dnssec-policy)

В современных версиях BIND (9.16+) вместо ручной генерации ключей через `dnssec-keygen` рекомендуется использовать механизм политик.

**Настройка в `/etc/bind/named.conf.options`:**

```conf
dnssec-policy "standard-policy" {
    keys {
        ksk lifetime unlimited algorithm rsasha256 2048;
        zsk lifetime P60D algorithm rsasha256 1024;
    };
};

zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com";
    dnssec-policy "standard-policy";
    inline-signing yes; // Подпись зоны "на лету" без изменения исходного файла
};
```

### 3. Расширенное логирование и отладка

Для детального анализа работы (например, мониторинга атак или отладки ACL) необходимо настроить каналы вывода.

**Подготовка директории:**
```bash
sudo mkdir -p /var/log/named
sudo chown bind:bind /var/log/named
```

**Конфигурация логирования:**
```conf
logging {
    channel security_file {
        file "/var/log/named/security.log" versions 3 size 5m;
        severity dynamic;
        print-time yes;
    };
    category security { security_file; };
    category xfer-in { security_file; };
    category xfer-out { security_file; };
};
```

### 4. Управление через rndc (Remote Name Daemon Control)

**rndc** — утилита для безопасного управления демоном имён без прерывания обслуживания.

| Команда | Описание |
|---------|----------|
| `sudo rndc reload` | Перезагрузка конфигурации и всех зон. |
| `sudo rndc flush` | Очистка всего кэша DNS. |
| `sudo rndc status` | Информация о времени работы, версии и статистике. |
| `sudo rndc querylog` | Включение/выключение записи каждого входящего запроса в лог. |
| `sudo rndc reconfig` | Перечитывание только конфигурационного файла (без зон). |

## Дополнительная информация

*   **Производительность:** BIND 9.18+ и 9.20+ используют структуру **QP-trie (Quaternary Prefix Trie)** для эффективного управления оперативной памятью и ускорения обработки запросов на многоядерных **CPU (Central Processing Unit — центральный процессор)**.
*   **ARM (Administrator Reference Manual):** Официальный справочник администратора, доступный онлайн для каждой версии BIND.
*   [Диагностика BIND](./troubleshooting.md) — инструменты `named-checkconf` и методы анализа логов.
*   [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md) — защита от подмены кэша и шифрование трафика (**DoH/DoT**).
*   [Протокол DNS](../../../../Networking/Protocols/DNS/dns.md) — теоретические основы системы.
*   [Официальный сайт ISC](https://www.isc.org/bind/) — новости и обновления безопасности.
