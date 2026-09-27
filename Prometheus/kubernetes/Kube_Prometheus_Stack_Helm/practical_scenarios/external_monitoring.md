# Мониторинг внешних целей в kube-prometheus-stack

> [Назад к оглавлению](../overview.md)

## Определения

**Внешние цели (External Targets)** — ресурсы, находящиеся вне кластера Kubernetes (виртуальные машины, bare-metal серверы, физические сетевые устройства, контейнеры на внешних хостах), метрики которых необходимо собирать централизованным экземпляром Prometheus.

**`static_configs`** — механизм статического перечисления адресов целей в конфигурации Prometheus. Является базовым способом мониторинга объектов с неизменными сетевыми реквизитами.

**`additionalScrapeConfigs`** — параметр в `values.yaml` Helm-чарта `kube-prometheus-stack`, позволяющий добавить произвольные секции `scrape_config` напрямую в конфигурационный файл Prometheus.

**`ScrapeConfig` CRD** — современный (v0.65+) ресурс Prometheus Operator, позволяющий декларативно описывать конфигурации сбора метрик для внешних целей без редактирования глобальных секретов или `values.yaml`.

**Blackbox Exporter** — официальный инструмент Prometheus для внешнего мониторинга (blackbox-мониторинг) сетевых сервисов. Проверяет доступность эндпоинтов по протоколам HTTP, HTTPS, TCP, ICMP и gRPC изнутри кластера. Подробная документация: [Blackbox Exporter — SSoT](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md).

**`Probe` CRD** — ресурс Prometheus Operator (v0.65+), предназначенный для декларативного описания проверок Blackbox Exporter. Устраняет необходимость руческого `relabel_configs` для подмены адреса скрейпинга.

**HTTP SD (`http_sd_configs`)** — механизм Service Discovery, при котором Prometheus опрашивает внешний HTTP-эндпоинт, возвращающий список целей в JSON-формате. Подходит для интеграции с внутренними CMDB/инвентарными системами. Подробнее: [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md).

> **См. также:** [Service Discovery и Relabeling](../../../service_discovery_and_relabeling.md), [Blackbox Exporter](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md).

## Основные концепции

### Архитектура взаимодействия

Prometheus, запущенный внутри Kubernetes, инициирует исходящие соединения (Scrape) к внешним IP-адресам. Альтернативный путь — использование Blackbox Exporter для активных проверок доступности.

```
┌─────────────────────────────┐      HTTP GET      ┌──────────────────────┐
│  Kubernetes Cluster         │ ─────────────────► │  Внешний сервер      │
│  (kube-prometheus-stack)    │    :9100/metrics   │  (Node Exporter)     │
└─────────────────────────────┘                    └──────────────────────┘

┌─────────────────────────────┐     TCP/HTTP       ┌──────────────────────┐
│  Blackbox Exporter          │ ─────────────────► │  Проверяемый сервис  │
│  (внутри кластера)           │     :9115/probe    │  (HTTP/TCP/ICMP)     │
└─────────────────────────────┘                    └──────────────────────┘
```

### Ключевые требования

1.  **Сетевая связность:** Поды Prometheus должны иметь маршрут к внешним сетям. Если внешние хосты находятся в приватной сети, может потребоваться VPN или выделенный сетевой интерфейс.
2.  **Firewall:** На внешних хостах должен быть разрешён входящий трафик на порты экспортеров (например, 9100 для Node Exporter) с IP-адресов нод кластера или конкретного диапазона Pod CIDR.
3.  **Разрешение имен:** Если в качестве целей используются DNS-имена, CoreDNS в кластере должен уметь их разрешать (через `forward` или `stubDomains`).
4.  **MTU:** При использовании VPN или туннелей убедитесь, что MTU между кластером и внешними целями достаточный для передачи метрик без фрагментации.

### Выбор метода конфигурации

