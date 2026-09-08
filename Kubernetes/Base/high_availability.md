# Высокая доступность (High Availability)

## Определения

Для построения качественной системы в Kubernetes важно различать три взаимосвязанных понятия:

* **Высокая доступность (High Availability, HA)**: Архитектурная способность системы продолжать работу даже при выходе из строя отдельных компонентов инфраструктуры (узлов, дисков, сегментов сети). В Kubernetes это достигается за счет избыточности: нескольких узлов Control Plane, кластеризации `etcd` и балансировки нагрузки.
* **Надежность (Reliability)**: Способность системы работать стабильно и предсказуемо в течение длительного времени, избегая замедлений или ошибок под высокой нагрузкой. Надежность фокусируется на качественных показателях работы приложения (отсутствие 5xx ошибок, соблюдение latency).
* **Устойчивость (Resilience)**: Способность системы к быстрому и автоматическому восстановлению после сбоев. В Kubernetes реализуется через механизмы самовосстановления (self-healing), такие как автоматический перезапуск упавших контейнеров (`livenessProbe`) и резервные системы (ReplicaSet).

Общие принципы отказоустойчивости (RTO, RPO, кворум) описаны в разделе **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)**.

Основа HA в Kubernetes — **декларативный подход** и **цикл сверки (Reconciliation Loop)**. Контроллеры кластера непрерывно сравнивают текущее состояние (Actual State) с объявленным «желаемым состоянием» (Desired State) в `etcd` и предпринимают корректирующие действия для устранения расхождений.

### Структура отказоустойчивой среды

Высокую доступность в Kubernetes можно разделить на два уровня:

1.  **Защита «мозга» (Control Plane HA)**: Обеспечение избыточности управляющих компонентов (API, etcd, scheduler), чтобы кластер мог принимать решения даже при потере части серверов.
2.  **Создание устойчивой «рабочей силы» (Node & App HA)**: Гарантия того, что пользовательские приложения распределены по узлам и автоматически восстанавливаются.

## Основные концепции

### Отказоустойчивость рабочих нагрузок (Workloads)

#### Контроллеры репликации (Deployment и StatefulSet)
Эти объекты гарантируют запуск заданного количества идентичных экземпляров приложения (реплик).
*   **Механизм восстановления**: Если узел (Node) выходит из строя, контроллер [ReplicaSet](./replicaset.md) обнаруживает несоответствие количества работающих подов желаемому значению. Он инициирует создание новых подов, которые планировщик (`kube-scheduler`) размещает на оставшихся здоровых узлах.
*   **StatefulSet**: Обеспечивает стабильные идентификаторы и тома. При отказе узла требуется механизм **Fencing**, чтобы предотвратить одновременную запись данных с двух подов (см. раздел про Split-Brain).

#### Балансировка и эндпоинты (Service и Gateway API)
*   **Service**: Предоставляет стабильный виртуальный IP (ClusterIP) и DNS-имя. Контроллер эндпоинтов отслеживает состояние подов. Если под перестает проходить проверку готовности (`readinessProbe`), его IP немедленно исключается из `Endpoints` или `EndpointSlice`.
*   **Gateway API (GA v1.0+)**: Поддерживает сложные стратегии балансировки и мультикластерную конфигурацию (**Multi-cluster Services / MCS**). MCS позволяет распределять нагрузку между подами в разных кластерах, обеспечивая глобальную отказоустойчивость (Global HA).

### Наблюдаемость: Пробы (Probes)

Корректно настроенные пробы — фундамент самоисцеления:
*   **`livenessProbe`**: Проверяет работоспособность процесса. При сбое контейнер перезапускается.
*   **`readinessProbe`**: Проверяет готовность принимать трафик. При сбое под исключается из балансировки.
*   **`startupProbe`**: Защищает медленно стартующие приложения от преждевременного убийства другими пробами.
*   **Эндпоинты диагностики Control Plane**: Использование `/livez`, `/readyz` и `/healthz` для проверки состояния компонентов управляющей плоскости.

### Управление доменами отказа (Scheduling)

