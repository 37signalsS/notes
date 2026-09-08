# Устранение неполадок Deployment и RollingUpdate

Руководство по диагностике и решению проблем, возникающих при развертывании и обновлении stateless-приложений в Kubernetes: теория механики зависаний, системный алгоритм поиска причины и экстренные процедуры восстановления.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+, стабильная группа `apps/v1`).
- Установленный `kubectl` с доступом к кластеру и правами на `get`, `describe`, `logs`, `events`, `rollout`, `scale`, `annotate`, `wait`, `auth`.
  - Команда `kubectl events` доступна начиная с kubectl v1.24 (ранее — `kubectl alpha events`). Универсальный вариант — `kubectl get events`.
- Базовое понимание объектов [Deployment](./index.md), [Pod](../Pod/pod_overview.md) и [ReplicaSet](../replicaset.md), а также полей манифеста ([Манифест и лучшие практики](./deployment_manifest.md)).
- Для продвинутой диагностики: доступ к узлам (SSH), понимание [ResourceQuota/LimitRange](../../Scheduling/qos_limit_and_requests.md) и установленный `jq` для работы с JSON-выводом.
- Для анализа алертов и метрик: Prometheus + kube-state-metrics (см. [Kubernetes-алерты](../../../Grafana/alerting/kubernetes_alerts.md)).

## 1. Определения

**Зависшее обновление (Stuck Rollout)** — состояние объекта Deployment, при котором процесс перехода на новую версию (RollingUpdate) останавливается и не завершается в течение времени, заданного в `progressDeadlineSeconds`.

**ProgressDeadlineExceeded** — условие (`Condition`) в статусе Deployment (`type: Progressing`, `status: "False"`, `reason: ProgressDeadlineExceeded`), указывающее на то, что контроллер не смог завершить обновление в отведенный срок.

**ReplicaFailure** — состояние, сигнализирующее о невозможности контроллера создать поды (например, из-за нехватки прав, нарушения квот или ошибок планирования).

**observedGeneration** — значение `metadata.generation`, которое контроллер успел «заметить» и применить. Если `status.observedGeneration < metadata.generation`, контроллер еще не обработал последнее изменение спецификации — обновление технически даже не началось.

**Каскадный отказ (Cascading Failure)** — ситуация, когда сбой в одном компоненте (например, ConfigMap, Secret, PersistentVolume) вызывает цепочку перезапусков и зависание всего обновления.

**Зависший под в Terminating** — под, помеченный на удаление, но не завершившийся в течение `terminationGracePeriodSeconds` (причины: бесконечный `preStop`, finalizer, зависший kubelet). Блокирует масштабирование вниз старого ReplicaSet и, как следствие, rollout.

## 2. Основные концепции

### Зависшее обновление как механизм защиты

Зависшее обновление в Kubernetes — это **механизм защиты**, а не просто сбой. Контроллер Deployment намеренно приостанавливает процесс, если новые поды не проходят проверку готовности. Это предотвращает «выжигание» рабочей нагрузки: старые (здоровые) поды не удаляются, пока новые не подтвердят работоспособность.

### Контроллер не откатывает сам: повторные попытки

Важное теоретическое уточнение: после истечения `progressDeadlineSeconds` контроллер **не выполняет автоматический откат** и **не останавливает** попытки применить желаемое состояние. Он лишь выставляет condition `Progressing=False` с `reason=ProgressDeadlineExceeded` и продолжает повторные попытки (Reconcile Loop). Kubernetes «не предпринимает никаких действий», кроме публикации состояния, — восстановление всегда требует внешнего вмешательства оператора (откат, `rollout restart`, исправление конфигурации). Автоматический откат заявлен как будущая функциональность, рассчитывать на него нельзя.

Из этого следуют два операционных вывода:

1. Зависший rollout **сам по себе не завершится** и не навредит старым подам — триггер на восстановление обязан строить человек или CI/CD-автоматизация.
2. Условие `ProgressDeadlineExceeded` — это сигнал для алертинга и pipeline'ов (см. раздел «Мониторинг и алертинг»), а не штатное завершение процесса.

### Иерархия диагностики

Диагностику Deployment следует проводить по уровням — от симптома к корневой причине:

1. **Уровень 1 — Симптом:** `kubectl rollout status` не показывает прогресса.
2. **Уровень 2 — Conditions:** Анализ `status.conditions` в Deployment.
3. **Уровень 3 — ReplicaSet:** Проверка распределения реплик между старым и новым RS.
4. **Уровень 4 — Pod:** Глубокий анализ конкретных подов (события, логи, статус, init-контейнеры).
5. **Уровень 5 — Инфраструктура:** Узел, сеть, хранилище, квоты.

### Три режима зависания (точка отказа)

