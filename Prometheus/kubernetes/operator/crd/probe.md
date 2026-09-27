# Probe — Концепции (CRD)

## Определения

**`kind: Probe`** — Custom Resource Definition в Prometheus Operator, предназначенный для реализации **blackbox-мониторинга** (внешнего наблюдения) эндпоинтов. В отличие от `ServiceMonitor`, который собирает метрики состояния самого приложения, `Probe` проверяет доступность, корректность ответов и производительность сервисов по протоколам HTTP, HTTPS, TCP, ICMP, DNS и gRPC изнутри кластера.

**Blackbox Exporter** — вспомогательный компонент, который выступает в роли "прокси" для выполнения проверок. Prometheus опрашивает экспортер, а экспортер выполняет реальную проверку цели.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Blackbox Exporter — обзор](../../../Exporters/blackbox/blackbox_exporter_overview.md), [Конфигурация модулей](../../../Exporters/blackbox/blackbox_exporter_modules_configuration.md), [ServiceMonitor](./servicemonitor.md), [PodMonitor](./podmonitor.md).

## Базовые концепции

### Принцип работы и жизненный цикл

Процесс интеграции Probe CRD в стек мониторинга включает следующие этапы:

1.  **Наблюдение (Watch):** Prometheus Operator отслеживает создание и изменение объектов `Probe` в кластере.
2.  **Выборка (Selection):** Ресурс `Prometheus` через `probeSelector` определяет, какие именно Probe-ресурсы должны быть загружены в конкретный экземпляр сервера.
3.  **Генерация конфигурации:** Оператор формирует секцию `scrape_config` в конфигурации Prometheus, используя параметры `prober.url`, `module` и `targets` из CRD.
4.  **Применение (Apply):** Обновленная конфигурация записывается в Kubernetes Secret, который монтируется в под Prometheus.
5.  **Перезагрузка:** Контейнер `config-reloader` (sidecar) обнаруживает изменение Secret и отправляет сигнал `/-/reload` серверу Prometheus.
6.  **Верификация (Status):** В UI Prometheus (`Status -> Targets`) проверяется состояние целей. Успешный Probe возвращает `probe_success = 1`.

### Архитектура Multi-Target Scrape

Интеграция строится на модели делегирования сбора метрик:

1.  **Delegation:** Prometheus отправляет запрос не на целевой сервис, а на эндпоинт `/probe` Blackbox Exporter.
2.  **Execution:** Exporter получает параметры (адрес цели и модуль), выполняет проверку и возвращает результат в формате метрик Prometheus.
3.  **Metrics:** Основными метриками являются `probe_success` (1 — успех, 0 — провал) и `probe_duration_seconds`.

```text
[ Prometheus ]
      |
      | (GET /probe?target=example.com&module=http_2xx)
      v
[ Blackbox Exporter ] ------> [ Target: example.com ]
      |          (HTTP GET)        |
      |                            |
      |<--------- (Response) <-----|
      |
      | (probe_success 1)
      v
[ Prometheus TSDB ]
```

### Когда использовать Probe

*   **Внешние сервисы:** Мониторинг сайтов, API и микросервисов, находящихся за пределами кластера (публичные URL, корпоративные ресурсы, партнерские API).
*   **Ингресс и балансировщики:** Проверка доступности Ingress-контроллеров (Nginx, Traefik) и LoadBalancer-сервисов с точки зрения внешнего клиента.
*   **Сетевая инфраструктура:** Проверка доступности шлюзов, VPN-тоннелей, сетевого оборудования и удаленных хостов по ICMP/TCP.
*   **SSL/TLS мониторинг:** Контроль срока действия сертификатов на внешних доменах без установки агентов на целевые хосты.
*   **gRPC-сервисы:** Проверка состояния здоровья микросервисов, использующих gRPC Health Check Protocol.
*   **DNS-резолвинг:** Валидация работы внутренних и внешних DNS-серверов.
*   **Синтетический мониторинг:** Эмуляция действий реального пользователя для проверки сквозных сценариев (Synthetic E2E).

### Сравнение с ServiceMonitor и PodMonitor

