# Тюнинг производительности Istio (Performance & Capacity)

## Определения

**Sidecar Tax** — накладные расходы (CPU/RAM/задержка), которые добавляет каждый прокси к рабочей нагрузке. В Sidecar-модели это может достигать 10–15% ресурсов сервиса; Ambient-модель снижает оверхед до 1–3%.

**`proxy.istio.io/config`** — аннотация пода, задающая эффективную конфигурацию прокси (`ProxyConfig`): `concurrency`, `terminationDrainDuration`, `drainDuration`, `proxyMetadata` и др. Применяется к конкретному поду поверх глобального `MeshConfig.defaultConfig`.

**Concurrency (количество потоков Envoy)** — число worker-потоков Envoy. Влияет на использование CPU/памяти прокси (каждый поток добавляет память) и на задержку в однопоточных workers.

**Cardinality метрик** — количество уникальных комбинаций label-значений, порождаемых метрикой. Высокая кардинальность — главная причина роста памяти Prometheus и нагрузки на scrape.

**xDS Push** — доставка конфигурации от istiod прокси через протокол xDS (CDS/LDS/EDS/RDS). Частота/объём push-ев определяют загрузку Control Plane.

**Capacity Planning** — расчёт ресурсов контрольной и плоскостей данных под заданный размер кластера (число подов, сервисов, конфигов), включая запас на пики.

---

## Основные концепции

### Куда уходят ресурсы Istio

1. **Прокси (Data Plane)**: память растёт с числом известных кластеров (сервисов), CPU — с RPS и числом фильтров. Сокращение списка известных сервисов (`Sidecar` resource) уменьшает и то, и другое.
2. **istiod (Control Plane)**: память растёт с числом сервисов/эндпоинтов/конфигов (генерирует конфиги для всех), CPU — с частотой push и числом прокси, подключающихся одновременно.
3. **Ztunnel (Ambient)**: per-node DaemonSet, ресурсы растут с числом подов/потоков на узле.
4. **Waypoint Proxy**: L7-прокси на namespace/сервис; ресурсы зависят от RPS и числа политик.

### Ресурсные ориентиры (усреднённые)

| Компонент | requests | limits | Примечание |
| :--- | :--- | :--- | :--- |
| istiod (на 1000 подов) | 500m CPU / 1Gi RAM | — | минимум 2 реплики |
| istio-proxy (sidecar) | 50m–100m CPU / 128Mi RAM | под нагрузкой — больше | растёт с числом кластеров |
| ztunnel (на узел) | 50m CPU / 64Mi RAM | 200m CPU / 256Mi RAM | DaemonSet |
| waypoint (до 1000 RPS) | 100m CPU / 128Mi RAM | — | HPA |

Числа ориентировочные; фактические определяйте нагрузочным тестированием (см. ниже).

### Параметры `proxy.istio.io/config`

- **`concurrency`**: число потоков Envoy. По умолчанию 2. Увеличение до числа CPU повышает пропускную способность, но линейно растёт и память. На стабильно высоконагруженных прокси ставьте `concurrency: 2` fixed (стабильность), на коротких всплесках — не выше числа ядер.
- **`terminationDrainDuration`**: время доводки in-flight запросов при SIGTERM (см. [istio-graceful-shutdown.md](./istio-graceful-shutdown.md)).
- **`drainDuration`**: длительность draining-фазы listener'ов.
- **`proxyMetadata`**: дополнительные метаданные (например, `ISTIO_META_DNS_CAPTURE`).

### Как снижать накладные расходы

1. **Scoping через `Sidecar` resource** — самый эффективный инструмент: ограничьте список известных сервисов прокси до минимального (`egress.hosts`). Память прокси падает в разы на больших кластерах. См. [istio-sidecar-configuration.md](./istio-sidecar-configuration.md).
2. **Снижение кардинальности метрик** — через `Telemetry API` (`metrics` labels), `proxyStatsMatcher`, exclude/regex по label. Подробно: [Сценарий 7 в istio_observability_and_tools.md](./istio_observability_and_tools.md).
3. **HTTP/2 и мультиплексирование** — mesh по умолчанию использует HTTP/2; это сокращает число соединений и улучшает latency-профиль (важно: явно задавайте протокол, см. [istio-protocol-detection.md](./istio-protocol-detection.md)).
4. **Ambient вместо Sidecar** — для кластеров с низкой требовательностью к per-pod изоляции Ambient заметно снижает совокупный расход.
5. **DNS capture** — включайте при необходимости, но учтите дополнительное CPU на DNS-прокси.