| Метод | Плюсы | Минусы |
| :--- | :--- | :--- |
| **additionalScrapeConfigs** | Поддерживает любые виды Service Discovery (HTTP SD, Consul). | Требует обновления Helm-релиза и перезагрузки конфига через секрет. |
| **ScrapeConfig CRD** | Полностью декларативен, поддерживает проверку схемы (Validation), модульность. | Поддерживается в новых версиях Оператора (v0.65+). |
| **Probe CRD** | Специализирован для Blackbox Exporter, автоматическая подстановка адресов, поддержка в Operator. | Требует развертывания Blackbox Exporter в кластере. |
| **HTTP SD** | Динамическое обновление списка целей без перезагрузки Prometheus. | Требует наличия внешнего HTTP API, возвращающего JSON с целями. |

### Жизненный цикл конфигурации

1.  **Создание/обновление:** Пользователь применяет `ScrapeConfig`/`Probe`/изменяет `values.yaml`.
2.  **Отслеживание:** Prometheus Operator обнаруживает изменение через Informer Watch.
3.  **Генерация:** Operator агрегирует все ресурсы (`ServiceMonitor`, `ScrapeConfig`, `Probe`) и генерирует `prometheus.yaml`.
4.  **Доставка:** Сжатый конфиг сохраняется в Secret (`prometheus-<name>-generated`), который монтируется в под Prometheus.
5.  **Hot-reload:** `config-reloader` обнаруживает изменение Secret и отправляет сигнал SIGHUP процессу Prometheus.

## Практические сценарии

### Сценарий 1: Мониторинг внешних серверов через additionalScrapeConfigs

Классический способ добавления группы статических хостов через `values.yaml`.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-linux-servers'
        scrape_interval: 30s
        static_configs:
          - targets:
              - '192.168.10.50:9100'
              - '192.168.10.51:9100'
            labels:
              env: 'production'
              site: 'dc-1'
        relabel_configs:
          - source_labels: [__address__]
            regex: '(.*):9100'
            target_label: 'instance'
            replacement: '$1'
```

### Сценарий 2: Использование ScrapeConfig CRD (современный подход)

Создание отдельного ресурса для мониторинга внешней базы данных.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-postgres
  namespace: monitoring
spec:
  staticConfigs:
    - targets:
        - 'db-prod.internal:9187'
      labels:
        service: 'postgresql'
  relabelings:
    - targetLabel: 'cluster'
      replacement: 'main'
```

### Сценарий 3: Защищенный мониторинг с Basic Auth

Если экспортер на внешнем хосте защищен паролем.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'secure-external-app'
        static_configs:
          - targets: ['app.external.com:443']
        scheme: https
        basic_auth:
          username: 'prometheus-user'
          password: 'secret-password' # Рекомендуется использовать секрет
```

Для `ScrapeConfig` используйте ссылки на Secret:

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: basic-auth-external
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["prometheus-exporter.corp.local:9090"]
  basicAuth:
    username:
      name: basic-auth-secret
      key: username
    password:
      name: basic-auth-secret
      key: password
```

### Сценарий 4: Мониторинг внешних Docker-контейнеров (cAdvisor)

```yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'external-docker-hosts'
        static_configs:
          - targets: ['10.0.5.10:8080']
            labels:
              provider: 'bare-metal'
```

### Сценарий 5: Blackbox Exporter через Probe CRD

Мониторинг доступности внешних HTTP/TCP-сервисов. `Probe` CRD автоматически подставляет адрес Blackbox Exporter и передаёт проверяемую цель как параметр `target`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-website-check
  namespace: monitoring
spec:
  jobName: blackbox-http
  module: http_2xx
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  targets:
    staticConfig:
      static:
        - https://prometheus.io
        - https://api.example.com/health
  interval: 30s
  timeout: 10s
  labels:
    env: production
    team: platform
