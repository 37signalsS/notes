# Apache YuniKorn: планировщик для batch и ML-нагрузок

**Актуально для:** Apache YuniKorn 1.9.x

## Определения

* **Apache YuniKorn** — лёгкий универсальный планировщик ресурсов для систем оркестрации контейнеров (Kubernetes и Apache Hadoop YARN). Название составлено из «Y» (YARN) + «K» (K8s) + «Uni» (Unified); произносится как «Unicorn». Распространяется под Apache License 2.0.
* **Иерархические очереди (Hierarchical Resource Queues)** — древовидная структура очередей, маппящаяся на организационную структуру компании. Каждая очередь имеет гарантированный (`guaranteed`) и максимальный (`max`) объём ресурсов.
* **Application-aware scheduling** — YuniKorn распознаёт пользователей, приложения и очереди и учитывает их при принятии решений (в отличие от стандартного планировщика, который планирует под-под без контекста).
* **Gang scheduling** — планирование группы подов как единого целого: все поды группы запускаются одновременно или не запускаются вовсе.
* **Reservation (резервирование)** — механизм автоматического резервирования ресурсов на подходящем узле для ожидающего запроса, защищающий большой запрос от «голодания» из-за мелких, менее требовательных подов.
* **Preemption** — вытеснение низкоприоритетных задач высокоприоритетными с учётом иерархии очередей и `PriorityClass` Kubernetes.

---

## Основные концепции

### Архитектура

```
YuniKorn Scheduler (заменяет/дополняет kube-scheduler)
     │
     ├── Scheduler Core — алгоритмы планирования (платформонезависимы)
     │
     ├── K8s Shim — трансляция ресурсов и запросов Kubernetes
     │
     ├── Admission Controller — валидация аннотаций/лейблов при создании подов
     │
     └── Web UI — централизованная пансть мониторинга очередей, приложений, нод
```

YuniKorn деплоится как альтернативный планировщик: поды привязываются к нему через поле `schedulerName: yunikorn`. Конфигурация загружается из ConfigMap и обновляется «на лету» (hot-reload) без перезапуска.

### Иерархические очереди

Конфигурация очередей — дерево с корневой очередью `root`. Для каждой очереди (кроме root) задаются:

* `parent: true` — промежуточная очередь;
* `resources.guaranteed` — гарантированный минимум (reserved capacity);
* `resources.max` — потолок (resource quota);
* `maxapplications` — лимит приложений в очереди;
* `adminacl` / `submitacl` — ACL на администрирование и на отправку заданий.

Квота применяется **рекурсивно**: дочерняя очередь никогда не может использовать больше, чем квота родительской. Сумма дочерних квот может превышать родительскую (overcommit за счёт `max`).

### Порядок обслуживания (Job Ordering)

Приложения в очереди упорядочиваются по политике: **FIFO**, **Fair** (справедливое разделение), **StateAware** или **Priority**. Очереди с настроенным `max` корректно ставят задания в очередь: при нехватке ресурсов задания ждут в линии, а не создают поды, которые застревают в `Pending`.

### Gang scheduling

Групповое планирование задаётся аннотациями на подах драйвера (например, Spark):

* `yunikorn.apache.org/task-group-name` — имя группы;
* `yunikorn.apache.org/task-groups` — JSON-массив групп с `minMember` (минимальное число членов) и `minResource` (минимальные ресурсы группы).

YuniKorn удерживает группу, пока не сможет разместить `minMember` членов с требуемыми ресурсами.

### Preemption и Reservation

* **Preemption**: высокоприоритетные задачи динамически перераспределяют ресурсы, вытесняя низкоприоритетные; интегрируется с `PriorityClass` Kubernetes и иерархической системой очередей.
* **Reservation**: если под не может быть размещён, YuniKorn резервирует ресурсы на подходящем узле и пробует разместить под на этом зарезервированном узле до перебора остальных — защита от «голодания» крупных запросов.

### Bin-packing и эластичность

YuniKorn поддерживает bin-packing (упаковку подов на минимальное число узлов) — снижает стоимость в облаке; при работе в облаке интегрируется с автоскейлерами для эластичности.

---

## Предварительные требования

| Компонент | Требование |
|-----------|------------|
| Kubernetes | 1.24+ (поддержка 1.35.x — с версии YuniKorn 1.9.0) |
| YuniKorn | 1.9.x (компоненты: scheduler, admission-controller, web) |
| Helm | для установки через Helm chart |

---

## Практические сценарии

### Установка

YuniKorn распространяется через Helm chart (репозиторий `apache/yunikorn-release`, каталог `helm-charts/yunikorn`) и prebuilt Docker-образы scheduler / admission-controller / web. После установки поды привязываются к планировщику полем `schedulerName`.

### Настройка иерархии очередей