| Характеристика | ServiceMonitor / PodMonitor | Probe |
| :--- | :--- | :--- |
| **Тип мониторинга** | Whitebox (внутреннее состояние) | Blackbox (внешняя доступность) |
| **Источник данных** | `/metrics` самого приложения | Эндпоинт `/probe` экспортера |
| **Цели** | Сервисы и Поды внутри K8s | Любые эндпоинты (внешние URL, IP, Ingress) |
| **Протоколы** | HTTP (Prometheus format) | HTTP, HTTPS, TCP, ICMP, DNS, gRPC |
| **Механизм обнаружения** | Service Discovery через K8s API | Статические списки или Ingress-селекторы |
| **Зависимость от K8s Service** | Обязательна (ServiceMonitor) или отсутствует (PodMonitor) | Отсутствует |

### Селекторы в ресурсе Prometheus

Для того чтобы Prometheus обнаружил ресурсы `Probe`, в спецификации ресурса `Prometheus` должен быть настроен `probeSelector`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: prometheus
  namespace: monitoring
spec:
  probeSelector:
    matchLabels:
      release: prometheus-stack
```

> **Важно:** Без соответствующего `probeSelector` ресурсы `Probe` игнорируются Prometheus. Это распространенная ошибка при первом развертывании.

### Новые возможности (2025–2026)

*   **OAuth2 & Modern Auth:** Нативная поддержка OAuth2 и расширенных механизмов авторизации (bearer tokens) через Secret-ы.
*   **gRPC Monitoring:** Поддержка проверки здоровья gRPC-сервисов через соответствующие модули Blackbox Exporter.
*   **Native Histograms:** Поддержка высокоточных нативных гистограмм Prometheus 3.0.
*   **Scrape Protocols:** Возможность явного выбора приоритета протоколов (OpenMetrics vs Prometheus Text).
*   **ProxyConfig:** Поддержка корпоративных прокси через `proxyConfig` для выхода в интернет из изолированных сегментов сети.
*   **Сбор метаданных нод:** Возможность прикрепления лейблов узла к метрикам через `attachMetadata`.

## Практические сценарии

### Сценарий 1: Проверка внешнего HTTPS API с OAuth2

Актуально для мониторинга внешних сервисов, требующих авторизации.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-api-oauth2
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  jobName: api-health-check
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://api.external-service.com/v1/health
  oauth2:
    clientId:
      secret:
        name: api-credentials
        key: client-id
    clientSecret:
      name: api-credentials
      key: client-secret
    tokenUrl: https://auth.external-service.com/oauth/token
  interval: 1m
  scrapeTimeout: 30s
```

### Сценарий 2: Мониторинг всех Ingress по селектору

Автоматическое создание проверок для всех приложений, помеченных лейблом `probe: "enabled"`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: ingress-auto-probe
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    ingress:
      selector:
        matchLabels:
          probe: "enabled"
      namespaceSelector:
        any: true
```

### Сценарий 3: gRPC Health Check

Мониторинг доступности микросервисов, использующих gRPC.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: grpc-service-probe
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: grpc_health  # Модуль должен быть настроен в Blackbox Exporter
  targets:
    staticConfig:
      static:
        - my-grpc-app.prod.svc.cluster.local:50051
  interval: 30s
```

### Сценарий 4: ICMP (Ping) проверка инфраструктуры

Проверка доступности удаленных хостов или сетевого оборудования.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: infrastructure-ping
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: icmp
  targets:
    staticConfig:
      static:
        - 8.8.8.8
        - 10.0.0.1
        - vpn-gateway.company.com
  interval: 30s
```

### Сценарий 5: Проверка с базовой авторизацией и TLS

Мониторинг внутренних сервисов, защищенных Basic Auth.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: internal-basic-auth-probe
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://internal-admin.company.com/health
  basicAuth:
    username:
      secret:
        name: internal-credentials
        key: username
    password:
      secret:
        name: internal-credentials
        key: password
  tlsConfig:
    ca:
      secret:
        name: internal-ca
        key: ca.crt
    insecureSkipVerify: false
  interval: 30s
  scrapeTimeout: 10s
```

### Сценарий 6: Мониторинг через корпоративный прокси

Для кластеров в изолированных сетях без прямого доступа в интернет.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-via-proxy
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://external-api.example.com/health
  proxyConfig:
    proxyURL: http://squid.corp.internal:3128
    noProxy: "localhost,127.0.0.1,.internal.svc"
  interval: 1m
  scrapeTimeout: 15s