Прежде чем глубоко копать, определите, на каком этапе застрял процесс. Это сильно сужает поиск:

| Режим | Признак | Типовая причина | Что проверить в первую очередь |
| :--- | :--- | :--- | :--- |
| **A. Обновление не началось** | `rollout status` пишет «Waiting for deployment spec update to be observed...»; **новый RS не создан** | `observedGeneration < generation` (контроллер не увидел изменение), `paused: true`, изменение не в `template` | `observedGeneration`, флаг `paused`, история RS |
| **B. Новые поды не становятся Ready** | Новый RS создан, но `CURRENT > READY`; поды в `Pending`/`ImagePullBackOff`/`CrashLoopBackOff`/`Ready 0/1` | Пробы, образ, ресурсы, квоты, scheduling | Поды нового RS, их события и логи |
| **C. Старые поды не удаляются** | Новый RS достиг `READY`, но старый RS не масштабируется вниз (`DESIRED > 0`) | Поды застряли в `Terminating` (preStop/finalizer), kubelet не отвечает | Поды в `Terminating`, событие `FailedKillPod` |

### Параметры, влияющие на процесс обновления

| Параметр | Роль при сбое | Критическая ситуация |
| :--- | :--- | :--- |
| **`maxUnavailable`** | Определяет допустимую потерю мощности | При `0` контроллер не удалит ни одного старого пода, пока новый не станет `Ready`. Если ресурсы кластера на пределе, обновление застрянет. |
| **`maxSurge`** | Определяет временный всплеск ресурсов | Высокое значение ускоряет выкатку, но может вызвать срабатывание `ResourceQuota` или нехватку CPU/RAM на узлах. |
| **`minReadySeconds`** | Задержка признания пода «здоровым» | Позволяет выявить ошибки, возникающие не сразу после старта (например, утечки при инициализации). |
| **`progressDeadlineSeconds`** | Таймер ожидания успеха | По истечении этого времени (по умолчанию 600с) контроллер выставляет `Progressing=False` с `reason=ProgressDeadlineExceeded` и продолжает попытки. Должен быть **больше** `minReadySeconds` — при нарушении условие срабатывает сразу. |

### Условия (Conditions) в статусе Deployment

Каждое условие содержит поля: `type`, `status` (`True`/`False`/`Unknown`), `reason` (машиночитаемый код), `message` (человекочитаемое пояснение), `lastUpdateTime` и `lastTransitionTime`. Полезно понимать полный набор метаданных статуса: `observedGeneration`, `replicas`, `readyReplicas`, `availableReplicas`, `updatedReplicas`.

| Тип условия | `True` означает | Частые `reason` |
| :--- | :--- | :--- |
| **`Available`** | Достигнута минимальная доступность реплик | `MinimumReplicasAvailable` (True); `MinimumReplicasUnavailable` (False) |
| **`Progressing`** | Контроллер выполняет rollout | `NewReplicaSetAvailable` (успех); `DeploymentPaused` (пауза); `ReplicaSetCreateError`, `TimedOutReplicaSet` (False); **`ProgressDeadlineExceeded`** |
| **`ReplicaFailure`** | Имеются сбои при создании подов | Агрегируется из событий ReplicaSet (`FailedCreate`, `FailedScheduling`) |

Комбинированный анализ: `Available=False` + `Progressing=False` + `ProgressDeadlineExceeded` — приложение полностью недоступно и обновление провалено. `Available=True` + `Progressing=False` + `ProgressDeadlineExceeded` — старые поды продолжают работать, но rollout провален (самый частый «зависший» сценарий).

### Взаимодействие с PodDisruptionBudget (PDB)

PDB и `maxUnavailable` в Deployment — это **разные механизмы**, которые могут конфликтовать:

- **Deployment `maxUnavailable`**: контроллер сам решает, сколько подов может быть недоступно во время RollingUpdate.
- **PodDisruptionBudget**: внешний запрет на одновременное удаление подов (для защиты от Eviction, drains, upgrades).

**Ключевое различие:** PDB блокирует **только вытеснение (eviction)** — например, `kubectl drain` узла. На масштабирование ReplicaSets во время обычного rollout контроллер Deployment PDB не смотрит, поэтому сам по себе PDB не заблокирует обновление. Конфликт возникает, когда **drain узла** происходит одновременно с обновлением: PDB с `minAvailable: 3` не даст выселить поды ниже бюджета, обновление застрянет, а событие `Eviction`/`PodDisruptionBudget` появится у пода.

> Подробнее о механиках дедлоков PDB и их разрешении см. в [Проблемы завершения: блокировка PDB](../../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md) и [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).

## 3. Практические сценарии

### Алгоритм диагностики при зависании (Rollout Stuck)

Если команда `kubectl rollout status deployment <name>` не показывает прогресса, следуйте системному алгоритму.

