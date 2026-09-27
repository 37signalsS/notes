# Теневое развертывание (Shadow Deployment)

## Определения

- **Теневое развертывание (Shadow Deployment)**, также известное как **Зеркалирование трафика (Traffic Mirroring)** — стратегия прогрессивной поставки, при которой реальный пользовательский трафик дублируется и направляется на новую версию сервиса (**v2/Shadow**), не влияя на основной поток запросов к стабильной версии (**v1/Primary**).
- **Fire and Forget (Выстрелил и забыл)** — основной технический принцип зеркалирования: балансировщик копирует пакет/запрос и отправляет его в теневую среду, не дожидаясь ответа и не учитывая его результат при формировании ответа пользователю.
- **Blast Radius = 0** — ключевое преимущество стратегии; технические сбои в теневой версии физически не могут привести к деградации сервиса для реальных клиентов.
- **Comparison Engine (Движок сравнения)** — инструмент или компонент, сопоставляющий ответы от v1 и v2 для выявления логических расхождений.
- **Traffic Mirroring (Зеркалирование трафика)** — синоним shadow: побочный (side) поток копий запросов, параллельный основному.
- **Dark Launch (Тёмный запуск)** — выпуск нового кода в продакшен без изменения пользовательского интерфейса и без маршрутизации ответа клиенту; часто реализуется на уровне приложения через feature flags и является подвидом shadow.
- **Replay (Воспроизведение)** — повторная отправка предварительно захваченного трафика в теневую среду вне реального времени (офлайн-сценарий).
- **Асимметрия ответов (Response Asymmetry)** — v2 формирует и возвращает ответ внутреннему контуру, но он никогда не доходит до пользователя; пользователю отдаётся только ответ v1.
- **Shadow Database** — изолированная копия баз данных, к которой подключается теневая версия для предотвращения записи в продакшен.
- **eBPF Mirroring** — дублирование пакетов на уровне ядра Linux через eBPF-программы (Cilium), без sidecar-прокси и с минимальными накладными расходами.
- **L4 Mirroring** — дублирование трафика на транспортном уровне (TCP/UDP) через `tc mirred` или SPAN-порт коммутатора, независимо от протокола приложения.
- **Diffy** — OSS-инструмент от Twitter для сравнения ответов primary, secondary (обе v1) и candidate (v2) с фильтрацией шума.
- **Logical Replication / CDC** — механизм репликации данных (PostgreSQL `PUBLICATION`/`SUBSCRIPTION`, Change Data Capture), поддерживающий теневую БД в актуальном состоянии без полного дампа.
- **Mirror Percentage** — доля трафика, дублируемая в тень (например, 10%); позволяет контролировать нагрузку на shadow-инфраструктуру.

## Основные концепции

### Ключевые идеи

- **Изоляция исполнения** — теневая версия работает в полностью изолированном окружении, но на реальном, не синтетическом профиле нагрузки.
- **Валидация нефункциональных требований** — проверка производительности (Latency P99), потребления ресурсов (CPU/RAM Leakage) и стабильности под нагрузкой.
- **Функциональное сравнение (Diffing)** — логирование ответов обеих версий с последующим анализом расхождений в структурах данных (JSON/gRPC).
- **Прогрев кэшей** — использование Shadow для "прогрева" JIT-компиляторов, кэшей БД и пулов соединений перед реальным переключением трафика.
- **Тестирование в продакшене без риска (Testing in Production)** — shadow относится к методам TiP: реальная нагрузка, нулевой риск для пользователя.
- **Отсутствие влияния на бизнес-метрики** — поскольку ответ v2 не возвращается клиенту, конверсии, выручка и SLA по доступности пользовательского пути не затрагиваются.

### Архитектура зеркалирования

Выделяют несколько уровней реализации зеркалирования (применимы независимо от года выпуска; перечислены от L7 к L3 и к уровню приложения):

1.  **L7 Proxy (Envoy/Istio):** Зеркалирование на уровне HTTP/gRPC запросов. Самый гибкий, но ресурсоемкий метод.
2.  **eBPF / Network Level (Cilium):** Копирование пакетов на уровне ядра Linux. Минимальные накладные расходы, подходит для L4-протоколов.
3.  **Application Level (GoReplay):** Захват трафика с сетевого интерфейса и его воспроизведение.
4.  **L4 / Network Level (`tc mirred`, SPAN):** Дублирование пакетов на сетевом уровне ядра или коммутатора; не зависит от прикладного протокола.
5.  **Application Level (Feature Flags / Dark Launch):** Дублирование вызовов внутри кода приложения без сетевого зеркалирования.

### Реализация в традиционной инфраструктуре (Bare Metal / VM)

Стратегия над-технологична: зеркалирование применимо и вне Kubernetes. В on-prem и self-hosted средах shadow строится из следующих компонентов:

- **L7-балансировщик / reverse proxy** — Nginx (`mirror` module), Envoy (`request_mirror_policies`) или HAProxy (через Lua-скрипт) копируют HTTP/gRPC-запросы в теневой upstream. Полную схему зеркалирования на Nginx см. в **[сравнении стратегий](./comparison.md)**; механику весов, health check и маршрутизации — в **[балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.
- **Сетевой (L3/L4) уровень** — Linux Traffic Control (`tc mirred`) или SPAN-порт коммутатора дублируют пакеты на интерфейс захвата; подходит для любых протоколов, не только HTTP.
- **Захват и воспроизведение (capture & replay)** — GoReplay (`gor`), `tcpdump` + `tcpreplay` позволяют записать трафик и проиграть его в shadow асинхронно (офлайн).
- **Уровень приложения** — feature flags / dark launch дублируют вызовы внутри кода без изменения инфраструктуры (см. **[сценарии feature toggles](../../CI-CD/Testing/feature_toggles/scenarios.md)**).
- **Comparison Engine** — Diffy или самописный diff-сервис сопоставляет ответы v1/v2.
- **Теневой слой данных** — read-replica БД, логическая репликация (CDC) или mock-слой для изоляции побочных эффектов.

Отличие от оркестратора: в Kubernetes зеркалирование «бесплатно» дают Istio/Envoy/Cilium; в традиционной среде те же примитивы собираются вручную из proxy + инструментов захвата, зато не требуют кластера и control plane.

### Проблема Stateful-сервисов и побочных эффектов

Зеркалирование трафика на компоненты, изменяющие состояние (базы данных, кэши, внешние API), является **критическим риском**.

**Методы предотвращения побочных эффектов:**
1.  **Shadow Database:** Теневая версия подключается к копии БД, актуализированной на момент начала теста.
2.  **API Mocking / Virtualization:** Все исходящие вызовы к внешним системам (платежные шлюзы, SMS-провайдеры) перехватываются и заменяются заглушками.
3.  **Idempotency Keys:** Использование ключей идемпотентности для предотвращения дублирования операций, если теневая среда частично разделяет ресурсы с основной.
4.  **ReadOnly Mode:** Принудительное включение режима "только чтение" на уровне приложения или учетной записи БД для теневой версии.
5.  **Логическая репликация / CDC:** Теневая БД поддерживается в актуальном состоянии через logical replication (PostgreSQL `PUBLICATION`/`SUBSCRIPTION`) или Change Data Capture, что исключает ручное копирование дампа. Архитектурные паттерны CDC — в **[cdc_architectural_patterns.md](../../Databases/Concepts/cdc_architectural_patterns.md)**.
6.  **Dual-Write Suppression:** Если v2 делает запись, она перенаправляется в изолированное хранилище (отдельный schema/топик), а не в prod-источник.

### SRE-подход: наблюдаемость и сравнительный анализ (Comparison Engine)

Теневая версия бесполезна без оценки. SRE-практика сравнения описана в **[Мониторинге и оценке при Canary](./canary_monitoring_and_gating.md)** (методология относительного сравнения Ratio и дифференциального анализа применима и к shadow).

**Что сравнивать:**
- **Golden Signals** v1 vs v2: Latency (P50/P95/P99), Traffic (RPS), Errors (5xx, exception rate), Saturation (CPU, память, fd, потоки).
- **Ресурсная стоимость:** v2 потребляет отдельный пул; важно зафиксировать утечки (memory leak) и деградацию под нагрузкой.
- **Функциональный diff:** совпадение/несовпадение тел ответов (JSON-структуры, коды, бизнес-поля).

**Метод относительного сравнения (Ratio), а не абсолютные пороги.** Сравнивайте `error_rate(v2) / error_rate(v1)`; абсолютный «ошибок < 1%» некорректен при плавающей нагрузке. Пример PromQL с лейблом версии:

```promql
# Относительная ошибка shadow относительно stable
sum(rate(http_requests_total{version="v2", status=~"5.."}[5m]))
  /
sum(rate(http_requests_total{version="v1", status=~"5.."}[5m]))
```

```promql
# Отношение P99 латентности (должно быть близко к 1.0)
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{version="v2"}[5m])) by (le))
  /
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{version="v1"}[5m])) by (le))
```

### Сравнение: Shadow vs Canary

| Характеристика | Shadow Deployment | Canary Deployment |
| :--- | :--- | :--- |
| **Влияние на пользователя** | **Нулевое** (Blast Radius = 0) | Минимальное (Blast Radius = N%) |
| **Реальные ответы** | Игнорируются | Возвращаются пользователю |
| **Основная цель** | Нефункциональные тесты, Perf, Stability | Функциональные тесты, бизнес-метрики |
| **Стоимость** | Высокая (2x ресурсы) | Низкая (1x + delta) |
| **Сложность внедрения** | Высокая (изоляция Side Effects) | Средняя (L7 Routing) |

## Практические сценарии

### 1. Реализация через Gateway API (HTTPRoute)

Современный стандарт Kubernetes для управления теневым трафиком через фильтр `RequestMirror`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-shadow-route
spec:
  parentRefs:
  - name: public-gateway
  rules:
  - matches:
    - path: { type: PathPrefix, value: /api/v2 }
    filters:
    - type: RequestMirror
      requestMirror:
        backendRef:
          name: my-app-shadow
          port: 8080
    backendRefs:
    - name: my-app-stable
      port: 8080
      weight: 100
```

### 2. Реализация через Istio (VirtualService)

Istio выполняет зеркалирование асинхронно. Ответы от `mirror` версии отбрасываются.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: app-mirror
spec:
  hosts:
    - app.example.com
  http:
    - route:
        - destination:
            host: app-stable
          weight: 100
      mirror:
        host: app-shadow
      mirrorPercentage:
        value: 10.0 # Зеркалирование только 10% трафика для экономии ресурсов
```

### 3. eBPF-зеркалирование (Cilium)

Использование Cilium для зеркалирования трафика без внедрения sidecar-прокси. Подробнее о eBPF-возможностях — в **[Cilium Service Mesh](../../Kubernetes/Networking/Network/CNI/cilium.md)**.

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: shadow-policy
spec:
  endpointSelector:
    matchLabels:
      app: primary
  egress:
    - toServices:
        - serviceName: shadow-service
      # eBPF hook для копирования трафика
      mirror: 
        enabled: true
```

### 4. Использование GoReplay для анализа

Инструмент позволяет записывать трафик на Primary и воспроизводить его на Shadow с возможностью изменения весов или фильтрации.

```bash
# Захват трафика на порту 8000 и отправка на теневой сервер
gor --input-raw :8000 --output-http "http://shadow-server:8000"
```

**Расширенный запуск с фильтрацией, семплированием и модификацией заголовков:**

```bash
# Захват с фильтрацией URL, установкой маркерного заголовка и ограничением таймаута
gor --input-raw :8000 \
    --http-allow-url '/api/.*' \
    --http-set-header 'X-Shadow: true' \
    --output-http 'http://shadow-server:8000' \
    --output-http-timeout 5s

# Сохранение в файл для офлайн-воспроизведения
gor --input-raw :8000 --output-file 'requests.gor'

# Воспроизведение записанного файла на shadow (несколько раз, с ускорением)
gor --input-file 'requests.gor' --input-file-loop --rate 2 \
    --output-http 'http://shadow-server:8000'
```

> Для захвата сырого сокета GoReplay требует `CAP_NET_RAW` (запуск от root или `setcap cap_net_raw+ep gor`). Middleware (`--middleware`) позволяет модифицировать тело/заголовки перед отправкой в shadow (например, обезличить PII).

### 5. Зеркалирование через Nginx (mirror module) — Bare Metal / VM

Реверс-прокси Nginx дублирует каждый запрос в internal-location, ответ которой отбрасывается. Полный пример конфигурации и ограничения — в **[сравнении стратегий](./comparison.md)**; механику проксирования см. в **[балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.

```nginx
http {
    upstream stable_app {
        server 10.0.1.10:8080;
    }
    upstream shadow_app {
        server 10.0.2.20:8080;   # теневая нода, изолированная БД/кеш
    }

    server {
        listen 80;
        server_name app.example.com;

        location / {
            # Дублировать запрос в теневую среду
            mirror /shadow;
            proxy_pass http://stable_app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # Внутренняя локация: недоступна извне, ответ отбрасывается
        location = /shadow {
            internal;
            proxy_pass http://shadow_app$request_uri;
            proxy_set_header Host $host;
            # Обязательно: сигнал приложению v2 работать в read-only / mock-режиме
            proxy_set_header X-Shadow-Mode true;
            # При больших телах запроса можно отключить копию тела,
            # чтобы не удваивать буфер памяти:
            # mirror_request_body off;
        }
    }
}
```

**Валидация:**
```bash
nginx -t                 # → syntax is ok, test is successful
# Проверка, что теневой апстрим получает копии (в его access.log появляются те же URI):
tail -f /var/log/nginx/shadow_access.log
```
**Ограничения (Open Source Nginx):** `mirror` поддерживает только один целевой location и работает поверх HTTP/1.1 subrequest; тело запроса буферизуется; зеркалирование gRPC/HTTP2 требует Nginx Plus или Envoy.

### 6. Зеркалирование через Envoy (standalone, без Kubernetes)

Envoy может работать как самостоятельный L7-прокси на bare metal/VM. Зеркалирование задаётся через `request_mirror_policies` с долей трафика (runtime fraction).

```yaml
static_resources:
  listeners:
  - name: listener
    address: { socket_address: { address: 0.0.0.0, port_value: 8080 } }
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress
          route_config:
            name: routes
            virtual_hosts:
            - name: app
              domains: ["*"]
              routes:
              - match: { prefix: "/" }
                route:
                  cluster: stable
                  request_mirror_policies:
                  - cluster: shadow
                    runtime_fraction:
                      default_value: { numerator: 100, denominator: HUNDRED }
          http_filters:
          - name: envoy.filters.http.router
  clusters:
  - name: stable
    load_assignment:
      cluster_name: stable
      endpoints:
      - lb_endpoints:
        - endpoint: { address: { socket_address: { address: 10.0.1.10, port_value: 8080 } } }
  - name: shadow
    load_assignment:
      cluster_name: shadow
      endpoints:
      - lb_endpoints:
        - endpoint: { address: { socket_address: { address: 10.0.2.20, port_value: 8080 } } }
```

> Envoy — единственный из популярных OSS-прокси, поддерживающий зеркалирование gRPC/HTTP2 «из коробки». Детали маршрутизации в сервис-меш — в **[управлении трафиком в Service Mesh](../../Service_Mesh/traffic_management.md)**.

### 7. Сетевое зеркалирование через Linux `tc mirred` (L3/L4)

Для любых протоколов (не только HTTP) трафик дублируется на уровне ядра в виртуальный интерфейс `ifb`, который слушает захватчик (GoReplay/tcpdump).

```bash
# Загрузить модуль ifb и поднять виртуальный интерфейс
sudo modprobe ifb
sudo ip link set ifb0 up

# Включить ingress-дисциплину на внешнем интерфейсе
sudo tc qdisc add dev eth0 ingress

# Зеркалировать ВЕСЬ входящий трафик eth0 на ifb0
sudo tc filter add dev eth0 parent ffff: protocol ip u32 \
    match u32 0 0 action mirred egress mirror dev ifb0

# На ifb0 можно захватывать и кормить shadow
sudo tcpdump -i ifb0 -s 0 -w shadow.pcap port 8080
# либо сразу GoReplay со слушателя ifb0:
# gor --input-raw :8080 --output-http 'http://shadow-server:8080'
```

**Валидация:** `tc -s filter show dev eth0 parent ffff:` покажет счётчик `mirred`. Учтите, что `mirred mirror` дублирует только входящий поток; для полного L4-зеркала добавьте аналогичный фильтр на egress.

### 8. Офлайн-воспроизведение: tcpdump + tcpreplay

Захват реального трафика и его последующее проигрывание в теневую среду вне реального времени.

```bash
# Захват продакшен-трафика в файл
sudo tcpdump -i eth0 -s 0 -w /tmp/prod.pcap port 8080

# Проигрывание захвата в теневую сеть (eth1 ведёт к shadow)
sudo tcpreplay -i eth1 --topspeed /tmp/prod.pcap
```

> `tcpreplay` отправляет сырые пакеты; для корректной L7-обработки проще использовать GoReplay с `--input-file` (сценарий 4), который корректно формирует HTTP-запросы. `tcpdump`+`tcpreplay` оправданы для низкоуровневого replay или когда приложение слушает raw-сокет.

### 9. Теневая база данных через логическую репликацию (PostgreSQL)

Изоляция stateful-побочных эффектов: теневая БД синхронизируется с prod через logical replication, а приложение v2 работает под read-only ролью.

```sql
-- На primary: публикация всех таблиц
CREATE PUBLICATION shadow_pub FOR ALL TABLES;

-- На shadow: подписка на копию
CREATE SUBSCRIPTION shadow_sub
  CONNECTION 'host=primary dbname=app user=replicator'
  PUBLICATION shadow_pub;
```

```sql
-- Отдельная роль только для чтения для теневого приложения
CREATE ROLE shadow_ro LOGIN PASSWORD '***' IN ROLE pg_read_all_data;
```

Архитектурные паттерны CDC (log-based, trigger-based) — в **[cdc_architectural_patterns.md](../../Databases/Concepts/cdc_architectural_patterns.md)**.

### 10. Теневой запуск через Feature Flags (Dark Launch, уровень приложения)

Не требует прокси: код дублирует вызов в новую логику, возвращает пользователю старый результат. Подробнее — в **[сценариях feature toggles](../../CI-CD/Testing/feature_toggles/scenarios.md)**.

```python
def get_search_results(query: str):
    legacy_results = legacy_engine.search(query)

    # Теневой запуск через флаг
    if ff_client.is_enabled("shadow-search-v2"):
        try:
            # Вычисляем, но не используем в ответе
            shadow_results = v2_engine.search(query)
            # Логируем расхождения для анализа
            compare_and_log(legacy_results, shadow_results)
        except Exception as e:
            logging.error(f"Shadow search failed: {e}")

    return legacy_results
```

**Вариант Shadow Read для миграции БД** (чтение из старой и новых систем одновременно, возврат из старой):

```python
def get_user_profile(user_id: str) -> dict:
    old_result = old_db.users.find_one({"_id": user_id})
    if ff_client.is_enabled("shadow-read-new-db", {"user_id": user_id}):
        try:
            new_result = new_db.profiles.find_one({"user_id": user_id})
            if old_result != new_result:
                logger.info(f"Shadow read mismatch for {user_id}: "
                            f"old={old_result}, new={new_result}")
        except Exception as e:
            logger.warning(f"Shadow read failed: {e}")
    return old_result  # Всегда возвращаем из старой системы
```

### 11. Зеркалирование через очередь событий (Kafka)

Для асинхронных/event-driven сервисов shadow реализуется дублированием событий в отдельный топик, который консюмерит теневая версия.

```bash
# Дублирование топика через Kafka MirrorMaker / коннектор
# либо в коде продюсера:
producer.send("orders", event)        # основной
producer.send("orders-shadow", event) # теневой (read-only консьюмер)
```

Теневой консьюмер обрабатывает `orders-shadow`, не публикуя результаты в продакшен-топики. Это даёт полную изоляцию side effects и возможность replay с произвольной скоростью.

### 12. Comparison Engine: Diffy и самописный diff

**Diffy** (OSS от Twitter) шлет каждый запрос одновременно на primary, secondary (обе v1, для фильтрации шума) и candidate (v2), сравнивает ответы и отдаёт расхождения через UI/API.

```bash
java -jar diffy.jar \
  -candidate=http://shadow-app:8080 \
  -master.primary=http://v1-app:8080 \
  -master.secondary=http://v1-app:8080 \
  -service.protocol=http \
  -proxy.port=:8880
```

**Лёгкий fallback на Python** (сравнение логов/тел по хэшу, без отдельного прокси):

```python
import hashlib, json, logging

def compare_and_log(resp_v1: dict, resp_v2: dict, req_id: str):
    h1 = hashlib.sha256(json.dumps(resp_v1, sort_keys=True, default=str).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(resp_v2, sort_keys=True, default=str).encode()).hexdigest()
    if h1 != h2:
        # Игнорируем динамические поля (timestamp, requestId) до сравнения
        logging.warning(f"[shadow-diff] mismatch req={req_id} "
                        f"v1={resp_v1} v2={resp_v2}")
```

Поля, которые заведомо отличаются (время, случайные ID), следует исключать до сравнения, иначе возникнут ложные срабатывания (False Positive).

## Операции и команды

### Nginx / Angie — включение и валидация mirror

```bash
# Проверка конфигурации перед применением
nginx -t
# → syntax is ok, test is successful

# Применение конфигурации
nginx -s reload

# Проверка, что теневой апстрим получает копии
tail -f /var/log/nginx/shadow_access.log

# При больших payload отключить копирование тела для экономии памяти
# mirror_request_body off;
```

### Envoy — запуск с зеркалированием

```bash
# Запуск с конфигом, содержащим request_mirror_policies
envoy -c envoy-shadow.yaml --service-cluster shadow-cluster

# Проверка статистики зеркалирования
curl localhost:9901/stats | grep shadow
# → cluster.shadow.upstream_cx_total ...
```

### Istio — применение VirtualService

```bash
# Применить конфигурацию зеркалирования
kubectl apply -f virtualservice-mirror.yaml

# Проверить, что mirror-политика попала в прокси
istioctl proxy-config routes deploy/app-primary --name http.8080 -o json | jq '.virtualHosts[] | select(.name=="app.example.com:80") | .routes[] | select(.mirror != null)'
```

### Gateway API — применение HTTPRoute

```bash
kubectl apply -f httproute-shadow.yaml
kubectl get httproute api-shadow-route
# → NAME               PARENT REFS   HOSTNAMES   AGE
# → api-shadow-route   [public-gw]   [*]         2m
```

### Cilium — применение политики зеркалирования

```bash
cilium apply shadow-policy.yaml

# Проверка подключений и политик
cilium connectivity test --test-namespace default
```

### Linux `tc mirred` — настройка L4-зеркала

```bash
# Загрузить модуль ifb
sudo modprobe ifb

# Поднять виртуальный интерфейс
sudo ip link set ifb0 up

# Добавить ingress-дисциплину на внешний интерфейс
sudo tc qdisc add dev eth0 ingress

# Зеркалировать весь входящий трафик на ifb0
sudo tc filter add dev eth0 parent ffff: protocol ip u32 \
    match u32 0 0 action mirred egress mirror dev ifb0

# Проверить счётчики mirred
sudo tc -s filter show dev eth0 parent ffff:
# → filter parent ffff: protocol ip pref 49152 u32 chain 0
# → filter parent ffff: protocol ip pref 49152 u32 chain 0 fh 0x0:
# →     ht divisor 1fhash 1f (fifo) key 0 0 0 0
# →     ... mirred (mirror to dev ifb0) 1321/1321

# Для полного L4-зеркала добавить аналогичный фильтр на egress
sudo tc filter add dev eth0 parent 1: protocol ip u32 \
    match u32 0 0 action mirred egress mirror dev ifb0
```

### GoReplay — захват и воспроизведение

```bash
# Прямой mirror на shadow-сервер
gor --input-raw :8000 --output-http "http://shadow-server:8000"

# С фильтрацией URL, заголовком и таймаутом
gor --input-raw :8000 \
    --http-allow-url '/api/.*' \
    --http-set-header 'X-Shadow: true' \
    --output-http 'http://shadow-server:8000' \
    --output-http-timeout 5s

# Запись в файл для офлайн-воспроизведения
gor --input-raw :8000 --output-file 'requests.gor'

# Воспроизведение файла с ускорением x2
gor --input-file 'requests.gor' --input-file-loop --rate 2 \
    --output-http 'http://shadow-server:8000'

# Выдача CAP_NET_RAW бинарному файлу gor
sudo setcap cap_net_raw+ep $(which gor)
```

### tcpdump + tcpreplay — офлайн replay

```bash
# Захват продакшен-трафика
sudo tcpdump -i eth0 -s 0 -w /tmp/prod.pcap port 8080

# Воспроизведение в теневую сеть (eth1 → shadow)
sudo tcpreplay -i eth1 --topspeed /tmp/prod.pcap

# С контролем скорости (например, 2x от реальной)
sudo tcpreplay -i eth1 --multiplier 2 /tmp/prod.pcap
```

### PostgreSQL — логическая репликация для Shadow DB

```sql
-- На primary: создать публикацию
CREATE PUBLICATION shadow_pub FOR ALL TABLES;

-- На shadow: подписка
CREATE SUBSCRIPTION shadow_sub
  CONNECTION 'host=primary dbname=app user=replicator'
  PUBLICATION shadow_pub;

-- Роль только для чтения для теневого приложения
CREATE ROLE shadow_ro LOGIN PASSWORD '***' IN ROLE pg_read_all_data;
```

### Kafka — дублирование событий в теневой топик

```bash
# В коде продюсера (пример на Python)
producer.send("orders", event)        # основной поток
producer.send("orders-shadow", event) # теневой (read-only консьюмер)
```

### Diffy — запуск движка сравнения

```bash
java -jar diffy.jar \
  -candidate=http://shadow-app:8080 \
  -master.primary=http://v1-app:8080 \
  -master.secondary=http://v1-app:8080 \
  -service.protocol=http \
  -proxy.port=:8880
```

### Prometheus — относительные запросы для Shadow

```promql
# Относительная ошибка shadow относительно stable
sum(rate(http_requests_total{version="v2", status=~"5.."}[5m]))
  /
sum(rate(http_requests_total{version="v1", status=~"5.."}[5m]))

# Отношение P99 латентности (должно быть близко к 1.0)
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{version="v2"}[5m])) by (le))
  /
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{version="v1"}[5m])) by (le))
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Рост Latency на Primary** | Балансировщик ресурсов (CPU) перегружен процессом копирования трафика. | Снизить `mirrorPercentage` или перейти на eBPF-зеркалирование. |
| **Исчерпание соединений БД** | Теневая версия потребляет пулы соединений общей БД или Proxy. | Использовать Shadow DB или ограничить `max_connections` для Shadow. |
| **Дублирование транзакций** | Теневая версия выполнила запись в Production API. | Срочно проверить изоляцию; использовать Mock-сервисы. |
| **Расхождение в ответах (False Positive)** | Динамические данные (timestamp, random ID) в ответах вызывают ложный алерт Diff-движка. | Настроить фильтры игнорирования полей в Diffy или аналогах. |
| **OOMKilled в Shadow** | Теневая версия не справляется с объемом зеркалированного трафика. | Увеличить лимиты ресурсов или уменьшить процент зеркалирования. |
| **Nginx `mirror` не срабатывает** | В internal-location нет `internal`, либо `proxy_pass` указывает неверно; зеркало не видно в логах. | Проверить `nginx -t`; убедиться, что `location = /shadow` помечен `internal` и доступен из `upstream`; смотреть `shadow_access.log`. |
| **GoReplay: permission denied на сокете** | Нет прав `CAP_NET_RAW` для захвата сырого интерфейса. | Запуск от root либо `sudo setcap cap_net_raw+ep $(which gor)`. |
| **`tc mirred` не дублирует трафик** | `ifb0` не поднят, либо фильтр добавлен только на ingress (не хватает egress). | `ip link set ifb0 up`; добавить зеркало и на egress; проверить `tc -s filter show dev eth0 parent ffff:`. |
| **Утечка персональных данных (PII)** | Зеркалирование реальных запросов с PII в менее защищённую среду. | Анонимизация на прокси (`sub_filter`/Lua) или в GoReplay-middleware; маскирование полей до отправки. |
| **Ложные расхождения из-за времени** | Clock skew между v1 и v2 искажает поля времени/последовательности. | Синхронизация NTP на обеих нодах; исключить timestamp-поля из diff. |
| **Двойная нагрузка на внешний сервис** | Shadow вызывает тот же внешний API, что и prod. | Перехват через mock-слой или API Virtualization. |
| **Таймауты балансировщика** | Слишком медленный Shadow-бэкенд удерживает ресурсы балансировщика, даже если ответ игнорируется. | Увеличить `proxy_read_timeout` на shadow-ape; настроить `mirror` так, чтобы таймаут не влиял на primary. |
| **Внешние зависимости без мока** | Сервис вызывает внешний API, который невозможно замокать (банковский протокол, государственный шлюз). | Теневое развертывание этой функции невозможно; использовать отдельную нагрузочную среду с заглушкой. |
| **gRPC/HTTP2 не зеркалируется в OSS Nginx** | `mirror` работает поверх HTTP/1.1 subrequest; HTTP2 и gRPC не поддерживаются. | Перейти на Envoy или Nginx Plus для L7-зеркала gRPC. |
| **Буферизация тела запроса удваивает память** | При больших payload `mirror` копирует тело в буфер, что может привести к OOM прокси. | Отключить `mirror_request_body off`, если теневая версия не требует тела запроса. |
| **Недостаточный capacity (2x)** | Теневая среда не выдерживает пиковую нагрузку, зеркало отбрасывает пакеты. | Capacity planning: shadow должен иметь запас 30–50% выше пика primary. |
| **Sampling bias — редкие сценарии пропущены** | Зеркалирование 10% трафика пропускает низкочастотные ошибочные запросы. | Использовать 100% L4-зеркало (`tc mirred`) или полный capture+replay для ночных валидаций. |
| **Shadow без idempotency keys** | При частичном разделении ресурсов теневая запись создаёт дубли в prod. | Внедрить idempotency keys на всех мутирующих операциях; проверять дубли перед записью. |