```

**Пример для TCP-порта:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-tcp-check
  namespace: monitoring
spec:
  jobName: blackbox-tcp
  module: tcp_connect
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  targets:
    staticConfig:
      static:
        - db.example.com:5432
        - redis.example.com:6379
  interval: 15s
  timeout: 5s
```

### Сценарий 6: Динамические цели через HTTP SD

Использование внешнего HTTP API (CMDB) для получения списка целей. Prometheus опрашивает API с заданным интервалом и автоматически обновляет список целей без перезагрузки конфигурации.

```yaml
# values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'cmdb-servers'
        http_sd_configs:
          - url: 'http://inventory.corp.local/api/v1/targets'
            refresh_interval: 5m
        relabel_configs:
          - source_labels: [__meta_http_sd_target_tag_env]
            target_label: environment
            action: replace
```

**Формат JSON-ответа от API:**

```json
[
  {
    "targets": ["10.0.1.5:9100", "10.0.1.6:9100"],
    "labels": {
      "__meta_http_sd_target_tag_env": "production",
      "team": "devops"
    }
  }
]
```

### Сценарий 7: TLS/mTLS для внешних целей

Если экспортер требует клиентского сертификата или проверки сертификата сервера.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: tls-external-target
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["secure-exporter.corp.local:9100"]
  tlsConfig:
    ca:
      secret:
        name: external-ca-bundle
        key: ca.crt
    cert:
      secret:
        name: client-cert
        key: tls.crt
    keySecret:
      name: client-cert
      key: tls.key
    insecureSkipVerify: false
```

### Сценарий 8: Authorization Header (Bearer Token) для внешних API

Многие внешние API требуют передачи токена в заголовке `Authorization`.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: bearer-token-api
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["metrics-api.corp.local"]
  authorization:
    type: Bearer
    credentials:
      name: api-token-secret
      key: token
  # Или через credentialsFile (Prometheus 2.29+)
  # credentialsFile: /etc/prometheus/secrets/api-token/token
```

### Сценарий 9: OAuth2 для внешних API

Использование OAuth2 Client Credentials Flow для получения access token.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: oauth2-external-api
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["api.corp.local"]
  oauth2:
    clientId:
      secret:
        name: oauth-creds
        key: id
    clientSecret:
      name: oauth-creds
      key: secret
    tokenUrl: https://auth.corp.local/token
  tlsConfig:
    ca:
      secret:
        name: api-ca
        key: ca.crt
    insecureSkipVerify: false
```

### Сценарий 10: Мониторинг внешних веб-сервисов через Blackbox Exporter (Probe + модули)

Развертывание Blackbox Exporter в кластере и создание Probe для проверки множества внешних сайтов.

**Развертывание Blackbox Exporter:**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install blackbox prometheus-community/prometheus-blackbox-exporter \
  --namespace monitoring --create-namespace
```

**Пример конфигурации модуля (через values.yaml):**

```yaml
config:
  modules:
    http_2xx:
      prober: http
      timeout: 5s
      http:
        valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
        valid_status_codes: [200]
        method: GET
        preferred_ip_protocol: "ip4"
        ip_protocol_fallback: true
    tcp_connect:
      prober: tcp
      timeout: 3s
```

### Сценарий 11: Мониторинг внешних сетевых устройств (SNMP)

Для сетевого оборудования (роутеры, коммутаторы) используйте SNMP Exporter. Создайте ScrapeConfig, указывающий на внешний SNMP Exporter.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-snmp-devices
  namespace: monitoring
spec:
  staticConfigs:
    - targets:
        - '192.168.1.1:9116'
        - '192.168.1.2:9116'
      labels:
        device_type: 'router'
  relabelings:
    - targetLabel: 'site'
      replacement: 'dc-1'
```

## Настройка параметров сбора

### Интервалы и таймауты

Для внешних целей через нестабильные каналы (Internet/VPN) рекомендуется увеличивать `scrape_interval` до 30–60 секунд и `scrape_timeout` до 10–20 секунд. Таймаут в Blackbox Exporter должен быть меньше `scrape_timeout` Prometheus на 500мс-1с.

```yaml
# Для ScrapeConfig
spec:
  interval: 30s
  timeout: 10s

