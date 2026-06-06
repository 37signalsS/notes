# Cluster Autoscaler (CA)

## Определения

**Cluster Autoscaler (CA)** — компонент Kubernetes для автоматического изменения размера кластера путём добавления или удаления узлов (виртуальных машин) в зависимости от потребности в ресурсах.

**Node Group** — группа однотипных узлов с одинаковыми характеристиками (CPU, RAM, тип инстансов), управляемая как единый пул ресурсов.

**Scale-Up** — процесс добавления новых узлов в кластер при нехватке ресурсов для размещения подов.

**Scale-Down** — процесс удаления слабо утилизированных узлов из кластера при избытке ресурсов.

## Основные концепции

### Принцип работы

#### Масштабирование вверх (Scale-Up)

CA добавляет новый узел, если обнаруживает поды в состоянии `Pending`, которые не могут быть размещены из-за нехватки ресурсов (CPU, RAM, GPU).

**Процесс:**

1. Обнаруживаются `Pending` поды.
2. CA проверяет заранее определённые **группы узлов (Node Groups)** и симулирует, поможет ли добавление нового узла из одной из этих групп разместить поды.
3. Если да, CA отправляет запрос в API облака на создание нового узла в рамках выбранной группы.

#### Масштабирование вниз (Scale-Down)

CA удаляет узел, если он одновременно:

1. **Слабо утилизирован** в течение определённого времени (по умолчанию 10 минут, порог утилизации < 50%).
2. Все его поды **могут быть безопасно перемещены** на другие узлы.

### Компоненты архитектуры

* **Cluster Autoscaler** — основной контроллер, работающий как Deployment в namespace `kube-system`.
* **Cloud Provider Integration** — интеграция с облачным провайдером (AWS Auto Scaling Groups, GCP Instance Groups, Azure VM Scale Sets).
* **Expander** — стратегия выбора группы узлов при масштабировании вверх.

### Стратегии выбора узлов (Expander)

| Стратегия | Описание |
|-----------|----------|
| `random` | Случайный выбор (по умолчанию) |
| `most-pods` | Выбор группы с наибольшим количеством подов |
| `least-waste` | Минимизация отходов ресурсов (наилучшее соответствие) |
| `price` | Выбор наименее дорогой группы (для spot-инстансов) |
| `priority` | Выбор по приоритету (настраивается пользователем) |

### Ключевые параметры конфигурации

| Параметр | Значение по умолчанию | Описание |
|----------|----------------------|----------|
| `--scan-interval` | `10s` | Интервал сканирования кластера |
| `--scale-down-utilization-threshold` | `0.5` | Порог утилизации узла для удаления |
| `--scale-down-unneeded-time` | `10m` | Время слабой утилизации перед удалением |
| `--scale-down-unready-time` | `20m` | Время ожидания готовности нового узла перед удалением |
| `--max-node-provision-time` | `15m` | Максимальное время создания узла |
| `--skip-nodes-with-local-storage` | `true` | Запрет удаления узлов с `hostPath`/`emptyDir` |
| `--balance-similar-node-groups` | `false` | Балансировка похожих групп узлов |
| `--expander` | `random` | Стратегия выбора группы узлов |

## Практические сценарии

### Развёртывание Cluster Autoscaler

#### On-premises (bare-metal)

Для bare-metal окружений CA требует интеграции с инструментами управления инфраструктурой:

* **Metal3** — provisioning металлических серверов
* **Tinkerbell** — автоматизация развёртывания железа
* **MAAS** (Metal as a Service) от Canonical

### Аннотации для управления CA

| Аннотация | Значение | Описание |
|-----------|----------|----------|
| `cluster-autoscaler.kubernetes.io/scale-down-disabled` | `"true"` | Запрещает удаление узла |
| `cluster-autoscaler.kubernetes.io/safe-to-evict` | `"false"` | Запрещает выселение подов с узла |
| `cluster-autoscaler.kubernetes.io/skip-scale-up` | `"true"` | Пропускает масштабирование вверх для группы |

**Пример использования:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: critical-stateful-pod
  annotations:
    cluster-autoscaler.kubernetes.io/safe-to-evict: "false"
spec:
  containers:
  - name: app
    image: my-app:latest
```

### Диагностика и мониторинг

#### Проверка статуса CA

```bash
# Просмотр логов Cluster Autoscaler
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=100

# Проверка событий масштабирования
kubectl get events -n kube-system --field-selector reason=ScaleUp
kubectl get events -n kube-system --field-selector reason=ScaleDown
```

#### Метрики для мониторинга

| Метрика | Описание |
|---------|----------|
| `cluster_autoscaler_cluster_safe_to_autoscale` | Готовность кластера к автомасштабированию |
| `cluster_autoscaler_scaled_up_nodes_total` | Количество добавленных узлов |
| `cluster_autoscaler_scaled_down_nodes_total` | Количество удалённых узлов |
| `cluster_autoscaler_pending_pods_count` | Количество подов в состоянии Pending |
| `cluster_autoscaler_unschedulable_pods_count` | Количество подов, которые не могут быть размещены |

### Лучшие практики

* **Используйте несколько Node Groups** — разделяйте узлы по типам нагрузки (GPU, memory-optimized, compute-optimized) для гранулярного управления.
* **Настройте `--expander=least-waste`** — для оптимизации затрат и утилизации ресурсов.
* **Масштабирование до нуля** — для тестовых и пакетных задач установите `min-size: 0` в группе узлов.
* **PDB для критических приложений** — всегда создавайте [PodDisruptionBudget](pod_disruption_budget.md) для обеспечения доступности при scale-down.
* **Правильные `requests`** — CA и HPA основывают решения на `requests`, а не на фактическом потреблении.
* **Monitor Pending Pods** — настройте алерты на поды в состоянии `Pending` более 5 минут.
* **Используйте spot-инстансы** — для fault-tolerant рабочих нагрузок с `--expander=price`.

## Дополнительная информация

### Интеграции

CA работает в связке с другими компонентами экосистемы Kubernetes: [HPA](HPA/index.md) и [KEDA](./keda/keda_concepts.md) создают поды, которые триггерят масштабирование CA, [VPA](vpa_detailed.md) оптимизирует `requests` для улучшения работы CA, а **[Karpenter](./Karpenter/overview.md)** является альтернативой CA. При scale-down CA учитывает [Pod Disruption Budget](pod_disruption_budget.md), а правила [распределения подов](../Scheduling/affinity.md) влияют на возможность удаления узла.

### Ограничения

* **Задержка масштабирования** — создание нового узла занимает 3–15 минут в зависимости от облака.
* **Требует облачной интеграции** — для bare-metal нужны дополнительные инструменты (Metal3, Tinkerbell, MAAS).
* **Не работает с DaemonSet** — CA не учитывает DaemonSet при расчёте утилизации.
* **Масштабирование до нуля** — требует специальной настройки и не всегда поддерживается.

### Сравнение с Karpenter

Karpenter является современной альтернативой Cluster Autoscaler для облачных сред. Подробное сравнение характеристик, преимуществ и архитектурных отличий приведено в разделе **[Отличия от Cluster Autoscaler](./Karpenter/overview.md#отличия-от-cluster-autoscaler)**.
