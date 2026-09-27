# Маршрутизация в Traefik: правила, приоритет и конфликты

## Определения

**Router** — компонент Traefik, который связывает входящий запрос на конкретном entrypoint с сервисом. К роутеру привязываются правило (rule), приоритет, middleware, TLS-настройки и сервис.

**Rule (правило)** — логическое выражение из матчеров, которое определяет, подходит ли входящий запрос к роутеру. Если правило истинно — роутер активируется.

**Matcher** — элементарный предикат сравнения (например, `Host(`example.com`)`).

**Priority (приоритет)** — числовой вес роутера. Чем выше значение, тем раньше роутер проверяется, если несколько роутеров подходят под запрос.

**ruleSyntax** — версия синтаксиса правил (`v2` или `v3`), используется при миграции с Traefik v2.

**redirectScheme / redirectRegex** — middleware, перенаправляющие запрос с одного scheme/URL на другой (301/302/307).

## Базовые концепции

### Как выбирается роутер

При поступлении запроса на entrypoint Traefik:

1. Отбрасывает роутеры, не привязанные к этому entrypoint.
2. Проверяет правило каждого оставшегося роутера.
3. Из совпавших выбирает роутер с **наибольшим приоритетом**.
4. Выполняет middleware в порядке их перечисления, затем направляет запрос в сервис.

Важно: роутер для HTTP всегда должен ссылаться на сервис, иначе Traefik вернет `404 Page not found`. (Исключение — родительские роутеры в multi-layer routing, см. [Обзор Traefik](./traefik_overview.md).)

### Расчёт приоритета по умолчанию

Если `priority` не задан (или равен `0`), Traefik сортирует роутеры по **длине правила в символах**: чем длиннее правило, тем оно специфичнее и тем выше приоритет.

| Роутер | Правило | Приоритет (дефолт) |
| :--- | :--- | :--- |
| Router-1 | `HostRegexp(`[a-z]+\.traefik\.com`)` | 34 |
| Router-2 | `Host(`foobar.traefik.com`)` | 26 |

Приоритет `0` игнорируется (используется сортировка по длине), отрицательные значения допустимы. Максимальное значение для пользовательских роутеров ограничено: `MaxInt - 1000` (например, `2147482647` на 32-бит и т.д.) — верхний диапазон зарезервирован под внутренние роутеры Traefik (например, ACME challenge имеет приоритет `MaxInt`).

Правило **не должно полагаться только на длину** там, где есть перекрытие — конфликт лучше разрешать явным `priority`.

### Приоритет провайдеров

Если два роутера из **разных провайдеров** (например, File и Docker) имеют одинаковый числовой приоритет, победителя определяет статическая опция `providers.precedence` — выигрывает провайдер, стоящий в списке первым.

### Матчеры (полный список)

Значения матчеров задаются в обратных кавычках `` ` `` или экранированных двойных кавычках. Одинарные кавычки не принимаются (значения — Go string literals). Регулярные выражения — в Go-синтаксисе. Операторы: `&&` (И), `||` (ИЛИ), `!` (НЕ), группировка скобками.

| Матчер | Назначение | Пример |
| :--- | :--- | :--- |
| `Host(domain)` | Совпадение хоста; поддержка wildcard `*.example.com` (одноуровневый), а также catch-all `` Host(`*`) `` | `` Host(`example.com`) `` |
| `HostRegexp(regexp)` | Совпадение хоста по regexp (Go) | `` HostRegexp(`^.+\.example\.com$`) `` |
| `Path(path)` | Точное совпадение пути | `` Path(`/products`) `` |
| `PathPrefix(prefix)` | Совпадение префикса пути; в v3 **не** regexp | `` PathPrefix(`/api`) `` |
| `PathRegexp(regexp)` | Совпадение пути по regexp | `` PathRegexp(`\.(jpeg|jpg|png)$`) `` |
| `Header(key, value)` | Значение заголовка | `` Header(`Content-Type`, `application/json`) `` |
| `HeaderRegexp(key, regexp)` | Заголовок по regexp (регистр — `(?i)` для нечувствительности) | `` HeaderRegexp(`X-Tier`, `^(enterprise\|business)$`) `` |
| `Method(method)` | HTTP-метод | `` Method(`GET`) `` |
| `Query(key)` / `Query(key, value)` | Query-параметр (не обязательно со значением) | `` Query(`mobile`) `` |
| `QueryRegexp(key, regexp)` | Query-параметр по regexp | `` QueryRegexp(`mobile`, `^(true\|yes)$`) `` |
| `ClientIP(ip)` | IP клиента (IPv4/IPv6/CIDR); **не** использует `X-Forwarded-For` | `` ClientIP(`192.168.1.0/24`) `` |

Особенности:

- `` Host(`*.example.com`) `` матчит только прямой поддомен: `foo.example.com`, но не `foo.bar.example.com` и не сам `example.com`.
- `` Host(`*`) `` — catch-all, матчит любой запрос, включая без Host-заголовка.
- `PathPrefix(`/products`)` матчит `/products`, `/products/shoes` и даже `/products-for-sale` (простая проверка префикса, без границ слов).
- `ClientIP` в роли матчера и `IPAllowList`/`RateLimit` опираются на RemoteAddr, а не на `X-Forwarded-For` (см. [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md)).

### Синтаксис правила: v2 и v3

В v3 по умолчанию используется синтаксис v3: матчеры переименованы (`Headers` → `Header`, `HeadersRegexp` → `HeaderRegexp`), path-матчеры без `{placeholders}`.

Если возникает необходимость в v2-синтаксисе (например, при переезде), разрешается включать его на роутер:

```yaml
http:
  routers:
    router-v2:
      rule: 'HostRegexp(`{subdomain:[a-z]+}.example.com`)'
      ruleSyntax: v2