## Лучшие практики

1.  **Изолируйте stateful-сервисы:** используйте Shadow DB, read-only роль, CDC или логическую репликацию вместо общей БД.
2.  **Анонимизируйте PII:** применяйте маскирование на прокси (`sub_filter`/Lua) или в middleware GoReplay перед отправкой в тень.
3.  **Начинайте с малого процента:** 10% `mirrorPercentage` достаточно для валидации; 100% зеркало требуйте только при capacity >2x.
4.  **Синхронизируйте часы:** NTP на primary и shadow нодах, иначе timestamp-поля дадут ложные расхождения.
5.  **Исключайте динамические поля из diff:** requestId, timestamp, nonce — иначе Comparison Engine будет генерировать False Positive.
6.  **Используйте eBPF/`tc mirred` для не-HTTP протоколов:** gRPC, raw TCP, UDP — Open Source Nginx mirror их не поддерживает.
7.  **Планируйте capacity 2x:** shadow требует полной копии compute, DB, cache; без capacity planning есть риск OOM и деградации prod.
8.  **Отключайте `mirror_request_body` для больших payload:** в Nginx это предотвращает дублирование буфера памяти.
9.  **Используйте feature flags для Dark Launch, когда прокси-зеркалирование невозможно по архитектурным причинам.**
10. **Мониторьте shadow-пул отдельно:** метрики CPU/RAM/fd shadow не должны смешиваться с primary в дашбордах.
11. **При side effects используйте idempotency keys:** если shadow всё же попадает в prod-систему, повторная обработка не создаст дублей.
12. **Для gRPC/HTTP2 выбирайте Envoy или Nginx Plus:** Open Source Nginx mirror работает поверх HTTP/1.1 subrequest.
13. **Валидируйте mirroring перед полным включением:** проверяйте `tc -s filter`, `nginx -t`, `istioctl proxy-status` и логи `shadow_access.log`.
14. **Используйте Comparison Engine с относительными метриками (Ratio), а не абсолютными порогами:** `error_rate(v2)/error_rate(v1)` корректнее при плавающей нагрузке.