#### Шаг 0: Определить характер зависания

Сначала выясните, на каком режиме (A/B/C из раздела «Три режима зависания») находится rollout:

```bash
# Сгенерированное поколение и обработанное контроллером
kubectl get deploy <name> -o jsonpath='observedGeneration={.status.observedGeneration} generation={.metadata.generation}{"\n"}'

# Пауза?
kubectl get deploy <name> -o jsonpath='paused={.spec.paused}{"\n"}'

# Список RS: есть ли новый кандидат?
kubectl get rs -l app=<your-app-label>
```

- `observedGeneration < generation` → режим **A**: контроллер не увидел изменение. Проверьте флаг `paused` и корректность `metadata.generation` (изменялся ли именно `spec.template`).
- Новый RS создан, но реплики не готовы → режим **B**: переходите к шагам 2–3.
- Новый RS полностью готов, но старый не сворачивается, поды в `Terminating` → режим **C**: см. раздел «Поды не завершаются (Terminating)».

#### Шаг 1: Инспекция объекта Deployment

```bash
kubectl describe deployment <name>
```

Ищите в секции `Conditions`:
- **Type=Progressing, Status=False, Reason=ProgressDeadlineExceeded**: Обновление официально признано проваленным (контроллер продолжает попытки).
- **Type=Progressing, Reason=DeploymentPaused**: вовремя не выполнен `kubectl rollout resume`.
- **Type=Available, Status=False, Reason=MinimumReplicasUnavailable**: приложение недоступно для пользователей.
- **Type=ReplicaFailure**: контроллер не может создать поды.

```bash
# Машиночитаемый вывод условий (для скриптов)
kubectl get deploy <name> -o jsonpath='{range .status.conditions[*]}{.type}={.status} reason={.reason}{"\n"}{end}'
```

#### Шаг 2: Анализ ReplicaSets

Deployment создает новый `ReplicaSet` (RS) для каждой ревизии. Проверьте количество реплик в новом RS:

```bash
kubectl get rs -l app=<your-app-label>
# → NAME                        DESIRED   CURRENT   READY   AGE
# → my-app-7f6f8d6f5d          1         1         0       2m     ← новый
# → my-app-5c6b7c8d9e          3         3         3       1h     ← старый
```

Интерпретация колонок (см. также [Анализ полей ReplicaSet](./lifecycle_management.md)):
- Если в новом RS `DESIRED > CURRENT` или `CURRENT > READY` — проблема на уровне создания или готовности подов (режим **B**).
- Если новый RS `READY` полный, но старый `DESIRED > 0` — проблема завершения старых подов (режим **C**).

Детальная информация по конкретному RS:
```bash
kubectl describe rs <new-rs-name>
# → Events содержит FailedCreate / FailedScheduling от ReplicaSet-контроллера
```

#### Шаг 3: Глубокая диагностика подов

```bash
# Список подов (метка pod-template-hash помогает отличить ревизии)
kubectl get pods -l app=<label> -o wide

# Детальный осмотр проблемного пода
kubectl describe pod <new-pod-name>

# Логи текущего запуска
kubectl logs <new-pod-name>

# Логи предыдущего запуска (если контейнер падает и перезапускается)
kubectl logs <new-pod-name> --previous

# Логи init-контейнера (статусы Init:Error, Init:CrashLoopBackOff)
kubectl logs <new-pod-name> -c <init-container-name>
```

Особые статусы подов, характерные для rollout:
- `Pending` — не удалось запланировать (resources/taints/affinity). См. [Диагностика Pod Pending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md).
- `Init:CrashLoopBackOff` / `Init:Error` — падает подготовительный контейнер (миграции, ожидание зависимостей).
- `Ready 0/1` — не проходит `readinessProbe` (раздел «Проблемы с пробами»).
- `Terminating` — не завершается (раздел «Поды не завершаются (Terminating)»).
- `OOMKilled` — превышение `limits.memory`, exit code 137. См. [Анализ OOMKilled](../../Troubleshooting/Common_Errors/oomkilled_pods.md).

#### Шаг 4: Проверка событий кластера

```bash
# События конкретного пода
kubectl events --for pod/<pod-name> --watch        # kubectl >= 1.24
kubectl get events --field-selector involvedObject.name=<pod-name> -A

# События уровня неймспейса за последние 10 минут
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -20

# События, связанные с конкретным Deployment (только верхнеуровневые)
kubectl get events --field-selector involvedObject.name=<deployment-name>,involvedObject.kind=Deployment

# События по конкретной причине (справедливо и для FailedCreate, FailedScheduling)
kubectl get events -n <namespace> --field-selector reason=ProgressDeadlineExceeded
```

