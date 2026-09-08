# Netdata: Мониторинг в реальном времени

## Определения

**Netdata** — высокопроизводительная система для мониторинга производительности систем и приложений в реальном времени с посекундным разрешением. Ключевое отличие от Prometheus — детализация метрик до секунды, встроенное машинное обучение для обнаружения аномалий и готовые интерактивные дашборды без необходимости конфигурации.

**Child (DaemonSet)** — легковесный агент Netdata, развертываемый на каждом узле кластера Kubernetes. Собирает метрики хоста, контейнеров и приложений, передает данные родительскому узлу (Parent). В режиме `memory_mode = ram` хранит данные только в оперативной памяти, исключая нагрузку на диск рабочих узлов.

**Parent (Deployment)** — центральный узел Netdata для агрегации данных от всех Child-агентов. Использует базу данных dbengine для долгосрочного хранения сжатых данных на PersistentVolume. Поддерживает многоуровневое хранение (Tiered Storage) для архивации метрик за месяцы и годы.

**dbengine** — движок хранения временных рядов Netdata, разработанный специально для высокопроизводительной работы с метриками. Использует сжатие данных (LZ4/ZSTD) и автоматическую агрегацию по времени (downsampling), что позволяет хранить месяцы и годы данных на относительно небольших дисках.

**eBPF (Extended Berkeley Packet Filter)** — технология ядра Linux, позволяющая безопасно выполнять пользовательский код в пространстве ядра. Netdata использует eBPF для глубокого мониторинга сети (TCP/UDP), процессов и файловой системы без внедрения агентов в контейнеры.

**Anomaly Advisor** — встроенный инструмент Netdata для обнаружения аномалий, основанный на машинном обучении (k-means). Автоматически подсвечивает метрики, поведение которых отклоняется от нормы, помогая коррелировать события во время инцидентов.

**War Rooms** — виртуальные пространства в Netdata Cloud для организации мониторинга по командам, сервисам или инфраструктуре. Объединяют разрозненные инсталляции Netdata в единое управляемое пространство.

**Netdata Cloud** — SaaS-платформа для централизованного управления, визуализации и коллаборации, которая связывает разрозненные инсталляции (Parent-узлы) в единое пространство (War Rooms) без необходимости пробрасывать порты наружу.

**Область применения:**
- Отладка производительности в реальном времени (high-resolution) с посекундным разрешением.
- Анализ инцидентов и обнаружение аномалий (Anomaly Advisor).
- Мониторинг системных вызовов и сети через eBPF.
- Централизованный мониторинг распределенной инфраструктуры через Parent-Child архитектуру.
- Долгосрочное хранение метрик с агрегацией по времени (Tiered Storage).

Подробно о концепциях наблюдаемости: **[Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md)**.

## Основные концепции

### Архитектура в Kubernetes (Parent-Child)

Netdata оптимизирована для работы в Kubernetes по гибридной модели:

#### Child (DaemonSet)

Легковесные агенты на каждом узле кластера. Рекомендуется использовать режим `memory_mode = ram` для хранения данных только в оперативной памяти, что исключает нагрузку на диск рабочих узлов. Собирает метрики хоста, контейнеров и приложений.

**Преимущества Child-агентов:**
- Минимальное потребление ресурсов (50–100Mi RAM)
- Автоматическое обнаружение сервисов и контейнеров
- Работа без特权жных прав (non-root)
- Сбор метрик через eBPF без sidecar-контейнеров

**Собираемые метрики Child:**
| Категория | Примеры метрик | Источник |
|:---|:---|:---|
| **Система** | CPU, память, диск, сеть | /proc, /sys |
| **Контейнеры** | CPU, память, сеть, I/O | cAdvisor, runtime |
| **Процессы** | CPU, память, потоки | /proc, eBPF |
| **Сеть** | TCP/UDP, соединения, ошибки | eBPF, /proc/net |
| **Файловая система** | Задержки VFS, I/O операции | eBPF |

#### Parent (Deployment)

Центральный узел для агрегации данных. Использует базу данных dbengine для долгосрочного хранения сжатых данных на PersistentVolume. Поддерживает многоуровневое хранение (Tiered Storage) для архивации метрик за месяцы и годы на небольших дисках за счет агрегации исторических данных.

