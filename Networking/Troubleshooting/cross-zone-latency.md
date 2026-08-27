# Межзонный трафик и сетевые задержки (Cross-zone Latency)

## Определения

**Межзонный трафик (Cross-zone traffic)** — передача данных между ресурсами (серверами, контейнерами, базами данных), расположенными в разных зонах доступности (Availability Zones, AZ) одного региона облачного провайдера. 

**Задержка между зонами (Cross-zone latency)** — дополнительное время, затрачиваемое на прохождение пакетов через сетевую инфраструктуру, соединяющую AZ. 
- **Типичные значения:** 1.0 – 2.5 мс.
- **Внутризонные задержки (Intra-zone):** 0.2 – 0.5 мс.
- **Влияние:** Межзонная задержка в 5–10 раз выше внутризонной, что критично для высоконагруженных систем с большим количеством микросервисных взаимодействий.

**Стоимость межзонного трафика (Egress Cost)** — облачные провайдеры (AWS, GCP, Azure, Yandex Cloud) обычно взимают плату за трафик между зонами (Data Transfer Out / Egress), в то время как трафик внутри одной зоны часто бесплатен или значительно дешевле. Оптимизация задержек напрямую связана с сокращением расходов (FinOps).

## Предварительные требования

### Необходимые инструменты

Для диагностики межзонных задержек требуются следующие утилиты:

| Инструмент | Назначение | Установка (Debian/Ubuntu) | Установка (RHEL/CentOS) |
| :--- | :--- | :--- | :--- |
| `mtr` | Трассировка маршрута с RTT | `sudo apt install mtr-tiny` | `sudo dnf install mtr` |
| `ss` | Просмотр активных соединений | Встроен в ядро | Встроен в ядро |
| `nstat` | Счётчики TCP | Входит в `iproute2` | Входит в `iproute2` |
| `tcpdump` | Захват пакетов | `sudo apt install tcpdump` | `sudo dnf install tcpdump` |
| `kubectl` | Управление K8s | [Официальная инструкция](https://kubernetes.io/docs/tasks/tools/) | Аналогично |
| `iperf3` | Тест пропускной способности | `sudo apt install iperf3` | `sudo dnf install iperf3` |

### Требования к среде

- Доступ к кластеру Kubernetes с правами `kubectl describe`, `kubectl exec`, `kubectl logs`.
- Доступ к облачной консоли (AWS Console / GCP Console / Azure Portal) для просмотра метрик сети.
- Минимум 2 пода в разных зонах доступности для тестирования cross-zone трафика.
- Если используется Service Mesh (Istio/Linkerd) — доступ к Dashboard или CLI меша.

### Права доступа

| Операция | Минимальные права |
| :--- | :--- |
| Диагностика соединений (`ss`, `mtr`, `nstat`) | Root или `CAP_NET_ADMIN` + `CAP_NET_RAW` |
| Захват пакетов (`tcpdump`) | Root или `CAP_NET_RAW` |
| `kubectl` (описание подов, сервисов) | RBAC: `get`, `list`, `describe` на `pods`, `services`, `endpointslices` |
| `kubectl exec` (внутри пода) | RBAC: `create` на `pods/exec` |
| Изменение Service (включение Topology Aware Routing) | RBAC: `update` на `services` |

## Базовые концепции и причины возникновения

Проблема часто проявляется не как полная недоступность, а как деградация производительности («медленный бэкенд»), особенно после масштабирования или изменения топологии приложения.

### Основные сценарии:
1.  **Несбалансированное масштабирование:** Backend поднялся в AZ-B, а клиент (frontend или другой микросервис) остался в AZ-A и продолжает ходить через балансировщик, который перенаправляет трафик в другую зону.
2.  **Цепочка вызовов (Multi-hop):** 
    - Frontend (AZ-A) → API Gateway (AZ-B) → Backend (AZ-A) → Database (AZ-B).
    - Каждый переход между зонами добавляет задержку. Один пользовательский запрос может превратиться в 5–20 мс чистого сетевого оверхеда.
3.  **Влияние на P95/P99:** Даже небольшая разница в 1–2 мс на одном запросе критично сказывается на хвостовых перцентилях, если сервис делает несколько последовательных (sequential) обращений к смежным компонентам или базе данных.
4.  **Синхронная репликация БД:** Если база данных настроена на синхронную репликация между зонами, запись не будет подтверждена до тех пор, пока данные не дойдут до реплики в другой AZ. Это напрямую увеличивает задержку каждой операции записи (Write Latency).

## Диагностика

Для подтверждения проблемы необходимо проверить, куда реально уходят соединения и какова задержка до конкретных эндпоинтов.

### Алгоритм диагностики (Bottom-up)

1. Определите IP-адреса целевых сервисов и их зоны.
2. Измерьте RTT до эндпоинтов в разных зонах.
3. Сравните задержки: разница >0.5 мс указывает на cross-zone.
4. Проверьте счётчики TCP на наличие ретрансмиссий.
5. Проанализируйте облачные метрики для количественного подтверждения.

### Шаг 1: Определение зон эндпоинтов

Прежде чем измерять задержки, необходимо узнать, в какой зоне находится каждый backend.

```bash
# Получение IP-адресов подов сервиса
kubectl get endpointslices -l kubernetes.io/service-name=<service-name> -o wide

# Определение зоны по метке пода
kubectl get pods -l app=<app-label> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}{end}'
# → pod-abc123    zone-a
# → pod-def456    zone-b
# → pod-ghi789    zone-a
```

**Валидация:** Убедитесь, что поды распределены минимум по 2 зонам. Если все поды в одной зоне — cross-zone трафик отсутствует по определению.

### Шаг 2: Анализ активных соединений (ss)

Проверка адресов backend-ов, к которым подключено приложение. Если адреса принадлежат подсетям разных AZ, это явный признак cross-zone трафика.

```bash
# Просмотр установленных соединений с отображением процессов
ss -tnp

# Фильтрация по порту сервиса
ss -tnp | grep ':5432'

# Вывод только удалённых адресов (без дублирования)
ss -tn state established '( dport = :5432 )' | awk '{print $5}' | sort -u
# → 10.0.1.15:5432
# → 10.0.2.23:5432
```

**Интерпретация:** Если IP-адреса принадлежат разным подсетям (например, `10.0.1.x` и `10.0.2.x`), это подсети разных AZ. Различие определяется по нумерации: в AWS первая пара/octet определяет VPC, вторая — подсеть AZ.

*Подробнее: **[Анализ сокетов (ss)](../../Linux/Diagnostics/Networking/ss.md)**.*

### Шаг 3: Сравнение задержек через MTR

Наиболее эффективный инструмент для выявления разницы в задержках до разных реплик backend-а.

```bash
# TCP-трассировка до эндпоинта в «своей» зоне (требует root)
sudo mtr -T -P 5432 --report --report-cycles 20 <backend-ip-local-zone>
# → HOST: localhost          Loss%   Snt   Last   Avg  Best  Wrst StDev
# →   1. 10.0.1.15           0.0%    20    0.3   0.4   0.2   0.8   0.1

# TCP-трассировка до эндпоинта в удалённой зоне
sudo mtr -T -P 5432 --report --report-cycles 20 <backend-ip-remote-zone>
# → HOST: localhost          Loss%   Snt   Last   Avg  Best  Wrst StDev
# →   1. 10.0.2.23           0.0%    20    1.2   1.5   1.0   2.3   0.3
```

**Валидация:** Сравните колонки `Avg` и `Best`. Разница >0.5 мс между эндпоинтами подтверждает влияние межзонных переходов. Если разница <0.3 мс — задержка не связана с топологией AZ.

*Подробнее: **[Альтернативы ping](./ping_alternatives.md)** — TCP-пинг и инструменты диагностики.*

### Шаг 4: Анализ счетчиков TCP (nstat)

Рост задержек может сопровождаться увеличением таймаутов и повторных передач (retransmissions).

```bash
# Снимок счетчиков ДО тестирования
nstat -az | grep -E 'TcpExtTCPTimeouts|TcpRetransSegs' > /tmp/nstat_before.txt

# ... выполнение нагрузочного теста ...

# Снимок счетчиков ПОСЛЕ тестирования
nstat -az | grep -E 'TcpExtTCPTimeouts|TcpRetransSegs' > /tmp/nstat_after.txt

# Разница (дельта)
paste /tmp/nstat_before.txt /tmp/nstat_after.txt | awk '{print $1, $2, $5-$2}'
# → TcpExtTCPTimeouts 1523 45
# → TcpRetransSegs 8921 120
```

**Интерпретация:**
- Рост `TcpExtTCPTimeouts` — указывает на丢失 пакетов или проблемы с маршрутизацией.
- Рост `TcpRetransSegs` — повторная передача сегментов, следствие потерь или задержек.
- Если оба счётчика стабильны — проблема не в сетевом стеке, а в приложении или БД.

### Шаг 5: Облачные метрики (Cloud Performance)

Использование нативных инструментов мониторинга сети от провайдеров:

**AWS:**
```bash
# CloudWatch: метрика NetworkPerformance
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name NetworkPerformance \
  --dimensions Name=InstanceId,Value=<instance-id> \
  --start-time $(date -u -d '1 hour ago' +%FT%TZ) \
  --end-time $(date -u +%FT%TZ) \
  --period 60 \
  --statistics Average Maximum

# VPC Flow Logs: анализ cross-zone трафика
aws logs filter-log-events \
  --log-group-name /aws/vpc/flowlogs \
  --filter-pattern "[version, account, eni, srcAddr, dstAddr, srcPort, dstPort, protocol, packets, bytes, start, end, action, logStatus]" \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

**GCP:**
```bash
# Network Intelligence Center: экспорт метрик через Monitoring API
gcloud monitoring time-series list \
  --filter='metric.type="network.googleapis.com/agent/received_bytes_count"' \
  --interval-end-time=$(date -u +%FT%TZ) \
  --interval-start-time=$(date -u -d '1 hour ago' +%FT%TZ)
```

**Azure:**
```bash
# Network Watcher: анализ задержек
az network watcher flow-log list \
  --location <resource-group-location> \
  --query "[].targetResourceId"
```

**Валидация:** Метрики должны показывать корреляцию между ростом RTT и увеличением cross-zone трафика. Если cross-zone трафик стабилен, а задержки растут — проблема на стороне приложения или БД.

### Шаг 6: Захват пакетов (tcpdump)

Детальный анализ трафика при неясных случаях.

```bash
# Захват TCP-синхронизации с флагами (SYN/ACK/RST)
sudo tcpdump -i any 'host <backend-ip> and port 5432 and tcp[tcpflags] & (tcp-syn|tcp-ack|tcp-rst) != 0' -nn -c 50

# Анализ задержек между SYN и SYN/ACK (time to connect)
sudo tcpdump -i any 'host <backend-ip> and port 5432 and tcp[tcpflags] & tcp-syn != 0' -nn -tttt -c 10
# → 2026-01-01 12:00:00.000001 IP 10.0.1.5.43210 > 10.0.2.23.5432: Flags [S]
# → 2026-01-01 12:00:00.001523 IP 10.0.2.23.5432 > 10.0.1.5.43210: Flags [S.]
# RTT = 0.001523 сек = 1.5 мс (межзонная задержка)
```

**Валидация:** Разница во времени между `Flags [S]` (SYN) и `Flags [S.]` (SYN/ACK) показывает реальную RTT. Сравните для эндпоинтов в разных зонах.

## Архитектурные решения

### 1. Kubernetes: Управление топологией
Начиная с Kubernetes 1.31 (и в рамках развития механизма Hints), приоритет отдается новым полям управления трафиком.

- **Topology Aware Routing:** Использование аннотации `service.kubernetes.io/topology-mode: Auto`. Требует равномерного распределения подов по зонам (минимум 3 реплики на зону для стабильной работы).
- **trafficDistribution (v1.31+):** Новое поле в спецификации Service, позволяющее более гибко управлять локальностью.
  ```yaml
  spec:
    trafficDistribution: PreferClose # Предпочитать эндпоинты в той же зоне/узле
  ```
- **internalTrafficPolicy: Local:** Ограничивает трафик только текущим узлом. Исключает межзонные и даже внутризонные переходы, но лишает отказоустойчивости в рамках узла (если пода на узле нет, запрос не уйдет в сеть).

### 2. Service Mesh: Зональная балансировка
Современные Service Mesh предоставляют более продвинутые механизмы контроля задержек:
- **Istio:** Настройка `Locality Load Balancing` в ресурсе `DestinationRule`. Позволяет задавать веса для разных зон и настраивать failover (например, 99% трафика в свою зону, 1% — в соседнюю).
- **Linkerd (Buoyant Enterprise):** Использование **HAZL** (High Availability Zonal Load balancing). Динамически перераспределяет трафик не только на основе зон, но и на основе текущей нагрузки и задержек эндпоинтов.

### 3. Правила размещения (Affinity)
- **Pod Affinity/Anti-Affinity:** Использование правил для того, чтобы сильно связанные сервисы (например, App и его Cache) гарантированно попадали в одну зону доступности или на один узел.
- **Topology Spread Constraints:** Гарантирует, что поды распределены по зонам равномерно, что необходимо для корректной работы Topology Aware Routing.

### Сравнительная таблица архитектурных решений

| Решение | Уровень | Версия K8s | Отказоустойчивость | Сложность настройки | Когда использовать |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Topology Aware Routing** | L4 (Service) | 1.27+ (Beta), 1.31+ (stable) | Высокая (автопереключение при дисбалансе) | Низкая | Стандарт для новых сервисов |
| **trafficDistribution: PreferClose** | L4 (Service) | 1.31+ | Высокая (мягкое управление) | Низкая | Предпочтительный вариант для K8s 1.31+ |
| **internalTrafficPolicy: Local** | L4 (Service) | 1.14+ | Низкая (нет failover между нодами) | Низкая | DaemonSet-прокси (PgBouncer, envoy) |
| **Istio Locality LB** | L7 (Mesh) | — | Высокая (настраиваемый failover) | Средняя | Контроль весов и failover policies |
| **Linkerd HAZL** | L7 (Mesh) | — | Высокая (динамическая балансировка) | Средняя | Автоматическая зональная балансировка |
| **Pod Affinity/Anti-Affinity** | L3 (Scheduling) | — | Средняя (статическое размещение) | Низкая | Гарантия локальности связанных сервисов |
| **Topology Spread Constraints** | L3 (Scheduling) | — | Средняя (равномерное распределение) | Средняя | Равномерное размещение подов по зонам |

**Рекомендация по приоритету:**
1. **trafficDistribution: PreferClose** (K8s 1.31+) — если версия кластера позволяет.
2. **Topology Aware Routing** (annotation `topology-mode: Auto`) — для более ранних версий.
3. **internalTrafficPolicy: Local** — только для DaemonSet/sidecar прокси.
4. **Istio/Linkerd** — если уже используется Service Mesh.

## Практические сценарии

### Сценарий 1: Рост задержки записи в PostgreSQL

**Проблема:** После переезда в облако время выполнения `INSERT` выросло в 3 раза.

**Причина:** БД развернута в HA-режиме (Primary в AZ-A, Replica в AZ-B) с синхронной репликацией. Сетевая задержка между AZ составляет 1.5 мс, что добавляется к каждому коммиту.

**Диагностика:**
```bash
# 1. Определение зон реплик
kubectl get pods -l app=postgres -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}{end}'
# → postgres-primary-0    zone-a
# → postgres-replica-0    zone-b

