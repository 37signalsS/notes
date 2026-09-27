# Недоступность узла: Определения

Состояние недоступности узла в Kubernetes — это критическая ситуация, при которой Control Plane теряет возможность управлять ресурсами на конкретном хосте или получает сигнал о его неработоспособности. Понимание базовых определений и внутренних механизмов необходимо для корректной диагностики и настройки отказоустойчивости.

## Основные определения

**`NodeNotReady`** — статус узла (`Ready: False`), при котором агент `kubelet` на хосте запущен и поддерживает связь с API-сервером, но сообщает о внутренних проблемах, препятствующих нормальному запуску или работе подов. Узел не принимает новые поды, но существующие продолжают работать (если не сработали механизмы эвикции).

**`Node Unknown`** — состояние (`Ready: Unknown`), возникающее, когда API-сервер не получает обновлений от узла в течение заданного времени (по умолчанию **40 секунд**). Это основной индикатор потери сетевой связности или полного отказа хоста/kubelet. Узел считается недоступным для планирования, запускается механизм Taint-based Eviction.

**`Node Maintenance`** (Обслуживание) — административное состояние, при котором узел намеренно выводится из эксплуатации для технических работ. Управляется через `kubectl cordon <node>`, что устанавливает taint `node.kubernetes.io/unschedulable:NoSchedule`. В современных версиях (1.31+) может управляться через декларативный `NodeMaintenance` API (Alpha).

**`Graceful Node Shutdown`** (K8s 1.21+, стабильно с 1.24) — механизм, позволяющий `kubelet` корректно завершать поды при выключении самого узла через взаимодействие с `systemd-logind`. `kubelet` регистрирует Shutdown Hook в `systemd-logind`, и при начале выключения ОС (через `systemctl poweroff`, IPMI и т.д.) получает уведомление с выделенным временем на завершение. Настраивается через параметры `shutdownGracePeriod` и `shutdownGracePeriodCriticalPods` в `KubeletConfiguration`. Важно: не работает при аппаратном выключении (hardware reset, IPMI power off).

