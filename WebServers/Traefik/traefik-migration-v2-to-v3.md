# Миграция с Traefik v2 на v3

## Определения

**Breaking changes** — изменения, требующие правки существующей v2-конфигурации перед v3.

**v2 rule syntax** — старый синтаксис правил с `Headers`, `HeadersRegexp`, path-placeholders (`{id:[0-9]+}`).

**v3 rule syntax** — новый синтаксис по умолчанию в v3: переименованные матчеры и отказ от плейсхолдеров в пользу regexp.

**Migration tool** — официальный кранччандж-скрипт `traefik-migration-tool` (по CLI), помогает найти проблемные поля в v2-конфиге.

## Базовые концепции

### Почему v3 отличается

Traefik v3 сделал синтаксис правил строже, убрал давно устаревшие поля, включил HTTP/3 по умолчанию, изменил схему CRD в Kubernetes, разделил механику ACME (обновление), убрал проксирование через `Headers`-ssl и легаси-трейсинг. Основные разделы изменений:

| Область | В v2 | В v3 |
| :--- | :--- | :--- |
| **Правила** | `Headers(Content-Type, application/json)` | `Header(...)`, `HeaderRegexp(...)` |
| **Path matcher** | `PathPrefix(`/api`)` (без плейсхолдеров) | То же, но **regexp** — в `PathRegexp` |
| **Client IP / IPAllowList** | `ipWhiteList` | `ipAllowList`, `clientIP` matcher |
| **SSL-редирект** | `sslRedirect: true` в Headers middleware | Удален; `redirections.entryPoint` / `redirectScheme` |
| **preferServerCipherSuites** | поле TLS options | Удалено |
| **HTTP/3** | экспериментальный флаг | Включен явно на entrypoint (опция `http3`) |
| **Трейсинг** | Datadog, Jaeger, Zipkin и др. | Только OpenTelemetry (OTLP) |
| **Compress** | `encodings` / `excludedContentTypes` | Единые `encodings` |
| **ContentType middleware** | отсутствовал | Появился (`contentType`) — принудительный пересчёт `Content-Type` |
| **ACME** | `certificatesResolvers.myresolver.acme` | Те же поля, обновленная схема для ACME (см. обзор) |

### Автоматическая проверка конфигурации

Перед миграцией запустите:

```bash
traefik config validate --providers.docker=false
# или через container:
docker run --rm -v $(pwd)/traefikconfig.yml:/etc/traefik/traefik.yml \
  traefik:v3.7 config validate
```

Ошибка «Configuration does not fit the model» указывает на несовместимые поля (в т.ч. бывшие v2-поля).

## Практические сценарии

### Сценарий 1: Пошаговая миграция роутеров

1. Замените `Headers(` на `Header(` (и `HeadersRegexp` → `HeaderRegexp`).
2. Замените `PathPrefix(` без изменений; для regexp путей — переведите в `PathRegexp`.
3. Удалите `sslRedirect`, `sslTemporaryRedirect`, `featurePolicy`, `preferServerCipherSuites`; настройте `redirections.entryPoint`.
4. `ipWhitelist` → `ipAllowList` (в middleware и у `ClientIP` matcher).
5. Проверьте `serversTransport`, `tls.options` на отсутствие старых опций.

Пример до/после:

```yaml
# v2
http:
  routers:
    api:
      rule: "Host(`api.example.com`) && PathPrefix(`/v1`)"
      entryPoints: [websecure]
      tls: {}
      middlewares:
        - secure-headers
  middlewares:
    secure-headers:
      headers:
        sslRedirect: true
        browserXssFilter: true
        stsSeconds: 86400
```

```yaml
# v3
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true

http:
  routers:
    api:
      rule: "Host(`api.example.com`) && PathPrefix(`/v1`)"
      entryPoints: [websecure]
      tls: {}
      middlewares:
        - secure-headers
  middlewares:
    secure-headers:
      headers:
        browserXssFilter: true
        stsSeconds: 86400
```

### Сценарий 2: Миграция правил с плейсхолдерами

```yaml
# v2
rule: "Path(`/api/{id:[0-9]+}`)"

# v3
rule: "PathRegexp(`/api/[0-9]+`)"
```

### Сценарий 3: Продакшн-план поэтапного перехода

- На stage: `traefik config validate` + переключите `core.defaultRuleSyntax: v2` (временный гейт на время миграции).
- Переносите роутеры один за другим; контролируйте по метрикам ошибок (`traefik_http_requests_total{code="5xx"}`) и по сквозным проверкам 200/404.
- Обновите CRD (Kubernetes) и перевыпустите конфиг.

## Операции и команды

