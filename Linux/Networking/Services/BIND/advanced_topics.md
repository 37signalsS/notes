# BIND: Дополнительная информация

## Определения

**Views (Представления)** — механизм BIND, позволяющий отдавать разные ответы на DNS-запросы в зависимости от источника запроса (IP-адреса клиента).

**ACL (Access Control List)** — именованный список IP-адресов или сетей для контроля доступа.

## Базовые концепции

### Сценарии использования Views

| Сценарий | Описание |
|----------|----------|
| **Split-horizon DNS** | Разные ответы для внутренней и внешней сети |
| **Геораспределение** | Разные IP для клиентов из разных регионов |
| **Тестирование** | Отдельные зоны для staging/production |

### Типы ACL

| ACL | Описание |
|-----|----------|
| `any` | Все адреса |
| `none` | Никаких адресов |
| `localhost` | Локальные интерфейсы сервера |
| `localnets` | Сети, к которым подключён сервер |
| Пользовательская | Список IP/сетей в формате `acl "name" { ... };` |

## Практические сценарии

### 1. Split-horizon DNS (разделение внутреннего и внешнего DNS)

**Конфигурация в `/etc/bind/named.conf`:**

```conf
// ACL для внутренней сети
acl "internal-net" {
    172.16.0.0/16;
    127.0.0.1;
};

// Представление для внутренних клиентов
view "internal" {
    match-clients { internal-net; };
    recursion yes;  // Разрешаем рекурсию для своих

    // Внутренние зоны
    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.internal";
    };

    // Подключение общих настроек
    include "/etc/bind/named.conf.options";
};

// Представление для внешних клиентов
view "external" {
    match-clients { any; };
    recursion no;  // Запрещаем рекурсию для чужих

    // Публичные зоны
    zone "example.com" {
        type master;
        file "/etc/bind/zones/db.example.com.external";
        allow-transfer { 172.16.0.6; };
    };
};
```

**Важно:**
- Views обрабатываются по порядку — первый подходящий используется
- Все зоны должны быть определены внутри views (не глобально)
- `named.conf.default-zones` также нужно включить в каждый view

### 2. Настройка логирования

**Создание директории для логов:**

```bash
sudo mkdir /var/log/named
sudo chown bind:bind /var/log/named
sudo chmod 755 /var/log/named
```

**Настройка AppArmor (если используется):**

```bash
# /etc/apparmor.d/local/usr.sbin.named
/var/log/named/** rw,
```

**Конфигурация логирования в `/etc/bind/named.conf`:**

```conf
logging {
    // Лог DNS-запросов
    channel query.log {
        file "/var/log/named/query.log" versions 5 size 10m;
        severity info;
        print-time yes;
        print-category yes;
        print-severity yes;
    };

    // Лог ошибок
    channel default_log {
        file "/var/log/named/default.log" versions 3 size 5m;
        severity info;
        print-time yes;
    };

    // Категории логов
    category queries { query.log; };
    category default { default_log; };
};
```

**Включение логирования запросов:**

```conf
options {
    ...
    querylog yes;  // Включить логирование запросов
};
```

**Перезапуск и проверка:**

```bash
sudo systemctl restart bind9

# Просмотр логов в реальном времени
tail -f /var/log/named/query.log
```

### 3. Управление BIND с помощью rndc

**Генерация ключа:**

```bash
sudo rndc-confgen -a -c /etc/bind/rndc.key
sudo chown bind:bind /etc/bind/rndc.key
sudo chmod 640 /etc/bind/rndc.key
```

**Основные команды:**

```bash
# Перезагрузка конфигурации (без обрыва соединений)
sudo rndc reload

# Перезагрузка конкретной зоны
sudo rndc reload example.com

# Очистка кэша
sudo rndc flush

# Статус сервера
sudo rndc status

# Включение/выключение логирования запросов
sudo rndc querylog on
sudo rndc querylog off

# Остановка сервера (грациозная)
sudo rndc stop
```

### 4. DNSSEC-подпись зоны

**Генерация ключей:**

```bash
cd /etc/bind
sudo rndc-confgen -a  # если ещё не создан

# Генерация KSK (Key Signing Key)
sudo dnssec-keygen -a RSASHA256 -b 2048 -n ZONE example.com

# Генерация ZSK (Zone Signing Key)
sudo dnssec-keygen -a RSASHA256 -b 1024 -n ZONE example.com
```

**Подпись зоны:**

```bash
sudo dnssec-signzone -o example.com /etc/bind/zones/db.example.com
```

**Добавление в конфигурацию:**

```conf
zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com.signed";
    auto-dnssec maintain;
    inline-signing yes;
};
```

## Дополнительная информация

- **RFC 970** — Split-horizon DNS
- **RFC 6781** — DNSSEC-операции
- **QP-trie:** BIND 9.20+ использует QP-trie вместо RBTDB (улучшение производительности на 4-7%)
- **Утилиты:**
  - `named-checkconf` — проверка конфигурации
  - `named-checkzone` — проверка файла зоны
  - `dig`, `nslookup` — диагностика
  - `rndc` — удалённое управление
- **Сопутствующие заметки BIND:**
  - [Overview](./overview.md) — общая информация
  - [Troubleshooting](./troubleshooting.md) — диагностика
  - [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md) — DNSSEC, DoH, DoT