```yaml
# ConfigMap с конфигурацией очередей (hot-reload)
apiVersion: v1
kind: ConfigMap
metadata:
  name: yunikorn-queue-config
  namespace: yunikorn
data:
  queues.conf: |
    partitions:
    - name: default
      queues:
      - name: root
        submitacl: '*'
        queues:
        - name: ml
          parent: true
          resources:
            guaranteed: { memory: "200G", vcore: 100 }
            max: { memory: "800G", vcore: 400 }
          queues:
          - name: training
            resources:
              guaranteed: { memory: "100G", vcore: 50 }
              max: { memory: "400G", vcore: 200 }
          - name: inference
            resources:
              guaranteed: { memory: "100G", vcore: 50 }
              max: { memory: "400G", vcore: 200 }
        - name: batch
          resources:
            guaranteed: { memory: "50G", vcore: 25 }
            max: { memory: "200G", vcore: 100 }
```

### Gang scheduling через аннотации (пример Spark)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: spark-driver
  annotations:
    yunikorn.apache.org/task-group-name: spark-driver
    yunikorn.apache.org/task-groups: '[
      {"name":"spark-driver","minMember":1,"minResource":{"cpu":"1","memory":"896Mi"}},
      {"name":"spark-executor","minMember":3,"minResource":{"cpu":"1","memory":"896Mi"}}
    ]'
spec:
  schedulerName: yunikorn
  containers:
  - name: spark
    image: spark:3.5
```

YuniKorn удержит driver и executors, пока не сможет разместить всю группу (1 driver + 3 executor) одновременно.

### Автоматический маппинг namespace → очередь

Вместо ручной маршрутизации можно ограничить namespace квотой через аннотации — YuniKorn автоматически создаёт очередь для namespace:

```bash
kubectl annotate namespace team-ml \
  yunikorn.apache.org/namespace.max.cpu="64" \
  yunikorn.apache.org/namespace.max.memory="100Gi"
```

### Проверка событий gang scheduling

```bash
kubectl get events --field-selector reason=GangScheduling
# → Normal  GangScheduling  20s  yunikorn  default/spark-driver is queued and waiting for allocation
```

---

## Проверка работы (валидация)

```bash
# Поды, запланированные YuniKorn
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.schedulerName=="yunikorn") | .metadata.name'

# Состояние очередей и приложений — через встроенный Web UI
kubectl port-forward -n yunikorn svc/yunikorn-web 9889:9889
# → YuniKorn UI доступен на http://localhost:9889

# Логи планировщика
kubectl logs -n yunikorn -l app=yunikorn-scheduler --tail=50
```

---

## Траблшутинг

| Симптом | Причина | Решение |
|---------|---------|---------|
| Поды остаются в `Pending` | Квота очереди исчерпана или `max` очереди/namespace слишком мал | Проверить `guaranteed`/`max` в ConfigMap; `kubectl describe queue` через UI |
| Gang не собирается | `minMember` × ресурсы не помещаются в квоту очереди | Увеличить `max` очереди или уменьшить `minMember` |
| Изменения конфигурации не применяются | ConfigMap не перечитан | YuniKorn поддерживает hot-reload — проверить, что ConfigMap привязан к scheduler; при необходимости перезапустить scheduler |
| ACL блокирует отправку | `submitacl` очереди не разрешает пользователю | Настроить `submitacl`/`adminacl` для очереди |

---

## Лучшие практики

* **Маппинг очередей на оргструктуру**: иерархия очередей должна повторять структуру команд/отделов — так квоты и ACL управляются на нужном уровне.
* **`guaranteed` vs `max`**: `guaranteed` — SLA команды, `max` — burst-потолок. Не ставьте `max` равным `guaranteed` — теряется эластичность.
* **Gang scheduling для распределённого обучения** — предотвращает фрагментацию: часть executors не запускается «впустую».
* **Bin-packing** для снижения облачных затрат; сочетайте с автоскейлером.
* **Web UI** как единое окно мониторинга загрузки очередей и tenants.

---

## Дополнительная информация

### Ограничения

* YuniKorn — полноценная замена `kube-scheduler` для подов с `schedulerName: yunikorn`; стандартные поды продолжают планироваться kube-scheduler (multi-scheduler режим).
* Настройка иерархии очередей и ACL — самая трудоёмкая часть внедрения по сравнению с Kueue.
* Поддерживает как K8s, так и YARN (через shim), но K8s-интеграция — основной сценарий.

### См. также

* [Kueue](./kueue.md) — более простая альтернатива для квот и очередей (встроенные API, без замены планировщика)
* [Volcano для batch-нагрузок](../Autoscaling/on_premise_autoscaling.md#volcano-для-batch-нагрузок) — gang scheduling + приоритетные очереди
* [KAI Scheduler](./kai_scheduler.md) — topology-aware GPU-планирование
* [Kube-scheduler](../Concepts/kube_scheduler.md) — стандартный планировщик
* [Обзор решений для планирования](./scheduling_solutions_overview.md) — матрица выбора
* [Официальная документация Apache YuniKorn](https://yunikorn.apache.org/)