# 2. Измерение RTT до Primary
sudo mtr -T -P 5432 --report --report-cycles 10 <primary-ip>
# → Avg: 0.4 мс (внутризонная)

# 3. Измерение RTT до Replica (при синхронной репликации)
sudo mtr -T -P 5432 --report --report-cycles 10 <replica-ip>
# → Avg: 1.8 мс (межзонная)

# 4. Проверка логов PostgreSQL на задержки
kubectl logs postgres-primary-0 | grep -i "replication" | tail -5
# → LOG: standby replication latency: 1.523 ms
```

**Решение:**
1. Перевод репликации в асинхронный режим (если допустима потеря данных).
2. Использование инструментов типа `PgBouncer` с привязкой к локальным зонам для чтения.
3. Оптимизация батчинга запросов для уменьшения количества сетевых переходов.

**Валидация:** После изменений повторите измерение RTT. Задержка записи должна снизиться до <0.5 мс (внутризонная).

### Сценарий 2: Аномальные счета за трафик в AWS

**Проблема:** Стоимость «Inter-AZ Data Transfer» превышает стоимость самих серверов.

**Причина:** Микросервисы общаются через `LoadBalancer` без учета топологии. Трафик хаотично гуляет между AZ-A, AZ-B и AZ-C.

**Диагностика:**
```bash
# 1. Анализ VPC Flow Logs на cross-zone трафик
aws logs filter-log-events \
  --log-group-name /aws/vpc/flowlogs \
  --filter-pattern "[version, account, eni, srcAddr, dstAddr, srcPort, dstPort, protocol, packets, bytes, start, end, action, logStatus]" \
  --start-time $(date -u -d '24 hours ago' +%s)000 \
  --query 'events[].message' --output text | \
  awk '{print $4, $5}' | sort | uniq -c | sort -rn | head -10

