# Taints и Tolerations (Отравления и Терпимость): Управление размещением подов

## Определения

* **Taints (отравления)**: Механизм, применяемый к узлам Kubernetes, который «отталкивает» поды, не имеющие соответствующего `toleration`. Состоит из ключа (`key`), значения (`value`) и эффекта (`effect`).

    ```bash
    kubectl taint nodes <node-name> <key>=<value>:<effect>
    # Пример:
    kubectl taint nodes worker-1 dedicated=ml:NoSchedule
    # → node/worker-1 tainted
    # Пример удаления (дефис в конце):
    kubectl taint nodes worker-1 dedicated=ml:NoSchedule-
    ```

* **Tolerations (терпимость)**: Свойство, задаваемое в спецификации пода (`pod.spec`), которое позволяет ему «терпеть» `taint` на узле и быть размещённым на нём.
* **Node Controller (Контроллер узлов)**: Системный компонент Control Plane, который следит за состоянием узлов и автоматически накладывает Taints при аппаратных или сетевых сбоях.

### Эффекты Taint

* **`NoSchedule`**: Kubernetes не размещает на узле **новые** поды без `toleration`. Существующие поды продолжают работать.
* **`PreferNoSchedule`**: «Мягкая» версия `NoSchedule`. Kubernetes старается не размещать на узле новые поды без `toleration`, но сделает это при отсутствии альтернатив.
* **`NoExecute`**: Самый строгий эффект. Новые поды без `toleration` не размещаются, а существующие поды без `toleration` **вытесняются (evicted)**.

---

## Основные концепции

### Зачем нужны Taints и Tolerations?

В больших кластерах Kubernetes не все узлы одинаковы. Некоторые могут иметь специализированное оборудование (GPU), другие — быть выделены под конкретные задачи. Без механизмов ограничения планировщик может разместить любой под на любом свободном узле, что приведет к неэффективному использованию ресурсов или проблемам с производительностью. Основные сценарии применения:

1. **Выделение узлов для специфических задач**: Гарантия того, что дорогостоящие ресурсы (например, узлы с GPU) используются только теми подами, которым они действительно необходимы для работы (машинное обучение, обработка графики).
2. **Изоляция узлов для обслуживания или устранения неполадок**: Вы можете «испортить» (taint) узел, на котором проводится обслуживание, чтобы предотвратить планирование новых подов, при этом разрешая работу только критически важным нагрузкам (имеющим соответствующий `toleration`).
3. **Защита от проблемных узлов**: Если на узле возникают системные ошибки (проблемы с диском, сетью), Kubernetes автоматически применяет taints. Это позволяет запретить планирование новых подов на нестабильном оборудовании до тех пор, пока проблема не будет решена.
4. **Удаление подов с узлов (Eviction)**: Использование эффекта `NoExecute` позволяет принудительно выселить все поды с узла при обнаружении критических проблем.

### Как действуют запятнания и терпимость?

Механизм работает по принципу «отталкивания» и «допуска»:
* **Taint (Запятнание)** применяется к **узлу**. Оно сигнализирует планировщику, что узел «отталкивает» все поды, которые не имеют специфического разрешения.
* **Toleration (Терпимость)** применяется к **поду**. Она позволяет модулю игнорировать («терпеть») пятно на узле и быть запланированным на нем.

### Эффекты Taint и поведение подов

| Taint Effect | Поведение для **новых** подов (без toleration) | Поведение для **существующих** подов (без toleration) |
| :--- | :--- | :--- |
| `NoSchedule` | Не размещаются | Продолжают работать |
| `PreferNoSchedule` | Kubernetes старается не размещать | Продолжают работать |
| `NoExecute` | Не размещаются | Вытесняются (evicted) |

### Операторы Toleration

В `toleration` пода указывается оператор для сопоставления с `taint` узла:

* `operator: "Equal"`: `toleration` срабатывает, если `key`, `value` и `effect` точно совпадают с `taint`.
* `operator: "Exists"`: `toleration` срабатывает для любого `taint` с указанным `key` и `effect`, независимо от `value`. Если указан только `operator: "Exists"`, под стерпит **любые** taints на узле.

> **Важно**: `toleration` не гарантирует, что под попадёт именно на ноду с соответствующим `taint` — он лишь снимает запрет на размещение. Для направления пода на конкретную ноду используйте `nodeSelector` или `nodeAffinity`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  tolerations:
  - key: "key1"
    operator: "Equal"
    value: "value1"
    effect: "NoSchedule"
  - key: "key2"
    operator: "Exists"
    effect: "NoExecute"