### Масштабирование istiod

- Минимум 2 реплики для >500 подов; HPA по CPU (>70%).
- Память istiod растёт с числом сервисов и их эндпоинтов; следите за `heap` и push-задержкой.
- `istioctl proxy-status` показывает статус прокси; стабильная задержка push (lastPushTime) — признак здорового Control Plane.
- Конфигурационные push-и генерируются по событиям; частое менение манифестов в больших кластерах увеличивает CPU istiod — оформляйте изменения батчами через GitOps.

### Методология нагрузочного тестирования

Правильный подход — A/B с контрольной точкой:
1. Измерить baseline БЕЗ меша (или без прокси для конкретного потока): latency, RPS, ресурсы.
2. Включить меш и измерить то же самое при той же нагрузке.
3. Вычислить «процент накладных»: (P99_mesh − P99_base) / P99_base × 100%.
4. Менять один параметр за раз (concurrency, resources, scoping) и повторять.

Инструменты: `vegeta`, `fortio`, `ghz` (gRPC).

---

## Практические сценарии

### Сценарий 1: Назначение ресурсов и concurrency для sidecar

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        proxy.istio.io/config: |
          concurrency: 2
          terminationDrainDuration: 15s
          drainDuration: 5s
    spec:
      containers:
      - name: my-app
        image: my-app:1.0
      - name: istio-proxy
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: "2"
            memory: 512Mi
```

Применение и проверка фактического потребления:

```bash
kubectl rollout restart deployment/my-app -n production
kubectl top pod my-app-xxx -n production --containers | grep istio-proxy
# → my-app-xxx   istio-proxy   120m    256Mi
```

### Сценарий 2: Снижение памяти sidecar через `Sidecar` resource

```yaml
apiVersion: networking.istio.io/v1
kind: Sidecar
metadata:
  name: default
  namespace: production
spec:
  egress:
  - hosts:
    - "production/*"
    - "istio-system/*"
```

```bash
# Сравните число известных кластеров до и после
istioctl proxy-config cluster deploy/my-app -n production | wc -l
# → 120 → 12  ← память прокси упала пропорционально
```

Детали: [istio-sidecar-configuration.md](./istio-sidecar-configuration.md).

### Сценарий 3: Настройка istiod (реплики + HPA + ресурсы)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: istiod-hpa
  namespace: istio-system
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: istiod
  minReplicas: 2
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

```bash
# Проверка push-синхронизации
istioctl proxy-status
# → NAME                              CDS     LDS     EDS     RDS
# → istio-ingressgateway...           SYNCED  SYNCED  SYNCED  SYNCED

# Логи и метрики istiod
kubectl logs -n istio-system deploy/istiod --tail=50
kubectl top pod -n istio-system -l app=istiod
```

### Сценарий 4: Уменьшение кардинальности метрик через Telemetry API

```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: prune-metrics
  namespace: production
spec:
  metrics:
  - providers:
    - name: prometheus
    overrides:
    - match:
        metric: REQUEST_COUNT
      tagOverrides:
        request_protocol:
          operation: REMOVE
```

```bash
# Проверка: label request_protocol исчез из метрик
# → В Prometheus: sum without(request_protocol) (istio_requests_total)
```

Полный материал по оптимизации кардинальности: [istio_observability_and_tools.md](./istio_observability_and_tools.md).

### Сценарий 5: Нагрузочное тестирование A/B (с мешем и без)

```bash
# База без mesh: приложение напрямую (порт приложения)
vegeta attack -duration=30s -rate=1000 -targets=http.txt | vegeta report
# → Latencies [mean, 50, 90, 99, max] 2.1ms 1.8ms 3.1ms 4.0ms 12.3ms