**Функции Parent:**
- Агрегация данных от множества Child-агентов
- Долгосрочное хранение и агрегация по времени (downsampling)
- Обработка алертов и уведомлений
- Предоставление API для интеграций
- Централизованное управление конфигурацией

#### Схема взаимодействия

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Node 1   │  │  Node 2   │  │  Node 3   │  │  Node N   │  │
│  │  Child    │  │  Child    │  │  Child    │  │  Child    │  │
│  │  DaemonSet│  │  DaemonSet│  │  DaemonSet│  │  DaemonSet│  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │              │         │
│       └──────────────┴──────────────┴──────────────┘         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  Parent        │                         │
│                   │  Deployment    │                         │
│                   │  (dbengine)    │                         │
│                   └────────┬───────┘                         │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                             ▼
                   ┌────────────────┐
                   │  Netdata Cloud │
                   │  (War Rooms)   │
                   └────────────────┘
```

### Движок dbengine: модель хранения

dbengine — это оптимизированный движок для хранения временных рядов, разработанный Netdata. Он использует несколько уровней сжатия и агрегации:

**Уровни хранения (Tiered Storage):**
| Уровень | Период | Разрешение | Потребление места |
|:---|:---|:---|:---|
| **Tier 0** | Последние 1–7 дней | 1 секунда | Высокое |
| **Tier 1** | Последние 1–4 недели | 1 минута | Среднее |
| **Tier 2** | Последние 1–6 месяцев | 1 час | Низкое |
| **Tier 3** | Более 6 месяцев | 1 день | Минимальное |

**Принцип работы:**
1. Данные поступают от Child с посекундным разрешением (Tier 0)
2. Раз в час dbengine выполняет downsampling: агрегирует данные по минутам (Tier 1), часам (Tier 2) и дням (Tier 3)
3. Старые данные автоматически удаляются при заполнении диска
4. Сжатие LZ4/ZSTD позволяет хранить до 10x больше данных на том же диске

**Рекомендации по размеру диска:**
| Объем метрик | Размер Tier 0 (7 дней) | Размер Tier 1 (4 недели) | Итого |
|:---|:---|:---|:---|
| 10K метрик | ~1 GB | ~2 GB | ~3 GB |
| 100K метрик | ~10 GB | ~20 GB | ~30 GB |
| 1M метрик | ~100 GB | ~200 GB | ~300 GB |

### Глубокая видимость с eBPF

Netdata включает нативный коллектор eBPF, который позволяет отслеживать:

- **Сеть L4**: Пропускная способность TCP/UDP, ретрансмиссии, ошибки на уровне сокетов.
- **Процессы**: Жизненный цикл (fork/exit), использование CPU потоками, переключение контекста.
- **Файловая система**: Задержки VFS, операции ввода-вывода.

Это дает видимость происходящего внутри контейнеров без внедрения агентов (sidecars).

**Требования к eBPF:**
- Ядро Linux версии 4.14+ (рекомендуется 5.4+)
- Смонтированный `debugfs` (обычно автоматически)
- Поддержка BTF (BPF Type Format) для работы без перекомпиляции ядра
- Права `CAP_SYS_ADMIN` или разрешение `CAP_BPF`

**Проверка поддержки eBPF:**
```bash
# Проверка версии ядра
uname -r
# → 5.4.0-100-generic (или выше)

# Проверка наличия debugfs
mount | grep debugfs
# → debugfs on /sys/kernel/debug type debugfs (rw,nosuid,nodev,noexec,relatime)

