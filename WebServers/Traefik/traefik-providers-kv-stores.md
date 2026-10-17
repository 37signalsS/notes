# Провайдеры конфигурации: Consul, etcd, Redis, ZooKeeper

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6; с замечаниями по обратной совместимости с Traefik v2.x)

---

## Определения

- **KV Provider (Key-Value провайдер)** — механизм Traefik для получения динамической конфигурации (роутеров, сервисов, middleware, serversTransport, TLS-опций) из распределенного иерархического хранилища пар «ключ-значение» (Consul KV, etcd, Redis, Apache ZooKeeper).
- **Static Configuration (Статическая конфигурация)** — неизменяемые во время работы параметры процесса Traefik (точки входа `entryPoints`, подключение к KV-хранилищам `providers.consul`, логирование, метрики), задаваемые через файл `traefik.yml`, флаги командной строки (CLI) или переменные окружения.
- **Dynamic Configuration (Динамическая конфигурация)** — граф маршрутизации (HTTP/TCP/UDP роутеры, правила `rule`, middleware, балансировщики `loadBalancer`, адреса бэкендов `servers`), который считывается из провайдера на лету без перезапуска процесса Traefik.
- **Root Key (`rootKey`)** — базовый префикс в дереве ключей хранилища (по умолчанию `traefik`), под которым Traefik ожидает обнаружить иерархическую структуру динамических параметров.
- **Debouncing (`providersThrottleDuration`)** — защитный интервал задержки (по умолчанию `2s`), в течение которого Traefik накапливает пачку событий об изменении ключей из хранилища перед пересборкой внутреннего графа маршрутизации, предотвращая шторм перезагрузок и высокое потребление CPU.
- **Consul KV** — распределенное транзакционное key-value хранилище на базе алгоритма консенсуса Raft, встроенное в HashiCorp Consul. Позволяет организовать долгоживущие HTTP-подписки (blocking queries).
- **etcd** — распределенное надежное key-value хранилище с консенсусом Raft, использующее gRPC и стриминговый протокол Watch API для моментальной доставки дельт ключей.
- **Redis Provider** — интеграция с Redis (отдельный инстанс, реплики или кластер под управлением Redis Sentinel), где иерархия ключей Traefik хранится в виде строковых значений в заданной базе данных (`db`).
- **Apache ZooKeeper** — распределенный сервис координации с древовидной структурой узлов (znodes) и механизмом оповещений (watches), широко применяемый в корпоративных On-Premise кластерах.
- **Cross-Provider Reference (`@<provider>`)** — механизм ссылок на ресурсы других провайдеров. Внутри KV-дерева сервисы или middleware могут ссылаться на статические или внешние объекты (например, `service = "api@internal"` или `serversTransport = "secure-transport@file"`).

---

## Базовые концепции и архитектура

### Принцип трансляции YAML в дерево ключей

В отличие от файлового провайдера (`providers.file`), где динамическая конфигурация описывается декларативным документом YAML или TOML, KV-провайдеры оперируют плоским списком ключей и значений. Traefik выполняет автоматический маппинг вложенных структур YAML в пути ключей по следующим строгим правилам:

1. **Разделитель иерархии:** В качестве разделителя уровней вложенности всегда используется прямой слэш (`/`).
2. **Списки и массивы:** Элементы коллекций индексируются целыми числами, начиная с нуля: `/0`, `/1`, `/2` и т. д. Форматы со скобками (такие как `entryPoints[]`) **не допускаются**.
3. **Регистронезависимость:** Пути ключей в Traefik нечувствительны к регистру (case-insensitive), однако для стандартизации рекомендуется придерживаться `lowerCamelCase` или единого нижнего регистра.
4. **Запрет символа `@` в именах:** Имена создаваемых роутеров, сервисов и middleware не должны содержать символ `@`, так как он зарезервирован ядром Traefik для разделения имени ресурса и названия провайдера-источника (например, `app-router@consul`).
5. **Типы данных:**
   - Строки: обычный текст (строки с пробелами и спецсимволами передаются без внешних кавычек в само значение, либо экранируются в зависимости от CLI хранилища).
   - Булевы флаги: литералы `true` или `false`.
   - Числа: строковое представление целого числа (например, `42`, `8080`).
   - Длительности (Duration): число с суффиксом времени Go (например, `10s`, `500ms`, `2m`).