```

### Сценарий 7: Проверка SSL-сертификатов с алертингом

Мониторинг срока действия сертификатов на внешних доменах.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: ssl-expiry-check
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    staticConfig:
      static:
        - https://example.com
        - https://api.example.com
        - https://admin.example.com
  interval: 1h
  scrapeTimeout: 10s
```

### Сценарий 8: Динамические цели через Ingress с фильтрацией

Проверка только Production-ингрессов с дополнительным relabeling.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: production-ingress-probe
  namespace: monitoring
  labels:
    release: prometheus-stack
spec:
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  module: http_2xx
  targets:
    ingress:
      selector:
        matchLabels:
          environment: production
      namespaceSelector:
        matchNames:
          - production
  interval: 30s
  scrapeTimeout: 10s
  metricRelabelings:
    - sourceLabels: [__param_target]
      targetLabel: domain
    - action: drop
      regex: ".*\\.internal\\..*"
```

## Дополнительная информация

### Требования к правам (RBAC)

Для корректной работы `Probe` и связанного Blackbox Exporter необходимо настроить права доступа:

**Для Prometheus Operator:**
*   Права `get`, `list`, `watch` на ресурсы `probes` в целевых неймспейсах.
*   Права на чтение `secrets` для получения учетных данных (OAuth2, Basic Auth, TLS).

**Для Blackbox Exporter:**
*   **ICMP:** Capability `NET_RAW` для выполнения Ping без root:
    ```bash
    sudo setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter
    ```
*   **Сетевая изоляция:** Разрешите только исходящий трафик на целевые порты (обычно 80, 443, 53, 5432). Ограничьте доступ к порту `9115` только IP-адресами серверов Prometheus.
*   **Kubernetes RBAC:** ServiceAccount экспортера должен иметь права на чтение Ingress-ресурсов, если используется `targets.ingress`.

### Ключевые параметры спецификации (v1)

| Параметр | Описание | Особенности / Лимиты |
| :--- | :--- | :--- |
| **`prober.url`** | Адрес Blackbox Exporter. | Формат `host:port`. Должен быть доступен из Prometheus. |
| **`module`** | Имя модуля в конфиге экспортера. | Должно совпадать с `blackbox.yml`. |
| **`jobName`** | Переопределение имени задания. | Задает значение метки `job` в метриках. |
| **`interval`** | Периодичность выполнения проверок. | По умолчанию берется из глобальных настроек Prometheus. |
| **`scrapeTimeout`** | Максимальное время ожидания ответа. | **Важно:** должен быть больше таймаута в модуле Blackbox Exporter на 500мс-1с. |
| **`targets.staticConfig`** | Список фиксированных целей. | Поддерживает кастомные `labels`. |
| **`targets.ingress`** | Динамический поиск целей через Ingress. | Использует `host` из правил Ingress. |
| **`oauth2`** | Конфигурация OAuth2. | **Mutual Exclusion:** нельзя использовать вместе с `basicAuth`. |
| **`basicAuth`** | Базовая авторизация. | Поддерживает `username` и `password` из Secret. |
| **`authorization`** | Настройка Bearer-токена. | Поддерживает `credentials` из Secret. |
| **`tlsConfig`** | TLS для соединения с целью. | Влияет на валидацию сертификата целевого сервиса. |
| **`proxyConfig`** | Настройка прокси. | Используется для выхода в интернет из изолированных сетей. |
| **`scrapeProtocols`** | Приоритет протоколов сбора. | OpenMetrics, PrometheusText. |
| **`scrapeNativeHistograms`** | Включение нативных гистограмм. | Требует Prometheus >= 3.0. |
| **`metricRelabelings`** | Трансформация метрик после сбора. | Используется для удаления лишних метрик. |
| **`relabelings`** | Трансформация целей до сбора. | Используется для фильтрации и модификации. |

### Параметры targets

#### staticConfig

```yaml
targets:
  staticConfig:
    static:
      - https://example.com
      - https://api.example.com:8443/health
    labels:
      env: production
      team: platform
```

| Поле | Описание |
| :--- | :--- |
| `static` | Список строк с целями (URL, IP, хост). |
| `labels` | Кастомные лейблы, добавляемые ко всем метрикам от этого списка. |

#### ingress

```yaml
targets:
  ingress:
    selector:
      matchLabels:
        probe: "enabled"
    namespaceSelector:
      any: true
      matchNames:
        - production