## Граничные случаи и ограничения

- **Таймауты балансировщика:** В некоторых реализациях слишком медленный Shadow-бэкенд может удерживать ресурсы балансировщика, даже если ответ игнорируется.
- **Внешние зависимости (Side Effects):** Если сервис вызывает внешнюю систему, которую невозможно "замокать" (например, сложный банковский протокол), теневое развертывание этой функции невозможно.
- **Протокольные ограничения OSS Nginx:** `mirror` работает только поверх HTTP/1.1 subrequest; зеркалирование gRPC/HTTP2 требует Envoy или Nginx Plus.
- **Буферизация тела запроса:** `mirror` копирует тело запроса, что при больших payload удваивает потребление памяти прокси; использовать `mirror_request_body off`, если тело не нужно теневому сервису.
- **Стоимость ресурсов (2x):** Теневая среда требует практически полной копии вычислительных мощностей, БД и кэша. Требуется capacity-планирование.
- **Смещение выборки (sampling bias):** Зеркалирование 10% трафика может пропустить редкие сценарии (ошибочные/граничные запросы). Для полноты используйте 100%-е L4-зеркало (`tc mirred`) или полный capture.
- **Идемпотентность:** Если зеркало всё же вызывает side effect, необходимы idempotency keys, чтобы повторная обработка не создала дублей.