# Проверка BTF (опционально, но рекомендуется)
ls -la /sys/kernel/btf/vmlinux
# → Если файл существует, BTF поддерживается
```

### Машинное обучение и аномалии

Netdata обучает модели машинного обучения (k-means) для каждой собираемой метрики непосредственно на узлах.

**Принцип работы ML в Netdata:**
1. **Сбор данных**: Netdata собирает посекундные значения метрик в течение 24–48 часов
2. **Обучение модели**: Для каждой метрики строится профиль нормального поведения (k-means кластеризация)
3. **Детекция отклонений**: Значения, не попадающие в кластер "нормы", помечаются как аномалии
4. **Визуализация**: Anomaly Advisor показывает аномальные метрики с указанием степени отклонения

**Преимущества ML-подхода:**
- Нулевая настройка — модели адаптируются к нагрузке автоматически
- Детекция медленных деградаций (drift), не ловимых статическими порогами
- Работа на edge-узлах без централизованного обучения

**Ограничения:**
- Начальный период обучения: 24–48 часов до формирования профиля
- Не работает для метрик с непредсказуемыми паттернами (например, разовые нагрузки)
- Требует достаточно данных для обучения (минимум 2000 точек)

### Безопасность и управление доступом

Netdata **не имеет встроенной системы аутентификации** в открытом исходном коде. Доступ к дашбордам полностью открыт по умолчанию.

**Методы защиты:**

1. **Netdata Cloud**: Локальный UI отключается, доступ осуществляется через SaaS с ролевой моделью (RBAC) и SSO.
   - Поддержка SAML, OIDC, OAuth2
   - Audit logs для отслеживания действий
   - Шифрование данных в покое и при передаче

2. **Reverse Proxy**: Использование Ingress-контроллера с Basic Auth, OAuth2-Proxy или OIDC для защиты локального Parent-узла.
   - TLS termination на Ingress
   - Rate limiting для защиты от DoS
   - IP-based access control

3. **Network Policies**: Ограничение доступа к портам Netdata на уровне сети.
   - Порт 19999: Web UI
   - Порт 20000: Streaming (Child → Parent)
   - Порт 8125: StatsD

**Пример Network Policy:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: netdata-policy
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: netdata
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 19999
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 443
```

### Экспорт метрик (Netdata как Exporter)

Netdata может выступать как "умный" exporter для Prometheus или VictoriaMetrics. Вместо использования классического Node Exporter, Netdata предоставляет эндпоинт `/api/v1/allmetrics?format=prometheus`, позволяя совмещать редкий скрейпинг Prometheus (например, раз в минуту) с секундным мониторингом в дашбордах самой Netdata.

**Преимущества использования Netdata как Exporter:**
- Посекундное разрешение метрик (vs 15 секунд у Node Exporter)
- Автоматическое обнаружение сервисов
- Встроенные алерты и аномалии
- Меньшее потребление ресурсов

**Пример конфигурации Prometheus:**
```yaml
scrape_configs:
  - job_name: 'netdata'
    scrape_interval: 60s
    honor_labels: yes
    static_configs:
      - targets: ['netdata-parent.monitoring:19999']
    metrics_path: '/api/v1/allmetrics?format=prometheus&prefix=netdata'
```

### Преимущества и недостатки

**Преимущества:**
- Посекундное разрешение метрик
- Автоматическое обнаружение сотен сервисов
- eBPF из коробки без дополнительных агентов
- Низкое потребление ресурсов (при правильной настройке limits)
- Встроенное машинное обучение для обнаружения аномалий
- Готовые дашборды без конфигурации
- Поддержка 800+ интеграций

**Недостатки:**
- Отсутствие встроенной аутентификации в OSS-версии
- Ограниченная кастомизация дашбордов (в сравнении с Grafana)
- Сложность настройки алертов по сложным составным условиям
- Зависимость от версии ядра Linux для eBPF
- Высокое потребление CPU при большом количестве метрик

## Практические сценарии

### Установка через Helm (с Netdata Cloud и лимитами)

Рекомендуется использовать официальный чарт с настройкой Parent-Child, установленными лимитами ресурсов (чтобы избежать вытеснения других подов) и интеграцией с Netdata Cloud.

#### Предварительные требования

- Kubernetes кластер версии 1.20+
- Helm 3.x установлен
- Доступ к кластеру через kubectl
- NFS сервер для хранения данных Parent (опционально)
- Аккаунт в Netdata Cloud (для cloud-интеграции)

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

**Параметры конфигурации:**
| Параметр | Описание | Рекомендуемое значение |
|:---|:---|:---|
| `dbengine.page_cache_size` | Размер кэша в страницах (4KB каждая) | 512–2048 |
| `dbengine_multihost_disk_space` | Максимальный размер диска в MB | 10240–51200 |
| `memory_mode` | Режим хранения данных Child | `ram` для рабочих узлов |
| `ebpf.enabled` | Включение eBPF-коллектора | `true` |

**Шаг 3: Установка релиза**
```bash
helm install netdata netdata/netdata \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml
# → NAME: netdata
# → STATUS: deployed
```