Для предотвращения одновременного падения всех реплик используются:
*   **`podAntiAffinity`**: Запрет запуска подов на одном хосте.
*   **`topologySpreadConstraints` (GA v1.24)**: Равномерное распределение подов по зонам (AZ) или стойкам.
*   **PodDisruptionBudget (PDB)**: Ограничение количества одновременно недоступных подов при плановом обслуживании.

**Три инструмента дополняют друг друга**, закрывая разные сценарии: `podAntiAffinity` запрещает соседство, `topologySpreadConstraints` распределяет равномерно, а PDB защищает от «чрезмерного» выселения во время плановых работ. На практике включают и antiaffinity, и spread-констрейнты одновременно.

**Пример равномерного распределения реплик по узлам и зонам:**

```yaml
# Фрагмент Deployment: распределить 3 реплики по 3 разным узлам
spec:
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: DoNotSchedule   # либо ScheduleAnyway
        labelSelector:
          matchLabels:
            app: web-api
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              topologyKey: kubernetes.io/hostname
              labelSelector:
                matchLabels:
                  app: web-api
```

*   `maxSkew: 1` — разница в количестве реплик между самыми «заполненным» и «пустым» доменом не более 1.
*   `whenUnsatisfiable: DoNotSchedule` — если распределить нельзя, под вообще не планируется (жёсткое требование); `ScheduleAnyway` — распределяем «по-возможности».
*   Для топологии облачных зон `topologyKey` заменяют на `topology.kubernetes.io/zone`, для стоек — на соответствующую label узла.

**Проверка фактического распределения:**

```bash
# С каких узлов/зон обслуживаются поды сервиса
kubectl get pods -l app=web-api -o wide

# Нагрузка по узлам, если есть метки зон
kubectl get nodes -o custom-columns=NAME:.metadata.name,ZONE:.metadata.labels.topology\.kubernetes\.io/zone
```

**PDB — пример и проверка:**

```yaml
# Обеспечить рабочим сервисом минимум 2 пода во время плановых работ
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-api-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: web-api
```

```bash
# Сколько подовых можно выселить одновременно (разница между ALLOWED DISRUPTIONS)
kubectl get pdb web-api-pdb
# NAME          MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# web-api-pdb   2               N/A               1                     5m
```

Детально о параметрах и взаимодействии с Rolling Update — в [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md).

## Отказоустойчивость Control Plane

### Архитектура и кворум

Плоскость управления (Control Plane) требует избыточности для непрерывного функционирования.

*   **Минимум три узла**: Развертывание нечетного количества узлов для обеспечения **кворума** (Majority).
*   **Понятие кворума**: Минимальное количество узлов `etcd`, необходимых для фиксации изменений (`N/2 + 1`).
*   **API Priority and Fairness (APF)**: Механизм управления приоритетами запросов к API-серверу, предотвращающий его перегрузку при каскадных сбоях.

| Количество узлов | Кворум (большинство) | Допустимый отказ |
| :--- | :--- | :--- |
| 1 | 1 | 0 |
| 3 | 2 | 1 |
| 5 | 3 | 2 |

### Настройка через kubeadm

Для настройки HA-кластера используется параметр `controlPlaneEndpoint`, указывающий на балансировщик (LB).

**Пример конфигурации (`ClusterConfiguration`):**
```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
controlPlaneEndpoint: "lb-k8s.example.com:6443"
```

### Обслуживание etcd

Для стабильной работы HA-кластера `etcd` требует регулярного обслуживания:
*   **Snapshotting**: Регулярное создание резервных копий состояния (db file).
*   **Defragmentation**: Освобождение неиспользуемого пространства в БД после удаления больших объемов данных.
*   **Мониторинг задержек (fsync)**: `etcd` критичен к I/O. Высокий `wal_fsync_duration_seconds` — основной индикатор проблем с HA.

Практический минимум для SRE — проверка здоровья членов кластера etcd и текущего кворума:

```bash
# На узле control-plane (внутри etcd-контейнера/manifest):
alias etcdctl="etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key"

# Здоровье и ревизии всех членов (RAFT TERM совпадает, REVISION без сильного расхождения)
etcdctl endpoint health
etcdctl endpoint status -w table

# Список участников (должно быть 3 для кворума 2)
etcdctl member list -w table
```

