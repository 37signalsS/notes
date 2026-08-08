# Netdata: Мониторинг в реальном времени

## Определения

**Netdata** — высокопроизводительная система для мониторинга производительности систем и приложений в реальном времени. Ключевое отличие от Prometheus — детализация метрик до секунды, встроенное машинное обучение для обнаружения аномалий и готовые интерактивные дашборды.

**Netdata Cloud** — SaaS-платформа для централизованного управления, визуализации и коллаборации, которая связывает разрозненные инсталляции (Parent-узлы) в единое пространство (War Rooms) без необходимости пробрасывать порты наружу.

**Область применения:**
- Отладка производительности в реальном времени (high-resolution).
- Анализ инцидентов и обнаружение аномалий (Anomaly Advisor).
- Мониторинг системных вызовов и сети через eBPF.

Подробно о концепциях наблюдаемости: **[Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md)**.

## Основные концепции

### Архитектура в Kubernetes (Parent-Child)
Netdata оптимизирована для работы в Kubernetes по гибридной модели:
- **Child (DaemonSet)**: Легковесные агенты на каждом узле кластера. Рекомендуется использовать режим `memory_mode = ram` для хранения данных только в оперативной памяти, что исключает нагрузку на диск рабочих узлов. Собирает метрики хоста, контейнеров и приложений.
- **Parent (Deployment)**: Центральный узел для агрегации данных. Использует базу данных `dbengine` для долгосрочного хранения сжатых данных на PersistentVolume. Поддерживает многоуровневое хранение (Tiered Storage) для архивации метрик за месяцы и годы на небольших дисках за счет агрегации исторических данных.

### Глубокая видимость с eBPF
Netdata включает нативный коллектор eBPF, который позволяет отслеживать:
- **Сеть L4**: Пропускная способность TCP/UDP, ретрансмиссии, ошибки на уровне сокетов.
- **Процессы**: Жизненный цикл (fork/exit), использование CPU потоками, переключение контекста.
- **Файловая система**: Задержки VFS, операции ввода-вывода.
Это дает видимость происходящего внутри контейнеров без внедрения агентов (sidecars). 
**Требования:** Для работы eBPF-коллектора ядра Kubernetes-узлов должны поддерживать eBPF, а также требовать смонтированного `debugfs` (обычно монтируется автоматически в современных дистрибутивах).

### Машинное обучение и аномалии
Netdata обучает модели машинного обучения (k-means) для каждой собираемой метрики непосредственно на узлах.
- **Anomaly Advisor**: Автоматически подсвечивает метрики, поведение которых отклоняется от нормы, помогая коррелировать события во время инцидентов.
- **Нулевая настройка**: ML-модели не требуют ручной настройки порогов и адаптируются к нагрузке кластера в течение 24–48 часов.

### Безопасность и управление доступом
Netdata **не имеет встроенной системы аутентификации** в открытом исходном коде. Доступ к дашбордам полностью открыт по умолчанию. Для защиты применяются:
1. **Netdata Cloud:** Локальный UI отключается, доступ осуществляется через SaaS с ролевой моделью (RBAC) и SSO.
2. **Reverse Proxy:** Использование Ingress-контроллера с Basic Auth, OAuth2-Proxy или OIDC для защиты локального Parent-узла.

### Экспорт метрик (Netdata как Exporter)
Netdata может выступать как "умный" exporter для Prometheus или VictoriaMetrics. Вместо использования классического Node Exporter, Netdata предоставляет эндпоинт `/api/v1/allmetrics?format=prometheus`, позволяя совмещать редкий скрейпинг Prometheus (например, раз в минуту) с секундным мониторингом в дашбордах самой Netdata.

### Преимущества и недостатки
- **Преимущества**: Посекундное разрешение, автоматическое обнаружение сотен сервисов, eBPF из коробки, низкое потребление ресурсов (при правильной настройке limits).
- **Недостатки**: Отсутствие встроенной аутентификации в OSS-версии, ограниченная кастомизация дашбордов (в сравнении с Grafana), сложность настройки алертов по сложным составным условиям.

## Практические сценарии

### Установка через Helm (с Netdata Cloud и лимитами)
Рекомендуется использовать официальный чарт с настройкой Parent-Child, установленными лимитами ресурсов (чтобы избежать вытеснения других подов) и интеграцией с Netdata Cloud.

**Шаг 1: Подготовка репозитория**
```bash
helm repo add netdata https://netdata.github.io/helmchart/
# → "netdata" has been added to your repositories
helm repo update
# → ...Successfully got an update from the "netdata" chart repository
```

**Шаг 2: Настройка и установка**
Создайте `values.yaml` для оптимизации хранения, eBPF и Cloud:
```yaml
parent:
  database:
    storageClass: "managed-nfs-storage"
    volumesize: 20Gi
  config:
    dbengine:
      page_cache_size: 512
      dbengine_multihost_disk_space: 10240 # 10GB для Tier 0
  claim:
    enabled: true
    token: "YOUR_CLAIM_TOKEN"
    rooms: "YOUR_ROOM_ID"

child:
  config:
    health:
      enabled: false # Отключаем алерты на child, оставляем на parent
    memory_mode: ram
  ebpf:
    enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi # Важно для ограничения потребления RAM агентом
  claim:
    enabled: true
    token: "YOUR_CLAIM_TOKEN"
    rooms: "YOUR_ROOM_ID"

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
# → STATUS: deployed
```

### Настройка алертинга (Уведомления)
Netdata Parent использует конфигурационные файлы для отправки уведомлений. В Kubernetes настройки пробрасываются через Helm `values.yaml` (блок `alarms`):
```yaml
parent:
  alarms:
    health_alarm_notify: |
      SEND_TELEGRAM="YES"
      TELEGRAM_BOT_TOKEN="123456789:ABCdefGHI"
      TELEGRAM_CHAT_ID="-1001234567890"
```

### Доступ через Ingress с аутентификацией
Для безопасного доступа к локальному интерфейсу родительского узла (с использованием Basic Auth через Nginx):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    cert-manager.io/issuer: "kubernetes-ca-issuer"
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: netdata-basic-auth # Секрет с htpasswd
    nginx.ingress.kubernetes.io/auth-realm: "Authentication Required"
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

### Диагностика (Troubleshooting)
Полезные команды для проверки состояния Netdata:
```bash
# Проверка логов родительского узла (ошибки базы данных dbengine или eBPF)
kubectl logs -n monitoring -l app=netdata,component=parent --tail=100

# Статус claim в Netdata Cloud изнутри пода (проверка связи с SaaS):
kubectl exec -it -n monitoring deploy/netdata-parent -- netdatacli claim-status

# Принудительная перезагрузка health-чеков (алертов) без перезапуска пода:
kubectl exec -it -n monitoring deploy/netdata-parent -- netdatacli reload-health
```

## Дополнительная информация

### Интеграция с OpenTelemetry
Netdata может выступать в роли бэкенда для OpenTelemetry, принимая данные по протоколу OTLP (gRPC/HTTP). Это позволяет визуализировать метрики приложений, собранные через OpenTelemetry SDK, с использованием аналитики Netdata.

### Смежные темы
- **[Monitoring and Logging Architecture](./kubernetes-monitoring-logging-architecture.md)** — архитектура мониторинга в Kubernetes.
- **[Metrics Collection Strategies](../../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md)** — стратегии сбора телеметрии.
- **[Prometheus Installation](../../Prometheus/installation/prometheus_server_installation.md)** — долгосрочное хранение и сложные алерты.