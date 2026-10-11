**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

# Consul Service Mesh (Connect)

## Определения

**Consul Service Mesh (ранее Connect)** — это инфраструктурный слой, обеспечивающий безопасное взаимодействие между сервисами с использованием Mutual TLS (mTLS), автоматическую авторизацию (Intentions) и наблюдаемость трафика.

**Data Plane (Слой данных)** — сеть прокси-серверов (обычно **Envoy**), которые работают рядом с каждым экземпляром сервиса (Sidecar). Они перехватывают весь входящий и исходящий трафик, применяют политики безопасности и динамическую маршрутизацию. Взаимодействие с плоскостью управления происходит по протоколу **xDS**.

**Control Plane (Слой управления)** — кластер серверов Consul, который управляет конфигурацией прокси, выпускает сертификаты TLS и хранит реестр сервисов. Идентификация сервисов базируется на стандарте **SPIFFE** (Secure Production Identity Framework for Everyone), где каждому workload-у присваивается уникальный SVID (SPIFFE Verifiable Identity Document).

**Mesh Gateway** — специализированный компонент для обеспечения связности между сервисами в разных дата-центрах или кластерах (Multi-cluster), работающий как входная/выходная точка для межкластерного трафика.

**[Consul API Gateway](./consul-api-gateway.md)** — современная замена Ingress Gateway для управления внешним (North-South) трафиком, реализующая Kubernetes Gateway API.

## Предварительные требования

Перед включением Service Mesh убедитесь, что кластер соответствует следующим требованиям:

- **Версия Consul:** 1.19.x или новее для всех функций, описанных в этом документе. Transparent Proxy доступен с Consul 1.10.0+.
- **Сеть:** Открыты порты 8300 (RPC), 8301 (Serf LAN), 8302 (Serf WAN), 8500 (HTTP), 8502 (gRPC), 8600 (DNS).
- **NTP:** Синхронизация времени на всех узлах (рассинхрон более 5 секунд приводит к невалидности mTLS-сертификатов).
- **Envoy:** Для VM-сред Envoy должен быть установлен на каждом клиентском узле. Поддерживаемые версии зависят от версии Consul.
- **ACL:** При включенных ACL создайте соответствующие политики для управления intentions и сертификатами CA.

## Основные концепции

### Прокси-сайдкар (Envoy)

Вместо того чтобы встраивать логику сетевого взаимодействия в код приложения, Consul использует паттерн Sidecar.

- **Envoy Proxy:** Промышленный стандарт L7-прокси. Он инжектируется в Pod (Kubernetes) или запускается рядом с процессом (VM).
- **Локальное взаимодействие:** Приложение общается с прокси через `localhost`. Прокси берет на себя поиск адреса (Service Discovery), шифрование и передачу данных.

### Прозрачное проксирование (Transparent Proxy)

В современных версиях Consul рекомендуется использование прозрачного проксирования:

- **Механизм:** Трафик перехватывается на уровне ОС (через `iptables` или `eBPF`) и автоматически направляется в Envoy.
- **Преимущество:** Приложениям не нужно знать о существовании прокси или использовать специальные порты на `localhost`. Сервисы обращаются друг к другу по стандартным DNS-именам или IP Kubernetes.
- **Доступность:** Transparent Proxy доступен для Kubernetes и VM-сред (Consul 1.10.0+ для K8s, 1.11.1+ для VM).

### Управление трафиком L7 (Router, Splitter, Resolver)

Consul реализует механизмы управления трафиком на прикладном уровне (L7) через **цепочку обнаружения (Discovery Chain)**. Это строго последовательный процесс обработки запроса от клиента (downstream) к целевому сервису (upstream).

#### 1. Жизненный цикл и порядок обработки (Evaluation Order)

Когда один сервис пытается связаться с другим, Consul оценивает конфигурационные записи в следующем порядке:

1.  **Service Router (`service-router`)** — *Точка входа*.
    - **Роль**: Перехватывает трафик на основе HTTP-путей, заголовков, методов или кук.
    - **Действие**: Направляет запрос в конкретный сервис или его подмножество (subset). Если соответствие не найдено, запрос идет по пути по умолчанию.
