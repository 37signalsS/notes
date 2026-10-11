# Consul UI — администрирование

**Актуально для:** Consul 2.0.x / 1.22.x / 1.20.x / 1.19.x

## Определения

**Consul UI** — веб-интерфейс на базе Ember.js для визуального управления кластером Consul. Встроен в бинарный файл агента и обслуживается встроенным Go HTTP-сервером на том же порту, что и API (по умолчанию 8500 HTTP, 8501 HTTPS). UI предоставляет доступ к каталогу сервисов, KV-хранилищу, ACL, intentions, Service Mesh topology и метрикам без использования CLI.

**ui_config** — блок конфигурации агента, управляющий включением UI (`enabled`), путем обслуживания (`content_path`), внешними директориями статики (`dir`), интеграцией с метриками (`metrics_provider`, `metrics_proxy`) и шаблонами внешних дашбордов (`dashboard_url_templates`).

**Metrics proxy** — встроенный эндпоинт агента (`/v1/ui/metrics-proxy`), который проксирует GET-запросы от UI к бэкенду метрик (например, Prometheus). Позволяет скрыть backend от браузеров пользователей и инжектировать заголовки авторизации.

**Dashboard URL template** — шаблон URL внешнего дашборда (Grafana, APM), подставляемый в UI для создания глубоких ссылок на сервис. Поддерживает плейсхолдеры `{{Service.Name}}`, `{{Service.Namespace}}`, `{{Service.Partition}}`, `{{Datacenter}}`.

**OIDC / SSO** — механизм единого входа в UI через внешнего провайдера идентификации (OpenID Connect). Доступен в Consul Enterprise. Позволяет аутентифицировать пользователей через браузер без распространения ACL-токенов.

**Blocking Queries** — режим реального времени обновления UI через long-polling HTTP-запросы к Consul API. Включен по умолчанию; может быть отключен в настройках UI для больших дата-центров.

**Feature flag** — флаг функциональности, передаваемый из агента в UI через инъекцию в `index.html` (например, `CONSUL_ACLS_ENABLED`, `CONSUL_PARTITIONS_ENABLED`, `CONSUL_SSO_ENABLED`). Управляет отображением разделов UI без переконфигурации агента.

## Основные концепции

### Архитектура UI

Consul UI — это single-page application (SPA) на Ember.js, которое поставляется в виде статических ассетов, встроенных в бинарный файл Consul агента. Агент обслуживает UI через встроенный Go HTTP-сервер. При запросе `/ui/` агент отдает `index.html`, инжектируя в него конфигурационные данные (флаги ACL, namespaces, datacenter, metrics provider) через Go-шаблоны.

Поток запроса:
1. Браузер запрашивает `/ui/` у Consul агента.
2. Агент возвращает `index.html` с подставленными runtime-параметрами.
3. Ember.js приложение делает API-запросы к тому же агенту (`/v1/...`) для получения каталога, KV, intentions и т.д.
4. Если настроен metrics proxy, запросы к метрикам идут через внутренний эндпоинт агента, который проксирует их в Prometheus или другой backend.

UI не является отдельным процессом и не требует выделенной инфраструктуры. При отключении `ui_config.enabled` порт 8500/8501 продолжает обслуживать только HTTP API.

### Возможности UI

| Раздел | Действия | Примечание |
| :--- | :--- | :--- |
| **Services** | Просмотр | Фильтрация по health status, type, поиск. Изначальная страница при открытии UI. |
| **Nodes** | Просмотр | Отображает статус узла, роль (server/client), количество сервисов. Бейдж рядом с узлом указывает хост лидера кластера. |
| **Key/Value** | Создание, чтение, обновление, удаление | Требует ACL-токен с `key:write`. Навигация по префиксам. |
| **Intentions** | Создание, чтение, обновление, удаление | Поддерживает L7 intentions (Application Aware) с методами, заголовками и путями. |
| **ACL** | Создание, чтение, обновление, удаление | Полное управление токенами, политиками, ролями и auth methods. Требует `acl:write`. |
| **Service Mesh** | Просмотр topology | Визуализация связности сервисов (требует Connect). |
| **Peers** | Просмотр | Статус cluster peering (Enterprise). |

