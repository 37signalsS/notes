# Провайдеры конфигурации Traefik: Nomad, Consul Catalog, HTTP, Go-шаблоны

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6)

## Определения

**Провайдер конфигурации (Configuration Provider)** — внутренний модуль Traefik, отвечающий за автоматическое обнаружение инфраструктуры и поставку динамической конфигурации (маршруты, балансировщики, промежуточные обработчики, TLS-параметры).

**Consul Catalog Provider (`providers.consulCatalog`)** — реестровый провайдер, подключающийся к API HashiCorp Consul Service Catalog для динамического построения роутеров и сервисов на основе зарегистрированных сервисов, их тегов (`tags`) и метаданных (`meta`). Отличается от KV-провайдера (`providers.consul`), который читает сырое дерево ключей.

**Nomad Provider (`providers.nomad`)** — реестровый провайдер оркестратора HashiCorp Nomad. Опрашивает Nomad HTTP API (allocations/jobs), автоматически создавая бэкенды для запущенных экземпляров задач и считывая правила маршрутизации из тегов сервисов в спецификации HCL.

**HTTP Provider (`providers.http`)** — провайдер периодического опроса (polling). Traefik с заданным интервалом выполняет HTTP(S) GET-запрос к внешнему эндпоинту (сервису управления конфигурацией, CMDB, внутреннему генератору) и загружает динамическую конфигурацию в формате JSON или YAML. Traefik API при этом работает строго в режиме чтения — внешняя запись через PUT/POST отсутствует.

**Go-шаблоны в File-провайдере** — механизм динамической препроцессорной обработки конфигурационных файлов Traefik с использованием синтаксиса Go `text/template` и встроенной библиотеки функций **Sprig v3** (переменные окружения, строковые трансформации, циклы, фильтры).

**Provider Namespace (`@<provider>`)** — суффикс контекстной изоляции ресурсов в объединенном реестре Traefik, позволяющий ссылаться на middleware или сервисы, объявленные в другом провайдере (например, `auth@file`, `api-srv@nomad`).

**Providers Throttle Duration (`providers.providersThrottleDuration`)** — глобальный интервал дебаунсинга (по умолчанию `2s`), задающий паузу между повторными пересборками динамического графа маршрутизации при лавинообразных изменениях в инфраструктуре.

---

## Архитектура и базовые концепции

### Модель слияния и приоритет провайдеров

Traefik поддерживает одновременную работу произвольного количества провайдеров. Конфигурации из всех активных источников объединяются в единый runtime-реестр:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Traefik Static Engine                           │
│  providers.providersThrottleDuration: 2s (дебаунсинг пересборок графа) │
└──────▲─────────────────▲──────────────────────▲─────────────────▲──────┘
       │                 │                      │                 │
