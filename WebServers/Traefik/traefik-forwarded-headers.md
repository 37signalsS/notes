# Доверенные заголовки и реальный IP клиента

## Определения

**Forwarded Headers** — заголовки `X-Forwarded-*` (`X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Forwarded-Port`, `X-Forwarded-Server`), через которые прокси передают информацию об исходном клиенте.

**`forwardedHeaders`** — конфигурация на entrypoint, определяющая, от каких источников (IP/CIDR) Traefik **доверяет** приходящим `X-Forwarded-*`.

**`trustedIPs`** — список IP/CIDR, от которых принимаются forwarded-заголовки.

**`forwardedHeaders.insecure`** — режим «доверять всем» (только для тестов).

**PROXY protocol** — сетевой протокол (v1/v2), несущий реальный IP клиента до TCP-соединения с принимающим сервером. Альтернатива `X-Forwarded-For` для L4.

**sourceCriterion** — параметр middleware (`RateLimit`, `inFlightReq`, `IPAllowList`), определяющий «источник» запроса (обычно IP из `X-Forwarded-For` на глубине `depth`).

## Базовые концепции

### Почему это важно

Если перед Traefik стоит внешний балансировщик (Nginx, HAProxy, облачный LB), все запросы приходят на Traefik **с IP балансировщика**. Без настройки доверия:
- приложение и логи увидят IP балансировщика, а не клиента;
- `RateLimit`/`IPAllowList` будут лимитировать всех клиентов как одного;
- злоумышленник может подделать `X-Forwarded-For` и обойти белые списки/лимиты.

### Как Traefik обрабатывает `X-Forwarded-*`

По умолчанию Traefik **не доверяет** приходящим заголовкам: он берет `RemoteAddr` соединения и сам добавляет его в `X-Forwarded-For`. 

Режимы на entrypoint:

| Режим | Когда использовать | Риск |
| :--- | :--- | :--- |
| `forwardedHeaders.insecure: true` | Только тесты/внутренние стенды | Spoofing `X-Forwarded-For` любым клиентом |
| `forwardedHeaders.trustedIPs: [...]` | Продакшн за известным LB | Доверие только адресам из списка |
| Не задано | Один хоп, прямой доступ | IP клиента потерян, если есть промежуточный LB |

Дополнительно доступны:
- `notAppendXForwardedFor: true` — не добавлять `RemoteAddr` к уже существующему `X-Forwarded-For`;
- `connection: [...]` — какие Connection-заголовки пропускать через цепочку middleware.

### Глубина (depth) в sourceCriterion

Middleware (`RateLimit`, `inFlightReq`, `IPAllowList`) выбирают источник по IP из цепочки `X-Forwarded-For` справа налево на глубине `depth` (0 = последний добавленный Traefik, уже не являющийся IP клиента при каскаде). Типичная схема: `X-Forwarded-For: <клиент>, <LB1>, <LB2>` — чтобы взять IP клиента за двумя прокси, задайте `ipStrategy.depth: 2`.

Ограничения:
- `depth` > 0 отключает `excludedIPs`;
- матчер `ClientIP` в правилах (см. [Правила и приоритет](./traefik-routers-and-rules.md)) **не** использует `X-Forwarded-For` вовсе — только RemoteAddr.

### PROXY protocol

Для L4/LB-сценариев (например, HAProxy, облачные LB) вместо `X-Forwarded-*` используется PROXY protocol. Он включается **на entrypoint** статической конфигурации:

```yaml
entryPoints:
  websecure:
    address: ":443"
    proxyProtocol:
      trustedIPs: ["10.0.0.0/8"]
```

`proxyProtocol.insecure: true` — доверять всем (только тесты). Теоретические основы и разбор с Nginx/HAProxy — в [обзоре PROXY protocol](../../Networking/Protocols/proxy_protocol.md).

## Практические сценарии

### Сценарий 1: Traefik за Nginx/HAProxy на том же хосте

```yaml
entryPoints:
  web:
    address: ":80"
    forwardedHeaders:
      trustedIPs:
        - "127.0.0.1/32"
        - "10.0.0.0/8"
```

### Сценарий 2: Несколько любимых LB (внешний + внутренний)

```yaml
entryPoints:
  websecure:
    address: ":443"
    forwardedHeaders:
      trustedIPs:
        - "192.168.1.10"      # внешний балансировщик
        - "10.90.0.0/16"      # внутренняя сеть мониторинга
```

### Сценарий 3: Rate Limit считает по IP клиента за LB

```yaml
http:
  middlewares:
    api-ratelimit:
      rateLimit:
        average: 100
        period: 1s
        burst: 50
        sourceCriterion:
          ipStrategy:
            depth: 1
```

Сочетается с `forwardedHeaders.trustedIPs` на entrypoint: Traefik должен знать, что за заголовком стоит доверенный LB, иначе depth «потеряет» клиента.

### Сценарий 4: Проверка реального IP

```bash
# Запрос через LB
curl -s http://127.0.0.1:8080/api/http/routers > /dev/null

# Со стороны приложения: проверка X-Forwarded-For
curl -s http://app-backend:8080/ -H "Host: app.example.com" | grep -i "X-Forwarded"
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **В логах приложения IP балансировщика** | На entrypoint не настроен `forwardedHeaders` | Добавьте `trustedIPs` с адресом LB |
| **RateLimit режет всех клиентов разом** | `sourceCriterion` по RemoteAddr (IP = LB) | Укажите `ipStrategy.depth: N` |
| **`X-Forwarded-For` подделывается** | Включен `insecure` или LB вне `trustedIPs` | Сужьте список доверенных IP |
| **IP пустой/обрывается** | `depth` больше числа IP в цепочке | Вычислите точное число прокси; выровняйте с настройкой LB |
| **PROXY protocol не распознается** | LB шлет обычный TCP, а Traefik ожидает PPv2 | Включите `proxyProtocol` у LB или выключите на Traefik |

## Рекомендации

- В продакшене используйте только `forwardedHeaders.trustedIPs` (никогда `insecure`).
- Держите `trustedIPs` максимально узким (%-хостов, служебных подсетей).
- Если за Traefik больше одного прокси — задайте `sourceCriterion.ipStrategy.depth` осознанно.
- Для L4/терминирующих LB предпочитайте PROXY protocol — он защищеннее, чем публичный заголовок.
- Внешние OpenID/аудит-сервисы должны доверять только `X-Forwarded-User` после проверки, что заголовок не подделан.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — base entrypoints и middleware.
- [PROXY protocol](../../Networking/Protocols/proxy_protocol.md) — общие принципы и таблица поддержки.
- [Прокси-сервер (концепция)](../../Networking/Concepts/proxy.md) — передача заголовков и реального IP в обратных прокси.
- [X-Forwarded-* заголовки](../../Networking/Protocols/HTTP/http_tls_hardening.md) — справочная таблица заголовков.