```

### Стандартные Taints узлов (Taint-based Eviction)

Kubernetes автоматически применяет следующие `taints` к узлам:

| Taint | Описание | Условие (Condition) |
| :--- | :--- | :--- |
| `node.kubernetes.io/not-ready:NoExecute` | Узел не готов | `Ready=False` |
| `node.kubernetes.io/unreachable:NoExecute` | Узел недоступен | `Ready=Unknown` |
| `node.kubernetes.io/memory-pressure:NoSchedule` | Нехватка памяти | `MemoryPressure=True` |
| `node.kubernetes.io/disk-pressure:NoSchedule` | Нехватка диска | `DiskPressure=True` |
| `node.kubernetes.io/pid-pressure:NoSchedule` | Исчерпание PID | `PIDPressure=True` |
| `node.kubernetes.io/network-unavailable:NoSchedule` | Сеть недоступна | `NetworkUnavailable=True` |
| `node-role.kubernetes.io/control-plane:NoSchedule` | Узел управления | Роль Control Plane |

### Процесс выселения (Eviction Timeline)

При потере связи с узлом процесс выселения подов проходит следующие этапы:

1. **Обнаружение**: `node-controller` ждёт время, указанное в `--node-monitor-grace-period` (по умолчанию 40с).
2. **Маркировка**: Состояние узла меняется на `Unknown`, добавляется taint `unreachable:NoExecute`.
3. **Ожидание**: Поды без специфических `tolerations` начинают выселяться по истечении `tolerationSeconds` (по умолчанию 300с для стандартных taints `not-ready` и `unreachable`). Для каждого пода запускается индивидуальный таймер.
4. **Удаление**: Поды удаляются из API и планируются на другие узлы.

### Параметры Node Controller

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--node-monitor-grace-period` | 40s | Время до присвоения статуса `Unknown` |
| `--pod-eviction-timeout` | 5m | Интервал между попытками выселения (в современных версиях приоритет отдается логике `tolerationSeconds`) |

### Поведение DaemonSet

Начиная с Kubernetes 1.17, поды DaemonSet планируются стандартным планировщиком (kube-scheduler), но с определенными послаблениями:
* **Автоматические Tolerations:** DaemonSet Controller автоматически добавляет tolerations для `node.kubernetes.io/unreachable:NoExecute` и `node.kubernetes.io/not-ready:NoExecute` без таймаута (`tolerationSeconds: null`), чтобы агент сбора логов или CNI никогда не выселялся с проблемного узла.
* **Игнорирование изоляции:** DaemonSet автоматически получает `toleration` для `node.kubernetes.io/unschedulable:NoSchedule` (при `kubectl cordon`).
* **Control Plane:** Однако, для запуска DaemonSet на master-узлах (Control Plane) **необходимо явно** прописать `toleration` в манифесте, так как этот taint имеет пользовательскую (административную) природу.

### Сравнение с Affinity

* **Taints и Tolerations работают «от ноды»**: Нода «отталкивает» поды. Используется для изоляции ресурсов (GPU, выделенные узлы).
* **Node Affinity работает «от пода»**: Под «тянется» к нодам. Используется для выбора узлов по характеристикам (тип диска, зона).
* **Совместное использование**: Taints удерживают лишние поды, а Node Affinity гарантирует попадание нужных подов на правильные узлы. Подробнее в [Affinity и Anti-Affinity](./affinity.md).

---

## Практические сценарии

### Сценарий 1: Выделение узлов под специфические задачи (GPU)

Узлы с дорогостоящим оборудованием (GPU, FPGA, SSD) «отравляются», чтобы на них не попадали обычные поды. Это оптимизирует использование специализированного оборудования. Однако самих `tolerations` недостаточно для гарантии того, что под попадет именно на узел с GPU — они лишь снимают запрет. Для точного планирования необходимо комбинировать их с **Node Affinity**.

**Настройка узла:**
```bash
# Применение taint для защиты узла от посторонних нагрузок
kubectl taint nodes node1 gpu=true:NoSchedule
# Применение метки для притяжения нужных нагрузок
kubectl label nodes node1 gpu=true
```

**Настройка пода:**
Поды приложения, требующие GPU, должны иметь и терпимость, и аффинити:

```yaml
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: gpu
            operator: In
            values:
            - "true"
  tolerations:
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"
```

### Сценарий 2: Разрешение запуска на Control Plane

По умолчанию узлы управления имеют taint, запрещающий запуск рабочих подов. Чтобы запустить на них, например, агент мониторинга через `DaemonSet`:

```yaml
tolerations:
- key: "node-role.kubernetes.io/control-plane"
  operator: "Exists"
  effect: "NoSchedule"
```