2.  **Service Splitter (`service-splitter`)** — *Распределение нагрузки*.
    - **Роль**: Разделяет трафик между разными сервисами или подмножествами на основе процентных весов.
    - **Сценарии**: Canary-релизы, Blue/Green деплой.
3.  **Service Resolver (`service-resolver`)** — *Финальное разрешение*.
    - **Роль**: Определяет, какие именно инстансы (IP:Port) соответствуют понятию «подмножество» (на основе тегов или метаданных).
    - **Действие**: Управляет обнаружением, политиками Failover (переключение на другие ДЦ/пиры) и стратегиями балансировки.

**Важное условие:** Для работы L7-механизмов в `service-defaults` целевого сервиса должен быть явно указан протокол `Protocol = "http"` или `"grpc"`. В противном случае трафик обрабатывается на уровне L4 (TCP), и L7-правила игнорируются.

#### 2. Детальный разбор компонентов

##### Service Router

Позволяет реализовать сложную логику маршрутизации без изменения кода приложения.

- **Match**: `PathPrefix`, `PathExact`, `Header`, `QueryParam`, `Method`.
- **Action**: `Service` (куда отправить), `PrefixRewrite` (изменение пути).

**Пример: Маршрутизация по заголовкам (Header-based Routing)**
```hcl
Kind = "service-router"
Name = "web-api"
Routes = [
  {
    Match {
      HTTP {
        Header = [
          {
            Name  = "x-version"
            Exact = "canary"
          }
        ]
      }
    }
    Destination {
      Service       = "web-api"
      ServiceSubset = "v2"
    }
  },
  {
    # Дефолтный маршрут
    Destination {
      Service       = "web-api"
      ServiceSubset = "v1"
    }
  }
]
```

##### Service Splitter

Управляет "весами" трафика. Сумма всех `Weight` в списке `Splits` должна быть равна 100.

```hcl
Kind = "service-splitter"
Name = "api-gateway"
Splits = [
  {
    Weight        = 90
    ServiceSubset = "v1"
  },
  {
    Weight        = 10
    ServiceSubset = "v2"
  }
]
```

##### Service Resolver

Связывает логические имена подмножеств с физическими атрибутами в каталоге.

- **Subsets**: Определение групп инстансов (например, `version == "2.0"`).
- **Failover**: Настройка цепочки переключения (например, если в локальном ДЦ нет здоровых инстансов, отправить запрос в другой ДЦ).

**Пример: Locality-Aware Balancing и Failover**

Для работы балансировки по близости агенты должны иметь настроенный параметр `locality` (region/zone).

```hcl
Kind = "service-resolver"
Name = "order-db"

# Приоритизация локальных инстансов (Zone-aware)
PrioritizeByLocality = {
  Mode = "failover"
}

# Цепочка отказоустойчивости
Failover = {
  "*" = {
    Targets = [
      {
        # 1. Попробовать найти в другом ДЦ
        Datacenter = "dc2"
      },
      {
        # 2. Попробовать резервный сервис
        Service    = "order-db-backup"
        Datacenter = "dc-backup"
      }
    ]
  }
}

Subsets = {
  "v1" = { Filter = "Service.Tags contains v1" }
}
```

#### 3. Практический сценарий: Canary Release с Failover

1.  **Downstream** запрашивает `web.service.consul/api/v2`.
2.  **Router** видит префикс `/api/v2` и перенаправляет запрос на виртуальный сервис `api-canary`.
3.  **Splitter** для `api-canary` делит трафик: 90% на `api-stable`, 10% на `api-beta`.
4.  **Resolver** для `api-beta` ищет инстансы с тегом `beta`. Если в текущем ДЦ их нет, согласно политике **Failover**, он перенаправляет запрос на инстансы с этим же тегом в соседний регион.

#### 4. Устойчивость и паттерны прерывания цепи (Circuit Breaking)

Consul позволяет повысить отказоустойчивость системы, ограничивая нагрузку на сервисы и автоматически исключая "плохие" инстансы.

##### Лимиты соединений и очередей (Connection Pools)