## Интеграция с GitLab CI/CD

### Полный пайплайн Shadow Deployment

```yaml
stages:
  - build
  - deploy_shadow
  - mirror
  - analyze

build_image:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:shadow-$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:shadow-$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_shadow:
  stage: deploy_shadow
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/deployment-shadow.yaml
    - kubectl rollout status deployment/my-app-shadow --timeout=300s
  environment:
    name: shadow
    url: https://shadow.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

configure_mirror:
  stage: mirror
  image: bitnami/kubectl:1.37
  needs:
    - deploy_shadow
  script:
    - kubectl apply -f k8s/virtualservice-mirror.yaml
    - kubectl get virtualservice my-app-mirror -o yaml
  environment:
    name: shadow
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

analyze_shadow:
  stage: analyze
  image: curlimages/curl:8.22.0
  needs:
    - configure_mirror
  script:
    - |
      # Сравнение latency shadow vs stable
      SHADOW_LATENCY=$(curl -s "http://prometheus:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket{version='shadow'}[5m]))by(le))" | jq '.data.result[0].value[1]')
      STABLE_LATENCY=$(curl -s "http://prometheus:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket{version='stable'}[5m]))by(le))" | jq '.data.result[0].value[1]')
      RATIO=$(echo "$SHADOW_LATENCY / $STABLE_LATENCY" | bc -l)
      echo "Shadow/Stable latency ratio: $RATIO"
      if (( $(echo "$RATIO > 1.2" | bc -l) )); then
        echo "WARNING: Shadow latency 20% higher than stable"
        exit 1
      fi
  environment:
    name: shadow
```