┌──────┴────────┐ ┌──────┴──────────────┐ ┌─────┴──────────┐ ┌────┴───────┐
│ providers.file│ │providers.consulCatalog│providers.nomad │ │providers.http│
│ (Go-templates)│ │ (Service Discovery) │ │(Job/Alloc Tags)│ │  (Polling)   │
└───────────────┘ └─────────────────────┘ └────────────────┘ └────────────┘
```

При совпадении идентификаторов однотипных объектов между несколькими провайдерами действует детерминированный приоритет (от наивысшего к низшему):

```
kubernetesgateway > kubernetescrd > kubernetes > kubernetesingressnginx
> swarm > docker > file > redis > knative > consul > consulcatalog
> nomad > etcd > ecs > http > zookeeper > rest
```

В on-premise и bare-metal инсталляциях без облачных контроллеров ключевая иерархия выглядит так:
`file` (приоритет 7) > `consul` (10) > `consulcatalog` (11) > `nomad` (12) > `etcd` (13) > `http` (15).

#### Межпровайдерные ссылки (Cross-Provider References)
Каждый ресурс при регистрации получает постфикс своего провайдера. Если роутер объявлен в Nomad или Consul Catalog, он может использовать middleware, объявленное в File-провайдере:

```hcl
# В Nomad job specification:
tags = [
  "traefik.http.routers.app.rule=Host(`app.internal.domain`)",
  "traefik.http.routers.app.middlewares=sec-headers@file,rate-limit@file",
  "traefik.http.routers.app.service=app-service"
]
```

Если суффикс провайдера не указан (например, `middlewares=sec-headers`), Traefik ищет ресурс внутри того же провайдера, в котором объявлен роутер.

### Принцип работы Go-шаблонов в File-провайдере

Шаблонизация активна по умолчанию для любых динамических файлов конфигурации, обрабатываемых `providers.file.directory` или `providers.file.filename`. Отдельного флага включения нет: если парсер обнаруживает блоки `{{ ... }}`, файл передается в шаблонизатор Go с зарегистрированными функциями **Sprig v3**.

Ключевые эксплуатационные свойства:
1. **Контекст исполнения:** шаблоны вычисляются внутри процесса Traefik. Функции `env` считывают переменные окружения процесса Traefik (из systemd unit, `/etc/environment` или переменных контейнера).
2. **Триггер вычисления:** Traefik рендерит шаблоны **только** при событиях файловой системы (inotify `MODIFY`/`CREATE`) или при старте процесса. Изменение переменной окружения в ОС без модификации файла (или `touch`) конфигурацию не обновляет.
3. **Атомарность:** если шаблон содержит синтаксическую ошибку или необработанное исключение, Traefik отклоняет весь файл целиком, оставляет в памяти предыдущую валидную конфигурацию и пишет `level=error` в лог.

### Реестровое обнаружение (Nomad / Consul) vs Опрос (HTTP)

| Характеристика | Nomad (`providers.nomad`) | Consul Catalog (`providers.consulCatalog`) | HTTP (`providers.http`) |
| :--- | :--- | :--- | :--- |
| **Механизм передачи** | HTTP Long-polling / Event Stream | Consul Blocking Queries (`/v1/catalog/...`) | Периодический GET-опрос (`pollInterval`) |
| **Реакция на события** | Мгновенная (< 100 мс после alloc update) | Мгновенная (< 100 мс по Consul watch index) | С задержкой до интервала `pollInterval` |
| **Формат правил** | Теги в блоке `service {}` Nomad HCL | Теги (`tags`) и метаданные (`meta`) сервиса | Полная структура dynamic YAML/JSON |
| **Нагрузка на оркестратор** | Постоянный пул соединений к Nomad API | Запросы к локальному Consul Agent (stale) | Запросы к HTTP-серверу по расписанию |
| **Область применения** | On-premise микросервисы в Nomad | Сервисный каталог bare-metal/VM | Интеграция с CMDB, GitOps-контроллерами |

---

## Практические сценарии и конфигурация

### Сценарий 1: HashiCorp Nomad Service Discovery (`providers.nomad`)

Интеграция с кластером Nomad на bare-metal с разграничением пространств имен, фильтрацией сервисов и канареечными релизами.

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  providersThrottleDuration: 2s
  nomad:
    endpoint:
      address: "http://127.0.0.1:4646"
      region: "global"
      token: "nomad-secret-acl-token-uuid"
    namespaces:
      - "default"
      - "production"
    refreshInterval: 15s
    exposedByDefault: false
    prefix: "traefik"
    defaultRule: "Host(`{{ .Name }}.internal.domain`)"
    constraints: "Tag(`traefik.enable=true`)"
    allowEmptyServices: false
    stale: true
```

#### 2. Задание Nomad с маршрутизацией HTTP и Canary-развертыванием (`api.nomad.hcl`)