### Доступ к UI

| Метод | URL | Примечание |
| :--- | :--- | :--- |
| **HTTP (dev)** | `http://localhost:8500/ui` | Без шифрования, UI включен по умолчанию в `-dev` режиме. |
| **HTTPS (prod)** | `https://consul.example.com:8501/ui` | TLS terminates на агенте при настроенной TLS-конфигурации. |
| **Reverse proxy** | `https://consul.example.com/consul/ui/` | Через Nginx/Angie/HAProxy с дополнительной аутентификацией. |

### Аутентификация и авторизация

- **ACL-токен:** Для доступа к KV, Intentions, ACL требуется токен с соответствующими правами. Токен передается в заголовке `X-Consul-Token` или вводится в поле шапки UI.
- **Least-privilege токен:** Рекомендуется создавать отдельные политики для read-only пользователей и операторов. Например, политика `ui-view-catalog` дает доступ только к сервисам и узлам, `ui-view-all` — также к KV и intentions. В Consul Enterprise для обхода partitions требуется `operator = "read"`.
- **OIDC SSO (Enterprise):** Вместо токенов пользователи авторизуются через внешнего провайдера (Auth0, Okta, Google). Consul выдает короткоживущий ACL-токен на основе claims. Callback URI для UI: `http://localhost:8500/ui/oidc/callback` или `https://{host:port}/ui/oidc/callback`. Для CLI используется отдельный callback: `http://localhost:8550/oidc/callback`.

### Интеграция с метриками

UI может отображать графики метрик и topology visualization для Service Mesh. Для этого требуется:
1. Включить `metrics_provider = "prometheus"` (встроенный provider с 1.9.0).
2. Настроить `metrics_proxy.base_url` — адрес, по которому Consul агент может достичь Prometheus.
3. Убедиться, что у пользователя UI есть ACL-токен с `service_prefix "" { policy = "read" }` и `node_prefix "" { policy = "read" }` (в Enterprise — обернуто в `namespace_prefix ""`).

Для ссылок на внешние дашборды (Grafana) используется `dashboard_url_templates.service` с подстановкой переменных.

## Практические сценарии

### 1. Включение UI в production

```hcl
# /etc/consul.d/server.hcl
ui_config {
  enabled = true
  content_path = "/ui/"
}

# Или через CLI флаг:
# consul agent -ui -config-dir=/etc/consul.d
```

```bash
# Проверка статуса UI
curl -s http://localhost:8500/v1/ui/health
# → {"ui":true}
```

### 2. Доступ через reverse proxy (Nginx/Angie)

```nginx
# /etc/nginx/conf.d/consul-ui.conf
upstream consul_servers {
  server 127.0.0.1:8500;
}

server {
  listen 443 ssl http2;
  server_name consul.example.com;

  ssl_certificate /etc/nginx/ssl/consul.crt;
  ssl_certificate_key /etc/nginx/ssl/consul.key;

  # Дополнительная аутентификация
  auth_basic "Consul UI";
  auth_basic_user_file /etc/nginx/.htpasswd;

  location /ui/ {
    proxy_pass http://consul_servers/ui/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

### 3. Аутентификация через ACL токен (least privilege)

```hcl
# ui-view-catalog.hcl — только чтение каталога
service_prefix "" {
  policy = "read"
}
node_prefix "" {
  policy = "read"
}
```

```bash
# Создание политики
consul acl policy create \
  -name "ui-view-catalog" \
  -rules @ui-view-catalog.hcl \
  -description "Allow viewing catalog in UI"

# Создание токена
consul acl token create \
  -description "UI read-only token" \
  -policy-name "ui-view-catalog"