# Для Probe
spec:
  interval: 30s
  timeout: 10s
```

### Native Histograms

Prometheus 3 поддерживает Native Histograms для внешних целей. Включение позволяет получать точные распределения вместо гистограмм с фиксированными bucket'ами.

```yaml
# ScrapeConfig
spec:
  scrapeNativeHistograms: true

# Для Probe Native Histograms не поддерживаются напрямую,
# но метрики blackbox_exporter (probe_duration_seconds) уже используют гистограммы
```

### Принципиальные различия: ScrapeConfig vs Probe

| Аспект | ScrapeConfig | Probe |
| :--- | :--- | :--- |
| **Назначение** | Сбор метрик с экспортеров на внешних хостах | Активные проверки доступности через Blackbox Exporter |
| **Цель** | `target:metrics` | `target:service endpoint` |
| **Типичные экспортеры** | Node Exporter, cAdvisor, PostgreSQL Exporter | Blackbox Exporter |
| **Типичные метрики** | CPU, RAM, Disk, QPS | `probe_success`, `probe_duration_seconds` |

## Relabeling паттерны для внешних целей

### Удаление порта из метки instance

```yaml
relabelings:
  - source_labels: [__address__]
    regex: '(.*):9100'
    target_label: 'instance'
    replacement: '$1'
```

### Добавление site-лейбла на основе CIDR

```yaml
relabelings:
  - source_labels: [__address__]
    regex: '192\.168\.10\..+'
    target_label: 'site'
    replacement: 'dc-1'
  - source_labels: [__address__]
    regex: '192\.168\.20\..+'
    target_label: 'site'
    replacement: 'dc-2'
```

### Поддержка IPv6

```yaml
relabelings:
  - source_labels: [__address__]
    regex: '\\[([^\\]]+)\\]:9100'
    target_label: 'instance'
    replacement: '$1'
```

## Диагностика и отладка

### Проверка конфигурации в Prometheus

После применения конфигурации необходимо убедиться, что цели (Targets) появились в UI Prometheus.

1.  Выполните port-forward: `kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090`.
2.  Перейдите в раздел **Status -> Targets**.
3.  Найдите `job_name`, указанный в конфигурации.
4.  Проверьте состояние `UP`/`DOWN` и причину ошибки, если цель недоступна.

### Проверка сгенерированного конфига

```bash
# Для additionalScrapeConfigs (конфиг в Secret)
kubectl get secret prometheus-main-generated -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | grep -A 20 "job_name: external"

# Для ScrapeConfig (статус ресурса)
kubectl get scrapeconfig -n monitoring
kubectl describe scrapeconfig external-postgres -n monitoring

# Для Probe
kubectl get probe -n monitoring
kubectl describe probe external-website-check -n monitoring
```

### Проверка доступности изнутри кластера

```bash
# Используя временный под
kubectl run debug --image=curlimages/curl -it --rm -- curl -v http://192.168.10.50:9100/metrics

# Проверка DNS-резолвинга
kubectl run debug --image=busybox -it --rm -- nslookup external-host.corp.local