```
                              Дерево ключей в хранилище (KV)
                       ┌──────────────────────────────────────────┐
                       │ traefik/http/routers/web-app/rule        │ = Host(`app.example.internal`)
                       │ traefik/http/routers/web-app/service     │ = app-service
                       │ traefik/http/routers/web-app/entrypoints/0│ = websecure
                       │ traefik/http/routers/web-app/middlewares/0│ = sec-headers
                       │ traefik/http/services/app-service/loadbalancer/servers/0/url │ = http://10.0.1.10:8080
                       │ traefik/http/services/app-service/loadbalancer/servers/1/url │ = http://10.0.1.11:8080
                       └──────────────────────────────────────────┘
                                            │
                                            ▼  Watch / Streaming / Polling
                       ┌──────────────────────────────────────────┐
                       │              Traefik Core                │
                       │   providersThrottleDuration (дебаунсинг)  │
                       └──────────────────────────────────────────┘
                                            │
                                            ▼  Пересборка рантайм-графа
                       ┌──────────────────────────────────────────┐
                       │               Входной трафик             │
                       │ EntryPoint (:443) -> Router -> Service    │
                       └──────────────────────────────────────────┘
```

Соответствие между форматом YAML и ключами KV:

```yaml
# Эквивалент в dynamic YAML:
http:
  routers:
    web-app:
      rule: "Host(`app.example.internal`)"
      service: "app-service"
      entryPoints:
        - "websecure"
      middlewares:
        - "sec-headers"
  services:
    app-service:
      loadBalancer:
        servers:
          - url: "http://10.0.1.10:8080"
          - url: "http://10.0.1.11:8080"
```

В KV-хранилище преобразуется в набор пар:

```text
traefik/http/routers/web-app/rule                                    -> "Host(`app.example.internal`)"
traefik/http/routers/web-app/service                                 -> "app-service"
traefik/http/routers/web-app/entrypoints/0                           -> "websecure"
traefik/http/routers/web-app/middlewares/0                           -> "sec-headers"
traefik/http/services/app-service/loadbalancer/servers/0/url        -> "http://10.0.1.10:8080"
traefik/http/services/app-service/loadbalancer/servers/1/url        -> "http://10.0.1.11:8080"
```

---

### Архитектура отслеживания изменений (Watch-механизмы)

Каждое хранилище реализует собственный транспортный механизм доставки изменений в Traefik:

1. **HashiCorp Consul KV:** Использует HTTP Long Polling с параметром `index` (Consul Blocking Queries). Traefik держит постоянное HTTP-соединение к Consul Agent или Server; при изменении метаданных индекса транзакции в Consul HTTP-ответ немедленно возвращает актуальное состояние поддерева.
2. **etcd v3:** Использует двунаправленный gRPC-стрим через `etcd/api/v3/v3rpc`. Traefik подписывается на диапазон ключей с префиксом `traefik/`. Изменения передаются моментально с минимальными накладными расходами на сетевой стек.
3. **Redis:** Опрашивает ключи и отслеживает обновления через внутренние механизмы драйвера (keyspace notifications и сканирование префиксов). При работе через Sentinel Traefik автоматически переключает чтение при смене мастера.
4. **Apache ZooKeeper:** Устанавливает ZK-вотчеры (`Watchers`) на корневой znode и его дочерние узлы. При изменении узла ZooKeeper отправляет однократное событие, после чего Traefik повторно запрашивает дерево и переустанавливает вотчер.

---

### Различие: KV-провайдеры vs Service Discovery (Catalog)

Важно не путать провайдеры сырого KV-дерева с сервисными провайдерами Service Discovery:

| Критерий | KV Провайдеры (`providers.consul`, `providers.etcd`, `providers.redis`, `providers.zooKeeper`) | Catalog / Orchestrator (`providers.consulCatalog`, `providers.nomad`, `providers.docker`) |
| :--- | :--- | :--- |
| **Источник данных** | Произвольное дерево ключей и строковых значений | Реестр зарегистрированных инстансов сервисов и их метаданные/теги |
| **Создание роутеров** | Явное: каждый роутер, правило и связь с сервисом должны быть записаны ключом | Автоматическое: Traefik генерирует роутеры на основе тегов сервиса (например, `traefik.http.routers...`) |
| **Управление бэкендами** | Внешнее: IP и порты серверов прописываются вручную или внешним скриптом/контроллером | Автоматическое: инстансы добавляются и удаляются по факту прохождения health-check в оркестраторе/каталоге |
| **Назначение** | Централизованное управление правилами маршрутизации, middleware, сертификатами, canary-релизами | Автоматическое обнаружение сервисов и динамическая регистрация эндпоинтов |

---

### Сравнительный анализ поддерживаемых KV-хранилищ

| Характеристика | Consul KV | etcd v3 | Redis | Apache ZooKeeper |
| :--- | :--- | :--- | :--- | :--- |
| **Протокол Traefik** | HTTP / HTTPS (REST API) | gRPC / HTTP/2 | TCP / TLS (RESP) | TCP / TLS (ZK binary) |
| **Модель консенсуса** | HashiCorp Raft | Raft (CoreOS) | Асинхронная репликация / Sentinel | ZAB (ZooKeeper Atomic Broadcast) |
| **Транспорт событий** | HTTP Blocking Queries | gRPC Streaming Watch | Polling / Pub-Sub | Node Watchers |
| **Максимальный размер значения** | 512 КБ (стандарт Consul) | 1.5 МБ (`--max-request-bytes`) | 512 МБ (практически < 1 МБ) | 1 МБ (`jute.maxbuffer`) |
| **Аутентификация** | ACL Token (Bearer), Basic Auth | Username / Password, mTLS | Password (AUTH), ACL (v6+) | Digest / SASL (Kerberos), mTLS |
| **Рекомендация SRE** | Отлично при наличии Consul в стеке | Стандарт для Kubernetes и etcd кластеров | Минимальные задержки, простота | Корпоративные BigData/Java кластеры |

---

## Практические сценарии

### Сценарий 1: HashiCorp Consul KV — защищенная маршрутизация с mTLS и ACL

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  providersThrottleDuration: "2s"
  consul:
    endpoints:
      - "127.0.0.1:8500"
    rootKey: "traefik"
    token: "s.a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    tls:
      ca: "/etc/traefik/certs/consul-ca.pem"
      cert: "/etc/traefik/certs/traefik-consul-client.pem"
      key: "/etc/traefik/certs/traefik-consul-client-key.pem"
      insecureSkipVerify: false

log:
  level: "INFO"
```

Эквивалент запуска через аргументы командной строки:

```bash
traefik \
  --entrypoints.web.address=:80 \
  --entrypoints.websecure.address=:443 \
  --providers.providersthrottleduration=2s \
  --providers.consul.endpoints=127.0.0.1:8500 \
  --providers.consul.rootkey=traefik \
  --providers.consul.token=s.a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
  --providers.consul.tls.ca=/etc/traefik/certs/consul-ca.pem \
  --providers.consul.tls.cert=/etc/traefik/certs/traefik-consul-client.pem \
  --providers.consul.tls.key=/etc/traefik/certs/traefik-consul-client-key.pem
```

#### 2. Заполнение дерева ключей через `consul kv put`

Настройка HTTP-маршрута с перенаправлением на HTTPS, ограничением частоты запросов (Rate Limiting) и проверкой здоровья серверов:

```bash
export CONSUL_HTTP_ADDR="https://127.0.0.1:8500"
export CONSUL_HTTP_SSL_VERIFY=true
export CONSUL_CACERT="/etc/traefik/certs/consul-ca.pem"
export CONSUL_HTTP_TOKEN="s.a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# 1. HTTP Роутер (HTTP -> HTTPS Redirect)
consul kv put traefik/http/routers/app-redirect/rule "Host(\`portal.internal\`)"
consul kv put traefik/http/routers/app-redirect/entrypoints/0 "web"
consul kv put traefik/http/routers/app-redirect/middlewares/0 "redirect-to-https"
consul kv put traefik/http/routers/app-redirect/service "noop@internal"

