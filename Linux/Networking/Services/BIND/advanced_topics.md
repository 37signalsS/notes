# BIND: Расширенные возможности

## Определения

**Views (Представления)** — механизм в BIND, позволяющий серверу предоставлять разные наборы данных (зон или параметров) в зависимости от источника DNS-запроса (например, IP-адреса клиента).

**ACL (Access Control List — список контроля доступа)** — именованный список IP-адресов, сетей или ключей, используемый для разграничения доступа к функциям сервера (рекурсии, трансферу зон, обновлениям).

## Базовые концепции

### Сценарии использования Views

| Сценарий | Описание |
|----------|----------|
| **Split-horizon DNS** | Разделение сетевого пространства: внутренние клиенты получают локальные адреса, внешние — публичные ([подробнее](../../../../Networking/Protocols/DNS/dns_advanced.md#split-horizon-dns-split-dns)). |
| **Геораспределение** | Направление клиентов на ближайшие серверы в зависимости от их географического положения (Geo-DNS). |
| **Тестирование** | Изоляция сред разработки или тестирования внутри одного экземпляра BIND. |

### Стандартные ACL

BIND имеет несколько предопределённых списков доступа:

* `any` — разрешает доступ всем.
* `none` — запрещает доступ всем.
* `localhost` — разрешает доступ только с IP-адресов локальных интерфейсов сервера.
* `localnets` — разрешает доступ из всех сетей, к которым напрямую подключён сервер.

### RFC 9704

**RFC 9704 (Request for Comments 9704)** — документ, описывающий лучшие практики и архитектурные подходы к реализации Split-horizon DNS.

## Практические сценарии

### 1. Настройка Split-horizon DNS

Механизм позволяет разделять ответы для внутренней сети организации и внешнего Интернета.

**Конфигурация в `/etc/bind/named.conf`:**

```conf
// Определение ACL для внутренней сети
acl "internal-net" {
    172.16.0.0/16;
    127.0.0.1;
};

// Представление для внутренних клиентов
view "internal" {
    match-clients { internal-net; };
    recursion yes;

    // Внутренняя версия зоны
    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.internal";
    };

    include "/etc/bind/named.conf.default-zones";
};

// Представление для внешних клиентов
view "external" {
    match-clients { any; };
    recursion no;

    // Публичная версия зоны
    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.external";
    };
};
```

**Важные правила:**

* Views обрабатываются последовательно: запрос попадает в первое подходящее по `match-clients` представление.
* Если используются Views, то все зоны (включая стандартные) должны быть описаны внутри блоков `view`.

### 2. Настройка расширенного логирования

Для детального анализа запросов и диагностики требуется создание отдельных файлов журналов.

**Подготовка файловой системы:**

```bash
sudo mkdir /var/log/named
sudo chown bind:bind /var/log/named
sudo chmod 755 /var/log/named
```

**Настройка AppArmor (в Debian/Ubuntu):**
Добавьте разрешение на запись в `/etc/apparmor.d/local/usr.sbin.named`:

```text
/var/log/named/** rw,
```

**Конфигурация в блоке logging:**

```conf
logging {
    channel query_log {
        file "/var/log/named/query.log" versions 5 size 10m;
        severity info;
        print-time yes;
        print-category yes;
    };

    category queries { query_log; };
};
```

### 3. Управление через rndc (Remote Name Daemon Control)

**rndc (Remote Name Daemon Control — удалённое управление демоном имен)** — утилита для безопасного управления сервером BIND без его перезапуска.

**Основные команды:**

* `sudo rndc reload` — полная перезагрузка конфигурации и всех зон.
* `sudo rndc flush` — полная очистка кэша DNS-сервера.
* `sudo rndc status` — отображение текущего состояния и статистики сервера.
* `sudo rndc querylog` — включение или выключение логирования запросов "на лету".

### 4. Подпись зоны с помощью DNSSEC

**DNSSEC (Domain Name System Security Extensions — расширения безопасности системы доменных имен)** — набор спецификаций для обеспечения аутентичности и целостности данных DNS.

**Этапы ручной подписи:**

1. **Генерация KSK (Key Signing Key — ключ для подписи ключей):**

   ```bash
   sudo dnssec-keygen -a RSASHA256 -b 2048 -n ZONE example.com
   ```

2. **Генерация ZSK (Zone Signing Key — ключ для подписи зоны):**

   ```bash
   sudo dnssec-keygen -a RSASHA256 -b 1024 -n ZONE example.com
   ```

3. **Подпись файла зоны:**

   ```bash
   sudo dnssec-signzone -o example.com /etc/bind/zones/db.example.com
   ```

## Дополнительная информация

* **Производительность:** В современных версиях BIND используется структура данных **QP-trie (Quaternary Prefix Trie)** для ускорения поиска в кэше и снижения нагрузки на **CPU (Central Processing Unit — центральный процессор)**.
* **ARM (Administrator Reference Manual):** Основной справочник администратора по BIND 9.
* [Диагностика BIND](./troubleshooting.md) — детальный разбор ошибок и инструментов отладки.
* [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md) — общие принципы защиты (DNSSEC, DoH, DoT).
* [Официальная документация ISC BIND 9](https://bind9.readthedocs.io/)