```hcl
job "api-service" {
  datacenters = ["dc1"]
  type        = "service"
  namespace   = "production"

  update {
    max_parallel     = 1
    canary           = 1
    min_healthy_time = "15s"
    healthy_deadline = "3m"
    auto_revert      = true
    auto_promote     = false
  }

  group "api-cluster" {
    count = 3

    network {
      mode = "host"
      port "http" {
        to = 8080
      }
    }

    service {
      name     = "api-service"
      port     = "http"
      provider = "nomad"

      # Метки канареечного релиза:
      canary_tags = [
        "traefik.enable=true",
        "traefik.nomad.canary=true",
        "traefik.http.routers.api-canary.rule=Host(`canary-api.internal.domain`)",
        "traefik.http.routers.api-canary.entrypoints=web",
        "traefik.http.services.api-service.loadbalancer.server.port=8080"
      ]

      # Основные производственные метки:
      tags = [
        "traefik.enable=true",
        "traefik.http.routers.api.rule=Host(`api.internal.domain`)",
        "traefik.http.routers.api.entrypoints=web",
        "traefik.http.routers.api.middlewares=strip-api-prefix@file",
        "traefik.http.services.api-service.loadbalancer.server.port=8080",
        "traefik.http.services.api-service.loadbalancer.healthcheck.path=/healthz",
        "traefik.http.services.api-service.loadbalancer.healthcheck.interval=5s",
        "traefik.http.services.api-service.loadbalancer.healthcheck.timeout=2s"
      ]

      check {
        type     = "http"
        path     = "/healthz"
        interval = "10s"
        timeout  = "2s"
      }
    }

    task "server" {
      driver = "docker"

      config {
        image        = "hashicorp/http-echo:latest"
        args         = ["-listen=:8080", "-text=production-api"]
        network_mode = "host"
      }

      resources {
        cpu    = 200
        memory = 128
      }
    }
  }
}
```

#### 3. Маршрутизация чистого TCP через Nomad

Для сервисов баз данных или брокеров очередей без HTTP-заголовков используются TCP-роутеры:

```hcl
service {
  name     = "pg-replica"
  port     = "postgres"
  provider = "nomad"

  tags = [
    "traefik.enable=true",
    "traefik.tcp.routers.pg.rule=HostSNI(`pg-replica.internal.domain`)",
    "traefik.tcp.routers.pg.entrypoints=postgres",
    "traefik.tcp.routers.pg.tls=true",
    "traefik.tcp.services.pg-srv.loadbalancer.server.port=5432"
  ]
}
```

---

### Сценарий 2: HashiCorp Consul Catalog (`providers.consulCatalog`)

Consul Catalog обнаруживает сервисы, зарегистрированные как на самом сервере Consul, так и через Consul Agent на физических серверах и виртуальных машинах.

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
providers:
  providersThrottleDuration: 2s
  consulCatalog:
    endpoint:
      address: "127.0.0.1:8500"
      scheme: "http"
      datacenter: "dc1"
      token: "consul-acl-token-secret"
    exposedByDefault: false
    prefix: "traefik"
    refreshInterval: 15s
    requireConsistent: false
    stale: true
    cache: true
    defaultRule: "Host(`{{ .Name }}.internal.domain`)"
    constraints: "Tag(`traefik.enable=true`)"
    connectAware: false