Настраиваются в ресурсе **`service-defaults`** для ограничения ресурсов, выделяемых на взаимодействие с апстримом.

```hcl
Kind = "service-defaults"
Name = "billing-api"
Protocol = "http"

UpstreamConfig = {
  Defaults = {
    Limits = {
      MaxConnections     = 1024 # Макс. одновременных TCP-соединений
      MaxPendingRequests = 1024 # Макс. запросов в очереди ожидания соединения
      MaxConcurrentRequests = 1024 # Макс. параллельных HTTP-запросов
    }
  }
}
```

##### Пассивная проверка здоровья (Outlier Detection)

Механизм временного изгнания (ejection) инстансов из пула балансировки на основе ошибок уровня L7 (например, кодов 5xx), без ожидания провала стандартного Health Check.

```hcl
UpstreamConfig = {
  Defaults = {
    PassiveHealthCheck = {
      Interval           = "10s" # Частота сканирования инстансов
      MaxFailures        = 5     # Порог последовательных ошибок для изгнания
      EnforcingConsecutive5xx = 100 # % 5xx ошибок, вызывающих срабатывание
      MaxEjectionPercent = 20  # Макс. % инстансов, которые можно изгнать одновременно
      BaseEjectionTime   = "30s" # Базовое время нахождения "вне игры"
    }
  }
}
```

##### Повторные попытки (Retries)

Настраиваются в ресурсе **`service-router`** для конкретных путей.

```hcl
# В секции Routes -> Retry
Retry {
  Attempts = 3
  RetryOn  = ["5xx", "connect-failure", "refused-stream"]
}
```

#### 5. Диагностика трафика L7

- **Проверка Discovery Chain:**
  ```bash
  consul config read -kind service-router -name <service-name>
  ```
- **Envoy Config Dump:** В выводе `curl localhost:19000/config_dump` ищите секции `route_config` и `weighted_clusters`. Они показывают, как Consul-правила транслировались в нативную конфигурацию Envoy.
- **Статистика:** Проверьте `consul.http.request` в Prometheus для анализа распределения трафика между версиями.

### Безопасность и mTLS (Zero Trust)

Consul обеспечивает шифрование трафика "из коробки" по модели **Zero Trust**.

- **Mutual TLS:** Шифрование трафика между прокси и проверка подлинности обеих сторон соединения.
- **Автоматическая ротация:** Consul автоматически обновляет сертификаты до истечения их срока действия.
- **Намерения (Intentions):** Декларативные политики доступа. Работают по принципу "Default Deny": все взаимодействия запрещены, пока не создано разрешающее правило. Intentions являются частью **[системы ACL](./consul_acl.md)** и требуют наличия соответствующих токенов для управления.

### Межкластерная связность и Sameness Groups

- **Cluster Peering:** Современный механизм связи независимых кластеров без общей корневой CA.
- **Sameness Groups:** Логическое объединение идентичных сервисов в разных кластерах. Позволяет прозрачно распределять нагрузку и выполнять автоматический failover.

### Управление сертификатами (Certificate Authority)

Consul Service Mesh использует CA для генерации и ротации TLS-сертификатов, обеспечивающих mTLS. Поддерживаются два основных типа провайдеров:

#### 1. Встроенный CA (Built-in)

Является провайдером по умолчанию. Подходит для небольших кластеров и сред, где безопасность самих серверов Consul считается достаточной.

- **Особенности:** Ключи хранятся в Raft-логе в зашифрованном виде. Автоматическая ротация корня и листовых сертификатов.
- **Конфигурация (HCL):**
```hcl
connect {
  enabled = true
  ca_provider = "consul"
  ca_config {
    private_key_type = "ec"
    private_key_bits = 256
    leaf_cert_ttl    = "72h" # Время жизни сертификата сервиса
  }
}
```

#### 2. Внешний CA (Vault PKI)

Рекомендуется для Production и сред с высокими требованиями к безопасности (compliance).

