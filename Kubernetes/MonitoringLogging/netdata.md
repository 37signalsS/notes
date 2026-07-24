# Netdata: Мониторинг в реальном времени

## Определения

**Netdata** — высокопроизводительная система для мониторинга производительности систем и приложений в реальном времени. Ключевое отличие от Prometheus — детализация метрик до секунды, встроенное машинное обучение для обнаружения аномалий и готовые интерактивные дашборды.

**Область применения:**
- Отладка производительности в реальном времени (high-resolution).
- Анализ инцидентов и обнаружение аномалий (Anomaly Advisor).
- Мониторинг системных вызовов и сети через eBPF.

Подробно о концепциях наблюдаемости: **[Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md)**.

## Основные концепции

### Архитектура в Kubernetes (Parent-Child)
Netdata оптимизирована для работы в Kubernetes по гибридной модели:
- **Child (DaemonSet)**: Легковесные агенты на каждом узле кластера. Рекомендуется использовать режим `memory_mode = ram` для хранения данных только в оперативной памяти, что исключает нагрузку на диск рабочих узлов. Собирает метрики хоста, контейнеров и приложений.
- **Parent (Deployment)**: Центральный узел для агрегации данных. Использует `dbengine` для долгосрочного хранения сжатых данных на PersistentVolume. Поддерживает многоуровневое хранение (Tiered Storage) для архивации метрик за месяцы и годы.

### Глубокая видимость с eBPF
Netdata включает нативный коллектор eBPF, который позволяет отслеживать:
- **Сеть L4**: Пропускная способность TCP/UDP, ретрансмиссии, ошибки на уровне сокетов.
- **Процессы**: Жизненный цикл (fork/exit), использование CPU потоками, переключение контекста.
- **Файловая система**: Задержки VFS, операции ввода-вывода.
Это дает видимость происходящего внутри контейнеров без внедрения агентов (sidecars).

### Машинное обучение и аномалии
Netdata обучает модели машинного обучения (k-means) для каждой собираемой метрики непосредственно на узлах.
- **Anomaly Advisor**: Автоматически подсвечивает метрики, поведение которых отклоняется от нормы, помогая коррелировать события во время инцидентов.
- **Нулевая настройка**: ML-модели не требуют ручной настройки порогов и адаптируются к нагрузке кластера в течение 24–48 часов.

### Преимущества и недостатки
- **Преимущества**: Посекундное разрешение, автоматическое обнаружение сотен сервисов, eBPF из коробки, низкое потребление ресурсов.
- **Недостатки**: Ограниченная кастомизация дашбордов (в сравнении с Grafana), сложность настройки алертов по сложным составным условиям.

## Практические сценарии

### Установка через Helm
Рекомендуется использовать официальный чарт с настройкой Parent-Child.

**Шаг 1: Подготовка репозитория**
```bash
helm repo add netdata https://netdata.github.io/helmchart/
# → "netdata" has been added to your repositories
helm repo update
# → ...Successfully got an update from the "netdata" chart repository
```

**Шаг 2: Настройка и установка**
Создайте `values.yaml` для оптимизации хранения и включения eBPF:
```yaml
parent:
  database:
    storageClass: "managed-nfs-storage"
    volumesize: 10Gi
  config:
    dbengine:
      tier0_expansion: 1
      tier1_expansion: 10

child:
  config:
    health:
      enabled: false # Отключаем алерты на child, оставляем на parent
    memory_mode: ram
  ebpf:
    enabled: true

ingress:
  enabled: false
```

Установка релиза:
```bash
helm install netdata netdata/netdata \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml
# → NAME: netdata
# → NAMESPACE: monitoring
# → STATUS: deployed
# → REVISION: 1
```

### Доступ через Ingress
Для безопасного доступа к интерфейсу родительского узла:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    cert-manager.io/issuer: "kubernetes-ca-issuer"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - netdata.k8s.local
    secretName: netdata-tls-certs
  rules:
  - host: netdata.k8s.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: netdata
            port:
              name: http
```
Настройка сертификатов: **[CA кластера](../ToolsUtilities/cert_manager/cluster_ca.md)**.

## Дополнительная информация

### Интеграция с OpenTelemetry
Netdata может выступать в роли бэкенда для OpenTelemetry, принимая данные по протоколу OTLP (gRPC/HTTP). Это позволяет визуализировать метрики приложений, собранные через OpenTelemetry SDK, с использованием аналитики Netdata.

### Смежные темы
- **[Monitoring and Logging Architecture](./kubernetes-monitoring-logging-architecture.md)** — архитектура мониторинга в Kubernetes.
- **[Metrics Collection Strategies](../../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md)** — стратегии сбора телеметрии.
- **[Prometheus Installation](../../../Prometheus/installation/prometheus_server_installation.md)** — долгосрочное хранение и сложные алерты.