### Shadow через Nginx mirror module (Bare Metal)

```yaml
shadow_nginx:
  stage: deploy_shadow
  image: alpine:3.24
  before_script:
    - apk add --no-cache openssh-client curl
  script:
    - scp nginx/shadow.conf deploy@lb:/etc/nginx/conf.d/
    - ssh deploy@lb "nginx -t && nginx -s reload"
    - ssh deploy@lb "tail -f /var/log/nginx/shadow_access.log" &
    - sleep 5
    - pkill -f "tail -f"
  environment:
    name: shadow
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

## Дополнительная информация

### Рекомендованные ссылки

- **[Сравнение стратегий развертывания](./comparison.md)** — матрица выбора стратегий, включая пример зеркалирования на Nginx.
- **[Балансировка нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)** — механика весов, health checks и traffic mirroring на Nginx/HAProxy (авторитетный материал по маршрутизации).
- **[Мониторинг и оценка трафика при Canary](./canary_monitoring_and_gating.md)** — методология дифференциального и относительного (Ratio) сравнения метрик, применимая к Comparison Engine.

### Рекомендации для собеседований

**Вопрос:** Почему Shadow Deployment считается самой безопасной, но самой дорогой стратегией?
**Ответ:** Самая безопасная, потому что пользователь никогда не видит ответов новой версии, что исключает функциональный риск. Самая дорогая, потому что требует полной копии инфраструктуры (Compute, DB, Cache) для адекватного воспроизведения нагрузки и изоляции побочных эффектов.

**Вопрос:** Как проверить корректность работы новой версии в Shadow, если ответы пользователю не уходят?
**Ответ:** Через "движки сравнения" (например, Diffy), которые сопоставляют ответы v1 и v2 в фоне, или через анализ технических метрик (ошибки в логах, метрики Prometheus), которые должны коррелировать с основной версией.