- **Преимущества:** Ключи никогда не покидают Vault. Централизованный аудит всех выпусков. Поддержка очень короткоживущих сертификатов.
- **Требования к Vault:** Необходим токен с правами на `update` для эндпоинта `/tune` промежуточного PKI.
- **Конфигурация (HCL):**
```hcl
connect {
  enabled = true
  ca_provider = "vault"
  ca_config {
    address = "https://vault.service.consul:8200"
    token   = "s.XXXXX" # ACL токен Vault
    root_pki_path         = "connect-root/"
    intermediate_pki_path = "connect-intermediate/"
    leaf_cert_ttl         = "24h"
  }
}
```

#### 3. Ротация и обновление

- **Root Rotation:** При смене корневого сертификата Consul временно поддерживает оба корня (старый и новый), чтобы прокси могли плавно перейти на новые сертификаты без прерывания трафика.
- **Leaf Rotation:** Агенты автоматически обновляют сертификаты сайдкаров (Envoy) задолго до их истечения.

#### 4. Ротация Intermediate CA в Vault (Zero-Downtime)

Обновление промежуточного сертификата (Intermediate CA) в Vault требует согласованности действий для предотвращения сбоев mTLS. Consul поддерживает механизм **Cross-signing**, который позволяет временно доверять обеим цепочкам сертификатов.

**Процедура ротации:**

1.  **Подготовка нового CA в Vault:**
    - Сгенерируйте новый Intermediate CA в Vault (в новом или существующем пути/issuer).
    - Подпишите его корневым CA (Root CA).
    - Убедитесь, что у токена Consul есть права на `update` для эндпоинта `/tune` нового пути.
2.  **Запуск ротации через Consul CLI:**
    Не изменяйте HCL-конфиг напрямую. Используйте команду `set-config` для инициализации управляемой ротации:
    ```bash
    # Создайте временный JSON с новой конфигурацией
    # {
    #   "Provider": "vault",
    #   "Config": {
    #     "Address": "https://vault.service.consul:8200",
    #     "IntermediatePKIPath": "pki_int_new",
    #     "RootPKIPath": "pki_root",
    #     "Token": "..."
    #   }
    # }
    consul connect ca set-config -config-file=new-ca-config.json
    ```
3.  **Автоматические этапы ротации:**
    - **Cross-signing**: Consul запрашивает у нового CA сертификат, перекрестно подписанный старым CA.
    - **Распространение**: Прокси получают обновленный Trust Bundle, содержащий оба корня.
    - **Leaf Renewal**: Consul постепенно перевыпускает листовые сертификаты всех сервисов, подписывая их уже новым CA.
4.  **Мониторинг и завершение:**
    - Проверьте список активных корней:
      ```bash
      consul connect ca list-roots
      ```
      В процессе ротации вы увидите два корня (один для подписи, другой для верификации).
    - После перевыпуска всех сертификатов Consul автоматически удалит старый CA из доверенного бандла.

> **Опасно:** Флаг `-force-without-cross-signing` приведет к немедленному отказу всех mTLS соединений, так как прокси перестанут доверять старым сертификатам до их перевыпуска.

### Телеметрия и наблюдаемость (Sidecar Metrics)

Поскольку весь трафик проходит через прокси, Consul автоматически собирает метрики. Данные обычно экспортируются через порт прокси `19000` (в Kubernetes часто агрегируются агентом).

#### Критические метрики Envoy (RED Pattern)

| Тип | Метрика | Описание | PromQL Пример |
| :--- | :--- | :--- | :--- |
| **Rate** | `envoy_cluster_upstream_rq_total` | Общее кол-во запросов. | `sum(rate(envoy_http_downstream_rq_total[5m]))` |
| **Errors** | `envoy_cluster_upstream_rq_xx` | Ошибки 4xx/5xx. | `sum(rate(envoy_http_downstream_rq_xx{code="5xx"}[5m]))` |
| **Duration** | `envoy_cluster_upstream_rq_time` | Задержка (Latency). | `histogram_quantile(0.99, sum(rate(..._bucket[5m])) by (le))` |

- **Ошибки соединений:** `envoy_cluster_upstream_cx_connect_fail` — рост указывает на проблемы с сетью или Firewall между сайдкарами.
- **Статус бэкендов:** Сравнение `envoy_cluster_membership_healthy` с `envoy_cluster_membership_total` позволяет выявить нездоровые инстансы в Mesh.