# Проверка TCP-порта
kubectl run debug --image=busybox -it --rm -- nc -zv external-host.corp.local 9100
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `context deadline exceeded` | Проблема сетевой доступности или Firewall. | Проверьте `ping` и `telnet` с ноды кластера до цели. |
| `connection refused` | Экспортер не запущен или слушает только `127.0.0.1`. | Проверьте статус сервиса на внешнем хосте и его `listen-address`. |
| `server returned HTTP status 403 Forbidden` | Неверные учетные данные или ограничения на стороне экспортера. | Проверьте настройки `basic_auth` или IP-фильтры экспортера. |
| ` TLS handshake error` | Сертификат невалиден, несовпадение CN/SAN, или отсутствует CA. | Проверьте `tlsConfig` в ScrapeConfig/Probe, убедитесь что CA содержит корневой сертификат. |
| `connection reset by peer` | Цель активно закрывает соединение (возможно, WAF/IPS). | Проверьте логи цели, убедитесь что IP Prometheus в whitelist. |
| `No route to host` | Маршрут до цели отсутствует или ARP-таблица сброшена. | Проверьте таблицу маршрутизации на ноде кластера. |
| `i/o timeout` | Цель недоступна или отвечает слишком медленно. | Увеличьте `scrape_timeout`, проверьте доступность цели извне кластера. |
| `probe_success 0` (Blackbox) | Модуль blackbox.yml не соответствует протоколу цели. | Проверьте `module` в Probe, убедитесь что модуль существует в blackbox.yml. |
| `404 Not Found` на /metrics | Экспортер запущен, но путь `/metrics` неверен. | Проверьте `metrics_path` в конфигурации; некоторые экспортеры используют нестандартные пути. |
| `insecureSkipVerify: false` ошибка | Сертификат цели не может быть проверён. | Добавьте CA в `tlsConfig.ca` или исправьте цепочку сертификатов на цели. |

## Пограничные случаи

### 1. Цель доступна из пода Prometheus, но не с ноды кластера

Иногда Calico/Cilium или NetworkPolicy блокируют трафик на уровне pods, но ноды имеют прямой доступ. Проверяйте доступность с помощью временного пода в том же namespace.

### 2. DNS-резолвинг работает внутри кластера, но не с нод

CoreDNS может иметь `stubDomains` или `forward`, недоступные с нод. Для внешних DNS-имен можно использовать IP-адреса напрямую или настроить `/etc/resolv.conf` на нодах.

### 3. Большое количество внешних целей (>1000)

При превышении лимита Secret в 1 MiB используйте `ScrapeConfig` для разделения конфигурации на несколько ресурсов или включите шардирование (`spec.shards`).

### 4. Rotate сертификатов внешних целей

При ротации TLS-сертификатов на внешних хостах Prometheus продолжает использовать старый CA bundle из Secret. Обновите Secret и дождитесь hot-reload config-reloader (обычно <30 секунд).

### 5. Внешние цели за NAT

Если внешние хосты находятся за NAT, убедитесь что NAT не модифицирует пакеты таким образом, что сбрасываются TCP-сегменты с опциями (например, Timestamp). В таком случае используйте MSS clamping.

### 6. Ротация учетных данных через External Secrets Operator

Для автоматической ротации Basic Auth или Bearer токенов используйте External Secrets Operator (ESO). При обновлении внешнего секрета ESO обновляет Kubernetes Secret, config-reloader detects изменение и перезагружает Prometheus.

### 7. Blackbox Exporter за Ingress

Если Blackbox Exporter доступен только через Ingress, проверьте что Ingress не кэширует ответы и передаёт все необходимые заголовки. Для ICMP-проверок требуется прямой доступ к экспортеру.

### 8. ScrapeConfig с OTLP endpoint

Prometheus 3.x может собирать метрики через OTLP. Для внешних целей, отправляющих метрики по OTLP/gRPC, используйте соответствующий endpoint configuration.

### 9. Протокол HTTP/2 и ALPN

При использовании HTTPS с HTTP/2 убедитесь что экспортер поддерживает ALPN. Некоторые старые экспортеры могут не поддерживать HTTP/2, что приведёт к ошибкам handshake.

### 10. Единый Blackbox Exporter для множества namespace

Если Blackbox Exporter развёрнут в одном namespace, а Probe создаются в разных, используйте ServiceMonitor с соответствующим `namespaceSelector` или разверните экспортер в каждом namespace.

## Валидация после внедрения

