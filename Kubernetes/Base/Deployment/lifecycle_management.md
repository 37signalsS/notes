# Управление жизненным циклом Deployment в Kubernetes

Декларативные и императивные процессы контроля состояния приложения: от развертывания и масштабирования до отката и диагностики.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+ для `apps/v1`) и доступ к нему.
- Установленный и настроенный `kubectl`. Флаг `--record` удален в v1.24 — причину ревизии задавайте аннотацией `kubernetes.io/change-cause` (см. [Документирование изменений](#документирование-изменений-change-cause)).
- RBAC-права на стороне оператора: `get`/`patch`/`update` на `deployments`, `replicasets`, `pods` и `events`. Команды `kubectl rollout ...` **не используют** отдельный субресурс `rollout` — они читают и изменяют сам объект Deployment (через standard API), поэтому права на `deployments` достаточно.
- Понимание базовых объектов: [Pod](../Pod/pod_overview.md), [ReplicaSet](../replicaset.md), проб (`readinessProbe`/`livenessProbe`/`startupProbe` — [Пробы в Kubernetes](../probes.md)).
- Общие концепции и описание полей манифеста см. в разделах:
  - [Kubernetes Deployment: Обзор](./index.md)
  - [Манифест и лучшие практики](./deployment_manifest.md)

## 1. Определения

**Управление жизненным циклом (Lifecycle Management)** — совокупность процессов по контролю состояния приложения в Kubernetes. Оно охватывает этапы развертывания (Rollout), обновления конфигурации, мониторинга готовности, отката к предыдущим ревизиям (Rollback), а также оперативного управления (пауза, возобновление и принудительный перезапуск).

- **Rollout (Выкатка)** — процесс перехода Deployment с одной версии шаблона пода на другую. Выполняется постепенной подменой подов в рамках стратегии `RollingUpdate` (или мгновенно — при стратегии `Recreate`).
- **Ревизия (Revision)** — зафиксированный снимок шаблона пода (`spec.template`) в истории Deployment. Каждое изменение шаблона создает новую ревизию; именно ревизии позволяют выполнить откат. Номер ревизии хранится в аннотации `deployment.kubernetes.io/revision`.
- **Откат (Rollback)** — возврат шаблона пода к одной из предыдущих ревизий. В Kubernetes откат — это новый rollout по старому шаблону, а не «перемотка времени» (история продолжает расти).
- **Пропорциональное масштабирование (Proportional Scaling)** — алгоритм контроллера Deployment, распределяющий новые реплики между всеми активными ReplicaSet, когда масштабирование происходит во время незавершенного (или приостановленного) rollout.
- **Пауза (Pause)** — установка `spec.paused: true`, после которой контроллер перестает реагировать на изменения шаблона пода (не запускает новые rollout), сохраняя работу текущих подов.
- **Rollover (Перекрытие выкаток)** — ситуация, когда новое обновление приходит до завершения предыдущего; контроллер не ждет завершения старого rollout.
- **Change-cause** — аннотация `kubernetes.io/change-cause`, документирующая причину изменения ревизии (видна в `kubectl rollout history`).

## 2. Базовые концепции

### Иерархия объектов и механизм владения

Управление осуществляется по цепочке:
`Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

Deployment не создает поды напрямую. Он управляет наборами реплик (`ReplicaSet`), которые, в свою очередь, обеспечивают работу нужного количества подов. Механизм `ownerReferences` в метаданных ресурсов обеспечивает каскадное управление и автоматическое удаление зависимых объектов (Garbage Collection): удаление Deployment удаляет его ReplicaSet и поды.

### Механизм Rolling Update на уровне ReplicaSet

Процесс обновления (Rollout) не редактирует существующие поды. Вместо этого происходит постепенная подмена одного ReplicaSet другим:

1.  **Создание новой ревизии:** При изменении `spec.template` контроллер Deployment создает **новый** ReplicaSet с обновленным шаблоном пода и уникальным хешем в метке `pod-template-hash` (хеш вычисляется от PodTemplate; подробно — [ReplicaSet](../replicaset.md#метка-pod-template-hash)).
2.  **Миграция реплик:** Начинается постепенное изменение количества реплик в старом и новом RS:
    - Старый RS: N → N-1 → ... → 0
    - Новый RS:  0 → 1   → ... → N
3.  **Контроль шага:** Параметры `maxSurge` (дополнительные поды) и `maxUnavailable` (допустимая потеря мощности) определяют «размер шага» этой миграции. Удаление старого пода происходит **только** после того, как новый под прошел `readinessProbe` и стал `Ready`.
4.  **Хранение истории:** Старый ReplicaSet сохраняется в системе, но масштабируется в 0 реплик. Это позволяет выполнить мгновенный откат (`rollout undo`), просто поменяв количество реплик между старым и новым RS (без перекачивания образов — шаблон уже известен контроллеру).
5.  **Новая ревизия помечается аннотацией:** контроллер увеличивает `deployment.kubernetes.io/revision` — это монотонный счетчик, отражающий количество запущенных rollout.

Пока идет обновление, старые поды продолжают принимать трафик — новая версия поднимается «рядом» и проходит проверки готовности, прежде чем трафик будет переведен на нее.

### Перекрывающиеся обновления (Rollover)

Если новое обновление отправлено, когда предыдущий rollout еще не завершен, контроллер **не ждет** завершения старого:

- Создается новый ReplicaSet под актуальный шаблон.
- ReplicaSet, который только начал раскатываться, «понижается» в ранге до старого и начинает масштабироваться вниз.
- Приоритет всегда отдается последнему желаемому состоянию — это важно для быстрых хотфиксов поверх незавершенного релиза.

Пример из официальной документации: при rollout `nginx:1.14.2` → `nginx:1.16.1`, когда удалось создать только 3 из 5 подов, контроллер немедленно начинает убивать эти 3 пода и создавать поды `1.16.1`, не дожидаясь набора всех 5 старых. Из-за этого промежуточные состояния `kubectl rollout status` могут выглядеть «хаотично» (требования по таймаутам — см. [Автоматизация в CI/CD](#автоматизация-в-cicd-rollout-status-как-гейт)).

### Триггеры обновления (Rollout)

Обновление (Rollout) инициируется **только** при изменении шаблона пода (`spec.template`).

| Тип изменения | Инициирует Rollout? | Примеры |
| :--- | :--- | :--- |
| **Спецификация контейнера** | **Да** | Изменение `image`, `command`, `env`, `resources`, `ports` |
| **Конфигурация томов** | **Да** | Изменение `volumes` или `volumeMounts` |
| **Пробы (Probes)** | **Да** | Обновление `liveness`, `readiness` или `startup` проб |
| **Масштабирование** | **Нет** | Изменение `spec.replicas` меняет только размер текущего RS |
| **Метаданные Deployment** | **Нет** | Изменение `labels` или `annotations` самого Deployment |
| **Метаданные шаблона** | **Да** | Изменение меток или аннотаций в `spec.template.metadata` |

Следствие: `kubectl apply -f` с неизменным `spec.template` (например, поменялись только `labels` самого Deployment) **не создает** новой ревизии, даже если изменились другие поля `spec`. Это важное отличие от Docker Compose, где контейнеры пересоздаются при любом изменении.

### Поведение ReplicaSet при масштабировании (Scaling)

В отличие от Rollout, операция масштабирования (`kubectl scale` или изменение `spec.replicas`) не создает новую ревизию и не инициирует создание нового ReplicaSet.

- **Активный процесс:** Контроллер Deployment напрямую обновляет поле `replicas` в **текущем активном** ReplicaSet (том, который соответствует текущему `pod-template-hash`).
- **Масштабирование во время обновления (пропорциональное):** Если масштабирование происходит в момент активного Rolling Update — в том числе когда rollout приостановлен (`paused`) — контроллер **пропорционально распределяет** новые реплики между всеми задействованными ReplicaSet, чтобы соблюсти ограничения `maxSurge` и `maxUnavailable`. Правила алгоритма:
  - Большая доля реплик направляется в ReplicaSet с наибольшим текущим числом реплик, меньшая — в остальные.
  - «Остаток» (leftover) от нецелого деления добавляется в RS с наибольшим числом реплик.
  - ReplicaSet с нулем реплик не масштабируется вверх.
  - Пример из официальной документации: 10 реплик, `maxSurge: 3`, `maxUnavailable: 2`, активный rollout; autoscaler увеличивает `replicas` до 15. Добавляемые 5 реплик распределяются между активными RS пропорционально их текущему числу — в примере документации 3 реплики получает RS с большим числом реплик и 2 — RS с меньшим. В итоге все реплики все равно переедут на новый RS по мере прохождения проверок готовности.
- **Приоритет новому RS:** в базовом сценарии (без активного rollout) приоритет отдается самому новому ReplicaSet.
- **Противодействие HPA:** Horizontal Pod Autoscaler масштабируется путем записи `spec.replicas` в объект Deployment. **Не изменяйте вручную `replicas`, если Deployment управляется HPA** — autoscaler постоянно сверяет и перезаписывает это значение. Взаимодействие HPA и RollingUpdate подробно: [HPA](../../Autoscaling/HPA/index.md).

### Параметры контроля стабильности и Zero-Downtime

Для предотвращения деградации сервиса и обеспечения выката без потерь (Zero-Downtime) используются следующие параметры:

- **`maxUnavailable: 0` и `maxSurge: 1`**: При дефолтных настройках Deployment может вывести часть подов из строя до того, как поднимутся новые. Если сервис работает на пределе мощности, это вызовет перегрузку и ошибки 504. Установка `maxUnavailable: 0` гарантирует, что старые поды не будут удалены, пока новые не станут `Ready`.
- **`minReadySeconds`**: Время ожидания после того, как под перешел в состояние `Ready` (согласно `readinessProbe`), прежде чем он будет считаться действительно рабочим (Available).
  - **Назначение:** Позволяет приложению «прогреться» (Warm-up), накатить кеши или выявить ошибки, которые возникают не сразу после старта.
- **`progressDeadlineSeconds`**: Время, в течение которого контроллер Deployment ожидает прогресса. Если за это время новый ReplicaSet не смог стать доступным, обновление помечается как проваленное (`Failed`). Подробный разбор «зависших» rollout — в [Устранение неполадок Deployment и RollingUpdate](./troubleshooting.md).
- **`terminationGracePeriodSeconds`**: Должен быть больше суммы времени `preStop sleep` и реального времени дренажа запросов приложением.

Дополнительные нюансы параметров (арифметика процентов, сочетание с ResourceQuota) — в [Манифест и лучшие практики](./deployment_manifest.md).

#### Выбор Readiness Probe для Zero-Downtime

Типовая ошибка — использование **TCP-пробы** вместо HTTP. TCP-сокет открывается ОС сразу при старте процесса, часто задолго до того, как приложение реально готово отвечать (прогреты пулы соединений, загружены кеши). Трафик идет на «холодный» под, что вызывает ошибки. Использование **HTTP-пробы** на эндпоинт (например, `/readyz`), который проверяет внутреннюю готовность, является обязательным для стабильного выката.

### Структура ревизий и глубина истории

Каждая новая ревизия — это отдельный ReplicaSet с уникальным `pod-template-hash`. Контроллер хранит старые ReplicaSet (даже с нулем реплик) для обеспечения отката:

- **`revisionHistoryLimit`** (по умолчанию **10**) — сколько старых ReplicaSet сохранять. Превышение лимита: старые RS удаляются, откат к удаленным ревизиям становится **невозможен**.
- **`revisionHistoryLimit: 0`** полностью отключает хранение истории и, как следствие, возможность `rollout undo`. Применять осознанно (например, для несущих окружений).
- Рекомендация для продакшена: `3–5` ревизий — баланс между глубиной отката и нагрузкой на `etcd` (детальный разбор поля — в [Манифест и лучшие практики](./deployment_manifest.md)).
- Удаленные из-за лимита ревизии **не восстанавливаются** — единственный способ вернуть такой шаблон — применить его повторно (манифест из Git/реестра).

### Откат (Rollback): устройство механизма

`kubectl rollout undo` восстанавливает шаблон пода из указанной (или предыдущей) ревизии:

1.  Контроллер находит ReplicaSet, соответствующий целевой ревизии (по `pod-template-hash`).
2.  Он масштабирует **текущий** (проблемный) RS вниз, а **целевой** — вверх, подчиняясь `maxSurge`/`maxUnavailable` — откат выполняется как обычный rollout.
3.  Образы повторно не качаются: целевой RS уже содержит шаблон со всеми параметрами (тегами, env, томами) — откат лишь меняет число реплик.
4.  **История продолжает расти:** откат не «перематывает» ревизии назад — создается новая ревизия с восстановленным шаблоном. Это позволяет в любой момент откатиться «назад к откату».

Особенности отката:
- Откат возможен **только для не-paused** Deployment: пока `spec.paused: true`, `kubectl rollout undo` не сработает (сначала `kubectl rollout resume`).
- Если ревизия с номером `--to-revision=N` не найдена (удалена лимитом истории) — команда завершится с ошибкой `unable to rollback to specified revision`.
- Если шаблон целевой ревизии **идентичен** текущему — откат является no-op: контроллер не создает новой ревизии и ничего не масштабирует (стоит проверить `kubectl rollout history --revision=N`, прежде чем считать откат неудавшимся).
- Откат **не возвращает** данные (схему БД, мутировавшие тома, содержимое ConfigMap/Secret) — это операция над шаблоном пода. Совместимость схемы БД обеспечивается паттерном [Expand-Contract](../../../Databases/Concepts/migrations/expand_contract.md)-подобных миграций.

### Пауза и возобновление: поведение контроллера

`kubectl rollout pause` устанавливает `spec.paused: true`. Это режим «заморозки» **rollout-логики**, а не остановки приложения:

| Действие | Поведение при paused |
| :--- | :--- |
| Работа существующих подов | Продолжает работу без изменений |
| Изменение `spec.template` (image, env, probes) | Записывается, но **не применяется**, пока не выполнен `resume` |
| Незавершенный rollout | Замораживается (масштабирование между RS не продолжается) |
| Масштабирование (`spec.replicas`) | Применяется **немедленно** (не создавая новой ревизии) |
| `kubectl rollout undo` | **Не работает** до `resume` |
| `kubectl rollout restart` (изменение шаблона) | Ставится в очередь, применяется после `resume` |

Технически пауза означает, что контроллер прекращает согласовывать (reconcile) изменения шаблона: условия Deployment принимают вид `Progressing: Unknown` с `reason: DeploymentPaused`. Проверить факт паузы можно только через `kubectl describe` (Conditions) или `kubectl get deploy <name> -o jsonpath='{.spec.paused}'` — колонки `kubectl get deploy` паузу не показывают.

**Назначение:** внести серию связанных изменений (образ + ресурсы + env) одним «пакетом», применив их единым rollout после `resume`. Это экономит ресурсы и предотвращает создание промежуточных «битых» ревизий. Пока пауза активна, изменения копятся в очереди; при `resume` запускается ровно **один** rollout со всеми накопленными правками.

### Перезапуск (Restart) как триггер rollout

`kubectl rollout restart` добавляет в `spec.template.metadata.annotations` значение `kubectl.kubernetes.io/restartedAt` (текущее время) — это **изменение шаблона**, поэтому запускается новый rollout (новая ревизия), но без изменения образов и конфигурации.

Применяется для:
- Применения нового содержимого ConfigMap/Secret, подключенных через переменные окружения (`envFrom`/`valueFrom`) — изменение содержимого существующего объекта **не** инициирует rollout, поды продолжают работать со старой конфигурацией.
- Сброса состояния при обнаружении утечек памяти.
- Перечитывания внешних данных из томов при необходимости немедленной репликации.

Работает для `Deployment`, `StatefulSet` и `DaemonSet` (с разной семантикой порядка обновления). Детальные сценарии и таблицы «какой ресурс как реагирует на изменение конфигурации» — в [pod_restarts.md](../Pod/pod_restarts.md), специфика конфигураций — в [Обновление и rollout ConfigMap](../ConfigMap/update_and_rollout.md).

## 3. Практические сценарии

### Основные команды управления

```bash
# Обновление образа приложения
kubectl set image deployment/nginx-deployment nginx=nginx:1.28.1-alpine
# → deployment.apps/nginx-deployment image updated

# Точечное обновление с одновременной фиксацией причины (через аннотацию)
kubectl annotate deployment/nginx-deployment kubernetes.io/change-cause="Обновление до 1.28.1-alpine"

# Отслеживание статуса развертывания
kubectl rollout status deployment/nginx-deployment
# → Waiting for deployment "nginx-deployment" rollout to finish: 1 of 3 updated replicas are available...
# → deployment "nginx-deployment" successfully rolled out

# Тот же статус, но с ограничением времени ожидания (обязательно в скриптах/CI)
kubectl rollout status deployment/nginx-deployment --timeout=5m

# Мгновенный снимок состояния (без ожидания)
kubectl rollout status deployment/nginx-deployment --watch=false
```

Точные параметры команды `rollout status`: по умолчанию ждет бесконечно (`--timeout=0`), возвращает код `0` при успешном завершении rollout и ненулевой код при таймауте или сбое (например, `error: deployment "my-app" exceeded its progress deadline`).

### Управление ревизиями и Rollback

Каждый запуск Rollout создает новую ревизию в истории. Это важнейшая «сеть безопасности» (safety net) для производственных операций.

```bash
# Просмотр истории изменений
kubectl rollout history deployment/nginx-deployment
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         Обновление до v1.28.1-alpine

# Детальный просмотр конкретной ревизии (шаблон пода, причины)
kubectl rollout history deployment/nginx-deployment --revision=2

# Откат к предыдущей стабильной версии
kubectl rollout undo deployment/nginx-deployment
# → deployment.apps/nginx-deployment rolled back

# Откат к определенной ревизии по номеру
kubectl rollout undo deployment/nginx-deployment --to-revision=1

# Пробный откат: посмотреть, какой объект получится, ничего не применяя
kubectl rollout undo deployment/nginx-deployment --dry-run=server -o yaml | head -40

# После отката — дождаться завершения (с таймаутом для CI)
kubectl rollout status deployment/nginx-deployment --timeout=5m
```

Предусловия успешного отката:
- Deployment **не приостановлен** (`spec.paused != true`). Если он paused — сначала `kubectl rollout resume`.
- Целевая ревизия **не удалена** из истории (`revisionHistoryLimit`). После отката завершите его rollout и контролируйте выход в строку `successfully rolled out`.
- Откат выполняется как обычный rollout и подчиняется `maxSurge`/`maxUnavailable` — для мгновенного восстановления в аварийной ситуации это учтите (см. [Устранение неполадок Deployment и RollingUpdate](./troubleshooting.md)).

### Документирование изменений (change-cause)

Для того чтобы в истории ревизий вместо `<none>` отображалась причина, используйте аннотацию `kubernetes.io/change-cause`. Аннотация задается на Deployment **до или в момент** запуска rollout — она копируется в создаваемую ревизию и показывается в колонке `CHANGE-CAUSE`.

- **Через манифест (лучшая практика):**
  ```yaml
  metadata:
    annotations:
      kubernetes.io/change-cause: "Обновление образа до 1.28.1-alpine"
  ```
- **Через CLI:**
  ```bash
  kubectl annotate deployment/nginx-deployment kubernetes.io/change-cause="Исправление лимитов памяти"
  ```

Флаг `--record` для `kubectl set image`/`kubectl apply` объявлен устаревшим и удален в kubectl v1.24 — используйте аннотацию. Она также помогает аудиту и автоматизации (напр., извлечение причины в CI-пайплайнах через `-o jsonpath`).

### Оперативное управление: пауза и возобновление

Классический сценарий «пакет правок»:

```bash
# 1. Поставить rollout на паузу
kubectl rollout pause deployment/nginx-deployment
# → deployment.apps/nginx-deployment paused

# 2. Внести несколько изменений (каждое НЕ запускает rollout)
kubectl set image deployment/nginx-deployment nginx=nginx:1.28.1-alpine
kubectl set resources deployment/nginx-deployment --limits=cpu=500m,memory=512Mi
kubectl set env deployment/nginx-deployment LOG_LEVEL=info

# 3. Убедиться, что изменения накоплены, и возобновить — запустится ОДИН rollout
kubectl rollout resume deployment/nginx-deployment
# → deployment.apps/nginx-deployment resumed

# 4. Дождаться завершения
kubectl rollout status deployment/nginx-deployment --timeout=5m
```

Контроль состояния: `kubectl describe deployment` → блок `Conditions` (при паузе `Progressing: Unknown` с `reason: DeploymentPaused`), либо `kubectl get deploy <name> -o jsonpath='{.spec.paused}'`.

Типичная ошибка — оставить Deployment на паузе после incident-разбора: следующие правки или restart «невидны». Следите за `spec.paused` после применения пакета.

### Принудительный перезапуск (Restart)

```bash
# Пересоздание подов без изменения манифеста
kubectl rollout restart deployment/nginx-deployment
# → deployment.apps/nginx-deployment restarted

# Вариант с ожиданием завершения в CI
kubectl rollout restart deployment/nginx-deployment && \
  kubectl rollout status deployment/nginx-deployment --timeout=5m
```

Команда добавляет аннотацию `kubectl.kubernetes.io/restartedAt: <timestamp>` в шаблон пода, создавая новую ревизию. Ограничение: если Deployment paused, перезапуск применится только после `rollout resume`. Сценарии использования (ConfigMap/Secret, утечки памяти) — в [pod_restarts.md](../Pod/pod_restarts.md).

### Автоматизация в CI/CD: rollout status как гейт

`kubectl rollout status` — стандартный «шлюз» (gate) пайплайна: команда выполняет блокирующее ожидание и завершается с кодом `0` при успешном rollout, `1+` при таймауте или сбое. Корректный паттерн в скриптах:

```bash
# Деплой + контроль готовности + автоматический откат при сбое
kubectl set image deployment/my-app my-app=my-app:$BUILD_TAG

if ! kubectl rollout status deployment/my-app --timeout=5m; then
  echo "Rollout failed, rolling back"
  kubectl rollout undo deployment/my-app
  kubectl rollout status deployment/my-app --timeout=2m
  exit 1
fi
```

Полезные флаги:
- `--timeout=...` — **обязательно**: без него команда ждет бесконечно, и пайплайн «зависнет» при застрявшем rollout.
- `--watch=false` — мгновенный снимок состояния (для легких чеков).
- `--revision=N` — проверять готовность конкретной ревизии (полезно при откатах и canary-подъемах; если новая ревизия обогнала указанную — команда завершится и вернет ненулевой код).

Ограничение для автоматики: `rollout status` зависит от устойчивого соединения с API-server (watch); при транзиентных сетевых сбоях возможен ложный отказ — закладывайте retry. Интеграция с алертингом и порядок incident-response: [Incident Response в CI/CD](../../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md), общие процедуры отката: [Проверки здоровья и откат](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md).

### Масштабирование на практике

```bash
# Ручное масштабирование
kubectl scale deployment/nginx-deployment --replicas=5
# → deployment.apps/nginx-deployment scaled

# Императивное изменение манифеста (аналог)
kubectl patch deployment/nginx-deployment -p '{"spec":{"replicas":5}}'

# Масштабирование до и после плановых работ (например, перед drain узла)
kubectl scale deployment/nginx-deployment --replicas=0   # остановка всех подов
kubectl scale deployment/nginx-deployment --replicas=<прежнее>

# Декларативная проверка согласованности (защита от перезаписи коллегами)
kubectl patch deployment/nginx-deployment --type merge -p '{"spec":{"replicas":5}}' --subresource scale
```

Правила и ограничения масштабирования см. в [Базовые концепции — Scaling](#поведение-replicaset-при-масштабировании-scaling). Актуально при HPA: не выполняйте `kubectl scale` для Deployment, которым управляет autoscaler — значение будет перезаписано. Автоматическое масштабирование: [HPA](../../Autoscaling/HPA/index.md).

### Анализ событий: Rollout против Scaling

Различие между процессами можно отследить по системным событиям (`Events`):

| Процесс | Основные события (Events) | Источник (Source) |
| :--- | :--- | :--- |
| **Scaling** | `ScalingReplicaSet`: Scaled down/up replica set <rs-name> to X | `deployment-controller` |
| **Rollout** | `ScalingReplicaSet`: Scaled up replica set <new-rs> to Y<br>`ScalingReplicaSet`: Scaled down replica set <old-rs> to X | `deployment-controller` |
| **Создание/удаление подов** | `SuccessfulCreate` / `SuccessfulDelete` | `replicaset-controller` |

При Rollout события всегда затрагивают как минимум два ReplicaSet (уменьшение старого и увеличение нового), тогда как при обычном масштабировании изменяется только текущий активный RS. Наличие в событиях только `SuccessfulCreate`/`SuccessfulDelete` от `replicaset-controller` при отсутствии `ScalingReplicaSet` от `deployment-controller` указывает на пересоздание пода вручную (например, `kubectl delete pod`), а не на rollout.

Фильтрация событий по объекту:
```bash
kubectl get events --field-selector involvedObject.name=nginx-deployment
```

### Экспорт и очистка манифеста

При извлечении текущей конфигурации:
```bash
kubectl get deployment nginx-deployment -o yaml > deployment.yaml
```
**Важно:** Перед применением файла в другом окружении ОБЯЗАТЕЛЬНО удалите:
- Поля `uid`, `resourceVersion`, `creationTimestamp` и `selfLink`.
- Весь блок `status`, так как он генерируется кластером автоматически.
- Системные аннотации (например, `kubectl.kubernetes.io/last-applied-configuration`).

## 4. Диагностика при сбоях rollout

Если обновление «зависло», старые поды продолжают работать, пока новые не пройдут проверку готовности.

**Быстрый алгоритм отладки:**
1.  **События Deployment:** `kubectl describe deployment <name>` — смотрим блок `Conditions`. Ищите записи вида `ProgressDeadlineExceeded` или `ReplicaFailure`, а также проверьте `spec.paused` (пауза блокирует rollout).
2.  **Анализ ReplicaSets:** `kubectl get rs` — проверяем, какой именно RS (обычно самый новый) не может набрать нужное количество реплик.
3.  **Детализация пода:** `kubectl describe pod -l app=<label>` — ищем ошибки уровня контейнера (`ImagePullBackOff`, `CrashLoopBackOff`, неудачные пробы).
4.  **Логи:** `kubectl logs <pod-name> --previous` — критически важно для анализа причин падения контейнера в `CrashLoopBackOff`.

Полный системный алгоритм диагностики, разбор условий (`Progressing`/`Available`/`ReplicaFailure`), таблицы причин и реальные кейсы — в [Устранение неполадок Deployment и RollingUpdate](./troubleshooting.md) (данный файл не дублирует диагностику).

## 5. Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Иммутабельные теги и версии:** Используйте конкретные теги (`nginx:1.28.1-alpine`) или дайджесты, никогда `:latest` — иначе перепутаетесь в истории ревизий и откат «ничего не вернет».
2.  **Change-cause для каждой ревизии:** Заполняйте `kubernetes.io/change-cause` — история без причин бесполезна при RCA.
3.  **Zero-Downtime:** Для критичных сервисов `maxUnavailable: 0`, `maxSurge: 1` + HTTP-`readinessProbe`. Убедитесь, что в кластере есть запас ресурсов под surge.
4.  **Глубина истории:** `revisionHistoryLimit: 3–5` вместо дефолтных 10 — баланс между откатом и нагрузкой на `etcd`.
5.  **Таймауты в CI:** Всегда задавайте `kubectl rollout status --timeout=...` и при ненулевом коде выполняйте автоматический откат через `rollout undo` (см. [Автоматизация в CI/CD](#автоматизация-в-cicd-rollout-status-как-гейт)).
6.  **Пакет правок через pause/resume:** Несколько связанных изменений конфигурации выполняйте через паузу — это снижает число ревизий и риск «битого» промежуточного состояния (не забывайте `resume`).
7.  **Не вмешивайтесь в HPA:** Если Deployment управляется HPA — не меняйте `replicas` вручную; масштабируйте через autoscaler.
8.  **`minReadySeconds` для «медленных» приложений:** Устанавливайте 30–60с для критических сервисов, чтобы выявлять отложенные отказы только после попадания в трафик.
9.  **Откат данных ≠ откат кода:** Откат кода не вернет схему БД и содержимое ConfigMap/Secret — планируйте их совместный откат (см. [Обновление и rollout ConfigMap](../ConfigMap/update_and_rollout.md)).

### Ограничения и сложные случаи (Edge Cases)

1.  **Rollover (параллельные обновления):** Контроллер не ждет завершения текущего rollout при поступлении нового — старые RS сворачиваются, приоритет последнему шаблону. Это корректно, но усложняет чтение `rollout status`.
2.  **Откат приостановленного Deployment:** `kubectl rollout undo` не сработает для paused Deployment — сначала `rollout resume`.
3.  **`revisionHistoryLimit: 0`:** откат невозможен; удаленные из-за лимита ревизии невосстановимы — только повторное применение манифеста.
4.  **Откат к несуществующей ревизии:** `--to-revision` с номером вне истории → ошибка `unable to rollback to specified revision`.
5.  **Откат при идентичном шаблоне:** если целевой шаблон совпадает с текущим — откат no-op (Kubernetes «считает» его ненужным); проверяйте различия через `kubectl rollout history --revision=N`.
6.  **HPA против ручного масштабирования:** HPA перезаписывает вручную заданные `replicas`; при `maxUnavailable: 0` и нехватке узлов HPA и RollingUpdate конкурируют за ресурсы — следите за профицитом мощности.
7.  **ConfigMap/Secret не инициируют rollout:** изменение содержимого уже существующего объекта не перезапускает поды; применение — `rollout restart` или хеш-аннотация в шаблоне (детали — в [deployment_manifest.md](./deployment_manifest.md) и [update_and_rollout.md](../ConfigMap/update_and_rollout.md)).
8.  **Масштабирование во время rollout:** распределяется пропорционально между активными RS, а не всё в новый RS — ожидания «все реплики сразу в новой версии» при активном rollout неверны.
9.  **`rollout status` в CI и сетевые разрывы:** блокирующее ожидание зависит от watch API; транзиентные сбои соединения дают ложный отказ — добавьте retry.
10. **Мутабельные теги:** обновление `spec.template` с тем же тегом (`:latest`) не создает различаемого снимка — образ может быть другим при том же `pod-template-hash`-семействе; история деградирует.
11. **Рестарт на paused:** `rollout restart` при `spec.paused: true` ставит изменение в очередь — поды пересоздадутся только после `resume`.

### См. также

- [Манифест и лучшие практики](./deployment_manifest.md)
- [Устранение неполадок Deployment и RollingUpdate](./troubleshooting.md)
- [Проверки состояния (Probes)](../probes.md)