**Настройка в Kubernetes:**
Добавьте аннотацию к поду для автоматического сбора метрик:
`consul.hashicorp.com/enable-metrics: "true"`

### Визуализация в Grafana

Рекомендуемая структура дашборда для Consul Service Mesh должна включать 4 логических уровня:

1.  **Global Mesh Health (Gauges)**:
    - `consul_up` (Статус агентов).
    - `consul_raft_peers` (Кол-во участников кворума).
    - `consul_autopilot_healthy` (Общий статус кластера).
2.  **Control Plane Stability (Time-series)**:
    - Задержка фиксации Raft (`consul_raft_commitTime`).
    - Задержка контакта лидера (`consul_raft_leader_lastContact`).
3.  **Inbound Traffic (RED Method)**:
    - Интенсивность входящих запросов (RPS).
    - Процент ошибок (Error Rate %).
    - Тайминги P95/P99.
4.  **Outbound & Upstream (Connect Performance)**:
    - Успешность запросов к зависимостям.
    - Заполненность пулов соединений (`envoy_cluster_upstream_cx_active`).

## Архитектура

### Взаимодействие компонентов

1.  **Consul Servers (Control Plane):** Хранят конфигурацию, политики и выпускают сертификаты.
2.  **Consul Clients:** Запускаются на каждом узле, обеспечивают связь прокси с серверами.
3.  **Envoy Proxies (Data Plane):** Обрабатывают фактический трафик между сервисами.

### Межкластерная связность (Multi-cluster)

Consul позволяет объединять независимые кластеры в единую сервисную сетку.

- **Mesh Gateways:** Проксируют трафик между кластерами через защищенные каналы.
- **Федерация:** Серверы в разных кластерах обмениваются информацией о доступных сервисах.
- **Failover:** При сбое сервиса в одном кластере, трафик может быть автоматически перенаправлен на аналогичный сервис в другом кластере.

### Гибридные среды (VM и Kubernetes)

Consul рассматривает виртуальные машины (VM) как "граждан первого класса".

- **Единая сетка:** Сервис в Kubernetes может прозрачно обращаться к базе данных на VM, используя те же механизмы mTLS и Intentions.
- **Коннекторы:** Агенты Consul на VM подключаются к Control Plane так же, как и Pod-ы в K8s.

## Практические сценарии

### Интеграция с Kubernetes

Развертывание в Kubernetes обычно выполняется через официальный Helm-чарт.

**Основные настройки Helm (values.yaml):**
```yaml
global:
  connectInject:
    enabled: true        # Включение автоматической инъекции прокси
  tls:
    enabled: true        # Включение TLS между компонентами
meshGateway:
  enabled: true          # Включение шлюзов для multi-cluster
connectInject:
  transparentProxy:
    defaultEnabled: true # Включение прозрачного проксирования по умолчанию
```

**Валидация установки:**
```bash
# Проверка инжекции прокси
kubectl get pods -n consul -l app=consul,component=connect-injector
# → consul-consul-connect-injector-xxx   1/1     Running

# Проверка сервисов с Connect
consul catalog services -connect
# → api-service, web-service, db-service
```

### Канареечный релиз (Canary Deployment)

Пример разделения трафика между стабильной версией (v1) и новой (v2) в соотношении 90/10.

```hcl
# service-splitter.hcl
Kind = "service-splitter"
Name = "web-service"
Splits = [
  {
    Weight        = 90
    ServiceSubset = "v1"
  },
  {
    Weight        = 10
    ServiceSubset = "v2"
  }
]
```
Применение: `consul config write service-splitter.hcl`.

**Валидация:**
```bash
# Проверка применения конфигурации
consul config read -kind service-splitter -name web-service
# → Splits: [{"Weight":90,"ServiceSubset":"v1"},{"Weight":10,"ServiceSubset":"v2"}]
```

### Настройка политик доступа (L7 Intentions)

Пример политики, разрешающей только GET-запросы к пути `/public/`.