# 2. Middleware для редиректа
consul kv put traefik/http/middlewares/redirect-to-https/redirectscheme/scheme "https"
consul kv put traefik/http/middlewares/redirect-to-https/redirectscheme/permanent "true"

# 3. HTTPS Роутер
consul kv put traefik/http/routers/portal-secure/rule "Host(\`portal.internal\`) && PathPrefix(\`/api\`)"
consul kv put traefik/http/routers/portal-secure/entrypoints/0 "websecure"
consul kv put traefik/http/routers/portal-secure/service "portal-backend"
consul kv put traefik/http/routers/portal-secure/tls "true"
consul kv put traefik/http/routers/portal-secure/middlewares/0 "api-ratelimit"
consul kv put traefik/http/routers/portal-secure/middlewares/1 "strip-api"

# 4. Middleware: Ограничение запросов (Rate Limit) и удаление префикса
consul kv put traefik/http/middlewares/api-ratelimit/ratelimit/average "100"
consul kv put traefik/http/middlewares/api-ratelimit/ratelimit/burst "50"
consul kv put traefik/http/middlewares/api-ratelimit/ratelimit/period "1s"
consul kv put traefik/http/middlewares/strip-api/stripprefix/prefixes/0 "/api"

# 5. Балансировщик сервиса (LoadBalancer) с двумя бэкендами
consul kv put traefik/http/services/portal-backend/loadbalancer/servers/0/url "http://10.10.20.11:8080"
consul kv put traefik/http/services/portal-backend/loadbalancer/servers/1/url "http://10.10.20.12:8080"
consul kv put traefik/http/services/portal-backend/loadbalancer/passhostheader "true"

# 6. Настройка активного Health Check бэкендов
consul kv put traefik/http/services/portal-backend/loadbalancer/healthcheck/path "/healthz"
consul kv put traefik/http/services/portal-backend/loadbalancer/healthcheck/interval "5s"
consul kv put traefik/http/services/portal-backend/loadbalancer/healthcheck/timeout "2s"
```

#### 3. Верификация конфигурации

```bash
# Просмотр всего дерева конфигурации Traefik в Consul
consul kv get -recurse traefik/
# → traefik/http/middlewares/api-ratelimit/ratelimit/average:100
# → traefik/http/middlewares/api-ratelimit/ratelimit/burst:50
# → ...
# → traefik/http/services/portal-backend/loadbalancer/servers/0/url:http://10.10.20.11:8080
```

---

### Сценарий 2: etcd v3 Cluster — балансировка TCP-трафика и mTLS RBAC

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
entryPoints:
  db-entry:
    address: ":5432"

providers:
  providersThrottleDuration: "2s"
  etcd:
    endpoints:
      - "https://etcd-01.internal:2379"
      - "https://etcd-02.internal:2379"
      - "https://etcd-03.internal:2379"
    rootKey: "traefik"
    username: "traefik_reader"
    password: "EtcdSecureReaderPassword"
    tls:
      ca: "/etc/traefik/certs/etcd-ca.crt"
      cert: "/etc/traefik/certs/etcd-client.crt"
      key: "/etc/traefik/certs/etcd-client.key"
      insecureSkipVerify: false
```

#### 2. Заполнение дерева ключей через `etcdctl put`

Настройка TCP-роутера и TCP-сервиса (L4 балансировка без TLS-терминации):

```bash
export ETCDCTL_API=3
export ETCDCTL_CACERT="/etc/traefik/certs/etcd-ca.crt"
export ETCDCTL_CERT="/etc/traefik/certs/etcd-client.crt"
export ETCDCTL_KEY="/etc/traefik/certs/etcd-client.key"
export ETCDCTL_ENDPOINTS="https://etcd-01.internal:2379,https://etcd-02.internal:2379,https://etcd-03.internal:2379"
export ETCDCTL_USER="traefik_reader:EtcdSecureReaderPassword"

# Настройка TCP-маршрутизации (PostgreSQL L4 Proxy)
etcdctl put traefik/tcp/routers/postgres-router/entrypoints/0 "db-entry"
# В TCP правило HostSNI(`*`) принимает любые подключения
etcdctl put traefik/tcp/routers/postgres-router/rule "HostSNI(\`*\`)"
etcdctl put traefik/tcp/routers/postgres-router/service "postgres-service"

# Настройка бэкенд-серверов TCP
etcdctl put traefik/tcp/services/postgres-service/loadbalancer/servers/0/address "10.20.30.1:5432"
etcdctl put traefik/tcp/services/postgres-service/loadbalancer/servers/1/address "10.20.30.2:5432"
etcdctl put traefik/tcp/services/postgres-service/loadbalancer/terminationdelay "100ms"
```

