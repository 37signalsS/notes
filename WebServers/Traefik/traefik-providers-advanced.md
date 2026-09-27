# Провайдеры конфигурации Traefik: Nomad, Consul Catalog, HTTP (API), Go-шаблоны

## Определения

**Провайдер конфигурации** — источник динамической конфигурации Traefik (роутеры, сервисы, middleware). Провайдеров несколько; статические опции при этом всегда берутся из файла/CLI/флагов.

**Consul Catalog** — провайдер, читающий реестр сервисов HashiCorp Consul (health-статусы, теги, метаданные) и строящий маршруты по меткам (аналогично Docker-меткам). В отличие от **KV-store провайдера** (`providers.consul` — чтение ключей `traefik/` напрямую), Consul Catalog использует именно известный сервисный каталог.

**Nomad** — оркестратор HashiCorp; провайдер Nomad читает allocation/job метаданные и генерирует маршруты аналогично Docker.

**HTTP (API) провайдер** — способ передать динамическую конфигурацию в Traefik в рантайме через REST-эндпоинт `/api/providers/http` (в v2 назывался REST provider через `/api/providers/rest`).

**Go-шаблоны в File-провайдере** — обработка динамических файлов конфигурации как шаблонов с функциями Go `text/template` + библиотеки Sprig (например `{{ env "VAR" }}`, циклы `range`).

## Базовые концепции

### Общая модель и приоритет провайдеров

Traefik может использовать сразу несколько провайдеров одновременно: они **объединяются** в единую конфигурацию динамики. При конфликте одинаковых ключей провайдеры имеют строгий приоритет (перечислен в официальной документации, порядок от высшего к низшему):

```
kubernetesgateway > kubernetescrd > kubernetes > kubernetesingressnginx
> swarm > docker > file > redis > knative > consul > consulcatalog
> nomad > etcd > ecs > http > zookeeper > rest
```

Правила безопасности при конкурентном использовании:

- один и тот же роутер, объявленный в нескольких провайдерах, «побеждает» провайдер с более высоким приоритетом;
- не используйте несколько KV/реестровых провайдеров с перекрывающимися маршрутами — только если уверены, что об этом знаете (типичный баг продакшена: Docker-метки + File-шаблоны дублируют одни и те же роутеры).

### Go-шаблоны в File-провайдере (важно!)

Шаблонизацию **включать не нужно** — для файлов в `providers.file.directory` или `providers.file.filename`, когда файл содержит `{{ ... }}`, Traefik обработает его как Go-шаблон с функциями **Sprig**. Особенности:

- работают только в динамических файлах (не в основном `traefik.yml`/статике);
- доступны: `{{ env "MY_ENV_VAR" }}`, `{{ range $i, $e := .MyList }}`, функции Sprig (`default`, `upper`, `join`, итд);
- шаблон выполняется на каждый приход «раскатки» — переменные окружения должны существовать у процесса Traefik;
- при ошибке выполнения шаблона Traefik не применяет конфиг и пишет ошибку в лог — файл не «полуприменяется».

Пример динамического файла с шаблоном:

```yaml
# /etc/traefik/dynamic/backend.yml
http:
  routers:
    app:
      rule: "Host(`{{ env "APP_DOMAIN" }}`)"
      service: "app"
      tls: {}
  services:
    app:
      loadBalancer:
        servers:
          - url: "http://{{ env "BACKEND_HOST" }}:8080"
```

И в статике только:

```yaml
providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true
```

## Практические сценарии

### Сценарий 1: Провайдер Nomad

```yaml
providers:
  nomad:
    endpoint:
      address: "http://127.0.0.1:4646"     # URL API Nomad
    namespaces: []                        # все неймспейсы (для multitenancy)
    exposedByDefault: false               # включать только метченые
    prefix: "traefik"                     # ключ меток
    defaultRule: "Host(`{{ .Name }}.nomad.local`)"
    constraints:
      - "status == running"
```

Метки на задании (job) — аналогично Docker (docker-compose пример см. [Traefik с Docker Compose](./traefik_with_docker_compose.md)):

```hcl
service {
  name = "app"
  tags = ["traefik.enable=true", "traefik.http.routers.app.rule=Host(`app.example.com`)"]
  port = 8080
}
```

- `consulCatalog` и `nomad` — реестровые провайдеры: Traefik слушает изменения каталога и пересобирает роутеры в рантайме.
- Назначение: мультиВМ/bare-metal и инфраструктура на Nomad/Consul без контейнеров Docker (масштабируется до множества инстансов Traefik — [HA](./traefik-high-availability.md)).

### Сценарий 2: Провайдер Consul Catalog

```yaml
providers:
  consulCatalog:
    endpoint:
      address: "10.0.0.10:8500"
    exposedByDefault: false
    prefix: "traefik"
    defaultRule: "Host(`{{ .Name }}.example.com`)"
    constraints:
      - "operator == support"            # фильтр по value-value метке
    scheme: "http"                       # / https
    watch: true
```

Метка в Consul (через `consul services register` c `meta`/`tags`):

```bash
consul services register consulkv_register(
  "meta": {
    "traefik.enable": "true",
    "traefik.http.routers.frontend.rule": "Host(`consul.example.com`)"
  }
)
```

Обратите внимание: метаданные (`meta`) поддерживаются в свежих версиях Consul/провайдера; при старом Consul используйте `tags`.

### Сценарий 3: HTTP (API) провайдер — динамическое обновление конфига без рестарта и без файлов

Включение — не требуется отдельной секции «провайдер»: эндпоинт всегда доступен при включенном API (см. [Обзор Traefik](./traefik_overview.md), `api.insecure`/`entryPoints.api`).