```

| Поле | Описание |
| :--- | :--- |
| `selector` | Label Selector для фильтрации Ingress-ресурсов. |
| `namespaceSelector` | Селектор неймспейсов. `any: true` — все неймспейсы. |

### Ограничения и крайние случаи

*   **Взаимное исключение `basicAuth` и `oauth2`:** В одной Probe-конфигурации можно использовать только один из методов авторизации.
*   **Зависимость от сети:** Результаты Probe отражают состояние сетевого пути между Blackbox Exporter и целью, а не только состояние самого приложения.
*   **ICMP и фаерволлы:** На уровне хоста или сети ICMP часто блокируется фаерволлом. Для проверки доступности хоста используйте TCP-проверки на порт 80 или 443.
*   **Таймауты:** `scrapeTimeout` должен быть больше таймаута модуля в `blackbox.yml` на 500мс-1с. В противном случае Prometheus отменит проверку до получения результата.
*   **Cardinality:** Каждый уникальный target создает отдельный временной ряд. Для >10 000 уникальных целей используйте шардирование или разделение на несколько Probe-ресурсов.
*   **URL-кодирование:** Параметр `target` должен быть корректно URL-encoded. Prometheus relabeling обрабатывает это автоматически для большинства случаев.
*   **Зависимость от Blackbox Exporter:** Ресурс `Probe` не работает без запущенного Blackbox Exporter в кластере. При его недоступности все проверки будут возвращать `probe_success = 0`.

### Диагностика

1.  **Проверка генерации таргетов:** В UI Prometheus перейдите в `Status -> Targets`. Найдите job с именем вашего Probe. Цель должна иметь адрес в формате `http://<blackbox-exporter>:9115/probe?target=<цель>&module=<модуль>`.
2.  **Проверка запроса к экспортеру:**
    ```bash
    curl "http://blackbox-exporter.monitoring.svc.cluster.local:9115/probe?target=google.com&module=http_2xx"
    ```
3.  **Проверка селектора Prometheus:**
    ```bash
    kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.probeSelector}' | jq .
    # Убедитесь, что селектор соответствует лейблам вашего Probe
    ```
4.  **Логи Оператора:** Если таргеты не появились, проверьте логи `prometheus-operator` на наличие ошибок валидации CRD:
    ```bash
    kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator | grep -i probe
    ```
5.  **Проверка статуса ресурса:**
    ```bash
    kubectl get probe -n monitoring
    kubectl describe probe <name> -n monitoring
    ```

### Типичные проблемы и устранение неполадок

1.  **Probe не появляется в Targets Prometheus**
    *   **Причина:** Отсутствует `probeSelector` в ресурсе `Prometheus` или несовпадающие лейблы.
    *   **Решение:** Проверьте `kubectl get prometheus -o yaml | grep -A5 probeSelector`. Убедитесь, что Probe имеет соответствующие лейблы.

2.  **Ошибка `Invalid module`**
    *   **Причина:** Модуль, указанный в параметре `module`, отсутствует в `blackbox.yml` или опечатка в имени.
    *   **Решение:** Проверьте конфигурацию: `kubectl get configmap blackbox-exporter-config -n monitoring -o yaml | grep -A5 http_2xx`. Убедитесь в отсутствии опечаток.

3.  **`probe_success` постоянно `0` при доступном сервисе**
    *   **Причина:** Неправильный модуль (например, `http_2xx` для TCP-сервиса), редиректы, которые не обрабатываются, или блокировка фаерволлом.
    *   **Решение:** Используйте `follow_redirects: true` для HTTP. Убедитесь, что модуль соответствует протоколу цели. Проверьте цепочку: `kubectl exec -it <prometheus-pod> -- curl -v "http://blackbox-exporter:9115/probe?target=<цель>&module=<модуль>"`.

4.  **Несоответствие таймаутов**
    *   **Причина:** Таймаут в модуле (`timeout` в `blackbox.yml`) больше, чем `scrapeTimeout` в Probe CRD.
    *   **Решение:** Установите `timeout` в модуле на 500мс-1с меньше, чем `scrapeTimeout`. Например, если `scrapeTimeout: 10s`, используйте `timeout: 9s` в модуле.

