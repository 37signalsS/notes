# Обслуживание узлов Kubernetes: Cordon и Drain

## Определения

**Обслуживание узлов** — процесс безопасного вывода узла из эксплуатации для плановых работ (обновление ядра, перезагрузка, замена оборудования) с последующим возвратом в кластер.

**Cordon** — команда `kubectl cordon`, которая помечает узел как `unschedulable`. Планировщик прекращает размещение новых подов на этом узле. Статус узла: `SchedulingDisabled`.

**Drain** — команда `kubectl drain`, которая безопасно выселяет (evict) все поды с узла. Неявно выполняет `cordon` перед началом работы.

**Uncordon** — команда `kubectl uncordon`, которая снимает пометку `unschedulable` и возвращает узел в пул доступных для планирования.

## Основные концепции

### Команды управления узлами

| Команда | Назначение | Влияние на поды |
| :--- | :--- | :--- |
| `kubectl cordon <node>` | Запрет планирования новых подов | Существующие поды продолжают работу |
| `kubectl drain <node>` | Выселение всех подов с узла | Поды пересоздаются на других узлах |
| `kubectl uncordon <node>` | Возврат узла в работу | Новые поды могут быть размещены |

### Процесс безопасного обслуживания

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Cordon    │ →  │    Drain    │ →  │   Работы    │ →  │  Uncordon   │
│ (запрет)    │    │ (выселение) │    │  на узле    │    │  (возврат)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

1. **Cordon:** Изоляция узла от новых размещений
2. **Drain:** Безопасное выселение существующих подов
3. **Проведение работ:** Обслуживание самого узла
4. **Uncordon:** Возврат узла в кластер

### Нюансы команды `drain`

`kubectl drain` останавливается при обнаружении определённых условий. Требуются флаги:

| Флаг | Назначение | Когда использовать |
| :--- | :--- | :--- |
| `--ignore-daemonsets` | Игнорировать поды DaemonSet | Почти всегда (CNI, logging, monitoring) |
| `--delete-emptydir-data` | Удалять temporary данные | Если поды используют `emptyDir` |
| `--force` | Принудительное удаление | Для "голых" подов без контроллера |
| `--grace-period=<sec>` | Таймаут завершения подов | Контроль времени shutdown |
| `--timeout=<duration>` | Максимальное время drain | Ограничение общей длительности |

**Ограничения `drain`:**

* **DaemonSet:** Поды не переносятся (должны работать на всех узлах)
* **Static Pods:** Управляются kubelet, не через API
* **PodDisruptionBudget:** Drain уважает PDB и не нарушит доступность
* **Голые поды:** Без контроллера не будут пересозданы (требуется `--force`)

> **Важно:** Процесс `drain` уважает [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — если выселение нарушит минимальную доступность, команда остановится.

## Практические сценарии

### Стандартный вывод узла

**Шаг 1: Cordon**

```bash
kubectl cordon <node-name>
# node/<node-name> cordoned
```

**Шаг 2: Drain**

```bash
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

**Шаг 3: Проверка**

```bash
kubectl get nodes
# NAME           STATUS                     AGE
# node-1         Ready,SchedulingDisabled   10d
# node-2         Ready                      10d
```

**Шаг 4: Проведение работ**

```bash
# Подключение к узлу
ssh <node-name>

# Обновление системы
sudo apt update && sudo apt upgrade -y

# Перезагрузка
sudo reboot
```

**Шаг 5: Uncordon**

```bash
kubectl uncordon <node-name>
# node/<node-name> uncordoned
```

### Перенос подов на конкретный узел

`kubectl drain` не позволяет указать целевой узел напрямую. Решения:

#### Способ 1: Временное ограничение планирования

```bash
# 1. Запретить планирование на всех узлах, кроме целевого
kubectl cordon node-1
kubectl cordon node-2
# node-3 остаётся доступным

# 2. Выполнить drain исходного узла
kubectl drain node-source --ignore-daemonsets --delete-emptydir-data

# 3. Вернуть узлы в работу
kubectl uncordon node-1
kubectl uncordon node-2
```

> **Предупреждение:** Не рекомендуется для production — создаёт риск простоя при ошибках.

#### Способ 2: Node Affinity (рекомендуемый)

```bash
# 1. Добавить метку на целевой узел
kubectl label node <target-node> my-target-node=true

# 2. Обновить Deployment с nodeAffinity
kubectl patch deployment <app> --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/affinity",
   "value": {
     "nodeAffinity": {
       "requiredDuringSchedulingIgnoredDuringExecution": {
         "nodeSelectorTerms": [{
           "matchExpressions": [{
             "key": "my-target-node",
             "operator": "In",
             "values": ["true"]
           }]
         }]
       }
     }
   }
  }
]'

# 3. Перезапустить поды
kubectl rollout restart deployment <app>

# 4. Выполнить drain
kubectl drain <source-node> --ignore-daemonsets --delete-emptydir-data
```

### Проверка статуса узла

```bash
# Статус всех узлов
kubectl get nodes -o wide

# Детальная информация
kubectl describe node <node-name>

# Проверка тентов
kubectl get node <node-name> -o jsonpath='{.spec.taints}'

# Поды на узле
kubectl get pods --all-namespaces -o wide --field-selector spec.nodeName=<node-name>
```

## Дополнительная информация

### Автоматизация обслуживания

| Инструмент | Назначение |
| :--- | :--- |
| **Cluster Autoscaler** | Автоматическое масштабирование node groups в облаках |
| **Kured** | Автоматическая перезагрузка узлов при kernel updates |
| **Draino** | Автоматический drain узлов по условиям (taints, labels) |
| **Lens** | GUI для мониторинга состояния узлов и подов |

### Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Drain завис** | `kubectl get pods -A \| grep Terminating` | Проверить PDB, finalizers |
| **PDB violation** | `kubectl get pdb` | Увеличить `minAvailable` или подождать |
| **DaemonSet блокирует** | `kubectl drain` выводит ошибку | Добавить `--ignore-daemonsets` |
| **EmptyDir data loss** | Предупреждение о потере данных | Добавить `--delete-emptydir-data` |
| **Голые поды** | `unable to drain with unmanaged pods` | Проверить поды, добавить `--force` |

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Проверка PDB** | Убедиться, что PDB настроены корректно перед drain |
| **Очередь обслуживания** | Выводить узлы по очереди с ожиданием миграции подов |
| **Мониторинг** | Отслеживать метрики кластера во время обслуживания |
| **Backup** | Резервное копирование критических данных перед работами |
| **Тестирование** | Отработать процедуру на staging-кластере |

### Связанные темы

* [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — защита доступности при выселении
* [Обновление кластера](upgrading_clusters.md) — обслуживание узлов при обновлении
* [Высокая доступность](../Base/high_availability.md) — отказоустойчивость при потере узла
* [Affinity и Anti-Affinity](../Scheduling/affinity.md) — управление размещением подов
* [Troubleshooting: Node Unavailability](../Troubleshooting/Common_Errors/NodeUnavailability/maintenance.md) — диагностика проблем