```hcl
# l7-intention.hcl
Kind = "service-intentions"
Name = "api-service"
Sources = [
  {
    Name   = "web-service"
    Action = "allow"
    Permissions = [
      {
        HTTP {
          Methods = ["GET"]
          PathPrefix = "/public/"
        }
      }
    ]
  }
]
```

**Валидация:**
```bash
# Проверка intentions
consul intention match web-service api-service
# → Разрешенное взаимодействие

# Тестовый запрос
curl -X POST http://api-service:8080/public/data
# → 403 Forbidden (L7 политика блокирует POST)

curl http://api-service:8080/public/data
# → 200 OK (GET разрешен)
```

## Лучшие практики

- **Default Deny:** Всегда настраивайте `default_intention_policy = "deny"` в ACL. Разрешайте только необходимые взаимодействия.
- **Transparent Proxy:** Используйте прозрачный прокси в Kubernetes и VM для исключения обхода mesh.
- **mTLS everywhere:** Включайте mTLS для всех сервисов. Используйте permissive mode только при онбординге.
- **L7 Intentions:** Применяйте L7-политики для чувствительных путей (`/admin`, `/api/internal`), а не только L4.
- **Circuit Breaking:** Настраивайте лимиты соединений и outlier detection для всех внешних зависимостей.
- **Canary Releases:** Используйте Service Splitter для постепенного rollout'а, а не для долгого разделения трафика.
- **Leaf Cert TTL:** Устанавливайте `leaf_cert_ttl` не более 24 часов для минимизации риска при компрометации.
- **Мониторинг:** Экспортируйте метрики Envoy в Prometheus и настройте алерты на `envoy_cluster_upstream_cx_connect_fail` и `UH` response flags.
- **Валидация:** После каждого изменения конфигурации запускайте `consul config validate` и проверяйте Discovery Chain.
- **Версии:** Используйте Consul 1.19+ и Helm chart 0.48+ для поддержки CNI plugin и всех функций Transparent Proxy.

## Проверка и валидация

### Проверка работоспособности Mesh

```bash
# 1. Проверка статуса агентов
consul members
# → server  1.2.3.4:8301  alive   server  2.0.0  2
# → client  1.2.3.5:8301  alive   client  2.0.0  2

# 2. Проверка сертификатов CA
consul connect ca list-roots
# → 2 roots found (cross-signing during rotation)

# 3. Проверка intentions
consul intention match web-service api-service
# → Allowed

# 4. Проверка Connect-сервисов
consul catalog services -connect
# → api-service, web-service, db-service
```

### Проверка Envoy Sidecar

```bash
# Статус здоровья апстримов
curl localhost:19000/clusters | jq '.cluster_statuses[] | {name: .name, healthy: (.host_statuses | map(.health_status.flags) | any(. == "healthy"))}'
# → {"name":"api-service.default.dc1.internal.xxx.consul","healthy":true}

# Проверка mTLS сертификатов
curl localhost:19000/certs | jq '.certificates[] | {subject: .subject_alt_names, expiration: .validity.expiration_date}'
# → SPIFFE ID и срок действия корректны

# Проверка конфигурации маршрутов
curl localhost:19000/config_dump | jq '.configs[] | select(.type_url == "type.googleapis.com/envoy.config.route.v3.RouteConfiguration")'
# → Маршруты соответствуют Consul-правилам
```

### Проверка xDS-доставки

```bash
# Метрики xDS сервера
curl localhost:8500/v1/agent/metrics | jq -r 'to_entries[] | select(.key | startswith("consul.xds")) | "\(.key): \(.value | .Gauge.Value)"'
# → consul.xds.server.streams: 15
# → consul.xds.server.update_max_per_second: 0

# Валидация intentions через troubleshoot
consul troubleshoot proxy -upstream-ip <upstream-ip>
# → ✓ Certificates are valid
# → ✓ Envoy has 0 rejected configurations
# → ✓ Envoy has detected 0 connection failure(s)
```

## Устранение неполадок (Troubleshooting)

### Проблемы с аутентификацией (mTLS)

Симптом: `Connection reset by peer` или ошибки SSL.