# 2. Проверка текущей конфигурации Service
kubectl get svc -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\t"}{.spec.topologyMode}{"\t"}{.spec.trafficDistribution}{"\n"}{end}'
# → prod/api-service    Auto    
# → prod/web-service           PreferClose
```

**Решение:** Включение `Topology Aware Routing` для всех внутренних сервисов. Перевод связи на `PreferClose` (K8s 1.31+), что снизило объем межзонного трафика на 85%.

**Валидация:** Через 24 часа проверьте стоимость в Billing Dashboard. Объём Inter-AZ Data Transfer должен снизиться на 70-90%.

## Диагностика типичных проблем

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Задержки растут только при нагрузке | Cross-zone трафик + конкуренция за пропускную способность | `mtr --report` + облачные метрики Network Bandwidth | Включить Topology Aware Routing; увеличить пропускную способность каналов |
| Высокий P99 при низком P50 | Хвостовые запросы идут через удалённую зону | `kubectl logs` + анализ percentiles в Prometheus | Проверить распределение эндпоинтов по зонам; использовать `trafficDistribution: PreferClose` |
| Рост `TcpRetransSegs` | Потери пакетов на маршруте между AZ | `nstat -az \| grep Retrans` + `mtr` | Обратиться в поддержку облачного провайдера; проверить Security Groups/ACL |
| `Connection timeout` к БД | NetworkPolicy или Security Group блокирует трафик | `kubectl exec -it app-pod -- nc -zv db-service 5432` | Проверить NetworkPolicy и Security Group; добавить разрешающие правила |
| Трафик идёт через LoadBalancer | Отсутствие Topology Aware Routing | `kubectl get svc -o yaml` + проверка аннотаций | Добавить аннотацию `service.kubernetes.io/topology-mode: Auto` |
| Разная задержка при одинаковых IP | NAT или proxy между зонами | `tcpdump` + анализ Source IP | Проверить конфигурацию NAT Gateway/Transit Gateway |
| Sidecar вносит задержку >0.5 мс | Envoy sidecar overhead | `kubectl logs <pod> -c istio-proxy` + анализ RTT | Перейти на Ambient Mesh или eBPF-решение (Cilium) |

## Граничные случаи и особенности

### Малое количество подов (<3 на зону)

Topology Aware Routing требует минимум 3 подов на зону для стабильной работы. При меньшем количестве K8s может отключить подсказки (hints) и направлять трафик случайно.

```bash
# Проверка статуса EndpointSlice Hints
kubectl get endpointslices -l kubernetes.io/service-name=<service> -o jsonpath='{.items[*].endpoints[*].hints}'
# Если hints отсутствуют — K8s не может распределить топологически
```

**Решение:** Увеличьте количество реплик до минимум 3 на зону или используйте `trafficDistribution: PreferClose` (более мягкий подход).

### Однозонные кластеры

Если все ноды кластера находятся в одной AZ, cross-zone трафик отсутствует. Topology Aware Routing в этом случае бесполезен, но и не вредит.

### Асимметричное распределение подов

Если в AZ-A 90% подов, а в AZ-B 10%, Topology Aware Routing будет направлять 90% трафика в AZ-A, но оставшиеся 10% запросов попадут в AZ-B и создадут cross-zone задержку.

```bash
# Проверка распределения подов по зонам
kubectl get pods -A -l app=<app> -o jsonpath='{range .items[*]}{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}{end}' | sort | uniq -c
# → 9 zone-a
# → 1 zone-b
```

**Решение:** Используйте `Topology Spread Constraints` для равномерного распределения.

### Сторонние сервисы (External Services)

Для внешних сервисов (RDS, Cloud SQL) cross-zone трафик определяется провайдером. Topology Aware Routing не влияет на трафик к внешним эндпоинтам. Используйте привязку реплик чтения к локальной зоне через `ExternalName` или Headless Service.

### Service Mesh: побочные эффекты sidecar

Sidecar-прокси (Envoy) добавляет ~0.1–0.5 мс к каждому запросу. В сценариях с высокой частотой запросов (10k+ RPS) это может стать значимым.

**Решение:** Использовать Ambient Mesh (Istio) или eBPF-решения (Cilium) для sidecar-less архитектуры.

### Версии Kubernetes

- `topology-mode: Auto` — стабильно с v1.27, рекомендуется.
- `trafficDistribution: PreferClose` — стабильно с v1.31, предпочтительный вариант.
- `internalTrafficPolicy: Local` — стабильно с v1.14.

При использовании Managed Kubernetes (EKS, GKE, AKS) проверьте доступные версии — не все провайдеры поддерживают новые API сразу после релиза.

## Практические рекомендации

1. **Мониторинг:** Настройте алертинг на разницу RTT между зонами. Порог: >0.5 мс стабильно в течение 5 минут.
2. **Капацити-планирование:** При масштабировании учитывайте равномерное распределение подов по зонам. Используйте `Topology Spread Constraints` с `maxSkew: 1`.
3. **Тестирование:** Регулярно выполняйте `mtr --report` до всех реплик БД для контроля задержек.
4. **Батчинг:** Объединяйте мелкие запросы в батчи для уменьшения количества cross-zone переходов.
5. **Read Replicas:** Направляйте запросы чтения на реплики в той же зоне, что и приложение.
6. **FinOps:** Проверяйте стоимость Inter-AZ трафика ежемесячно. При росте >20% — проводите аудит топологии.
7. **Каскадная оптимизация:** Начинайте с Topology Aware Routing (нативный K8s), затем Service Mesh, затем eBPF — только при необходимости.

## Безопасность

- Межзонный трафик проходит через внутреннюю сеть провайдера, но рекомендуется шифрование (mTLS) для данных в compliance-средах (PCI DSS, HIPAA).
- При использовании Transit Gateway или VPC Peering убедитесь, что межзонные потоки проходят через security appliances (IDS/IPS).
- NetworkPolicy не блокирует cross-zone трафик по умолчанию — проверьте политики для каждого namespace.

## Дополнительная информация

*   **[Сетевая связность K8s и PostgreSQL в многозонных средах](../../Databases/PostgreSQL/Operations/kubernetes_connectivity.md)** — глубокий разбор задержек для БД.
*   **[Практические сценарии Service в Kubernetes](../../Kubernetes/Networking/Service/service_practical_scenarios.md)** — детали использования `trafficDistribution` и `Topology Aware Routing`.
*   **[Управление трафиком в Service Mesh](../../Service_Mesh/traffic_management.md)** — подробнее про HAZL (Linkerd) и Locality Load Balancing (Istio).
*   **[Альтернативы ping](./ping_alternatives.md)** — диагностика доступности по TCP/UDP.
