# Pod Disruption Budget (PDB)

## Определения

**Pod Disruption Budget (PDB)** — объект Kubernetes, ограничивающий количество подов, которые могут быть одновременно недоступны в результате добровольных прерываний.

**Добровольные прерывания (Voluntary Disruptions)** — плановые операции, инициируемые пользователем или системой:
* Drain узла (`kubectl drain`)
* Обновление Deployment (rolling update)
* Освобождение узла Cluster Autoscaler/Karpenter
* Обновление узлов кластера

**Недобровольные прерывания (Involuntary Disruptions)** — непредвиденные события, от которых PDB **не защищает**:
* Аппаратные сбои
* Паника ядра
* Сетевые проблемы
* Отключение питания

**Eviction API** — механизм Kubernetes для безопасного выселения подов с учётом PDB.

## Основные концепции

### Принцип работы

1. Пользователь или система инициирует операцию, требующую удаления пода (например, `kubectl drain`).
2. Kubernetes отправляет запрос к **Eviction API** (подзапрос к Pod).
3. PDB проверяет, не нарушит ли выселение пода бюджет доступности.
4. Если бюджет соблюдается — под выселяется немедленно.
5. Если бюджет нарушается — операция приостанавливается до восстановления доступности.

### Параметры конфигурации

| Параметр | Описание | Примеры |
|----------|----------|---------|
| `selector` | Метки подов, подпадающих под защиту | `matchLabels: app: web` |
| `minAvailable` | Минимальное количество/процент доступных подов | `3` или `50%` |
| `maxUnavailable` | Максимальное количество/процент недоступных подов | `1` или `25%` |

**Важно:** Можно указать только `minAvailable` **или** `maxUnavailable`, не оба одновременно.

### Округление процентов

При указании процентов значения всегда округляются **в большую** сторону:

| Реплик | `minAvailable: 30%` | `minAvailable: 35%` | `maxUnavailable: 25%` |
|--------|---------------------|---------------------|----------------------|
| 10 | 3 пода | 4 пода | 2 пода |
| 7 | 3 пода | 3 пода | 2 пода |
| 3 | 1 под | 2 пода | 1 под |

### Ограничения PDB

PDB **не защищает** от:
* Аппаратных сбоев
* Паники ядра
* Проблем с сетью
* Недобровольных прерываний любого типа
* Прямого удаления через `kubectl delete pod` (не использует Eviction API)

### Важные нюансы

* **PDB работает только с Eviction API** — при использовании `kubectl delete pod <name>` запрос Eviction не формируется, PDB не сработает.
* **DaemonSet** — применение PDB к DaemonSet не имеет смысла (один под на каждой ноде).
* **Jobs** — применение PDB к Jobs бессмысленно (Job должен завершиться).
* **Single Replica Deployment** — при `replicas: 1` и `minAvailable: 1` drain будет заблокирован. Используйте `minAvailable: 0` или удаляйте под вручную.
* **StatefulSet** — для StatefulSet используйте `maxUnavailable: 1` для последовательного обновления.

## Практические сценарии

### Сценарий 1: Базовый PDB с minAvailable

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
  namespace: default
spec:
  minAvailable: 80%  # Всегда доступно не менее 80% подов
  selector:
    matchLabels:
      app: web
```

### Сценарий 2: PDB с фиксированным количеством

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payment-service-pdb
spec:
  minAvailable: 3  # Всегда доступно не менее 3 подов
  selector:
    matchLabels:
      app: payment-service
```

### Сценарий 3: PDB с maxUnavailable (для StatefulSet)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-pdb
spec:
  maxUnavailable: 1  # Одновременно недоступен только 1 под
  selector:
    matchLabels:
      app: kafka-broker
```

### Сценарий 4: PDB для критического сервиса (5 реплик)

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: critical-api-pdb
spec:
  minAvailable: 4  # Из 5 реплик минимум 4 должны быть доступны
  selector:
    matchLabels:
      app: critical-api
      tier: backend
```