*   Полноценный процесс снапшотов и восстановления описан в **[etcd — операции](../Concepts/etcd_operations.md)**.
*   Перед восстановлением из снапшота и после крупных удалений выполняется defrag; снапшот забирается командой `etcdctl snapshot save`.

### Доступность API-сервера

*   **Балансировка**: Использование L4-балансировщика (например, HAProxy + Keepalived, kube-vip, или управляемые NLB/GCP LB) для порта `6443`, чтобы шлюз не был единой точкой отказа (SPOF).
*   **Validation**: Перед подключением рабочего узла балансировщик должен отдавать здоровье от API-серверов; health-проверка обычно бьётся по TCP `6443` либо по `/livez`.
*   **Leader Election**: Компоненты `scheduler` и `controller-manager` используют механизм **Lease** (в пространстве имён `kube-node-lease`/`kube-system`) для выбора активного экземпляра; остальные работают в standby и перехватывают управление при сбое лидера.
*   **Pre-filtering**: Использование `priority-and-fairness` для защиты API от "шумных соседей".

Практическая проверка живучести Control Plane — через эндпоинты диагностики и `kubectl`:

```bash
# Здоровье API-сервера: каждая контрольная точка отвечает "ok"
kubectl get --raw='/livez?verbose'   # жив ли
kubectl get --raw='/readyz?verbose'  # готов ли принимать запросы
kubectl get --raw='/healthz'

# Достижимость каждого control-plane узла через LB (VIP)
for ip in 10.0.0.11 10.0.0.12 10.0.0.13; do
  curl -k https://$ip:6443/readyz && echo "  <- $ip ok"
done

# Активный лидер связки controller-manager/scheduler (Lease)
kubectl get lease -n kube-system
# holderIdentity показывает, какой экземпляр сейчас лидер
```

Полная процедура настройки L4-балансировки на bare-metal (Keepalived + HAProxy, kube-vip) и верификации — в [HA API-сервера с Keepalived и HAProxy](../Installation/kubeadm/ha_concepts.md) и [проверке HA-кластера](../Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md).

### Fencing и предотвращение Split-Brain

*   **NodeOutOfServiceVolumeDetach (GA v1.28)**: Позволяет безопасно отмонтировать тома от недоступного узла через пометку узла как `out-of-service`. Это решает проблему блокировки томов для `StatefulSet`.
*   **Fencing механизмы**: Принудительная изоляция узла на уровне сети или питания для предотвращения некорректной записи данных.

## Практические сценарии

### Сценарий 1: Аварийный сбой узла (Unplanned Failure)

1.  **Обнаружение**: `NodeLifecycleController` фиксирует отсутствие heartbeats.
2.  **Tainting**: На узел накладывается таинт `node.kubernetes.io/unreachable`.
3.  **Eviction**: По истечении таймаута (по умолчанию 300с) поды выселяются и пересоздаются на других узлах.

### Сценарий 2: Глобальная отказоустойчивость (Multi-Cluster HA)

При отказе целого региона или крупной зоны:
1.  **GSLB (Global Server Load Balancing)**: Перенаправляет трафик на другой кластер.
2.  **MCS API**: Обеспечивает связность сервисов между кластерами, позволяя поду в Кластере А обращаться к сервису в Кластере Б через локальное имя.

### Сценарий 3: Валидация HA (Chaos Engineering)

Проверка отказоустойчивости должна быть регулярной:
*   **Инструменты**: Chaos Mesh, LitmusChaos.
*   **Тесты**: Принудительная остановка узлов Control Plane, эмуляция сетевых задержек между узлами `etcd`, удаление подов критических системных компонентов.

**Минимальный ручной прогон (без внедрения инструментов):**

```bash
# 1. Остановить (poweroff) one control-plane узел и убедиться, что API жив
kubectl get nodes                        # узел перейдет в NotReady
curl -k https://lb-k8s.example.com:6443/readyz   # должен отвечать ok

# 2. Убедиться, что сервисы самовосстанавливаются
kubectl get pods -A | grep -Ev 'Running|Completed'
# → пустой вывод означает, что все поды восстановлены/работают

# 3. Вернуть узел и дождаться готовности
kubectl get nodes -w                     # NotReady → Ready после reboot
```