- **Проверка сертификатов:** Убедитесь, что все узлы кластера имеют актуальное время (NTP). Рассинхрон более чем на несколько секунд может привести к невалидности сертификатов.
- **Cluster Peering:** При связи кластеров проверьте, что Mesh Gateways доступны по сети и TLS-хендшейк проходит успешно.

### Отладка политик (Intentions)

Симптом: `403 Forbidden` при обращении к сервису.

- **Анализ соответствия:** Используйте CLI для проверки, разрешено ли взаимодействие:
  ```bash
  consul intention check <source-service> <destination-service>
  ```
- **L7 логи:** Если включены L7-интенции, проверяйте логи Envoy (sidecar) на наличие записей `rbac_access_denied`.

### Диагностика Envoy Sidecar

Каждый прокси имеет административный интерфейс (по умолчанию доступен только внутри Pod на порту `19000`).

- **Дамп конфигурации:** `curl localhost:19000/config_dump` — показывает все правила, полученные от Consul.
- **Список апстримов:** `curl localhost:19000/clusters` — показывает статус здоровья всех бэкендов, о которых знает прокси.

### Диагностика CA и сертификатов

- **Просмотр конфигурации CA:**
  ```bash
  consul connect ca get-config
  ```
- **Проверка сертификатов в Envoy:**
  Используйте `curl localhost:19000/certs` для просмотра текущих SVID и сроков их действия. Убедитесь, что поле `serial_number` и `subject` соответствуют ожидаемому сервису (SPIFFE ID).
- **Логи ротации:** Серверы Consul логируют процесс обновления корневого сертификата. Ищите записи `Connect CA rotation started`.

### Каталог типичных ошибок Envoy (Response Flags)

При анализе логов доступа Envoy (Access Logs) поле `response_flags` содержит двухсимвольные коды, объясняющие причину разрыва соединения или ошибки запроса.

| Флаг | Значение | Причины в контексте Consul | Что проверить |
| :--- | :--- | :--- | :--- |
| **UF** | **Upstream Connection Failure** | Envoy не смог установить соединение с целевым сервисом. | Проверьте **Intentions** (запрещено ACL). Убедитесь, что целевой под/процесс запущен. |
| **UC** | **Upstream Connection Termination** | Соединение было установлено, но разорвано целевым сервисом. | Проверьте логи целевого приложения на наличие крэшей или таймаутов. |
| **NR** | **No Route Configured** | Для запроса не найдено подходящего маршрута. | Проверьте регистрацию сервиса в каталоге. Убедитесь в корректности **Service Router** или **Splitter**. |
| **UH** | **No Healthy Upstream** | Все инстансы целевого сервиса не прошли проверки здоровья. | Проверьте статус Health Checks целевого сервиса в Consul UI или через CLI. |
| **LH** | **Local Healthcheck Failed** | Локальный сервис (рядом с которым стоит Envoy) нездоров. | Проверьте работоспособность приложения, для которого этот Envoy является сайдкаром. |
| **DC** | **Downstream Connection Termination** | Клиент (downstream) разорвал соединение до завершения обработки. | Проверьте таймауты на стороне клиента. Часто бывает при долгой обработке на бэкенде. |
| **UR** | **Upstream Remote Reset** | Целевой сервис сбросил соединение (TCP RST). | Проверьте несовпадение протоколов (например, HTTP/2 на порт с HTTP/1.1). |

#### Алгоритм отладки Mesh-взаимодействия

1.  **Проверка прав (Intentions)**:
    Если запрос блокируется, проверьте, разрешено ли взаимодействие:
    ```bash
    consul intention check <source-service> <destination-service>
    ```
2.  **Использование `troubleshoot` (Consul 1.15+)**:
    Интегрированная команда для проверки связности между прокси:
    - **Kubernetes**: `consul-k8s troubleshoot proxy -upstream-envoy-id <envoy-id>`
    - **VM**: `consul troubleshoot proxy -upstream-ip <upstream-ip>`
    - **Общий upstreams**: `consul troubleshoot upstreams` — показывает все апстримы для текущего прокси.