### Сценарий 5: PDB с процентом для масштабируемого приложения

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: scalable-app-pdb
spec:
  minAvailable: 66%  # Две трети подов всегда доступны
  selector:
    matchLabels:
      app: scalable-app
```

### Диагностика и мониторинг

#### Проверка статуса PDB

```bash
# Список всех PDB
kubectl get pdb -A

# Детальная информация
kubectl describe pdb web-pdb -n default

# Проверка ожидающих eviction
kubectl get events --field-selector reason=Eviction
```

#### Пример вывода `kubectl get pdb`

```
NAME          MIN AVAILABLE   CURRENT   DESIRED   ALLOWED DISRUPTIONS   AGE
web-pdb       80%             5         5         1                     10m
kafka-pdb     N/A             3         3         1                     5m
```

| Поле | Описание |
|------|----------|
| `MIN AVAILABLE` | Настроенный бюджет |
| `CURRENT` | Текущее количество доступных подов |
| `DESIRED` | Ожидаемое количество подов |
| `ALLOWED DISRUPTIONS` | Сколько подов можно удалить без нарушения PDB |

#### Проверка блокировок drain

```bash
# Drain узла с таймаутом
kubectl drain node-1 --timeout=30s

# Если PDB блокирует, будет ошибка:
# error: unable to drain node "node-1", aborting command:
# 
# There are pending nodes to be drained:
#  node-1
# error: cannot delete Pods with deletionCost set and PDB:
#  kube-system/vpa-recommender-xyz (deletionCost: 1000000)
```

### Лучшие практики

* **Создавайте PDB для production-сервисов** — обязательно для критичных приложений.
* **Учитывайте время запуска пода** — если под запускается долго, используйте `maxUnavailable: 1`.
* **Тестируйте перед production** — проверяйте поведение PDB при drain.
* **Используйте с Pod Anti-Affinity** — для максимальной отказоустойчивости.
* **Избегайте `minAvailable: 100%`** — это заблокирует любые плановые операции.
* **Для StatefulSet используйте `maxUnavailable: 1`** — обеспечивает последовательное обновление.
* **Мониторьте `ALLOWED DISRUPTIONS`** — значение 0 означает блокировку drain.

## Дополнительная информация

### Сценарии использования

| Сценарий | Описание |
|----------|----------|
| **Обновления узлов** | Предотвращение одновременной недоступности всех реплик при drain |
| **Масштабирование узлов** | Защита при освобождении узлов Cluster Autoscaler/Karpenter |
| **Обновления приложений** | Контроль rolling update Deployment |
| **Вертикальное масштабирование** | [VPA](vpa_detailed.md) использует PDB для минимизации прерываний |
| **Горизонтальное масштабирование** | [HPA](hpa_detailed.md) при масштабировании вниз учитывает PDB |

### Интеграции

* **[HPA](hpa_detailed.md)** — HPA учитывает PDB при масштабировании вниз.
* **[VPA](vpa_detailed.md)** — VPA использует PDB при eviction подов для обновления ресурсов.
* **[Cluster Autoscaler](cluster_autoscaler_detailed.md)** — CA проверяет PDB перед удалением узла.
* **[Karpenter](karpenter_detailed.md)** — Karpenter учитывает PDB при консолидации узлов.
* **[Pod Distribution](pod_distribution.md)** — совместное использование с Anti-Affinity для отказоустойчивости.
* **[Node Maintenance](../Operations/node_maintenance.md)** — drain использует Eviction API с учётом PDB.

### Эволюция PDB

| Версия Kubernetes | Изменения |
|-------------------|-----------|
| 1.4 | Введён PDB (API `policy/v1beta1`) |
| 1.21 | Стабилизация API `policy/v1` |
| 1.25 | Удаление `policy/v1beta1` |
| 1.32+ | Улучшенная обработка deletionCost |

### Ресурсы

* [Официальная документация Kubernetes: PDB](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)
* [Kubernetes Eviction API](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/#eviction-api)