# → Token secret ID сохраните и введите в поле ACL Token в шапке UI
```

Для Enterprise с namespaces и partitions:

```hcl
# ui-view-catalog-ent.hcl
operator = "read"
partition_prefix "" {
  namespace_prefix "" {
    service_prefix "" {
      policy = "read"
    }
    node_prefix "" {
      policy = "read"
    }
  }
}
```

### 4. Single Sign-On через OIDC (Enterprise)

```hcl
# /etc/consul.d/oidc.hcl
auth_method "oidc" "auth0" {
  OIDCDiscoveryURL = "https://<AUTH0_DOMAIN>/"
  OIDCClientID = "<AUTH0_CLIENT_ID>"
  OIDCClientSecret = "<AUTH0_CLIENT_SECRET>"
  BoundAudiences = ["<AUTH0_CLIENT_ID>"]
  AllowedRedirectURIs = [
    "http://localhost:8500/ui/oidc/callback",
    "http://localhost:8550/oidc/callback"
  ]
  ClaimMappings = {
    "http://consul.internal/first_name" = "first_name"
    "http://consul.internal/last_name" = "last_name"
  }
  ListClaimMappings = {
    "http://consul.internal/groups" = "groups"
  }
}

# Binding rule — автоматическая выдача роли
acl binding-rule create \
  -method=auth0 \
  -bind-type=role \
  -bind-entity=eng-role \
  -selector='engineering in list.groups'
```

В UI: **Log in** → **Continue with Auth0** → ввод учетных данных в браузере.

### 5. Просмотр сервисов и health checks

1. Откройте `https://consul.example.com/ui`.
2. Перейдите в **Services** (страница по умолчанию).
3. Выберите сервис (например, `web-api`).
4. Просмотрите:
   - Статус здоровья (passing/warning/critical).
   - Health checks и их вывод.
   - Экземпляры и их адреса.

### 6. Управление KV через UI

1. Перейдите в **Key/Value**.
2. Навигация по префиксам (например, `config/app/`).
3. Создание/редактирование ключа:
   - Нажмите **Create**.
   - Введите ключ и значение.
   - Настройте флаги (Flags) если нужно.
4. Удаление ключа.

**Важно:** Операции KV требуют ACL-токена с правами `key:write`.

### 7. Управление Intentions через UI

1. Перейдите в **Intentions**.
2. Нажмите **Create**.
3. Выберите Source и Destination сервисы.
4. Установите Action (Allow/Deny).
5. Для L7 intentions добавьте Permissions (методы, пути).

### 8. Интеграция с метриками (Prometheus)

```hcl
ui_config {
  enabled = true
  metrics_provider = "prometheus"
  metrics_proxy {
    base_url = "http://prometheus-server:9090"
    # path_allowlist по умолчанию: ["/api/v1/query_range", "/api/v1/query"]
    add_headers = [
      {
        name = "Authorization"
        value = "Bearer <token>"
      }
    ]
  }
  dashboard_url_templates {
    service = "https://grafana.example.com/d/lDlaj-NGz/service-overview?orgId=1&var-service={{Service.Name}}&var-namespace={{Service.Namespace}}&var-partition={{Service.Partition}}&var-dc={{Datacenter}}"
  }
}
```

### 9. Кастомный metrics provider (экспериментально)

```hcl
ui_config {
  enabled = true
  metrics_provider = "example-apm"
  metrics_provider_files = ["/usr/local/bin/example-metrics-provider.js"]
  metrics_provider_options_json = <<-EOT
    {
      "foo": "bar"
    }
  EOT
}
```

**Важно:** JavaScript файлы загружаются без sandboxing. Оператор несет полную ответственность за их содержимое и provenance.

## Операции и команды

### Проверка здоровья UI

```bash
curl -s http://localhost:8500/v1/ui/health
# → {"ui":true}
```

### CLI флаги