```

Параметры `stale: true` и `cache: true` критически важны для SRE: они разрешают Traefik обращаться к локальному Consul Agent и обслуживать запросы из кэша памяти агента, предотвращая перегрузку Raft-лидера Consul при частых повторных инициализациях.

#### 2. Регистрация сервиса в Consul через JSON-манифест (`/etc/consul.d/backend.json`)

```json
{
  "service": {
    "name": "billing-app",
    "id": "billing-app-node-01",
    "address": "10.10.20.15",
    "port": 9000,
    "tags": [
      "traefik.enable=true",
      "traefik.http.routers.billing.rule=Host(`billing.internal.domain`) && PathPrefix(`/api/v1`)",
      "traefik.http.routers.billing.entrypoints=websecure",
      "traefik.http.routers.billing.tls=true",
      "traefik.http.routers.billing.tls.options=default@file",
      "traefik.http.services.billing-app.loadbalancer.server.port=9000",
      "traefik.http.services.billing-app.loadbalancer.passhostheader=true",
      "traefik.http.services.billing-app.loadbalancer.responseforwarding.flushinterval=100ms"
    ],
    "meta": {
      "environment": "production",
      "owner": "finance-team"
    },
    "checks": [
      {
        "id": "billing-http-check",
        "name": "Billing HTTP Health Check",
        "http": "http://10.10.20.15:9000/health",
        "interval": "10s",
        "timeout": "2s"
      }
    ]
  }
}
```

После размещения файла манифеста на целевом хосте выполняется регистрация:

```bash
consul reload
# → Configuration reloaded!
```

---

### Сценарий 3: HTTP Polling Provider (`providers.http`)

Провайдер периодического опроса предназначен для получения динамической конфигурации от внешнего HTTP-сервера (внутреннего шлюза конфигураций, сервиса генерации топологии или централизованного оркестратора).

#### Архитектурное отличие от Traefik v1 REST Provider:
> [!IMPORTANT]
> В Traefik v2 и v3 **нет эндпоинта записи динамической конфигурации через `PUT /api/providers/...`**. Встроенный API Traefik (`api: {}`) строго read-only. Провайдер `providers.http` работает по модели **Pull (Polling)**: Traefik сам регулярно опрашивает внешний сервис, указанный в параметре `endpoint`, забирая динамический документ (JSON или YAML).

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
providers:
  providersThrottleDuration: 2s
  http:
    endpoint: "https://config-generator.internal:8443/api/v1/traefik-topology"
    pollInterval: 10s
    pollTimeout: 3s
    headers:
      Authorization: "Bearer sec-infra-token-987654"
      X-Datacenter: "dc-onprem-primary"
    maxResponseBodySize: 10485760 # 10 МБ максимум
    tls:
      ca: "/etc/traefik/certs/internal-ca.pem"
      cert: "/etc/traefik/certs/traefik-client.crt"
      key: "/etc/traefik/certs/traefik-client.key"
      insecureSkipVerify: false
```

#### 2. Спецификация ответа внешнего сервиса (Payload)

Внешний сервис по адресу `https://config-generator.internal:8443/api/v1/traefik-topology` на каждый GET-запрос должен возвращать HTTP 200 OK со стандартным содержимым dynamic configuration (схема идентична File-провайдеру):

```json
{
  "http": {
    "routers": {
      "external-crm": {
        "entryPoints": ["websecure"],
        "rule": "Host(`crm.internal.domain`)",
        "service": "crm-backend-service",
        "tls": {}
      }
    },
    "services": {
      "crm-backend-service": {
        "loadBalancer": {
          "passHostHeader": true,
          "servers": [
            { "url": "http://10.20.30.11:8080" },
            { "url": "http://10.20.30.12:8080" }
          ]
        }
      }
    }
  }
}
```

---

### Сценарий 4: Go-шаблоны и функции Sprig в File-провайдере

Генерация комплексных наборов роутеров для множества виртуальных хостов или сред на основе переменных окружения хоста без дублирования YAML-блоков.

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
providers:
  file:
    directory: "/etc/traefik/dynamic"
    watch: true
```

#### 2. Переменные окружения демона (например, в `/etc/systemd/system/traefik.service.d/env.conf`)

```ini
[Service]
Environment="TRAEFIK_ENV=production"
Environment="APP_LIST=auth,billing,orders,analytics"
Environment="AUTH_SERVERS=10.0.1.10:8000,10.0.1.11:8000"
Environment="BILLING_SERVERS=10.0.2.10:8000"
Environment="ORDERS_SERVERS=10.0.3.10:8000,10.0.3.11:8000,10.0.3.12:8000"
Environment="ANALYTICS_SERVERS=10.0.4.10:8000"
```

#### 3. Шаблонизированный динамический файл (`/etc/traefik/dynamic/services.yml`)

```yaml
{{- $env := env "TRAEFIK_ENV" | default "staging" }}
{{- $apps := env "APP_LIST" | default "app" | split "," }}