5.  **ICMP-проверки не работают (permission denied)**
    *   **Причина:** Недостаточно прав для ICMP.
    *   **Решение:** Выполните `sudo setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter` или добавьте `cap_add: [NET_RAW]` в спецификацию Pod-а экспортера.

6.  **TLS-ошибки (handshake failure, certificate verify failed)**
    *   **Причина:** Устаревший сертификат на цели, несовместимость версий TLS, неправильный SNI.
    *   **Решение:** Используйте `insecureSkipVerify: false` и явно укажите `serverName` в `tlsConfig` для корректной передачи SNI. Проверьте поддержку TLS 1.2+ на цели.

7.  **OAuth2-авторизация не работает**
    *   **Причина:** Неправильные Secret или неверный `tokenUrl`.
    *   **Решение:** Проверьте, что Secret содержит корректные `client-id` и `client-secret`. Убедитесь, что `tokenUrl` возвращает валидный JWT. Проверьте логи Blackbox Exporter.

8.  **Метрики `probe_duration_seconds` аномально высокие**
    *   **Причина:** Маршрутизация через узкие места, DNS-задержки, TLS-handshake на стороне цели.
    *   **Решение:** Используйте `probe_http_duration_seconds` с лейблом `phase` для диагностики фазы задержки. Рассмотрите размещение экспортера ближе к цели.

### Валидация работоспособности

После развертывания выполните следующие проверки:

**1. Проверка доступности эндпоинта `/probe` (ad-hoc):**
```bash
# Проверка доступности сайта через модуль http_2xx
curl "http://blackbox-exporter.monitoring.svc.cluster.local:9115/probe?target=google.com&module=http_2xx"

# Проверка DNS-резолвинга
curl "http://blackbox-exporter.monitoring.svc.cluster.local:9115/probe?target=8.8.8.8&module=dns_google"
```
Ожидаемый результат: HTTP 200 с текстовым форматом Prometheus, содержащим метрики `probe_success`, `probe_duration_seconds` и др.

**2. Проверка в Prometheus:**
```promql
# Проверка успешности всех проверок за последние 5 минут
avg_over_time(probe_success[5m])

# Проверка доступности самого экспортера
up{job="blackbox-exporter"}
```

**3. Проверка статуса применения:**
```bash
kubectl get probe -n monitoring
kubectl describe probe <name> -n monitoring
```

### Лучшие практики

*   **Размещение:** Размещайте Blackbox Exporter в той же сети, что и большинство целей. Для внешних проверок используйте географически распределенные инстансы.
*   **Масштабирование:** Ограничьте частоту проверок до разумного минимума (обычно 15s, 30s или 60s), чтобы не создавать DDoS-эффект на целевые сервисы.
*   **Безопасность:**
    *   Никогда не открывайте порт 9115 в публичную сеть без TLS и Basic Auth.
    *   Используйте `web-config.yml` с валидными сертификатами.
    *   Ограничьте доступ на уровне фаерволла только IP Prometheus.
*   **Таймауты:** Всегда настраивайте `timeout` в модуле меньше, чем `scrapeTimeout` в Probe CRD. Рекомендуемая разница — 500мс-1с.
*   **Мониторинг самого экспортера:** Добавьте в Prometheus проверку эндпоинта `/metrics` экспортера с помощью `up{job="blackbox_exporter"}`. Оптимальный интервал — 30s.
*   **Именование:** Используйте осмысленные имена модулей, отражающие тип проверки (`http_2xx`, `tcp_postgres`, `dns_external`).
*   **Cardinality (кардинальность):** Избегайте использования высококардинальных лейблов в `target`. Каждый уникальный target создает отдельный временной ряд.
*   **Версионирование:** Храните конфигурацию Blackbox Exporter (`blackbox.yml`) в системе контроля версий (Git).

### См. также

*   [Blackbox Exporter — настройка модулей](../../../Exporters/blackbox/blackbox_exporter_modules_configuration.md) — подготовка модулей и параметров проверки.
*   [Blackbox Exporter — установка и настройка](../../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md) — развертывание, включая Probe CRD.
*   [Prometheus Operator — Концепции](../concepts.md) — архитектура и роль CRD в мониторинге Kubernetes.
*   [Prometheus CRD](./prometheus.md) — селекторы целей и конфигурация сервера.
*   [Официальная документация Probe CRD](https://prometheus-operator.dev/docs/operator/design/#probe) — описание параметров и примеров от разработчиков.