```bash
# 1. Проверка, что ScrapeConfig/Probe созданы
kubectl get scrapeconfig,probe -n monitoring

# 2. Проверка статуса целей в Prometheus UI
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
# Откройте http://localhost:9090/targets

# 3. Проверка, что метрики появляются
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
curl -s "http://localhost:9090/api/v1/series?match[]=up{job=\"external-linux-servers\"}&start=now-5m" | jq '.data | length'

# 4. Проверка сгенерированного конфига (должен содержать вашу конфигурацию)
kubectl get secret prometheus-main-generated -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | grep -A 5 "job_name: external"

# 5. Проверка что config-reloader работает
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator -c config-reloader | tail -20

# 6. Проверка времени последней успешной перезагрузки
kubectl get secret prometheus-main-generated -n monitoring \
  -o jsonpath='{.metadata.annotations.prometheus\.operator\.io/reloadTime}'
```

## Откат и очистка

### Удаление ScrapeConfig

```bash
kubectl delete scrapeconfig external-postgres -n monitoring
# Дождаться перезагрузки Prometheus (config-reloader обновит конфиг)
kubectl rollout status statefulset/prometheus-operated -n monitoring --timeout=5m
```

### Удаление Probe

```bash
kubectl delete probe external-website-check -n monitoring
# Проверить что цель исчезла из /targets
```

### Откат additionalScrapeConfigs

```bash
# 1. Откат values.yaml к предыдущей версии
git checkout -- values.yaml
# или
helm rollback monitoring -n monitoring

# 2. Проверка rollout
kubectl rollout status statefulset/prometheus-operated -n monitoring --timeout=5m
```

### Полная очистка

```bash
# Удаление всех ScrapeConfig и Probe
kubectl delete scrapeconfig,probe --all -n monitoring

# Откат Helm-релиза
helm rollback monitoring -n monitoring

# Проверка что внешние цели исчезли из Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &
curl -s "http://localhost:9090/api/v1/label/job/values" | jq -r '.data[]' | grep external
```

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Интервалы сбора:** Для внешних целей через нестабильные каналы (Internet/VPN) рекомендуется увеличивать `scrape_interval` до 30–60 секунд и `scrape_timeout` до 10–20 секунд.
2.  **Безопасность:** Никогда не оставляйте экспортеры на внешних хостах открытыми в мир. Используйте VPN, IP-ограничения или TLS + Basic Auth.
3.  **Модульность:** Предпочитайте `ScrapeConfig` CRD вместо гигантского `values.yaml`, если ваша версия Оператора это позволяет.
4.  **Blackbox Exporter:** Размещайте экспортер в той же сети, что и большинство целей. Один инстанс может обслуживать тысячи целей, но ограничьте частоту проверок до разумного минимума (обычно 15s, 30s или 60s).
5.  **Relabeling:** Используйте `relabelings` для приведения имен инстансов к читаемому виду и добавления информативных меток (site, team, env).
6.  **Секреты:** Никогда не хардкодьте пароли в `additionalScrapeConfigs`. Используйте `basicAuth` с ссылками на Secret в `ScrapeConfig`.
7.  **Мониторинг Blackbox Exporter:** Добавьте в Prometheus проверку эндпоинта `/metrics` экспортера с помощью `up{job="blackbox_exporter"}`.
8.  **Ротация секретов:** Используйте External Secrets Operator для автоматической ротации учетных данных внешних целей.
9.  **Валидация:** Перед применением проверяйте конфигурацию через `kubectl apply --dry-run=client` и сгенерированный `prometheus.yaml`.
10. **Ограничения:** Не превышайте 1 MiB на сгенерированный Secret. При приближении к 800 KiB используйте шардирование или `ScrapeConfig`.

### Связанные ресурсы

*   [ServiceMonitor CRD](../../../kubernetes/operator/crd/servicemonitor.md)
*   [Экспортеры: общая информация](../../../Exporters/overview.md)
*   [Blackbox Exporter в Kubernetes](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md)