http:
  routers:
    {{- range $app := $apps }}
    {{- $cleanApp := $app | trim }}
    router-{{ $cleanApp }}:
      rule: "Host(`{{ $cleanApp }}.{{ $env }}.internal.domain`)"
      entryPoints:
        - "websecure"
      service: "srv-{{ $cleanApp }}"
      middlewares:
        - "sec-headers@file"
      tls: {}
    {{- end }}

  middlewares:
    sec-headers:
      headers:
        sslRedirect: true
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        frameDeny: true
        contentTypeNosniff: true

  services:
    {{- range $app := $apps }}
    {{- $cleanApp := $app | trim }}
    {{- $envVarName := printf "%s_SERVERS" ($cleanApp | upper) }}
    {{- $rawServers := env $envVarName }}
    srv-{{ $cleanApp }}:
      loadBalancer:
        passHostHeader: true
        servers:
          {{- if $rawServers }}
          {{- range $backend := $rawServers | split "," }}
          - url: "http://{{ $backend | trim }}"
          {{- end }}
          {{- else }}
          - url: "http://127.0.0.1:9999" # Fallback заглушка при отсутствии серверов
          {{- end }}
    {{- end }}
```

---

### Сценарий 5: Гибридная конфигурация с межпровайдерными ссылками

Объединение оркестратора (Nomad/Consul) с централизованным хранилищем политик безопасности и TLS в файлах:

```yaml
# /etc/traefik/dynamic/common-middlewares.yml
http:
  middlewares:
    global-rate-limit:
      rateLimit:
        average: 100
        burst: 50
    corp-whitelist:
      ipWhiteList:
        sourceRange:
          - "10.0.0.0/8"
          - "192.168.0.0/16"

tls:
  options:
    strict-tls:
      minVersion: "VersionTLS13"
      sniStrict: true
```

Использование в тегах сервиса Nomad:

```hcl
tags = [
  "traefik.enable=true",
  "traefik.http.routers.erp.rule=Host(`erp.internal.domain`)",
  "traefik.http.routers.erp.entrypoints=websecure",
  "traefik.http.routers.erp.middlewares=corp-whitelist@file,global-rate-limit@file",
  "traefik.http.routers.erp.tls.options=strict-tls@file",
  "traefik.http.services.erp-service.loadbalancer.server.port=8080"
]
```

---

## Операции и диагностика

Диагностические команды для проверки состояния провайдеров и регистрации сервисов.

### 1. Проверка состояния провайдеров через Traefik API

```bash
# Получить статус инициализации и ошибки загрузки провайдеров
curl -s "http://127.0.0.1:8080/api/overview" | jq '.providers'
# → {
# →   "file": true,
# →   "consulCatalog": true,
# →   "nomad": true,
# →   "http": true
# → }

# Проверить список активных роутеров и источник их провайдера
curl -s "http://127.0.0.1:8080/api/http/routers" | jq '.[] | {name: .name, provider: .provider, status: .status, rule: .rule}'
# → {
# →   "name": "api@nomad",
# →   "provider": "nomad",
# →   "status": "enabled",
# →   "rule": "Host(`api.internal.domain`)"
# → }
# → {
# →   "name": "billing@consulcatalog",
# →   "provider": "consulcatalog",
# →   "status": "enabled",
# →   "rule": "Host(`billing.internal.domain`)"
# → }

# Полный срез всех обнаруженных бэкендов в рантайме
curl -s "http://127.0.0.1:8080/api/rawdata" | jq '.services | to_entries[] | {name: .key, servers: .value.loadBalancer.servers}'
```

### 2. Инспекция сервисов в HashiCorp Nomad

```bash
# Проверить регистрацию сервиса в Nomad Service Discovery
nomad service list
# → Service Name  Job ID        Namespace
# → api-service   api-service   production