**Шаг 4: Валидация установки**
```bash
# Проверка статуса подов
kubectl get pods -n monitoring
# → NAME                        READY   STATUS    RESTARTS   AGE
# → netdata-parent-0             1/1     Running   0          2m
# → netdata-child-xxxxx          1/1     Running   0          2m

# Проверка логов Parent
kubectl logs -n monitoring netdata-parent-0 --tail=20
# → 2026-09-02 10:00:00: netdata: INFO: Netdata started
# → 2026-09-02 10:00:01: netdata: INFO: Listening on *:19999

# Проверка доступности API
kubectl port-forward -n monitoring svc/netdata 19999:19999 &
curl http://localhost:19999/api/v1/info
# → {"version":"v1.47.5","os":"linux","timezone":"UTC"}
```

### Настройка eBPF-коллектора

Для работы eBPF необходимы определенные разрешения ядра и конфигурация.

**Включение eBPF в Child:**
```yaml
child:
  ebpf:
    enabled: true
    # Опционально: ограничение собираемых метрик
    apps:
      enabled: true
    processes:
      enabled: true
    network:
      enabled: true
```

**Проверка работы eBPF:**
```bash
# Проверка загруженных BPF-программ
kubectl exec -n monitoring <child-pod> -- bpftool prog list | grep netdata
# → 42: tracing  name netdata_tcp_retransmits  ...

# Проверка метрик eBPF в Netdata
curl "http://localhost:19999/api/v1/allmetrics?format=json" | jq '.[] | select(.dimension | contains("tcp_retransmits"))'
```

**Траблшутинг eBPF:**
| Проблема | Причина | Решение |
|:---|:---|:---|
| `permission denied` | Недостаточно прав | Добавьте `CAP_SYS_ADMIN` в SecurityContext |
| `no such file` | Отсутствует debugfs | Смонтируйте: `mount -t debugfs none /sys/kernel/debug` |
| `not supported` | Ядро не поддерживает eBPF | Обновите ядро до версии 4.14+ |
| `failed to load` | Конфликт BPF-программ | Отключите конфликтующие коллекторы |

### Настройка алертинга (Уведомления)

Netdata Parent использует конфигурационные файлы для отправки уведомлений. В Kubernetes настройки пробрасываются через Helm `values.yaml` (блок `alarms`):

**Telegram уведомления:**
```yaml
parent:
  alarms:
    health_alarm_notify: |
      SEND_TELEGRAM="YES"
      TELEGRAM_BOT_TOKEN="123456789:ABCdefGHI"
      TELEGRAM_CHAT_ID="-1001234567890"
```

**Email уведомления:**
```yaml
parent:
  alarms:
    health_alarm_notify: |
      SEND_EMAIL="YES"
      DEFAULT_RECIPIENT_EMAIL="ops@example.com"
      SEND_POSTHOG="NO"
```

**Slack уведомления:**
```yaml
parent:
  alarms:
    health_alarm_notify: |
      SEND_SLACK="YES"
      SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
```

**Кастомные алерты:**
Создайте файл `health.d/custom.conf` в ConfigMap для собственных правил алертов:
```yaml
parent:
  custom:
    health.d: |
      # Алерт на высокое использование памяти
      alarm: high_memory_usage
        on: system.ram
      lookup: average -1m percentage of used
         calc: $used * 100 / ($used + $cached + $free)
        units: %
        every: 10s
         warn: $this > 80
         crit: $this > 95
        delay: down 15m multiplier 1.5
         info: Высокое использование памяти
        to: sysadmin
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

**Создание секрета для Basic Auth:**
```bash
# Установка htpasswd (если не установлен)
apt-get install apache2-utils

# Создание файла паролей
htpasswd -c auth admin
# → Enter password: ********
# → Re-type new password: ********

# Создание секрета в Kubernetes
kubectl create secret generic netdata-basic-auth \
  --from-file=auth \
  -n monitoring
```

Настройка сертификатов: **[CA кластера](../ToolsUtilities/cert_manager/cluster_ca.md)**.

### Интеграция с Prometheus

Netdata может выступать как источник метрик для Prometheus, предоставляя посекундные данные:

**Конфигурация Prometheus:**
```yaml
scrape_configs:
  - job_name: 'netdata'
    scrape_interval: 60s
    honor_labels: yes
    static_configs:
      - targets: ['netdata-parent.monitoring:19999']
    metrics_path: '/api/v1/allmetrics?format=prometheus&prefix=netdata'