---

### Сценарий 3: Redis c Sentinel — высокодоступная архитектура

При использовании Redis как KV-провайдера в продакшене одиночный инстанс Redis является единой точкой отказа (SPOF). Подключение через Redis Sentinel обеспечивает автоматическое обнаружение актуального мастера.

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  providersThrottleDuration: "3s"
  redis:
    endpoints:
      - "10.0.0.101:26379"
      - "10.0.0.102:26379"
      - "10.0.0.103:26379"
    rootKey: "traefik"
    db: 0
    sentinel:
      masterName: "mymaster"
      password: "SentinelAuthPassword"
    password: "RedisClusterAuthPassword"
```

#### 2. Запись ключей в Redis через `redis-cli`

> **Внимание:** В Redis ключи Traefik хранятся со стандартным разделителем `/` (слэш), а не через точки. Индексы списков задаются цифрами `0`, `1`.

```bash
export REDISCLI_AUTH="RedisClusterAuthPassword"

# Запись ключей роутера
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/routers/api-router/rule" "Host(\`api.internal\`)"
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/routers/api-router/entrypoints/0" "websecure"
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/routers/api-router/service" "api-service"
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/routers/api-router/tls" "true"

# Запись ключей сервиса
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/services/api-service/loadbalancer/servers/0/url" "http://10.0.5.21:8080"
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/services/api-service/loadbalancer/servers/1/url" "http://10.0.5.22:8080"
redis-cli -h 10.0.0.101 -p 6379 SET "traefik/http/services/api-service/loadbalancer/passhostheader" "true"
```

---

### Сценарий 4: Apache ZooKeeper в On-Premise инфраструктуре

#### 1. Статическая конфигурация Traefik (`/etc/traefik/traefik.yml`)

```yaml
entryPoints:
  web:
    address: ":80"

providers:
  providersThrottleDuration: "2s"
  zooKeeper:
    endpoints:
      - "zk-node1.corp.internal:2181"
      - "zk-node2.corp.internal:2181"
      - "zk-node3.corp.internal:2181"
    rootKey: "traefik"
    username: "traefik-app"
    password: "ZkSecurePassword"
```

#### 2. Создание znode структуры через `zkCli.sh`

В ZooKeeper каждый промежуточный узел пути должен физически существовать. При создании структуры необходимо создавать родительские znodes:

```bash
# Запуск консоли ZooKeeper
zkCli.sh -server zk-node1.corp.internal:2181

# В интерактивной консоли zkCli:
create /traefik ""
create /traefik/http ""
create /traefik/http/routers ""
create /traefik/http/routers/corp-app ""
create /traefik/http/routers/corp-app/rule "Host(`corp.internal`)"
create /traefik/http/routers/corp-app/entrypoints ""
create /traefik/http/routers/corp-app/entrypoints/0 "web"
create /traefik/http/routers/corp-app/service "corp-service"

create /traefik/http/services ""
create /traefik/http/services/corp-service ""
create /traefik/http/services/corp-service/loadbalancer ""
create /traefik/http/services/corp-service/loadbalancer/servers ""
create /traefik/http/services/corp-service/loadbalancer/servers/0 ""
create /traefik/http/services/corp-service/loadbalancer/servers/0/url "http://192.168.10.50:80"
```

---

### Сценарий 5: Автоматизация синхронизации Git -> KV (On-Premise GitOps без Cloud)

При ручной записи ключей велик риск оставить «осиротевшие» ключи (orphaned keys) от старых версий сервисов. Ниже представлен bash-скрипт для CI/CD конвейера (например, GitLab CI runner в On-Premise контуре), который выполняет полную синхронизацию (reconciliation) ключей в etcd:

```bash
#!/usr/bin/env bash
# sync-etcd-traefik.sh — синхронизация декларативного списка ключей с etcd
set -euo pipefail

PREFIX="traefik"
CONFIG_FILE="dynamic-keys.env"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Ошибка: файл ${CONFIG_FILE} не найден" >&2
  exit 1
fi

echo "==> 1. Получение текущего состояния ключей из etcd..."
CURRENT_KEYS=$(etcdctl get "${PREFIX}/" --prefix --keys-only)

echo "==> 2. Применение новых и обновленных ключей..."
APPLIED_KEYS=()
while IFS='=' read -r key value || [[ -n "${key}" ]]; do
  # Пропуск пустых строк и комментариев
  [[ -z "${key}" || "${key}" =~ ^[[:space:]]*# ]] && continue

  key=$(echo "${key}" | xargs)
  value=$(echo "${value}" | xargs)

  etcdctl put "${key}" "${value}" > /dev/null
  APPLIED_KEYS+=("${key}")
done < "${CONFIG_FILE}"

echo "==> 3. Удаление устаревших ключей (orphaned keys)..."
while IFS= read -r existing_key; do
  [[ -z "${existing_key}" ]] && continue

  # Проверяем, есть ли существующий ключ в списке примененных
  found=0
  for applied in "${APPLIED_KEYS[@]}"; do
    if [[ "${existing_key}" == "${applied}" ]]; then
      found=1
      break
    fi
  done

  if [[ ${found} -eq 0 ]]; then
    echo "Удаление устаревшего ключа: ${existing_key}"
    etcdctl del "${existing_key}" > /dev/null
  fi
done <<< "${CURRENT_KEYS}"

echo "==> Синхронизация завершена успешно. Обновлено ключей: ${#APPLIED_KEYS[@]}"
```

Формат файла `dynamic-keys.env`:

```ini
traefik/http/routers/web/rule = Host(`portal.internal`)
traefik/http/routers/web/entrypoints/0 = web
traefik/http/routers/web/service = web-svc
traefik/http/services/web-svc/loadbalancer/servers/0/url = http://10.0.1.5:8080
traefik/http/services/web-svc/loadbalancer/servers/1/url = http://10.0.1.6:8080
```

---

## Операции и команды

### Управление ключами Consul KV (`consul kv`)

| Операция | Команда | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Запись ключа** | `consul kv put traefik/http/routers/r1/rule "Host(\`app.loc\`)"` | `Success! Data written to: traefik/http/routers/r1/rule` |
| **Чтение ключа** | `consul kv get traefik/http/routers/r1/rule` | Выводит значение ключа в stdout |
| **Рекурсивный просмотр** | `consul kv get -recurse traefik/` | Список всех пар ключ-значение под префиксом |
| **Экспорт в JSON** | `consul kv export traefik/ > traefik-backup.json` | Бэкап конфигурации в файл |
| **Импорт из JSON** | `consul kv import @traefik-backup.json` | Восстановление дерева конфигурации |
| **Удаление поддерева** | `consul kv delete -recurse traefik/http/routers/r1/` | Удаление роутера и всех дочерних ключей |

### Управление ключами etcd (`etcdctl`)

| Операция | Команда | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Запись ключа** | `etcdctl put traefik/http/routers/r1/rule "Host(\`app.loc\`)"` | `OK` |
| **Чтение ключа** | `etcdctl get traefik/http/routers/r1/rule` | Выводит ключ и значение |
| **Просмотр префикса** | `etcdctl get traefik/ --prefix` | Полный листинг дерева ключей |
| **Список только ключей** | `etcdctl get traefik/ --prefix --keys-only` | Имена всех активных ключей без значений |
| **Мониторинг изменений** | `etcdctl watch traefik/ --prefix` | Стриминг событий PUT/DELETE в реальном времени |
| **Удаление поддерева** | `etcdctl del traefik/http/routers/r1/ --prefix` | `1` (число удаленных ключей) |

### Управление ключами Redis (`redis-cli`)

| Операция | Команда | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Запись значения** | `redis-cli SET "traefik/http/routers/r1/rule" "Host(\`app.loc\`)"` | `OK` |
| **Чтение значения** | `redis-cli GET "traefik/http/routers/r1/rule"` | `"Host(\`app.loc\`)"` |
| **Поиск ключей** | `redis-cli --scan --pattern "traefik/*"` | Безопасный итеративный список ключей без блокировки |
| **Удаление ключа** | `redis-cli DEL "traefik/http/routers/r1/rule"` | `(integer) 1` |
| **Пакетная запись** | `cat keys.txt \| redis-cli --pipe` | Загрузка конфигурации через протокол Mass Insertion |

---

## Устранение неисправностей

| Симптом / Ошибка | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Роутеры не появляются в Traefik Dashboard / API** | 1. Неверный разделитель (использованы точки вместо слэшей).<br>2. Ошибка в префиксе `rootKey`.<br>3. Не задан обязательный параметр `service` или `rule`. | `curl -s http://127.0.0.1:8080/api/rawdata \| jq '.http.routers'` | Проверить формат ключей: `traefik/http/routers/<name>/rule`. Убедиться, что имя сервиса совпадает с объявленным в `traefik/http/services/<name>`. |
| **404 Not Found при обращении к настроенному домену** | 1. Опечатка в правиле Matcher (в v3 строго `Header()`, а не `Headers()`).<br>2. Обратные кавычки правила были съедены шеллом при вызове CLI.<br>3. Роутер не привязан к целевому `entryPoint`. | `curl -vk https://app.example.internal/` | Проверить точное значение в KV: значение ключа `rule` должно содержать обратные кавычки: `Host(\`app.example.internal\`)`. При записи экранируйте их: `"Host(\\\`app\\\`)"`. |
| **Flapping конфигурации / 100% CPU у процесса Traefik** | Массовая поштучная запись сотен ключей в цикле без дебаунсинга; Traefik непрерывно перестраивает граф маршрутизации. | `top -p $(pgrep traefik)`<br>Логи: `Configuration received from provider consul` идут сплошным потоком. | 1. Задать параметр `providers.providersThrottleDuration: "2s"` (или `5s`).<br>2. Выполнять атомарную запись транзакциями (Consul Transaction API, etcd txn). |
| **Провайдер падает при старте: connection refused** | Сетевая недоступность KV-сервера, неверный порт или отклонение TLS handshake. | `journalctl -u traefik -e \| grep -E "(consul\|etcd\|redis\|zookeeper)"` | 1. Проверить доступность порта: `nc -zv 127.0.0.1 8500`.<br>2. Проверить валидность сертификатов и CA-бандла (`openssl verify`). |
| **Permission denied / ACL error в логах** | Токен Consul или учетная запись etcd/Redis не имеют прав на чтение/подписку префикса `rootKey`. | В логах: `etcd3: permission denied` или `Consul KV: 403 Forbidden` | 1. Для Consul: выдать политику `key_prefix "traefik/" { policy = "read" }`.<br>2. Для etcd: настроить `etcdctl role grant-permission traefik_role read --prefix=true "traefik/"`. |
| **502 Bad Gateway при живых бэкендах** | Серверы бэкенда недоступны по URL из ключа `servers/0/url` или не проходят настроенный `healthCheck`. | `curl -s http://127.0.0.1:8080/api/http/services \| jq .` | Проверить доступность адреса бэкенда с хоста Traefik (`curl -I http://10.0.1.10:8080/healthz`). Проверить таймауты `healthCheck`. |
| **Ошибка: invalid router name (contains `@`)** | В имени роутера использован зарезервированный символ `@` (например, `app@prod`). | В логах: `router name ... contains unauthorized character '@'` | Заменить символ `@` на дефис или подчеркивание (`app-prod`). |

---

## Рекомендации и лучшие практики

### 1. Надежность и производительность (SRE)
- **Обязательный дебаунсинг:** Всегда настраивайте директиву `providers.providersThrottleDuration: "2s"` (или `3s-5s` для крупных инсталляций). При автоматическом развертывании десятков маршрутов дебаунсинг предотвращает лавинообразные реконфигурации графа и деградацию обработки пользовательских запросов.
- **Пакетная запись (Atomic Batching):** Не производите запись ключей «по одному» в цикле прямого доступа. Используйте транзакционные интерфейсы (Consul Txn API, транзакции etcd, Redis MSET / pipelines), чтобы Traefik считывал завершенное состояние. Если роутер запишется раньше своего сервиса, клиенты могут кратковременно получать `502 Bad Gateway`.
- **Локальный кэш и отказоустойчивость:** Держите резервную копию динамической конфигурации на диске в формате YAML. При полной потере или падении кластера etcd/Consul включение аварийного файлового провайдера (`providers.file`) позволяет восстановить сервис за секунды.

### 2. Безопасность и разграничение доступа (DevOps / Sysadmin)
- **Принцип наименьших привилегий для Traefik:** Процессу Traefik требуется **строго доступ на чтение** префикса `rootKey/`. Права на запись должны иметь только доверенные CI/CD раннеры, Ansible-плейбуки или внутренние контроллеры инфраструктуры.
  - *Пример политики Consul ACL для Traefik:*
    ```hcl
    key_prefix "traefik/" {
      policy = "read"
    }
    node_prefix "" {
      policy = "read"
    }
    ```
- **Шифрование трафика (mTLS):** Никогда не передавайте конфигурацию по незашифрованным каналам. Всегда настраивайте взаимную аутентификацию по сертификатам (mTLS) между Traefik и хранилищами (etcd, Consul, ZooKeeper).
- **Секреты и пароли:** Не храните приватные ключи сертификатов и пароли middleware basicAuth в открытом виде в KV-хранилищах, если к ним имеют доступ непривилегированные пользователи. Используйте специализированные хранилища секретов (HashiCorp Vault) или монтируйте сертификаты локальными файлами, ссылаясь на них из KV (`@file`).

### 3. Эксплуатация и мониторинг
- **Мониторинг перезагрузок конфигурации:** Отслеживайте метрики Traefik в Prometheus:
  - `traefik_config_reloads_total` — общее число попыток перезагрузки конфигурации.
  - `traefik_config_reloads_failure_total` — счетчик ошибок валидации или синтаксиса в KV.
  - `traefik_config_reload_last_success_timestamp` — метка времени последнего успешного применения.
- **Очистка устаревших ключей (Housekeeping):** Регулярно запускайте аудит ключей хранилища. Забытые ключи удаленных сервисов продолжают оставаться в оперативной памяти Traefik, увеличивая накладные расходы на маршрутизацию и нагружая внутренний роутер.

---

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — фундаментальные концепции архитектуры, статической и динамической конфигурации.
- [Расширенные провайдеры Traefik](./traefik-providers-advanced.md) — детальный разбор провайдеров File, HashiCorp Nomad, Consul Catalog и HTTP Polling.
- [Роутеры и правила маршрутизации](./traefik-routers-and-rules.md) — синтаксис правил Matcher v3 (`Host`, `PathPrefix`, логические операторы), приоритеты.
- [Middleware безопасности](./traefik-middlewares-security.md) — настройка `ipAllowList`, `rateLimit`, заголовков безопасности и аутентификации.
- [Проверки здоровья (Health Checks)](./traefik-health-checks.md) — активный и пассивный мониторинг бэкендов в сервисах Traefik.
- [Высокая доступность Traefik (HA)](./traefik-high-availability.md) — кластерные топологии, Keepalived и отказоустойчивые архитектуры.
- [Наблюдаемость и метрики Traefik](./traefik-observability.md) — экспорт метрик Prometheus, трассировка OpenTelemetry и аудит логов.
- [Миграция с Traefik v2 на v3](./traefik-migration-v2-to-v3.md) — отличия синтаксиса, удаленные флаги и миграция правил.
- [KV-хранилище HashiCorp Consul](../../Consul/consul_kv_store.md) — архитектура Consul KV, транзакции, Sessions и Blocking Queries.
- [Система ACL в HashiCorp Consul](../../Consul/consul_acl.md) — создание токенов и политик с ограничением прав на `key_prefix`.
- [Справочник команд etcdctl](../../etcd/etcdctl_cheatsheet.md) — полный список команд для управления ключами, ролями и резервным копированием etcd.