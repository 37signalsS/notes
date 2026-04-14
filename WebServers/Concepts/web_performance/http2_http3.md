# HTTP/2 и HTTP/3

> **SSoT:** полное сравнение версий — [эволюция HTTP](../../../Networking/Protocols/HTTP/http_versions.md), конфигурация — [HTTP/2 и HTTP/3 в Nginx](../../Nginx/Performance/nginx_http_versions.md).

## Definitions

**HTTP/2** — вторая мажорная версия HTTP (RFC 9113, 2015/2022), разработанная для повышения производительности за счёт мультиплексирования и сжатия заголовков поверх TCP.

**HTTP/3** — третья мажорная версия HTTP (RFC 9114, 2022), использующая транспортный протокол [QUIC](../../../Networking/Protocols/HTTP/http_versions.md) на базе UDP для устранения HOL-блокировки на транспортном уровне.

**Head-of-Line (HOL) Blocking** — проблема, при которой потеря или задержка одного пакета блокирует обработку всех последующих данных в соединении. Решается на уровне приложения (HTTP/2) и транспорта (HTTP/3).

**HPACK / QPACK** — алгоритмы сжатия HTTP-заголовков. HPACK используется в HTTP/2, QPACK — в HTTP/3 (устраняет зависимость сжатия от порядка доставки пакетов).

## Basic Concepts

### Ключевые отличия HTTP/2 от HTTP/3

| Характеристика | HTTP/2 | HTTP/3 |
| :--- | :--- | :--- |
| **Транспорт** | TCP | QUIC поверх UDP |
| **HOL Blocking** | Решён на уровне приложения, остаётся на TCP | Полностью устранён |
| **Сжатие заголовков** | HPACK | QPACK |
| **Connection Migration** | Нет | Да — соединение привязано к ID, а не к IP |
| **Server Push** | Присутствует (устарел) | Убран |

Подробное сравнение всех версий HTTP, эволюция протокола и RFC — в [эволюции HTTP](../../../Networking/Protocols/HTTP/http_versions.md).

### Влияние на производительность

- **HTTP/2:** одно TCP-соединение вместо 6 (HTTP/1.1), но потеря одного TCP-пакета блокирует все стримы до ретрансмиссии.
- **HTTP/3:** 1–2 RTT до первого запроса (QUIC + TLS объединены), 0-RTT для повторных подключений через `ssl_early_data` (риск [replay-атак](../../Nginx/Performance/nginx_http_versions.md)).
- **Накладные расходы сервера:** +20–30% CPU/RAM по сравнению с HTTP/1.1 для обоих протоколов.

### Обнаружение HTTP/3 клиентами

**1. Заголовок `Alt-Svc`:**

```http
Alt-Svc: h3=":443"; ma=86400
```

Проблема «холодного старта» — при первой загрузке браузер ещё не получил заголовок, поэтому начинает с HTTP/2.

**2. DNS-запись типа HTTPS (предпочтительный вариант):**

```dns
example.com HTTPS 1 . alpn="h2,h3"
```

Браузер узнаёт о поддержке HTTP/3 до установки соединения. Подробнее: [DNS-записи HTTPS/SVCB](../../../Networking/Protocols/DNS/dns_records.md).

Полное описание механизмов обнаружения — в [конфигурации HTTP/2 и HTTP/3 в Nginx](../../Nginx/Performance/nginx_http_versions.md#дополнительная-информация).

## Practical Scenarios

### Проверка версии HTTP

```bash
# HTTP/2
curl -I --http2 https://example.com/

# HTTP/3
curl -I --http3 https://example.com/
```

В браузере: Developer Tools → Network → колонка **Protocol** (`h2` / `h3` / `http/1.1`).

### Диагностика проблем с HTTP/3

Полный алгоритм (проверка UDP-порта, Alt-Svc, DNS-записи HTTPS, модуля QUIC) — в [диагностике HTTP/3](../../Nginx/Performance/nginx_http_versions.md#практические-сценарии).

### Конфигурация

Полные примеры настройки Nginx и Angie — в [конфигурации HTTP/2 и HTTP/3 в Nginx](../../Nginx/Performance/nginx_http_versions.md#практические-сценарии).

## Additional Information

### Влияние на оптимизацию

- **Доменный шардинг** — антипаттерн с HTTP/2 (нет лимита в 6 соединений).
- **Конкатенация CSS/JS** — менее критична, иногда вредна (мультиплексирование эффективнее).
- **Динамическое сжатие** — медленные алгоритмы блокируют воркер, что критичнее при HTTP/2 (один воркер на все стримы). Подробнее: [сжатие в Nginx](../../Nginx/Performance/nginx_compression.md).

Сравнение RTT, waterfall-диаграммы и визуализация — в [сравнении протоколов](../../Nginx/Performance/nginx_http_versions.md#визуальное-сравнение-протоколов-waterfall-view).

### Выбор протокола

Рекомендации по выбору (HTTP/1.1 vs HTTP/2 vs HTTP/3) — в [выборе версии HTTP](../../../Networking/Protocols/HTTP/http_versions.md#выбор-версии-http-для-devops).

### Связанные темы

- Оптимизация [TLS](./tls_optimization.md)
- [Сжатие контента](./server_compression.md)
- [Кэширование](./caching.md)
- [Обзор web-производительности](./overview.md)