```

**Примеры метрик Netdata в Prometheus:**
```
netdata_system_cpu_percentage_average
netdata_system_ram_used_bytes
netdata_system_disk_read_kilobytes_per_sec
netdata_system_network_receive_kilobits_per_sec
```

### Диагностика (Troubleshooting)

Полезные команды для проверки состояния Netdata:
```bash
# Проверка логов родительского узла (ошибки базы данных dbengine или eBPF)
kubectl logs -n monitoring -l app=netdata,component=parent --tail=100

# Статус claim в Netdata Cloud изнутри пода (проверка связи с SaaS):
kubectl exec -it -n monitoring deploy/netdata-parent -- netdatacli claim-status

# Принудительная перезагрузка health-чеков (алертов) без перезапуска пода:
kubectl exec -it -n monitoring deploy/netdata-parent -- netdatacli reload-health

# Проверка использования диска dbengine
kubectl exec -it -n monitoring netdata-parent-0 -- du -sh /var/lib/netdata/dbengine/

# Проверка статуса eBPF
kubectl exec -it -n monitoring <child-pod> -- ls /sys/kernel/debug/tracing/

# Просмотр текущих алертов
kubectl exec -it -n monitoring netdata-parent-0 -- netdatacli aclk-alerts

# Проверка конфигурации
kubectl exec -it -n monitoring netdata-parent-0 -- netdatacli show-config
```

**Типичные ошибки и их решения:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Cannot connect to parent` | Child не может подключиться к Parent | Проверьте NetworkPolicy и DNS |
| `Database is corrupt` | Повреждение dbengine | Удалите `/var/lib/netdata/dbengine/` и перезапустите |
| `eBPF not working` | Недостаточно прав или ядро не поддерживает | Проверьте SecurityContext и версию ядра |
| `Claim failed` | Ошибка авторизации в Netdata Cloud | Проверьте токен и сетевую доступность |
| `High memory usage` | Child потребляет слишком много RAM | Увеличьте limits или уменьшите количество метрик |

## Дополнительная информация

### Оптимизация производительности

**Рекомендации по ресурсам:**

| Компонент | CPU Request | CPU Limit | Memory Request | Memory Limit |
|:---|:---|:---|:---|:---|
| Child (DaemonSet) | 100m | 500m | 256Mi | 512Mi |
| Parent (Deployment) | 500m | 2000m | 1Gi | 4Gi |

**Оптимизация dbengine:**
```yaml
parent:
  config:
    dbengine:
      # Размер кэша в страницах (4KB каждая)
      page_cache_size: 1024
      # Максимальный размер диска для Tier 0 (MB)
      dbengine_multihost_disk_space: 20480
      # Количество страниц для хранения в памяти
      dbengine_pages_per_extent: 128
```

**Снижение потребления памяти Child:**
```yaml
child:
  config:
    memory_mode: ram
    # Ограничение количества собираемых метрик
    apps_groups:
      enabled: true
    # Отключение неиспользуемых коллекторов
    diskstats:
      enabled: false
    # Уменьшение интервала сбора
    update_every: 5
```

### Требования к сети

**Порты Netdata:**
| Порт | Протокол | Назначение |
|:---|:---|:---|
| 19999 | TCP | Web UI и API |
| 20000 | TCP | Streaming (Child → Parent) |
| 8125 | UDP/TCP | StatsD |
| 19999 | TCP | Health checks |

**Рекомендации по полосе пропускания:**
- Child → Parent: 10–100 Kbps на агент (зависит от количества метрик)
- Parent → Internet: 100–500 Kbps для Netdata Cloud
- Рекомендуется выделить отдельный VLAN для мониторинга

### Резервное копирование и восстановление

**Бэкап конфигурации Parent:**
```bash
# Экспорт конфигурации
kubectl exec -n monitoring netdata-parent-0 -- cat /etc/netdata/netdata.conf > netdata-backup.conf

# Бэкап базы данных dbengine
kubectl cp monitoring/netdata-parent-0:/var/lib/netdata/dbengine/ ./dbengine-backup/
```

**Восстановление после сбоя:**
1. Удалите поврежденную базу данных: `rm -rf /var/lib/netdata/dbengine/*`
2. Перезапустите Parent: `kubectl rollout restart statefulset netdata-parent -n monitoring`
3. Дождитесь переобучения ML-моделей (24–48 часов)

### Высокая доступность (HA) для Parent

Для обеспечения отказоустойчивости Parent:

**Режим 1: ReplicaSet с общим хранилищем**
```yaml
parent:
  replicas: 2
  database:
    storageClass: "nfs-client"
    volumesize: 20Gi
```

**Режим 2: Кластер с внешним балансировщиком**
- Используйте StatefulSet с отдельными PersistentVolume для каждого реплики
- Настройте DNS round-robin или внешний балансировщик
- Child-агенты подключаются к ближайшему Parent

### Масштабирование

**Пороговые значения для масштабирования:**

| Метрика | Порог | Действие |
|:---|:---|:---|
| CPU Parent | >70%持续 5 минут | Увеличьте ресурсы или добавьте реплики |
| Memory Parent | >80% | Увеличьте limits.memory |
| Disk dbengine | >80% | Расширьте PV или уменьшите retention |
| Child count | >100 | Рассмотрите additional Parent |
| Network latency | >100ms между Child и Parent | Рассмотрите regional Parent |

**Рекомендации по масштабированию:**
- До 50 Child: 1 Parent (2 CPU, 4GB RAM)
- 50–200 Child: 2 Parent (4 CPU, 8GB RAM каждый)
- Более 200 Child: кластер Parent с внешним балансировщиком

### Интерфейсы управления

**CLI-команды netdatacli:**
```bash
# Статус агента
netdatacli show-status

# Перезагрузка конфигурации
netdatacli reload-config

# Перезагрузка health-чеков
netdatacli reload-health

# Статус claim
netdatacli claim-status

# Просмотр текущих алертов
netdatacli aclk-alerts

# Принудительная отправка алертов
netdatacli send-alarm "test_alarm" "critical"
```

**API-эндпоинты:**
```bash
# Информация о системе
curl http://localhost:19999/api/v1/info

# Все метрики в JSON
curl http://localhost:19999/api/v1/allmetrics?format=json

# Метрики в формате Prometheus
curl http://localhost:19999/api/v1/allmetrics?format=prometheus

# Список алертов
curl http://localhost:19999/api/v1/alarms

# Конкретная метрика
curl http://localhost:19999/api/v1/data?chart=system.cpu
```

### Устранение неполадок

**Диагностические команды:**
```bash
# Проверка состояния Netdata
kubectl get pods -n monitoring -l app=netdata
kubectl describe pod -n monitoring <pod-name>

# Проверка логов
kubectl logs -n monitoring <pod-name> --tail=100 --previous

# Проверка использования ресурсов
kubectl top pods -n monitoring

# Проверка сетевой доступности
kubectl exec -it -n monitoring <pod-name> -- curl -s http://localhost:19999/api/v1/info

# Проверка дискового пространства
kubectl exec -it -n monitoring netdata-parent-0 -- df -h /var/lib/netdata/dbengine/
```

**Частые проблемы и решения:**

| Симптом | Вероятная причина | Решение |
|:---|:---|:---|
| Child не подключается к Parent | NetworkPolicy блокирует порт 20000 | Добавьте правила для порта 20000 |
| Метрики отсутствуют в Parent | Неправильная конфигурация streaming | Проверьте `stream.conf` на Child и Parent |
| Высокое потребление CPU | Слишком много метрик | Уменьшите `update_every` или отключите коллекторы |
| Дашборды пустые | Проблемы с базой данных | Проверьте права доступа к `/var/lib/netdata/dbengine/` |
| Алерты не отправляются | Ошибка в конфигурации notifications | Проверьте `health_alarm_notify.conf` |

### Интеграция с OpenTelemetry

Netdata может выступать в роли бэкенда для OpenTelemetry, принимая данные по протоколу OTLP (gRPC/HTTP). Это позволяет визуализировать метрики приложений, собранные через OpenTelemetry SDK, с использованием аналитики Netdata.

**Пример конфигурации OTLP Receiver:**
```yaml
parent:
  config:
    otlp:
      enabled: true
      listen_port: 4317  # gRPC
      listen_port: 4318  # HTTP
```

### Смежные темы

- **[Monitoring and Logging Architecture](./kubernetes-monitoring-logging-architecture.md)** — архитектура мониторинга в Kubernetes.
- **[Metrics Collection Strategies](../../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md)** — стратегии сбора телеметрии.
- **[Prometheus Installation](../../Prometheus/installation/prometheus_server_installation.md)** — долгосрочное хранение и сложные алерты.