**`Out-of-Service` taint** (K8s 1.24+, GA в 1.28) — механизм безопасного восстановления после негрейсивного выключения узла. При наложении taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` контроллеры принудительно завершают поды и отмонтируют тома, что позволяет пересоздать их на других узлах. Используется **только** когда узел гарантированно выключен и не восстановится. Игнорирует PDB — требует осознанного применения.

**`UnhealthyPodEvictionPolicy`** (K8s 1.31, стабильно) — политика в `PodDisruptionBudget`, определяющая поведение при выселении нездоровых подов. Значение `AlwaysAllow` позволяет удалять поды, не проходящие Readiness-пробы, даже при нарушении бюджета. Решает проблему бесконечного ожидания `kubectl drain` из-за подов в `CrashLoopBackOff`.

**Важно:** Недоступность узла напрямую триггерит механизмы **Taint-based Eviction**, что приводит к массовому перезапуску подов на других узлах кластера. Для StatefulSet требуется дополнительное вмешательство через `out-of-service` taint (см. [Taints и выселение](./taints_and_eviction.md)).

## Механизмы отслеживания и состояния

### Состояния узла (Node Conditions)

Kubernetes отслеживает состояние узла через массив `conditions`. Критически важные индикаторы:

| Условие | Описание | Норма (Healthy) | Влияние на планирование |
| :--- | :--- | :--- | :--- |
| **`Ready`** | Готовность узла к приёму и запуску подов | `True` | `False`/`Unknown` — узел исключается из планирования |
| **`MemoryPressure`** | Нехватка оперативной памяти (активируется при достижении порогов `eviction-hard`) | `False` | Новые поды с Guaranteed QoS не планируются |
| **`DiskPressure`** | Критическая нехватка места на системном диске или для образов | `False` | Новые поды не планируются, начинается очистка образов |
| **`PIDPressure`** | Исчерпание лимита идентификаторов процессов в ОС | `False` | Новые поды не планируются |
| **`NetworkUnavailable`** | Проблемы в работе CNI-плагина или конфигурации сети | `False` | Узел не принимает поды, требующие сети |
| **`ContainersReady`** | Готовность всех контейнеров в подах узла | `True` | Не влияет на планирование новых подов |
| **`MemoryPressure` при Swap** | При включенном Swap (K8s 1.31+) может не наступать дольше, но производительность падает | `False` | Рекомендуется `swapBehavior: LimitedSwap` |

### Heartbeats и Lease API

Для мониторинга «живучести» узлов используются два дополняющих друг друга механизма:

1.  **Node Lease (основной)**: Легковесные объекты в пространстве имён `kube-node-lease`. `kubelet` обновляет свой Lease каждые **10 секунд** (`nodeLeaseDurationSeconds`). Это экономит ресурсы etcd в крупных кластерах, так как не требует обновления всего объекта `Node`. Объект Lease содержит только метаданные и временную метку обновления.

2.  **Node Status (редкий)**: Полная структура состояния узла отправляется раз в **5 минут** (`nodeStatusReportFrequency`) или только при значимых изменениях условий (Conditions). Содержит информацию о ресурсах, давлении и готовности.

**Временные интервалы (параметры `kube-controller-manager`):**
- `node-monitor-period`: частота проверки статусов (обычно 5с).
- `node-monitor-grace-period`: время до присвоения статуса `Unknown` (обычно 40с). Должен быть больше, чем `node-monitor-period` × 2, чтобы избежать ложных срабатываний.

**RBAC для Lease:**
Kubelet требует разрешений на чтение/запись объектов Lease в namespace `kube-node-lease`. Базовый ClusterRole `system:node` уже включает эти права. При настройке RBAC вручную убедитесь в наличии:
```yaml
- apiGroups: ["coordination.k8s.io"]
  resources: ["leases"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
```

### Автоматические Taints и Жизненный цикл эвикции

При переходе узла в нездоровое состояние, на него автоматически накладываются taints с эффектом `NoExecute`:
- `node.kubernetes.io/not-ready` (при `Ready: False`)
- `node.kubernetes.io/unreachable` (при `Ready: Unknown`)

**Таймлайн удаления подов:**
1.  **Детекция**: Узел помечается как нездоровый.
2.  **Ожидание (Grace Period)**: По умолчанию поды имеют толерантность к этим taints в течение **300 секунд (5 минут)**. Это значение задается параметром `defaultTolerationSeconds` в `kube-controller-manager`.
3.  **Эвикция**: Если через 5 минут связь не восстановилась, контроллер начинает удаление подов для их пересоздания на других узлах.
4.  **PDB Check**: Контроллер проверяет PodDisruptionBudget. Если удаление нарушит бюджет, под остается (если не применена политика `unhealthyPodEvictionPolicy: AlwaysAllow`).

## Влияние на различные типы нагрузок

| Тип workload | Поведение при недоступности узла | Особенности |
| :--- | :--- | :--- |
| **Deployment** | Автоматическое пересоздание подов на здоровых узлах через ReplicaSet | Быстрое восстановление, не требует вмешательства |
| **StatefulSet** | Поды **НЕ** пересоздаются автоматически (защита от Split-brain) | Требуется `out-of-service` taint для безопасного восстановления |
| **DaemonSet** | Поды пересоздаются на других узлах (если есть ресурсы) | Может привести к избыточной нагрузке на оставшиеся узлы |
| **Job/CronJob** | Задачи не перезапускаются автоматически | Зависят от стратегии `restartPolicy` |
| **Persistent Volume** | Том остается привязанным к недоступному узлу (RWO) | Требуется `out-of-service` taint или ручное отмонтирование |

## Практические сценарии

### Основные причины (Root Causes)

| Причина | Типичный статус | Диагностический фокус |
| :--- | :--- | :--- |
| Сбой или остановка `kubelet` | `NotReady` / `Unknown` | [Проблемы Kubelet](./kubelet_issues.md) |
| Сетевая изоляция (Network Partition) | `Unknown` | [Проблемы с сетью](./network_issues.md) |
| Давление ресурсов (Pressure) | `NotReady` | [Давление ресурсов](./resource_pressure.md) |
| Сбой CRI-рантайма (containerd) | `NotReady` | [Проблемы рантайма](./runtime_issues.md) |
| Переход на cgroup v2 / Проблемы ОС | `NotReady` | Логи ядра (`dmesg`) |
| Аппаратный сбой (диск, сеть, питание) | `Unknown` | IPMI/BMC логи, физический осмотр |
| Блокировка firewall (порт 6443) | `Unknown` | Проверка маршрутизации и файрвола |
| Переполнение conntrack table | `Unknown` | `dmesg | grep conntrack` |

### Команды для быстрой проверки

- **Статус узлов и условия:**
  ```bash
  kubectl get nodes -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[?(@.type=="Ready")].status,REASON:.status.conditions[?(@.type=="Ready")].reason
  # → NAME    STATUS    REASON
  # → node1   True      KubeletReady
  # → node2   False     KubeletNotReady
  ```

- **Полная проверка всех Conditions:**
  ```bash
  kubectl describe node <node-name> | grep -A 20 "Conditions:"
  # → Ready               True    Mon, 01 Jan 2026 00:00:00 +0000   KubeletReady    kubelet is posting ready status
  # → MemoryPressure      False   Mon, 01 Jan 2026 00:00:00 +0000   KubeletHasMemory  kubelet has memory available
  ```

- **Проверка Heartbeats (Lease):**
  ```bash
  kubectl get lease -n kube-node-lease <node-name> -o yaml
  # Проверьте поле renewTime: оно должно обновляться каждые 10 секунд.
  # Если renewTime старше 40 секунд — узел будет помечен как Unknown.
  ```

- **События узла:**
  ```bash
  kubectl get events --field-selector involvedObject.kind=Node,involvedObject.name=<node-name> --sort-by='.lastTimestamp'
  # Ищите события с reason: NodeNotReady, NodeUnknown, TaintManagerEviction
  ```

- **Проверка Taints на узле:**
  ```bash
  kubectl get node <node-name> -o jsonpath='{.spec.taints}'
  # → [{"key":"node.kubernetes.io/unreachable","effect":"NoExecute","timeAdded":"..."}]
  ```

- **Проверка доступности API-сервера из узла:**
  ```bash
  ssh <node> "curl -sk https://<api-server>:6443/healthz"
  # → ok
  ```

### Мониторинг и алертинг

Для обнаружения недоступности узлов в продакшн-среде рекомендуется настроить метрики и алерты:

**Prometheus Metрики:**
- `kube_node_status_condition` — статус всех Conditions узла
- `kube_node_spec_taint` — наличие taints на узлах
- `kubelet_node_process_cpu_seconds_total` — нагрузка на CPU от kubelet

**Примеры алертов (PrometheusRule):**
```yaml
- alert: NodeNotReady
  expr: kube_node_status_condition{condition="Ready",status="true"} == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Узел {{ $labels.node }} не готов"
    description: "Узел находится в статусе NotReady более 5 минут"

- alert: NodeLeaseExpired
  expr: time() - kube_node_status_condition{condition="LeaseExpired"} > 300
  for: 1m
  labels:
    severity: warning
```

## Дополнительная информация

- [Taints и выселение при недоступности](./taints_and_eviction.md) — детальная логика работы контроллеров и настройка tolerations.
- [Диагностика недоступности узла](./diagnostics.md) — пошаговый чек-лист поиска неисправностей.
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — регламент планового вывода из кластера.
- [PodDisruptionBudget](../../../Autoscaling/pod_disruption_budget.md) — защитные бюджеты и их влияние на выселение.
- [Node Maintenance API (K8s docs)](https://kubernetes.io/docs/concepts/architecture/nodes/#node-maintenance) — официальная документация по новому API.
- [SELinux и AppArmor](./security_profiles.md) — профили MAC и их влияние на доступность узла.
- [Тюнинг ядра](./kernel_tuning.md) — sysctl, ulimit, conntrack для Kubernetes.
- [Синхронизация времени](./time_sync.md) — NTP, clock skew, влияние на TLS.
- [Hostname и DNS](./hostname_dns_issues.md) — настройка имени узла и DNS-резолва.
- [SSH-доступ и bastion](./bastion_ssh_access.md) — диагностика узлов через SSH.