**Рекомендация SRE:** такие тесты проводите в выделенном staging-кластере перед релизом, фиксируя время восстановления (RTO) и сверяя его с целевым показателем.

### Сценарий 4: Плановое обслуживание (Drain/Cordon)

Грамотный вывод узла в обслуживание — базовая дисциплина SRE. Порядок действий:

1.  **Пометить узел как не планируемый** — новые поды на него не размещаются:
    ```bash
    kubectl cordon worker-1
    # node/worker-1 cordoned
    ```
2.  **Выселить существующие поды (eviction)** с учётом PDB и других ограничений:
    ```bash
    kubectl drain worker-1 --ignore-daemonsets --delete-emptydir-data
    ```
    *   `--ignore-daemonsets` — DaemonSet-поды игнорируются (их нельзя выселить).
    *   `--delete-emptydir-data` — удалить данные в `emptyDir` (иначе drain остановится с ошибкой).
    *   Если процесс блокируется на недоступных подах: `--force` (с осторожностью, только для пода, не поддающихся graceful).
3.  **Выполнить обслуживание**, затем вернуть узел:
    ```bash
    kubectl uncordon worker-1
    # node/worker-1 uncordoned
    ```

**Ключевая связь с HA:** во время drain работает `NodeLifecycleController` и учёт PDB — если `minAvailable` нарушается, drain приостановится до появления доступных подов. Бездумное последовательное выселение нескольких узлов может «погасить» весь сервис, поэтому количество одновременных узлов в обслуживании должно быть меньше допустимого по PDB. Подробности — в [обслуживании узлов (Cordon/Drain)](../Operations/node_maintenance.md).

### Сценарий 5: Потеря кворума etcd

Критический сценарий — потеря большинства узлов etcd. Кластер переходит в read-only режим: API-сервер не может фиксировать изменения.

*   **Симптомы**: `kubectl` возвращает `etcdserver: no leader`, операции записи падают, `kubectl get` частично работает.
*   **Диагностика**:
    ```bash
    etcdctl endpoint health -w table     # статус каждого члена
    etcdctl member list -w table
    ```
*   **Восстановление из бекапа** (если кворум невозможно вернуть):
    1.  Остановить etcd на всех, кроме одного сохранившегося узла.
    2.  Восстановить узел из снапшота: `etcdctl snapshot restore <backup.db> --data-dir /var/lib/etcd-restored`.
    3.  Обновить конфигурацию кластера etcd и запустить etcd, затем добавить остальные узлы.
    4.  Удалить не валидные члены: `etcdctl member remove <id>`.

*   **Важно (Edge Case):** флаг `--force-new-cluster` запускает etcd как новый одноузловой кластер без консенсуса — это восстанавливает доступность ценой потери всех данных вне снапшота. Применяйте его только как последнее средство, иначе есть риск получить два «независимых» кластера (split-brain).

Полный пошаговый процесс — в **[etcd — операции](../Concepts/etcd_operations.md)**.

### Сценарий 6: Кластер 3 ноды — потеря 2 Control Plane узлов

Типичная ситуация: HA-кластер с 3 control-plane узлами (Stacked etcd). Два узла одновременно вышли из строя (питание, сеть, паника ядра).

#### Математика кворума

| Параметр | Значение |
| :--- | :--- |
| Всего узлов etcd | 3 |
| Кворум (N/2 + 1) | 2 |
| Выживших узлов | 1 |
| **Результат** | **Кворум потерян** (1 < 2) |

#### Поведение компонентов

| Компонент | Состояние | Последствия |
| :--- | :--- | :--- |
| **etcd** | **Read-only** | Raft не может выбирать лидера, не фиксирует записи. `endpoint status` показывает `IS LEADER=false` |
| **kube-apiserver** | **Read-only** | `GET/LIST/WATCH` работают, **`CREATE/UPDATE/DELETE/PATCH` → `etcdserver: no leader`** |
| **kube-scheduler** | Standby | Нет лидера — новые поды не назначаются (зависают в `Pending`) |
| **kube-controller-manager** | Standby | Нет лидера — реплики не создаются, узлы не таинтятся, PDB не учитывается |
| **Data Plane (Pods на worker-узлах)** | **Работают** | Существующие поды продолжают обслуживать трафик, kubelet/kube-proxy функционируют автономно |