```bash
# Продавить полный конфиг динамики (PUT)
curl -X PUT -H "Content-Type: application/json" \
  -d '{"http":{"routers":{"dyr":{"rule":"Host(`dyn.example.com`)","service":"dynser"}},"services":{"dynser":{"loadBalancer":{"servers":[{"url":"http://10.0.0.5:8080"}]}}}}}' \
  "http://127.0.0.1:8080/api/providers/http"

# Проверить, что применено
curl -s "http://127.0.0.1:8080/api/http/routers" | jq '.[].name'

# Удалить целиком
curl -X DELETE "http://127.0.0.1:8080/api/providers/http"
```

Особенности:

- в v3 это HTTP Provider (PUT/DELETE на `/api/providers/http`); в v2 — REST Provider (`/api/providers/rest`). Миграция: см. [Миграция v2 → v3](./traefik-migration-v2-to-v3.md).
- эндпоинт **не аутентифицирован** по умолчанию — к `api` подключайте только через внутренний entrypoint/Trusted IPs, иначе любой сможет писать конфиг;
- конфиг не персистится — после рестарта Traefik всё «забывает» (это точечное решение, а не источник правды; для прод-постоянства используйте File/KV-хранилище);
- «http» в списке провайдеров (раздел выше) — это **данный** провайдер, у него же есть статическая секция `providers.http` для настройки дефолтной конфигурации, приходящей при PUT.

### DNS resolution и сервис-дискавери

Провайдеры Docker, Kubernetes, Consul, Nomad зависят от DNS для разрешения имен сервисов. Типичные проблемы:

1. **DNS timeout при старте Traefik** (Docker provider):
   - Traefik не может resolve имя бэкенда → `service not found` в логах.
   - Причина: Docker-сеть без DNS (передаете `network_mode: host`), или `ndots: 5` в `/etc/resolv.conf` пода Traefik заставляет ждать 5+ секунд на каждый не-FQDN запрос.
   - Решение: для контейнерного Traefik используйте стандартный `bridge`/`overlay` драйвер (встроенный DNS); для Kubernetes — проверьте CoreDNS.

2. **Consul Catalog: сервисы не появляются**:
   - Consul agent на `127.0.0.1:8500` не резолвится из контейнера Traefik.
   - Решение: использовать адрес Consul, доступный из сети Traefik (не `localhost`), или `network_mode: host`.

3. **Kubernetes: ExternalName сервисы**:
   - ExternalName возвращает CNAME; Traefik делает二次ный DNS-запрос.
   - Если CoreDNS пересылает на корпоративный resolver с низким TTL — кэш Traefik (если используется) может устареть.
   - Решение: `providers.kubernetes.ingressClass` и `allowExternalNameServices: true` (по умолчанию `false` в v3).

Диагностика:

```bash
# Внутри контейнера Traefik
docker compose exec traefik cat /etc/resolv.conf
# → nameserver 127.0.0.11 (Docker embedded DNS)

# Проверка резолва
docker compose exec traefik nslookup app-backend
# → должен вернуть IP

# Для Consul/K8s: проверка доступности API резолвера
curl -s http://consul:8500/v1/catalog/service/app | jq '.[].ServiceAddress'
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Роутеры не появляются из Nomad/Consul** | `exposedByDefault: false`, метки не совпадают с `prefix` (по умолчанию `traefik`) | Убедиться в метках `traefik.enable=true` и префиксе; проверить сетевую доступность API оркестратора |
| **Дубликаты роутеров из Nesting-провайдеров** | Одна и та же конфигурация в File и в реестре | Убрать дубли или делегировать одну «зону» провайдеру с более высоким приоритетом |
| **`{{ env "..." }}` стало `string`, а не переменная** | Файл не в `directory`, а в статическом `traefik.yml` | Шаблоны работают только в динамических файлах |
| **HTTP Provider: конфиг пропал после рестарта** | Это неустойчивое хранилище | Использовать File/KV как источник правды, HTTP Provider — для временных вмешательств |
| **503 Not ready до применения конфига** | Еще не «прикатился» PUT / не загружена директория | Дождаться загрузки; смотреть `traefik_service_`-метрики и лог |

## Рекомендации

- Двойная запись одного роутера в разных провайдерах — антипаттерн: приоритет выстраивается, но внезапные изменения в «верхнем» провайдере «перебивают» конфиг ниже.
- Не используйте HTTP Provider как единственный источник правды; его роль — оперативные исправления «на лету» при расследовании инцидентов.
- `exposedByDefault: false` всегда в реестровых провайдерах — так новые сервисы не «выстреливают» на prod-домены случайно.
- KV-store провайдеры (Consul/etcd/ZooKeeper/Redis) — отдельная тема, разобрана в [Traefik: KV-store провайдеры](./traefik-providers-kv-stores.md).
- Для множества одинаковых инстансов Traefik (HA) именно реестровые/файловые провайдеры дают общий источник конфига (см. [HA Traefik](./traefik-high-availability.md)).

## Дополнительная информация

- [Traefik: KV-store провайдеры](./traefik-providers-kv-stores.md) — Consul/etcd/ZooKeeper/Redis как хранилище конфигурации.
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — тот же паттерн меток для Docker.
- [Traefik на bare-metal](./traefik-bare-metal.md) — запуск без контейнеров, File-провайдер.
- [Nomad: основы](../../Nomad/definitions_and_concepts.md) — концепции HashiCorp Nomad.
- [Nomad + Consul Connect](../../Nomad/nomad_consul_connect.md) — интеграция с сетевой политикой Consul.