Важное различие уровней событий:
- Событие `ScalingReplicaSet` (deployment-controller) — контроллер принял решение масштабировать RS. Наличие события без результата → смотрим ниже.
- Событие `FailedCreate` (replicaset-controller) — не удалось создать под (квота, RBAC, схема). Это ключевое событие уровня ReplicaSet.
- События пода (`FailedScheduling`, `FailedMount`, `Warning`) — собственно причина на самом нижнем уровне.

#### Шаг 5: Проверка квот и ресурсов

```bash
# Текущее потребление квот в неймспейсе
kubectl describe quota -n <namespace>

# Доступные ресурсы на узлах
kubectl top nodes

# Поды, которые не могут быть запланированы (Pending)
kubectl get pods --field-selector=status.phase=Pending -n <namespace>
kubectl describe pod <pending-pod>  # → Events: "Insufficient cpu" или "node(s) had taint"

# Состояние узла (MemoryPressure, DiskPressure, PIDPressure)
kubectl describe node <node-name>
```

### Типичные ошибки и их решение

| Статус / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`Pending`** | Нехватка ресурсов, Taints, Affinity | `kubectl describe pod` → проверить Events. Увеличить ресурсы или уменьшить `requests`. См. [Pod Pending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md). |
| **`ImagePullBackOff`** | Ошибка реестра, неверный тег, отсутствие `imagePullSecrets` | Проверить имя образа, секрет доступа. См. [Ошибки загрузки образов](../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md). |
| **`CrashLoopBackOff`** | Ошибка приложения, мисконфигурация | `kubectl logs <pod> --previous`; изучить exit code. См. [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md). |
| **`Init:CrashLoopBackOff` / `Init:Error`** | Падает подготовительный контейнер | `kubectl logs <pod> -c <init-container> --previous`, проверить миграции и ожидание зависимостей. |
| **`Running (Ready 0/1)`** | Не проходит `readinessProbe` | Проверить логи, порт и путь пробы. Убедиться, что приложение слушает на ожидаемом порту. См. [Пробы](../probes.md). |
| **`OOMKilled`** | Превышение `limits.memory` | Увеличить лимит памяти. См. [Анализ OOMKilled](../../Troubleshooting/Common_Errors/oomkilled_pods.md). |
| **`CreateContainerConfigError`** | Ссылка на несуществующий ConfigMap/Secret | Проверить имена: `kubectl get configmap`, `kubectl get secret`. См. [CreateContainerConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/definitions.md). |
| **`Unhealthy` (livenessProbe)** | Приложение зависло или упало | `kubectl describe pod` → Last State → Exit Code. Читать логи, проверять дедлоки. |
| **`FailedScheduling`** | Нет подходящих узлов (Taints, Affinity, ресурсы) | Проверить `kubectl describe pod` → Events: "Insufficient cpu/memory", "node(s) had taint". |
| **`Evicted`** | Kubelet вытеснил под из-за давления на узле | Проверить `kubectl describe node <node>` → Conditions: MemoryPressure, DiskPressure. |
| **`ReplicaFailure`** | Контроллер не может создать под (квота, RBAC, PDB) | Проверить `kubectl describe deployment` → Conditions → Reason=ReplicaFailure. |
| **`Terminating`** (завис) | `preStop`, finalizer, зависший kubelet | См. раздел «Поды не завершаются (Terminating)». |

### Специфические проблемы

#### Конфликт с PodDisruptionBudget

Если обновление проходит, но во время него начался drain узла, PDB может заблокировать удаление старых подов:

```bash
# Проверить PDB, влияющие на поды вашего Deployment
kubectl get pdb -n <namespace>
kubectl describe pdb <pdb-name>

# Проверить, какие поды защищены PDB
kubectl get pods -l app=<label> -o json | jq '.items[].metadata.labels'

# Подтверждение блокировки eviction
kubectl get events -n <namespace> --field-selector reason=PodDisruptionBudget,reason=Evicted
```

**Решение:** Убедитесь, что `maxUnavailable` в Deployment и `minAvailable` в PDB совместимы. Например, если PDB требует `minAvailable: 3` из 5 подов, то `maxUnavailable` не должен превышать 1. При плановых работах на узлах связывайте во времени rollout и drain, либо временно ослабляйте PDB (`spec.unhealthyPodEvictionPolicy: AlwaysAllow` — см. [блокировка PDB](../../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md)).

#### Проблемы с ConfigMap и Secret

Если новая версия ссылается на ConfigMap/Secret, которого не существует, поды не запустятся (в статусе пода — `CreateContainerConfigError`):

```bash
# Проверить наличие ConfigMap и Secret
kubectl get configmap <name> -n <namespace>
kubectl get secret <name> -n <namespace>

# Проверить, что поды могут смонтировать тома
kubectl describe pod <pod-name> | grep -A5 "Mounts:"
kubectl describe pod <pod-name> | grep -A5 "Events:"
```