# Через mesh (сервисный DNS, sidecar)
vegeta attack -duration=30s -rate=1000 -targets=http-mesh.txt | vegeta report
# → Latencies [mean, 50, 90, 99, max] 2.9ms 2.4ms 4.2ms 5.8ms 21.0ms
# Оверхед P99 ≈ (5.8 − 4.0)/4.0 ≈ 45% (зависит от протокола/ядер)
```

Для gRPC — `ghz`:

```bash
ghz --insecure --concurrency=50 --duration=30s --rps=1000 \
  localhost:50051 helloworld.Greeter/SayHello
# → Summary: Total: 30000 requests, OK: 30000
```

### Сценарий 6: Диагностика деградерации

```bash
# 1. Какие прокси отстают от istiod
istioctl proxy-status | grep -v SYNCED

# 2. CPU прокси одного из топовых подов
kubectl top pod -n production -l app=my-app --containers | sort -k3 -h | tail

# 3. Активные соединения Envoy (при большом пуле — переполнение)
kubectl exec -n production deploy/my-app -c istio-proxy -- curl -s localhost:15000/stats | grep "upstream_cx_active"

# 4. Полный овервью ресурсов по namespace
kubectl top pods -n production
```

---

## Типичные ошибки и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Высокая задержка P99, но CPU прокси свободен | Protocol detection timeout / sniffing на неименнованных портах | Задать протокол явно (см. [istio-protocol-detection.md](./istio-protocol-detection.md)) |
| OOM в istio-proxy | Память растёт с числом кластеров/кардинальностью | `Sidecar` scoping; снизить кардинальность; увеличить limits осознанно |
| Прокси потребляет >1 CPU ядра | `concurrency` выше числа потоков, шаблонная выгрузка | Зафиксировать `concurrency: 2`; измерить профайл |
| istiod CPU 100% + медленные pushes | Слишком много конфигов/частая смена; один istiod | Увеличить реплики, HPA, батчить изменения |
| Высокая кардинальность: падение Prometheus | Метрики `request_protocol`/`response_flags` без принудительной чистки | Telemetry API overrides; proxyStatsMatcher |
| Задержка «через mesh» неприемлема | Причины в sidecar tax на конкретном пути | Перевести сервис на Ambient (waypoint) или сократить scoping прокси |
| Через mesh RPS хуже ожиданий | HTTP/1.1 вместо HTTP/2 между сервисами | Убедиться, что протокол портов http2/grpc; включить h2c |

---

## Лучшие практики эксплуатации

1. **Мерьте, потом тюньте**: без A/B-теста (mesh on/off) оптимизации не имеют смысла.
2. **Scoping — первый шаг**: `Sidecar` resource снижает память и задержку по всему кластеру.
3. **Фиксируйте `concurrency`** на прокси и не гоняйте ядра зря.
4. **Кардинальность — враг**: чистка labels через Telemetry API обязательна на кластерах с >10к активных серий.
5. **istiod HA**: 2+ реплики, HPA, ресурсные лимиты, мониторинг push-latency.
6. **Percentiles, не среднее**: `p50/p99/p999` для оценки overheda; среднее скрывает хвосты.
7. **Используйте Ambient для некритичных workloads** — снижение общего sidecar tax без потери безопасности.
8. **Гироскоп**: после изменения манифестов проверяйте `istioctl analyze` и `proxy-status`, следите за регрессией latency через свой SLO.

---

## Дополнительная информация

### Связь с другими темами

- Scoping и уменьшение конфигурации прокси — [istio-sidecar-configuration.md](./istio-sidecar-configuration.md).
- Снижение кардинальности и метрики — [istio_observability_and_tools.md](./istio_observability_and_tools.md).
- Дренаж и завершение прокси (влияет на простои при деплоях) — [istio-graceful-shutdown.md](./istio-graceful-shutdown.md).
- Протоколы и keepalive, влияющие на latency — [istio-protocol-detection.md](./istio-protocol-detection.md).

### См. также

- [Архитектура и компоненты Istio](./istio_architecture.md) — ресурсы istiod/ztunnel/waypoint
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md) — бенчмарки и сравнение overhead
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md) — диагностика производительности Envoy

Документация: [Istio: Performance and Scalability](https://istio.io/latest/docs/ops/deployment/performance-and-scalability/).