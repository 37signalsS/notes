# Детальный анализ DNS с помощью dig

**`dig` (Domain Information Groper)** — мощная утилита для выполнения DNS-запросов и получения детальной информации о доменах. Входит в состав пакета `dnsutils` (Debian) или `bind-utils` (RHEL). В отличие от `nslookup` или `host`, `dig` показывает полную информацию: заголовки запроса, секции ответа, время отклика и статистику.

## Установка

```bash
# Debian/Ubuntu
sudo apt-get install -y dnsutils

# RHEL/CentOS
sudo dnf install -y bind-utils

# Alpine
apk add bind-utils
```

## Основные примеры использования

### Простой запрос A-записи

```bash
dig cortel.cloud
```

**Пример вывода:**

```
; <<>> DiG 9.20.20 <<>> cortel.cloud
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 48488
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 4096
;; QUESTION SECTION:
;cortel.cloud.      IN  A

;; ANSWER SECTION:
cortel.cloud.    4746  IN  A  95.181.181.7

;; Query time: 174 msec
;; SERVER: 77.88.8.8#53(77.88.8.8) (UDP)
;; WHEN: Tue Mar 05 11:15:58 +03 2026
;; MSG SIZE  rcvd: 57
```

### Запрос к определённому DNS-серверу

```bash
dig @8.8.8.8 cortel.cloud    # использовать DNS Google
dig @1.1.1.1 example.com     # использовать DNS Cloudflare
```

### Краткий вывод (только IP)

```bash
dig cortel.cloud +short
# 95.181.181.7
```

## Полезные опции

| Опция | Описание |
| :--- | :--- |
| `+noall +answer` | Показать только секцию ответа |
| `+short` | Краткий вывод (только данные) |
| `+stats` | Добавить статистику (время, размер) |
| `+tcp` | Использовать TCP вместо UDP |
| `+dnssec` | Запросить DNSSEC-данные |
| `+trace` | Полный путь от корневых серверов |
| `+ttlid` | Показать TTL записей |
| `+multi` | Многострочный вывод (для DNSKEY) |

## Примеры использования опций

```bash
# Только ответ с TTL
dig +noall +answer +ttlid example.com

# Полный путь делегирования
dig google.com +trace

# Запрос DNSSEC-подписей
dig +dnssec example.com

# Запрос конкретных записей
dig ya.ru MX           # почтовые серверы
dig ya.ru NS           # авторитетные серверы
dig _http._tcp.example.com SRV  # SRV-запись
```

## Анализ ответа

| Поле | Описание |
| :--- | :--- |
| **STATUS** | `NOERROR` (успех), `NXDOMAIN` (домен не найден), `SERVFAIL` (ошибка сервера) |
| **Query time** | Время выполнения запроса (мс) |
| **SERVER** | DNS-сервер, который ответил |
| **flags** | `qr` (ответ), `rd` (рекурсия запрошена), `ra` (рекурсия доступна), `AA` (авторитетный ответ) |

> **Примечание:** Для детального анализа времени DNS-запроса в составе HTTP-запросов см. [Диагностика сетевых задержек с curl](./curl_network_diagnostics.md).

---

**Связанные темы:**

* [Базовая диагностика](./basic_diagnostics.md) — nslookup, ping
* [DNS и производительность](./performance.md) — измерение времени резолва
* [Обзор DNS](./overview.md) — утилиты диагностики