3.  **Инспекция состояния Envoy**:
    Используйте административный интерфейс прокси (порт 19000):
    - `curl localhost:19000/clusters` — статус здоровья всех апстримов.
    - `curl localhost:19000/certs` — проверка валидности mTLS сертификатов.
    - `curl localhost:19000/config_dump` — текущая конфигурация маршрутов.

### Отладка доставки конфигурации (xDS)

Проблемы с доставкой конфигурации от серверов Consul к прокси Envoy (Control Plane → Data Plane) могут приводить к задержкам обновлений или отсутствию маршрутов.

#### 1. Анализ через `consul debug`

Команда собирает полный архив диагностических данных (логи, метрики, профили) за указанный период.

```bash
consul debug -duration=2m -interval=30s
```

**В архиве ищите:**
- **Logs**: Файлы с уровнем `TRACE`, содержащие события `agent.envoy.xds`. Здесь видны моменты запроса снимков (snapshots) прокси-сервером и ошибки генерации конфигурации.
- **Metrics**: Метрики `consul.xds.server.*`, показывающие количество активных стримов и частоту обновлений.

#### 2. Инспекция xDS-стримов через API

Consul предоставляет внутренний эндпоинт для просмотра состояния активных gRPC-соединений с прокси.

```bash
curl localhost:8500/v1/agent/xds | jq
```

**На что обратить внимание:**
- **Resource Versions**: Версии LDS, RDS, CDS, EDS. Если версия на сервере не меняется при изменении настроек — проблема в Control Plane.
- **NACKs**: Если прокси отклонил конфигурацию (Negative Acknowledgement), вы увидите причину ошибки и версию, на которой "застрял" прокси.
- **Connected Since**: Длительность соединения. Частые переподключения могут указывать на нестабильность сети или агрессивные таймауты Load Balancer перед Consul.

#### 3. Критические xDS метрики

- `consul.xds.server.update_max_per_second` — указывает, достигнут ли лимит обновлений (защита от "шторма" конфигураций).
- `consul.xds.server.streams` — общее количество активных соединений с прокси.

## Граничные случаи

- **Transparent Proxy и не-mTLS трафик:** В permissive mTLS режиме L7-интенции не работают для незашифрованного трафика. При необходимости убедитесь, что `MeshDestinationsOnly` настроен корректно.
- **Sameness Groups и ACL:** При использовании Sameness Groups убедитесь, что ACL-токены имеют права на чтение сервисов в peered кластерах. Иначе failover будет блокирован.
- **Mesh Gateway и Catalog v2:** При использовании Mesh Gateways с Catalog v2 проверьте, что exported services настроены корректно, и discovery chains не ссылаются на несуществующие сервисы.
- **Vault PKI и сетевые разрывы:** При использовании внешнего CA (Vault) убедитесь, что серверы Consul могут достичь Vault даже при временных сетевых проблемах. Рекомендуется локальный кэш сертификатов.
- **Consul Dataplane и Vault:** В некоторых конфигурациях Vault может требовать классических клиентских агентов вместо Consul Dataplane. Проверяйте совместимость при переходе на Dataplane.
- **eBPF и iptables:** Transparent Proxy использует iptables по умолчанию. eBPF-режим требует ядра Linux 5.8+ и соответствующей поддержки. При проблемах с перехватом трафика проверьте модуль ядра `ip_tables`.

## Дополнительная информация

### См. также

- **[Архитектура Consul](./consul_architecture.md)** — подробнее о серверах и агентах.
- **[Service Mesh: основные концепции](../Service_Mesh/service_mesh_concepts.md)** — сравнение с Istio и Linkerd.
- **[Каталог служб](./consul_service_catalog.md)** — основа для Service Discovery.
- **[Здоровье сервисов (Health Checks)](./consul_health_checks.md)** — как Envoy агрегирует проверки здоровья.
- **[Consul Telemetry](./consul_telemetry.md)** — метрики и дашборды.
- **[Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md)** — управление конфигурацией Service Mesh.
- **[Consul Rate Limiting и Quotas](./consul_rate_limiting.md)** — защита Service Mesh от перегрузки.
- **[Consul ESM](./consul_esm.md)** — мониторинг внешних сервисов (Enterprise).