#### Симптомы для оператора

```bash
# kubectl get — работает
kubectl get nodes
# → 1 Ready, 2 NotReady

# Любая операция записи — ошибка
kubectl scale deploy web --replicas=5
# → Error from server (InternalError): etcdserver: no leader

# etcdctl диагностика
etcdctl endpoint health
# → https://10.0.0.1:2379 is healthy: committed proposal took 15ms
# → https://10.0.0.2:2379 is unhealthy: context deadline exceeded
# → https://10.0.0.3:2379 is unhealthy: context deadline exceeded

etcdctl endpoint status -w table
# → IS LEADER = false на единственном живом
```

#### Варианты восстановления (по приоритету)

**1. Вернуть упавшие ноды (RTO = время ребута/починки сети)**
- Если причина временная (перезагрузка, сеть) — просто ждёте возвращения 2-й ноды
- Как только 2-я нода rejoined → кворум восстановлен → кластер автоматически выходит в Normal
- **Это самый быстрый и безопасный путь**

**2. Disaster Recovery: восстановление из снапшота etcd (если ноды не вернутся)**

```bash
# На ВЫЖИВШЕМ узле:

# 1. Остановить kube-apiserver (static pod)
mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/

# 2. Остановить etcd
crictl stop $(crictl ps --name etcd -q)

# 3. Восстановить из снапшота с force-new-cluster
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot.db \
  --data-dir /var/lib/etcd-restored \
  --initial-cluster "survivor=https://10.0.0.1:2380" \
  --initial-cluster-token "recovery" \
  --initial-advertise-peer-urls https://10.0.0.1:2380 \
  --name survivor

# 4. Заменить datadir, запустить etcd, затем apiserver
mv /var/lib/etcd-restored/member /var/lib/etcd/
# systemd/containerd запустит etcd, затем kubelet поднимет apiserver

# 5. Удалить мёртвых членов etcd
etcdctl member remove <id_dead_1> <id_dead_2>

# 6. Добавить новые control-plane узлы через kubeadm join
```

**3. Экстренные меры для рабочих нагрузок (пока восстанавливаете Control Plane)**

```bash
# На выжившем узле проверить, какие критичные поды там запущены
kubectl get pods -A --field-selector spec.nodeName=<survivor-node>

# Если критичные поды упали — можно поднять вручную через crictl/nerdctl
# (временная мера, без Control Plane они не управляются)
```

#### Ключевые выводы для проектирования HA

| Аспект | Вывод |
| :--- | :--- |
| **Минимум нод** | 3 control-plane (кворум 2, допуск 1 отказа) |
| **Data Plane автономен** | Поды живут без Control Plane, но нет self-healing/scaling |
| **RTO зависит от** | Времени возврата нод ИЛИ времени восстановления снапшота |
| **Best Practice** | Снапшоты etcd каждые 5-15 мин, проверенная DR-процедура, мониторинг `etcd_server_has_leader` |
| **Риск split-brain** | При force-new-cluster без изоляции мёртвых нод — два кластера с diverged state |

---

## Операции и мониторинг

### Наблюдение за здоровьем Control Plane (SRE)

Базовый набор проверок для дежурного инженера:

```bash
# Готовность всех узлов
kubectl get nodes -o wide

# Системные компоненты не в состоянии Running/Completed
kubectl get pods -A | grep -Ev 'Running|Completed'

# Заблокированные/выселенные поды (Evicted, ImagePullBackOff и т.п.)
kubectl get pods -A | grep -Ev 'Running|Completed|Terminating'

# Проверка лидера (Lease) компонентов
kubectl get lease -n kube-system -o custom-columns=NAME:.metadata.name,HOLDER:.spec.holderIdentity

# Возраст сертификатов (безопасность и непрерывность работы)
kubeadm certs check-expiration
```

### Алертинг высокой доступности

Отказоустойчивость бесполезна без своевременного оповещения. Ниже — правила на основе метрик `kube-state-metrics` и экспортёров узлов:

| Сигнал | Метрика | Смысл |
| :--- | :--- | :--- |
| Узел недоступен | `kube_node_status_condition{condition="Ready",status="true"} == 0` | Слишком долго нет heartbeats — грозит потерей ёмкости для реплик. |
| Control Plane не готов | `up{job="apiserver"} == 0` и `/readyz` статус | API-сервер не отвечает или не принимает запросы. |
| Потеря лидера etcd | `etcd_server_has_leader == 0` | Нет лидера — кворум нарушен, кластер read-only. |
| Задержки диска etcd | `histogram_quantile` по `etcd_disk_wal_fsync_duration_seconds` | Критично для устойчивости Raft. |

**Пример правила (Prometheus):**

```yaml
groups:
- name: ha
  rules:
  - alert: KubeNodeNotReady
    expr: kube_node_status_condition{condition="Ready",status="true"} == 0
    for: 10m
    labels:
      severity: critical
    annotations:
      summary: "Узел {{ $labels.node }} не Ready дольше 10 минут"
      description: "Проверьте kubelet, сеть и загрузку узла; при необходимости cordon/drain."

  - alert: EtcdNoLeader
    expr: etcd_server_has_leader == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "В etcd нет лидера — кворум нарушен"
      description: "Кластер перешёл в read-only режим. Восстанавливайте кворум или снапшот."
```

Общая архитектура мониторинга — в [Kubernetes Monitoring & Logging](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

## Диагностика и устранение неполадок (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `kubectl` «подвисает» / ошибки записи | Потеря кворума etcd (`etcdserver: no leader`) | Восстановить кворум или снапшот; см. Сценарий 5. |
| API-сервер на одном узле падает при нагрузке | APF/приоритеты или нехватка ресурсов | Проверить `/livez`, `/readyz`, метрики API; настроить приоритеты. |
| Поды не переезжают после сбоя узла | Taint `unreachable` ещё не истёк (300 c) или мало свободных узлов | Дождаться таймаута выселения; проверить ёмкость и анти-аффинити. |
| `drain` «застревает» | Нарушение PDB / не выселяемый под | `kubectl get pdb -A`; `kubectl get pod -o wide`; использовать `--ignore-daemonsets`/`--force`. |
| Два узла «думают», что кластер их | Split-brain после `--force-new-cluster` | Fencing/изоляция на уровне сети/питания; вернуть единый кворум. |
| LB отдаёт на нездоровый API-сервер | Некорректная health-проверка балансировщика | Настроить check на TCP 6443 или `/readyz`; периодически тестировать. |
| etcd: высокий `wal_fsync_duration_seconds` | Медленный диск / высокая нагрузка I/O | Перевести etcd на NVMe/SSD, изолировать storage. |

## Дополнительная информация

### Рекомендации (Best Practices)

*   **Изоляция etcd**: Для высоконагруженных кластеров выносите `etcd` на выделенные узлы (**External etcd**), отделяя I/O-профиль хранилища от рабочих нагрузок.
*   **Дисковая подсистема**: Только NVMe/SSD с низкими и стабильными задержками (`fsync`); для внешнего etcd — отдельный пул дисков.
*   **Нечётное число Control Plane узлов**: 3 или 5, чтобы сохранить кворум при допустимом отказе (см. таблицу выше).
*   **L4-балансировщик не должен быть SPOF**: дублируйте узлы с Keepalived/kube-vip и мониторьте смену лидера.
*   **Topology Awareness**: Используйте `Topology Aware Hints` для минимизации межзонного трафика.
*   **Версионность**: Версии узлов не должны отставать от Control Plane более чем на 2 минорных релиза.
*   **Автоматизация Chaos-тестов**: регулярные сценарии 1 и 4 в staging предотвращают «сюрпризы» в проде; фиксируйте фактическое RTO/RPO.
*   **Резервное копирование etcd**: план снапшотов и восстановление должны проверяться регулярно.

### См. также

*   **[Под бюджет прерываний (PDB)](../Autoscaling/pod_disruption_budget.md)** — защита сервиса при плановых работах.
*   **[etcd — операции](../Concepts/etcd_operations.md)** — снапшоты, defrag, восстановление кворума.
*   **[HA API-сервера с Keepalived и HAProxy](../Installation/kubeadm/ha_concepts.md)** — L4-балансировка Control Plane на bare-metal.