### Сценарий 3: Управление временем выселения (Graceful Eviction)

Если под должен оставаться на недоступном узле дольше стандартных 5 минут (например, при кратковременных сбоях сети или для StatefulSet, который болезненно переносит смену хоста):

```yaml
tolerations:
- key: "node.kubernetes.io/unreachable"
  operator: "Exists"
  effect: "NoExecute"
  tolerationSeconds: 600 # 10 минут
```
*Для быстрого выселения (stateless микросервисы) можно установить `tolerationSeconds: 30`.*

### Сценарий 4: Динамическое управление и обслуживание (Maintenance)

Использование `taint` для временного вывода узла из планирования без его полной остановки, сохраняя при этом работу критических сервисов.

**Процесс обслуживания:**
1. **Применение taint**: Устанавливается запрет на новые поды, кроме критических.
   ```bash
   kubectl taint nodes worker-1 maintenance=true:NoSchedule
   ```
2. **Настройка критических подов**: Сервисы, которые должны продолжать работу во время обслуживания (или сам процесс обслуживания), снабжаются допуском:
   ```yaml
   tolerations:
   - key: "maintenance"
     operator: "Equal"
     value: "true"
     effect: "NoSchedule"
   ```
3. **Завершение работ**: Удаление taint (дефис в конце).
   ```bash
   kubectl taint nodes worker-1 maintenance=true:NoSchedule-
   ```

---

## Рекомендации (Best Practices)

* **Выделение специализированного оборудования**: Всегда используйте taints для узлов с GPU, SSD или FPGA. Это гарантирует, что дорогостоящие ресурсы не будут расходоваться на задачи общего назначения.
* **Упрощение ключей и значений**: Используйте четкие, краткие и понятные ключи (например, `gpu=true`, `env=prod`). Избегайте чрезмерно сложных конфигураций, которые затрудняют чтение и обслуживание манифестов.
* **Сочетание с Node Affinity**: Для максимальной точности используйте Taints для *отталкивания* лишних подов и Node Affinity для *притяжения* нужных подов к конкретным узлам. Это особенно важно для оборудования со специфическими конфигурациями.
* **Мониторинг эффективности**: Чрезмерное использование taints может привести к фрагментации кластера и недоиспользованию ресурсов. Используйте инструменты мониторинга (например, **Kubecost**) для анализа распределения ресурсов и оптимизации затрат.
* **Изоляция при сбоях (Проактивная защита)**: При обнаружении проблем на узле (например, перегрев, сбои диска) немедленно применяйте `NoSchedule` taint вручную, чтобы предотвратить деградацию новых рабочих нагрузок до выяснения причин.
* **Мгновенное выселение проблемных подов (`NoExecute`)**: Если узел был скомпрометирован (Security Breach) или на нем обнаружен сбой файловой системы, наложите `NoExecute` taint. Это немедленно "смахнёт" с узла все пользовательские поды без потери времени на Graceful Shutdown.
* **Взаимодействие с Pod Disruption Budget (PDB)**: Выселение по Taint `NoExecute` игнорирует PDB в старых версиях K8s, но начиная с K8s 1.31 выселения TaintManager обрабатываются более безопасно (добавляется условие `DisruptionTarget`).

---

## Дополнительная информация

* **DaemonSet**: По умолчанию игнорирует `NoSchedule` для `node.kubernetes.io/unschedulable`. Имеет встроенные tolerations для `node-role.kubernetes.io/master` и `node-role.kubernetes.io/control-plane` (эффект `NoSchedule`), поэтому работает на master-нодах без явной toleration в манифесте.
* **QoS классы**: Влияют на приоритет вытеснения при нехватке ресурсов. Подробнее в [QoS, Requests и Limits](./qos_limit_and_requests.md).
* **Диагностика**:

    ```bash
    # Вывод всех узлов с их taints (кастомные колонки)
    kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

    # Проверка taints на узле
    kubectl describe node <node-name> | grep Taints
    # → Taints:             dedicated=ml:NoSchedule

    # Проверка tolerations пода
    kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
    # → [{"key":"key1","operator":"Equal","value":"value1","effect":"NoSchedule"}]
    
    # Поиск причины зависания пода в Pending
    kubectl get events --field-selector reason=FailedScheduling
    # Пример ошибки: "0/3 nodes are available: 1 node(s) had untolerated taint {hardware: gpu}"
    ```

**См. также:**
* [Недоступность узла: Taints и выселение](../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md) — глубокий разбор аварийных ситуаций, связанных с `NoExecute` taints.