| Флаг | Эквивалент в конфиге | Описание |
| :--- | :--- | :--- |
| `-ui` | `ui_config.enabled = true` | Включает обслуживание UI. |
| `-ui-dir <path>` | `ui_config.dir` | Использует внешнюю директорию с ассетами UI вместо встроенных. |
| `-ui-content-path <path>` | `ui_config.content_path` | Меняет путь, по которому доступен UI (по умолчанию `/ui/`). Допустимы только alphanumerics, `-`, `_`. Путь `/v1/` запрещен. |

### Создание UI токена (CLI)

```bash
# 1. Создать политику
consul acl policy create \
  -name "ui-view-catalog" \
  -rules @ui-view-catalog.hcl \
  -description "Allow viewing catalog in UI"

# 2. Создать токен
consul acl token create \
  -description "UI read-only token" \
  -policy-name "ui-view-catalog"
```

### Перезагрузка конфигурации

При включенном `auto_reload_config = true` некоторые параметры `ui_config` (например, `metrics_provider`, `dashboard_url_templates`) применяются без перезапуска агента. Включение или отключение `enabled` требует перезапуска.

```bash
consul reload
# → Configuration reload triggered
```

## Устранение неполадок

### UI не загружается

- **Диагностика:**
  ```bash
  curl -s http://localhost:8500/v1/ui/health
  # → {"ui":true}
  ```
- **Решение:** Убедитесь, что `ui_config.enabled = true` в конфигурации серверов. В `-dev` режиме UI включен по умолчанию.

### 403 Forbidden при доступе к KV/ACL

- **Причина:** ACL включены, а токен не имеет прав.
- **Решение:** Введите management-токен или токен с политикой, содержащей `key:write` / `acl:write`. Для metrics proxy нужны `service_prefix "" { policy = "read" }` и `node_prefix "" { policy = "read" }` (в Enterprise — обернуто в `namespace_prefix ""`).

### UI медленно загружается / зависает при поиске

- **Причина:** Большой кластер (>5000 узлов) или включенные Blocking Queries.
- **Решение:** Отключите Blocking Queries в **Settings** UI. Используйте reverse proxy с кэшированием статики. Добавляйте фильтры вместо wildcard-запросов.

### Метрики не отображаются в UI

- **Диагностика:** Проверьте доступность Prometheus из агента:
  ```bash
  curl -s "http://prometheus-server:9090/api/v1/query?query=up"
  ```
- **Решение:** Убедитесь, что `metrics_provider = "prometheus"` и `metrics_proxy.base_url` указывает на доступный Prometheus. Проверьте, что ACL-токен пользователя содержит `service:read` и `node:read`.

### Metrics proxy возвращает 403

- **Причина:** У токена пользователя недостаточно прав.
- **Решение:** Предоставьте политику с `service_prefix "" { policy = "read" }` и `node_prefix "" { policy = "read" }`. При включенных namespaces в Enterprise оберните их в `namespace_prefix ""`.

### UI показывает данные только одного ДЦ

- **Причина:** UI подключается к тому агенту, которому принадлежит браузерный запрос.
- **Решение:** Для переключения ДЦ используйте дропдаун в шапке UI. Метрики через metrics proxy работают только для локального ДЦ; для remote-DC требуется Prometheus в каждом ДЦ.

## Лучшие практики