```

Глобально можно переключить дефолт статической опцией `core.defaultRuleSyntax: v2` (устаревает, используется только для миграции).

## Практические сценарии

### Сценарий 1: Явный приоритет для перекрывающихся правил

Классический конфликт: catch-all `/` и специфичный `/api`. Без явного приоритета при **_равной длине правила_ нельзя гарантировать выбор**, поэтому для перекрывающихся правил всегда задавайте `priority` вручную.

Файловый провайдер (dynamic.yml):

```yaml
http:
  routers:
    api-router:
      rule: "Host(`example.com`) && PathPrefix(`/api`)"
      service: api-service
      entryPoints: [websecure]
      priority: 100

    web-router:
      rule: "Host(`example.com`) && PathPrefix(`/`)"
      service: web-service
      entryPoints: [websecure]
      priority: 1

    catch-all:
      rule: "HostRegexp(`.+`)"
      service: 404-service@file
      entryPoints: [websecure]
      priority: 0
```

Docker Compose через labels:

```yaml
services:
  api:
    labels:
      - "traefik.http.routers.api.rule=Host(`example.com`) && PathPrefix(`/api`)"
      - "traefik.http.routers.api.priority=100"
```

### Сценарий 2: Перенаправление трафика (redirect)

Можно перенаправлять на уровне entrypoint (статическая конфигурация) или через middleware (детальнее).

Entrypoint (все запросы HTTP → HTTPS):

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true
```

Middleware `redirectScheme`:

```yaml
http:
  middlewares:
    redirect-https:
      redirectScheme:
        scheme: https
        permanent: true
```

Middleware `redirectRegex` (например, переезд поддомена):

```yaml
http:
  middlewares:
    redirect-old-domain:
      redirectRegex:
        regex: "^https://old.example.com/(.*)"
        replacement: "https://new.example.com/${1}"
        permanent: true
```

Совместимость: в YAML и доске-метках слеши в regexp экранируются дважды (`\\.`), а символ `$` в labels — как `$$`.

Примечание: в Traefik v3 `sslRedirect` из middleware Headers **удален** — для HTTPS-редиректа используйте `redirections.entryPoint` или `redirectScheme`.

### Сценарий 3: Комбинированные правила для канареечных контуров

```yaml
http:
  routers:
    enterprise-users:
      rule: 'Host(`api.example.com`) && HeaderRegexp(`X-Tier`, `^(enterprise|business)$`)'
      service: stable-backend
      entryPoints: [websecure]

    mobile-app:
      rule: 'Host(`api.example.com`) && Method(`GET`) && Query(`version`, `2`)'
      service: v2-backend
      entryPoints: [websecure]
```

## Операции и команды

```bash
# Список роутеров со статусами и правилами (через API)
curl -s http://localhost:8080/api/http/routers | jq '.[] | {name, rule, priority, service}'

# Проверка синтаксиса статического/динамического конфига
traefik config validate --providers.docker=false --providers.file.directory=/etc/traefik/dynamic
# → Configuration OK
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Запрос уходит не на тот роутер** | Перекрывающиеся правила, приоритет не задан, catch-all съедает трафик | Задайте `priority` явно; проверьте длину правил; смотрите `GET /api/http/routers` |
| **404, хотя роутер активен** | На роутере нет `service` (или имя сервиса опечатано) | Укажите `service`; проверьте имя сервиса в Dashboard |
| **`421 Misdirected Request`** | Хост в правиле не совпал с SNI/выбранным сертификатом при включённом SNI-роутинге | Проверьте соответствие `Host` и выданного сертификата |
| **Всё ловится wildcard-правилом** | `` HostRegexp(`.+`) `` (или `` Host(`*`) ``) с приоритетом выше специфичных | Понизьте приоритет wildcard или уберите его |
| **Redirection не работает из labels** | `$` в `replacement` интерпретируется YAML/labels | В labels используйте `$$` |
| **Регулярка в правиле не матчит** | Кавычки значения: используются одинарные или неверный синтаксис Go | Пишите regexp в обратных кавычках внутри YAML-строки на одну пару кавычек глубже |

## Рекомендации

- Для перекрывающихся правил всегда задавайте `priority` вручную — не полагайтесь на длину правила.
- Предпочитайте `` Host(\`*.example.com\`) `` вместо `HostRegexp` там, где нужен wildcard: он эффективнее и позволяет привязывать TLS-опции.
- Держите не более одного catch-all роутера на entrypoint и давайте ему минимальный приоритет.
- После изменения правил проверяйте их через Dashboard/`/api/http/routers`, а не «вслепую».
- Используйте `!` для исключений в рамках цепочки `&&` (например, `Host(\`api.example.com\`) && !PathPrefix(\`/health\`)`).

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура, middleware, ACME.
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — маршрутизация через labels.
- [Trusted Forwarded Headers](./traefik-forwarded-headers.md) — как `ClientIP`/`IPAllowList` видят реальный IP за балансировщиком.
- [TLS Options и сертификаты](./traefik-tls-options.md) — привязка TLS к роутерам и конфликты SNI.