**Типичная ошибка:** `Warning FailedMount` при монтировании тома из ConfigMap. Причины: ConfigMap/Secret не существует в неймспейсе пода, ссылка на несуществующий ключ (`key`) или недопустимое имя ключа (для томов запрещено начинаться с `.`). Решение: сверьте имя объекта и имя ключа в манифесте.

**Ограничения имен ключей:** значения, передаваемые через `env`/`envFrom`, должны быть валидными C-идентификаторами (без дефисов, начинаться с буквы или `_`). Ключ вида `my-key` работает как файл в томе, но не как переменная окружения.

**Важный нюанс:** изменение содержимого уже существующего ConfigMap/Secret **не инициирует Rollout** — поды продолжат работать со старой конфигурацией (тома обновляются kubelet'ом с задержкой, переменные окружения — только при пересоздании). Применяйте `kubectl rollout restart deployment/<name>`.

#### Проблемы с RBAC и ServiceAccount

Если приложению нужен доступ к API Kubernetes во время rollout (например, операторы, миграции), отсутствие прав приведет к падению новых подов:

```bash
# Проверить, какой ServiceAccount используется подом
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Проверить, существует ли ServiceAccount
kubectl get serviceaccount <name> -n <namespace>

# Проверить RoleBinding/ClusterRoleBinding
kubectl get rolebinding,clusterrolebinding -A | grep <name>

# Быстрая проверка прав от имени служебного аккаунта
kubectl auth can-i list secrets --as system:serviceaccount:<namespace>:<sa-name>
```

Подробный алгоритм — в [Ошибки доступа (RBAC)](../../Troubleshooting/Common_Errors/ApiAccessForbidden/diagnostics.md).

#### Поды не завершаются (Terminating)

Режим **C** зависания: новый RS полностью готов, но старый не сворачивается, потому что старые поды застряли в `Terminating`.

```bash
kubectl get pods -l app=<label> | grep Terminating
kubectl describe pod <old-pod-name>

# Как долго под висит и по какой причине
kubectl get pod <old-pod-name> -o jsonpath='{.metadata.deletionTimestamp}{"\n"}{.metadata.finalizers}{"\n"}'
```

Типовые причины и решения:

| Причина | Признак | Решение |
| :--- | :--- | :--- |
| Долгий `preStop` | Событие `Kill-container` происходит поздно | Сократить `preStop sleep`; он должен покрываться `terminationGracePeriodSeconds`. См. [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md). |
| Finalizer (внешний контроллер) | `metadata.finalizers` непуст после удаления | Найти контроллер, держащий finalizer; разобраться с ним, а не удалять вручную. См. [Проблемы с finalizer](../../Troubleshooting/Common_Errors/PodTerminating/finalizer_issues.md). |
| Kubelet не отвечает / NodeNotReady | Поды не удаляются с конкретного узла | Восстановить узел, либо `kubectl delete pod <name> --grace-period=0 --force` как крайнее средство. |

> Принудительное `--grace-period=0 --force` обходит `preStop` и может оставить orphaned-состояние в приложении. Применяется только после исчерпания остальных вариантов. Полный алгоритм — в [Диагностика завершения пода](../../Troubleshooting/Common_Errors/PodTerminating/diagnostics.md).

#### Проблемы с пробами (Ready 0/1)

Самая частая причина режима **B**. Поды запускаются, но не достигают `Ready` — rollout не продвигается.

```bash
# Статус пробы в описании пода
kubectl describe pod <new-pod-name> | grep -A8 "Readiness"

# Логи — приложение может не слушать на ожидаемом порту
kubectl logs <new-pod-name> --tail=50

# Проверка изнутри кластера (если в образе есть curl/wget)
kubectl exec -it <new-pod-name> -- curl -v http://127.0.0.1:<port><path>
```

**Расчет окна пробы:** максимальное время до признания пода неготовым = `initialDelaySeconds + (failureThreshold - 1) * periodSeconds`. Например, `initialDelaySeconds: 10`, `periodSeconds: 5`, `failureThreshold: 3` → 20 секунд до `NotReady`. Если приложению нужно 60 секунд на старт — окно должно быть больше, иначе под никогда не станет `Ready` (это классическая «мисконфигурация пробы», отличная от реального сбоя приложения).

Типовые исправления:
- Увеличить `initialDelaySeconds` / `failureThreshold`.
- Использовать `startupProbe` для медленных стартов (Java, кеши) — она не входит в `readiness`/`liveness` гонку.
- Проверить, что эндпоинт пробы не требует аутентификации и отвечает `2xx`.

Подробная настройка — в [Пробы (Probes)](../probes.md).

### Экстренные процедуры

#### Принудительная остановка зависшего обновления

Если обновление застряло и критически важно вернуть стабильность:

```bash
# Вариант 1: Откат к предыдущей ревизии (безопасно)
kubectl rollout undo deployment/<name>

# Вариант 2: Откат к конкретной ревизии
kubectl rollout history deployment/<name>       # Найти номер нужной ревизии
kubectl rollout undo deployment/<name> --to-revision=<N>

# Вариант 3: «Сухой» предпросмотр отката (ничего не меняет)
kubectl rollout undo deployment/<name> --dry-run=server -o yaml | head -40

# Вариант 4: Пауза обновления (остановить процесс, но не откатывать)
kubectl rollout pause deployment/<name>
```

Важные детали отката:
- `kubectl rollout undo` **не создает исключение из-за `--force`** — такого флага не существует. Принудительное пересоздание подов выполняется через `kubectl delete pod <name>` (ReplicaSet пересоздаст его) или `kubectl rollout restart`.
- Откат выполняется как **новая ревизия** (история не «отматывается», ревизии только увеличиваются) и подчиняется `maxSurge`/`maxUnavailable`.
- **Нельзя откатить приостановленный (paused) Deployment** — сначала выполните `kubectl rollout resume deployment/<name>`.
- Старый ReplicaSet уже существует и его образ не нужно тянуть из реестра — восстановление происходит быстро.
- Возможность отката ограничена `revisionHistoryLimit` (по умолчанию 10): удаленные старые RS для отката недоступны.

#### Экстренное масштабирование

Если новые поды падают и нагружают систему:

```bash
# Масштабировать Deployment до 0 (полная остановка)
kubectl scale deployment/<name> --replicas=0

# Дождаться завершения всех подов
kubectl rollout status deployment/<name> --timeout=5m

# После исправления — восстановить
kubectl scale deployment/<name> --replicas=<original-count>
```

### Реальный пример: Ошибка миграции БД

**Ситуация:** Обновление застряло на 1 новой реплике. Старые поды работают, но новые не становятся `Ready`.

**Диагностика:**
1. `kubectl rollout status` висит.
2. `kubectl get pods` показывает новый под в `Running`, но `Ready 0/1`.
3. `kubectl logs <pod>` выдает: `FATAL: database "users_db" does not have table "sessions"`.

**Причина:** Новая версия кода требует новую таблицу, но миграция БД в CI/CD не выполнилась или `Job` миграции упал.

**Решение:**
```bash
# 1. Выполнить миграцию вручную
kubectl create job --from=cronjob/db-migration manual-migration-$(date +%s)

# 2. Дождаться завершения миграции
kubectl get jobs -l app=db-migration --watch

# 3. После успешной миграции — перезапустить rollout
kubectl rollout restart deployment/<name>
```

### Реальный пример: Конфликт с квотами

**Ситуация:** Deployment имеет `maxSurge: 2`, в неймспейсе установлена квота `requests.cpu: 4`. Каждый под требует `requests.cpu: 1`. При 3 активных репликах и попытке создания 2 новых — обновление застряло.

**Диагностика:**
```bash
kubectl describe quota -n <namespace>
# → requests.cpu: 5/4  (5 запрошено, лимит 4)
```

**Решение:**
```bash
# Вариант 1: Уменьшить maxSurge
kubectl patch deployment <name> -p '{"spec":{"strategy":{"rollingUpdate":{"maxSurge":1}}}}'

# Вариант 2: Увеличить квоту (если есть права)
kubectl patch resourcequota default-quota -n <namespace> \
  -p '{"spec":{"hard":{"requests.cpu":"6"}}}'

# Вариант 3: Снизить requests (если реальное потребление меньше)
kubectl set resources deployment/<name> -c=<container> --requests=cpu=500m
```

### Реальный пример: Слишком строгая readiness-проба

**Ситуация:** Новые поды `Running`, но `Ready 0/1`; rollout не прогрессирует даже после нескольких попыток.

**Диагностика:**
```bash
kubectl describe pod <new-pod-name> | grep -A8 "Readiness"
# → Readiness probe failed: HTTP probe failed with statuscode: 503
kubectl logs <new-pod-name>
# → Cache warming... (приложение готово отвечать только через 90 секунд)
```

**Причина:** Окно пробы (`initialDelaySeconds + (failureThreshold-1)*periodSeconds`) меньше реального времени прогрева приложения.

**Решение:** добавить `startupProbe` со щадящими параметрами (например, `failureThreshold: 30, periodSeconds: 10` → окно 300с), а `readiness`/`liveness` оставить для штатной работы:

```bash
kubectl patch deployment <name> --type='json' -p '[{"op":"add","path":"/spec/template/spec/containers/0/startupProbe","value":{"httpGet":{"path":"/healthz","port":8080},"failureThreshold":30,"periodSeconds":10}}]'
```

## 4. Дополнительная информация

### Полезные команды для траблшутинга

```bash
# === Обзор состояния ===
# Статус Rollout с таймаутом (для скриптов; при зависании завершается с ненулевым кодом и сообщением "exceeded its progress deadline")
kubectl rollout status deployment/<name> --timeout=5m

# Ожидание достижения условия Available (альтернатива для CI)
kubectl wait --for=condition=Available deployment/<name> --timeout=5m

# История ревизий с аннотациями (причины изменений)
kubectl rollout history deployment/<name>

# Текущее и желаемое состояние
kubectl get deployment/<name> -o yaml | grep -E 'replicas:|availableReplicas:|unavailableReplicas:|observedGeneration|generation:'

# === Диагностика подов ===
# Поды с проблемами (не Running или не Ready)
kubectl get pods -l app=<label> -o wide | grep -v Running
kubectl get pods -l app=<label> -o wide | grep -v "1/1"

# Все контейнеры в поде и их статус
kubectl get pod <name> -o jsonpath='{range .status.containerStatuses[*]}{.name}{"\t"}{.state}{"\n"}{end}'

# Последние события пода (быстрый доступ)
kubectl describe pod <name> | grep -A10 "Events:"

# === Логи ===
# Логи всех реплик Deployment (селектор по метке)
kubectl logs -l app=<label> --tail=100

# Логи с фильтрацией по контейнеру
kubectl logs <pod-name> -c <container-name>

# Логи с таймстампами (для поиска циклов перезапуска)
kubectl logs <pod-name> --timestamps

# === Мониторинг в реальном времени ===
# Отслеживание пересоздания подов при обновлении
kubectl get pods -l app=<label> --watch

# События уровня кластера
kubectl get events --sort-by='.lastTimestamp' -n <namespace>

# === Откат и управление ===
# Откат с указанием причины
kubectl annotate deployment/<name> kubernetes.io/change-cause="Откат из-за критической ошибки" --overwrite
kubectl rollout undo deployment/<name>

# Пауза + возобновление (для пакетного обновления)
kubectl rollout pause deployment/<name>
kubectl set resources deployment/<name> -c=<container> --limits=cpu=200m,memory=256Mi
kubectl rollout resume deployment/<name>
```

### Коды завершения контейнеров (Exit Codes)

Быстрый справочник для шага 3 алгоритма — интерпретация `Last State → Exit Code` из `kubectl describe pod`:

| Exit code | Расшифровка | Типовая причина |
| :--- | :--- | :--- |
| `0` | Успешное завершение | Приложение корректно обработало сигнал завершения |
| `1` | Ошибка приложения | Паника, исключение, аварийный выход — чаще всего код 1 |
| `126` | Команда не может быть выполнена | Нет прав на выполнение, неверная архитектура бинарника (wrong arch) |
| `127` | Команда не найдена | Ошибка в `command`/`args`, отсутствие файла в образе |
| `130` | SIGINT | Приложение прервано по Ctrl+C / SIGINT (`128+2`) |
| `137` | SIGKILL | **OOMKilled** (превышение `limits.memory`) или принудительный kill (`128+9`) |
| `143` | SIGTERM | Корректное завершение по сигналу; ожидаемо при gracefully shutdown (`128+15`) |

См. также [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) и [Анализ OOMKilled](../../Troubleshooting/Common_Errors/oomkilled_pods.md).

### Мониторинг и алертинг

Правило «сдвига влево»: зависший rollout дешевле поймать по алерту, чем по жалобам пользователей. Базовые метрики kube-state-metrics:

- `kube_deployment_status_observed_generation` vs `kube_deployment_metadata_generation` — контроллер не обработал последнее изменение (режим A).
- `kube_deployment_status_condition{condition="Progressing",reason="ProgressDeadlineExceeded"}` — rollout провален (режим B/C). Метка `reason` доступна в kube-state-metrics 2.7+.
- `kube_deployment_spec_replicas != kube_deployment_status_available_replicas` — желаемое/фактическое число реплик не сходится.

Готовые примеры правил (включая чек `changes(kube_deployment_status_replicas_updated[10m]) == 0` для детекции отсутствия прогресса) — в [Kubernetes-алерты](../../../Grafana/alerting/kubernetes_alerts.md). В связке с метриками удобно использовать `kubectl rollout status --timeout` в пайплайнах (см. [Incident Response в CI/CD](../../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md)): команда возвращает ненулевой код при невыходе в срок, что позволяет автоматически откатывать релиз.

### Лучшие практики (Best Practices)

1. **Автоматизация диагностики:** Настройте алерты на зависшие rollout (метрики из раздела «Мониторинг и алертинг») с `for: 15m`, чтобы не срабатывать на легитимно долгие выкатки. Алерт на `kube_deployment_status_condition{condition="Progressing",status="false"}` без учета `reason` ловит и ранние провалы (`ReplicaSetCreateError`) — выделяйте именно таймауты через `reason="ProgressDeadlineExceeded"`.
2. **Причины изменений:** Флаг `--record` объявлен устаревшим и удален в kubectl v1.24. Всегда пишите причину через аннотацию `kubernetes.io/change-cause` — она видна в `kubectl rollout history` и ускоряет диагностику.
3. **MinReadySeconds в продакшене:** Устанавливайте `minReadySeconds: 30-60` для критических сервисов, чтобы выявлять медленные падения (например, после включения в трафик).
4. **Ограничение истории:** Устанавливайте `revisionHistoryLimit: 3-5` вместо дефолтных 10 для снижения нагрузки на etcd — однако не ниже, чем реально нужно для отката.
5. **Graceful Termination:** Убедитесь, что приложение корректно обрабатывает `SIGTERM` и завершает активные соединения. `terminationGracePeriodSeconds` должен покрывать `preStop` + время дренажа.
6. **PreStop хуки:** Используйте `preStop` для плавного дренажа соединений перед завершением пода (важно для HTTP-серверов и БД-клиентов). Не делайте `preStop` дольше `terminationGracePeriodSeconds`.
7. **Пробы — «make or break» rollout:** считайте окно пробы (`initialDelaySeconds + (failureThreshold-1)*periodSeconds`), для медленных стартов используйте `startupProbe`. Подробнее в [Пробах](../probes.md).
8. **Тайм-ауты в CI/CD:** всегда задавайте `kubectl rollout status --timeout=...` и завершайте пайплайн с ошибкой при невыходе в срок — тогда автоматика (или человек) успеет откатить до влияния на пользователей.
9. **ReadinessProbe обязательна:** без нее RollingUpdate удаляет старые поды до готовности новых — эффект «все упало разом».
10. **Проверяйте поколение:** перед отладкой смотрите `observedGeneration` — возможно, rollout даже не начался (режим A), и копать нужно в сторону paused/синхронизации манифеста.

### Ограничения и особенности (Edge Cases)

1. **Обновление с пустым `replicas`:** Если Deployment имеет `replicas: 0`, обновление шаблона не создаст поды и завершится сразу — ожидаемое поведение для временной остановки, неожиданное — для выкатки.
2. **Параллельные обновления (Rollover):** Если отправить второе обновление во время первого, контроллер не ждет завершения первого. При быстрой смене версий старые RS могут не успеть «до-`Ready`-иться» — отсюда хаотичный вывод `rollout status`.
3. **Неизменяемость селектора:** Поле `spec.selector` неизменяемо. Ошибка в селекторе приводит к бесконечному созданию подов. Проверяйте `kubectl get rs` перед первым применением.
4. **HPA и RollingUpdate:** Настраивайте HPA на Deployment, а не на ReplicaSet — иначе во время Rollout autoscaler масштабирует старый (неактивный) RS.
5. **Мутабельные теги:** `:latest`/`:stable` делает Rollout невоспроизводимым — Kubernetes не видит разницы и не инициирует обновление.
6. **ConfigMap/Secret не инициируют Rollout:** изменение содержимого не перезапускает поды. Для применения — `kubectl rollout restart` (или аннотация-хеш конфигурации). Переменные окружения из `envFrom` обновляются только при пересоздании пода.
7. **Нельзя откатить paused Deployment:** `kubectl rollout undo` не сработает, пока не выполнен `rollout resume`.
8. **`progressDeadlineSeconds` <= `minReadySeconds`:** условие срабатывает сразу — параметры конфликтуют.
9. **`rollout undo --force` не существует:** такой команды нет. Принудительное пересоздание — `kubectl delete pod` или `rollout restart`.
10. **Откат ограничен историей:** удаленный из-за `revisionHistoryLimit` старый RS нельзя использовать для отката.
11. **Зависшие `Terminating`:** блокируют масштабирование вниз (режим C). Помимо preStop/finalizer, причина может быть в невосприимчивом kubelet — смотрите события `FailedKillPod` и диагностику узла.
12. **Поды в `Terminating` при scale-down после rollout:** если приложение не отвечает на SIGTERM, оно может не получить ни `preStop`, ни корректное завершение — настройте обработку сигнала заранее (это и есть профилактика «зависших» обновлений).

### См. также
- [Deployment: Обзор и концепции](./index.md) — база для понимания контроллера и его состояний.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — процессы Rollout, Rollback, пауза и возобновление.
- [Поиск и устранение неисправностей в Kubernetes](../../Troubleshooting/troubleshooting_overview.md) — общий обзор методологии диагностики.