# Проверить теги конкретного экземпляра задачи
nomad service info -namespace=production api-service
# → Allocation ID  Address          Port  Tags
# → 4b1f8c32       10.10.10.15      8080  traefik.enable=true,traefik.http.routers.api.rule=Host(`api.internal.domain`)
```

### 3. Инспекция каталога в HashiCorp Consul

```bash
# Проверить адреса и теги зарегистрированных экземпляров
consul catalog nodes -service=billing-app
# → Node          Address      ServicePort  Tags
# → node-01       10.10.20.15  9000         traefik.enable=true,traefik.http.routers.billing.rule=...

# Выполнить проверку фильтрации по тегам через curl к API Consul
curl -s "http://127.0.0.1:8500/v1/health/service/billing-app?passing=true" | jq '.[].Service.Tags'
```

### 4. Принудительное обновление Go-шаблонов File-провайдера

```bash
# Обновить timestamp файла для вызова inotify-триггера Traefik
touch /etc/traefik/dynamic/services.yml

# Проверить журнал systemd на наличие синтаксических ошибок рендеринга шаблона
journalctl -u traefik -n 20 --no-pager | grep -i "template"
# → [OK при отсутствии ошибок]
```

---

## Устранение неисправностей

| Проблема | Диагностика | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Сервисы из Nomad/Consul не появляются в Traefik** | `curl 127.0.0.1:8080/api/http/routers` не содержит нужного маршрута; в логах нет упоминаний сервиса | 1. Установлен `exposedByDefault: false`, но в тегах отсутствует `traefik.enable=true`.<br>2. Имя тегов не начинается с `prefix` (по умолчанию `traefik`).<br>3. Токен ACL не имеет прав на чтение каталога (`service:read`). | Добавить `traefik.enable=true` в `tags`; проверить валидность ACL-токена: `nomad acl token self` или `consul acl token read -self`. |
| **502 Bad Gateway при балансировке на задачу Nomad** | В access-логе статус `502`; в Traefik логе: `dial tcp 10.10.10.15:0: connect: can't assign requested address` | У задачи объявлено несколько портов или динамический порт, и Traefik не смог определить целевой порт (выбрал `0`). | Явно зафиксировать порт сервиса в тегах: `traefik.http.services.<srv>.loadbalancer.server.port=<порт>`. |
| **Высокая нагрузка на CPU / Flapping при массовом перезапуске задач** | Процесс Traefik утилизирует 100% одного ядра CPU, постоянные логи `Configuration received from provider` | Слишком короткий интервал дебаунсинга; частые обновления из Nomad/Consul вызывают бесконечный рендеринг графа. | Увеличить задержку дебаунсинга: `providers.providersThrottleDuration: 2s` (или `5s` для крупных инсталляций). |
| **Ошибка рендеринга Go-шаблона в File-провайдере** | В логах Traefik: `error while reading configuration file ... function "foo" not defined` или `template: ... nil pointer` | Использована функция, отсутствующая в Sprig v3, либо переменная окружения не существует и не задан `default`. | Добавить безопасные значения по умолчанию: `{{ env "VAR" \| default "value" }}`; проверить список встроенных функций Sprig. |
| **Ошибки опроса в HTTP Provider (`providers.http`)** | В логах: `HTTP provider connection timeout` или `Error while polling configuration: 401 Unauthorized` | Внешний эндпоинт недоступен, отвечает дольше `pollTimeout`, либо передан невалидный заголовок `Authorization`. | Проверить доступность: `curl -v -H "Authorization: Bearer ..." <endpoint>`; настроить `pollTimeout: 10s` при тяжелых генерациях. |
| **Ошибка `middleware not found` при использовании общего middleware** | В логах: `middleware "corp-whitelist" does not exist` для роутера Nomad | Роутер из провайдера Nomad ищет middleware внутри пространства `@nomad`, а middleware создано в файле. | Указать явный суффикс провайдера: `traefik.http.routers.app.middlewares=corp-whitelist@file`. |
| **504 Gateway Timeout при обращении к Consul Catalog** | В логах: `consulCatalog: Failed to read services: Get ... context deadline exceeded` | Consul Agent перегружен Raft-запросами или сетевой задержкой между датацентрами при строгом кворуме. | Включить `stale: true` и `cache: true` в настройках `providers.consulCatalog`, чтобы читать данные из локального кэша агента. |