```bash
# Проверка конфига на предмет v2-остатка
traefik config validate

# Docker: validate
docker run --rm -v "$(pwd)/traefikconfig.yml:/etc/traefik/traefik.yml" \
  -v "$(pwd)/dynamic:/etc/traefik/dynamic" \
  traefik:v3.7 config validate --providers.docker=false

# Сравнение версий через API (старый инстанс → новый)
curl -s http://old-traefik:8080/api/rawdata | jq '.http.routers' > v2-routers.json
```

## Устранение неисправностей

| Ошибка/эффект | Причина | Решение |
| :--- | :--- | :--- |
| **`Configuration invalid` на старте** | Остались v2-поля (sslRedirect и т.п.) | `config validate` и пройдитесь по чек-листу |
| **Правила не матчат** | v2-placeholders или `Headers` | Перепишите в v3-синтаксис или `ruleSyntax: v2` на конкретный роутер |
| **Нет redirect HTTP→HTTPS** | Положились на `sslRedirect` | Настройте `redirections.entryPoint` |
| **503 на сервисах из трейсинга** | Старые трейсеры (Jaeger/Zipkin) недоступны; только OTLP | Мигрируйте на OTel Collector (`tracing.openTelemetry.address`) |
| **CRD-ресурсы не применяются** | Старая группа `traefik.containo.us/v1alpha1` | Смените на `traefik.io/v1alpha1` (K8s) |

### Version pinning и upgrade strategy

#### Версионирование образов

В production **никогда** не используйте `:latest`. Фиксируйте версию во всех местах:

```yaml
# Docker Compose
services:
  traefik:
    image: traefik:v3.7.0  # точная версия, не :latest

# Helm
image:
  tag: "3.7.0"
```

Проверка актуальной версии:

```bash
# Docker Hub
curl -s https://hub.docker.com/v2/repositories/traefik/traefik/tags | jq -r '.results[].name' | rg '^v3\.[0-9]+\.[0-9]+$' | sort -V | tail -5

# GitHub releases
curl -s https://api.github.com/repos/traefik/traefik/releases/latest | jq -r '.tag_name'
```

#### Upgrade Playbook (minor/patch)

```bash
# 1) Скачать новый образ
docker compose pull traefik

# 2) Пересоздать только Traefik (приложения не трогаем)
docker compose up -d --force-recreate traefik

# 3) Проверить /ping и метрики
curl -s http://localhost:8080/ping
curl -s http://localhost:8080/api/version | jq '.version'
```

В Helm:

```bash
helm upgrade --install traefik traefik/traefik \
  --namespace traefik --create-namespace \
  --version 33.0.0 \            # версия чарта, не образа!
  -f values.yaml
```

#### Rolling upgrade без даунтайма

- Минимум 2 реплики Traefik за LB с health check `/ping`.
- Обновляйте по одной реплике: LB drain → stop → start → health 200 → следующая.
- В Kubernetes Deployment: `strategy.rollingUpdate.maxSurge=1`, `maxUnavailable=0` при 2+ репликах.
- Для bare-metal: keepalived VIP переключается автоматически при drain.

#### Major upgrade (v2 → v3)

1. **Stage:** Разверните v3 параллельно v2 на отдельном entrypoint/домене.
2. **Validate:** Прогоните `traefik config validate` и интеграционные тесты.
3. **Promote:** Переключите DNS/LB на v3 entrypoint.
4. **Decommission:** Удалите v2 после 48h стабильной работы v3.

#### Мониторинг после upgrade

Алерты на 24–48h после обновления:
- `traefik_entrypoint_requests_total{code=~"5.."} > 0` (новые 5xx).
- `traefik_config_reload_total{status="failed"} > 0` (конфиг не применился).
- `traefik_service_open_connections` растет, но не падает (leak после обновления).

## Рекомендации

- Не переносите «всё сразу»: v3-стадию проверьте на отдельном entrypoint/домене.
- Используйте `config validate` как обязательный CI-шаг перед выкатом.
- На время большой миграции можно временно включить `ruleSyntax: v2` на точечные роутеры, но не закрепляйте это в прод-конфиге.
- Бэкап v2-конфига обязателен; сделайте дамп `/api/rawdata` для сравнения «до/после».
- Сначала переведите роутеры и middleware на v3-синтаксис и только затем обновляйте CRD/документацию.

## Дополнительная информация

- [Правила и приоритет](./traefik-routers-and-rules.md) — v3-матчеры и `ruleSyntax`.
- [TLS Options и mTLS](./traefik-tls-options.md) — удаленные TLS-поля в v3.
- [Middleware для безопасности](./traefik-middlewares-security.md) — Headers в v3 (без sslRedirect).
- [Наблюдаемость Traefik](./traefik-observability.md) — OTLP-трейсинг вместо Jaeger/Zipkin.