- **Least privilege:** Создавайте отдельные политики для read-only пользователей (`ui-view-catalog`) и операторов. Не давайте UI-токенам `acl:write` без необходимости. Для Enterprise добавьте `operator = "read"` для навигации по partitions.
- **HTTPS:** Всегда используйте TLS в production. Не допускайте доступ к UI по HTTP из внешней сети.
- **Reverse proxy auth:** Дополните защиту basic auth или OIDC перед reverse proxy. Это создает defense in depth.
- **Отключите Blocking Queries для больших кластеров:** В настройках UI снимите галочку Blocking Queries, если ДЦ содержит >5000 узлов.
- **Metrics proxy — осторожно в production:** При отключенных ACL metrics proxy exposes все метрики без аутентификации. Включайте его только с включенными ACL и рассмотрите `add_headers` для авторизации в Prometheus.
- **Кастомные providers:** Не загружайте непроверенные JavaScript файлы через `metrics_provider_files`. Они выполняются в контексте UI и имеют доступ к ACL-токенам и cookies.
- **Автоматизация:** Для CI/CD используйте CLI и HTTP API, а не UI. См. [Consul CLI Reference](./consul_cli_reference.md).
- **Аудит:** Включите audit logging для отслеживания изменений через UI. См. [Consul Audit Logging](./consul_audit_logging.md).

## Граничные случаи

- **Large clusters:** UI может "зависнуть" при отображении >5000 сервисов. Используйте фильтры и поиск. Отключите Blocking Queries.
- **High latency между browser и кластером:** Разместите reverse proxy в том же ДЦ, что и Consul серверы.
- **Multi-DC:** UI показывает данные только одного ДЦ за один запрос. Switching ДЦ через dropdown переподключает к агенту в выбранном ДЦ. Метрики через metrics proxy работают только для локального ДЦ.
- **Custom metrics provider:** Интерфейс экспериментальный и может меняться между версиями. Протестируйте обновление Consul перед применением в production.
- **Sub-path reverse proxy:** Consul UI не поддерживает автоматическую коррекцию API-префикса при размещении по подпути. Требуется ручная настройка прокси или размещение на `/ui/`.
- **Metrics proxy без ACL:** При отключенных ACL любой кто имеет доступ к порту 8500, может запрашивать метрики. Никогда не включайте metrics proxy без ACL в production.
- **Enterprise features in UI:** Наличие Admin Partitions, Namespaces, Cluster Peering и SSO в UI определяется флагами `CONSUL_PARTITIONS_ENABLED`, `CONSUL_NSPACES_ENABLED`, `CONSUL_PEERINGS_ENABLED`, `CONSUL_SSO_ENABLED`, которые автоматически инжектируются при наличии соответствующих блоков в конфигурации агента. См. [Consul Enterprise Licensing](./consul_enterprise_licensing.md).
- **Динамическая конфигурация:** При `auto_reload_config = true` изменение `ui_config` (metrics, dashboard URLs) применяется без рестарта. Включение/отключение `enabled` требует рестарта агента.
- **Одновременный доступ к нескольким ДЦ:** UI не поддерживает одновременный просмотр нескольких ДЦ на одной странице. Используйте отдельные вкладки браузера.

## Дополнительная информация

- **[Explore the Consul web UI](https://developer.hashicorp.com/consul/docs/fundamentals/interface/ui)** — обзор возможностей UI.
- **[UI parameters for Consul agent configuration files](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/ui)** — полный справочник `ui_config`.
- **[Observe service mesh telemetry on VMs](https://developer.hashicorp.com/consul/docs/observe/telemetry/vm)** — конфигурация metrics proxy и dashboard URL templates.
- **[Create a UI token](https://developer.hashicorp.com/consul/docs/secure/acl/token/ui)** — примеры политик для least-privilege доступа.
- **[OpenID Connect (OIDC) Auth Method](https://developer.hashicorp.com/consul/docs/secure/acl/auth-method/oidc)** — настройка SSO в UI.
- **[Consul ACL](./consul_acl.md)** — управление политиками и токенами.
- **[Consul Service Mesh](./consul_service_mesh.md)** — topology visualization и intentions.
- **[Consul Telemetry](./consul_telemetry.md)** — настройка метрик и бэкендов.
- **[Consul Architecture](./consul_architecture.md)** — порты, роли агентов, обслуживание HTTP API.
- **[Consul Enterprise Licensing](./consul_enterprise_licensing.md)** — сравнение OSS и Enterprise функций в UI.