---

## Лучшие практики

### 1. Безопасность и контроль доступа
- **Принцип наименьших привилегий для ACL:** токены Nomad (`token`) и Consul (`token`), передаваемые в Traefik, должны обладать строго read-only правами на пространства имен (`namespace { policy = "read" }`, `service_prefix "" { policy = "read" }`, `node_prefix "" { policy = "read" }`).
- **Скрытие сервисов по умолчанию:** всегда устанавливайте `exposedByDefault: false`. Это гарантирует, что случайно развернутые тестовые или служебные задачи не будут автоматически опубликованы во внешний периметр.
- **Отсутствие чувствительных данных в тегах:** никогда не передавайте приватные ключи, токены авторизации или пароли в строках тегов Nomad/Consul. Теги видны всем пользователям с правом чтения каталога. Все секреты и TLS-сертификаты должны подключаться через File-провайдер или хранилище секретов.

### 2. Надежность (SRE) и масштабируемость
- **Использование Stale Reads:** для провайдеров Consul и Nomad включайте флаг `stale: true`. Это снижает нагрузку на Raft-кворум лидеров в 10–50 раз, направляя поток запросов обнаружения сервисов на локальные агенты нод.
- **Тюнинг дебаунсинга:** на крупных bare-metal кластерах (от 50+ нод и 500+ сервисов) установите `providersThrottleDuration: 3s–5s`. Это предотвратит "шторм перезагрузок" во время массового обновления кластера оркестратором.
- **Таймауты опроса в HTTP-провайдере:** при использовании `providers.http` параметр `pollTimeout` должен быть строго меньше `pollInterval` (например, `pollInterval: 10s`, `pollTimeout: 3s`), чтобы предотвратить наложение конкурирующих запросов опроса.

### 3. Эксплуатационные стандарты именования
- **Пространства имен для сервисов:** используйте четкие соглашения именования роутеров и сервисов в тегах (например, `<namespace>-<app_name>`), чтобы исключить коллизии между командами.
- **Явная фиксация портов:** всегда указывайте `traefik.http.services.<srv>.loadbalancer.server.port` в тегах сервисов, если контейнер или задача экспонирует более одного сетевого порта.

---

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — фундаментальные концепции, архитектура ядра и жизненный цикл запроса.
- [Traefik: KV-store провайдеры](./traefik-providers-kv-stores.md) — детальный разбор сырых Key-Value провайдеров: Consul KV, etcd, Redis, ZooKeeper.
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — конфигурация роутеров и балансировки с использованием меток Docker.
- [Traefik на bare-metal](./traefik-bare-metal.md) — развертывание Traefik в виде systemd-сервиса на выделенных серверах.
- [Высокая доступность Traefik (HA)](./traefik-high-availability.md) — организация кластера Traefik с общей конфигурацией и балансировкой.
- [Миграция с Traefik v2 на v3](./traefik-migration-v2-to-v3.md) — изменения в синтаксисе правил маршрутизации и конфигурационных опций.
- [Основы Nomad: концепции и архитектура](../../Nomad/definitions_and_concepts.md) — базовые принципы работы оркестратора HashiCorp Nomad.
- [Практические сценарии Nomad](../../Nomad/practical_scenarios.md) — развертывание и эксплуатация рабочих нагрузок в Nomad.
- [Архитектура HashiCorp Consul](../../Consul/consul_architecture.md) — принципы работы агентов, серверов и протокола Raft.
- [Каталог сервисов Consul](../../Consul/consul_service_catalog.md) — регистрация сервисов, проверка работоспособности и интеграция с DNS.