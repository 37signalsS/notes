# ReplicaSet — контроллер репликации

## Определения

**ReplicaSet** — это объект API Kubernetes (контроллер), основной задачей которого является поддержание стабильного набора идентичных подов (**Pod**, реплик) в любой момент времени. Он гарантирует, что в кластере запущено ровно то количество подов, которое указано в его спецификации (`spec.replicas`).

**Одиночный Pod как точка отказа:** Использование подов без контроллера (ad-hoc поды) является критической ошибкой в архитектуре. Если узел, на котором он запущен, выйдет из строя или процесс завершится с ошибкой, под не будет перезапущен. Контроллеры (ReplicaSet, Deployment, StatefulSet) обеспечивают отказоустойчивость путем автоматического воссоздания ресурсов.

**Исторический контекст:** `ReplicaSet` является развитием устаревшего **ReplicationController**. Ключевое техническое отличие — поддержка расширенных селекторов (**Set-based selectors**), позволяющих использовать операторы `In`, `NotIn`, `Exists`. ReplicationController поддерживал только простое равенство меток (**Equality-based**).

## Основные концепции

### Жизненный цикл создания (Event Flow)

Процесс появления подов через ReplicaSet управляется циклом согласования (Reconciliation Loop):
1.  **Запрос (Request):** Пользователь (или контроллер Deployment) создает объект ReplicaSet через API Server.
2.  **Обнаружение (Watch):** `ReplicaSet Controller` (в составе `kube-controller-manager`) получает уведомление о новом объекте.
3.  **Сравнение (Diff):** Контроллер проверяет количество существующих подов с нужными метками.
4.  **Генерация (Generate):** Если подов не хватает, контроллер создает манифесты `Pod` на основе шаблона (`spec.template`).
5.  **Владение (OwnerReference):** API Server при создании подов прописывает в них `ownerReferences`, связывая их с данным RS.
6.  **Планирование (Schedule):** `kube-scheduler` видит новые поды в статусе `Pending` и назначает их на узлы.
7.  **Исполнение (Execute):** `Kubelet` на узле запускает контейнеры.
8.  **Отчетность (Report):** Состояние пода обновляется, и контроллер ReplicaSet видит, что желаемое состояние достигнуто.

### Анатомия спецификации и параметры контроля

*   **`replicas`**: Целевое число реплик. Если установлено в `0`, все поды будут удалены (часто используется Deployment-ом для старых ревизий).
*   **`selector`**: Определяет область управления. **Внимание:** Поле `spec.selector` является неизменяемым (immutable) после создания объекта.
    *   `matchLabels`: Простое равенство.
    *   `matchExpressions`: Операторы `In`, `NotIn`, `Exists`, `DoesNotExist`.
*   **`template`**: Описание пода. Изменения в шаблоне не влияют на уже запущенные поды. Для обновления требуется пересоздание подов.
*   **`minReadySeconds`**: Время ожидания после того, как под перешел в состояние `Ready`, прежде чем он будет считаться действительно рабочим. Позволяет приложению «прогреться» или выявить ошибки, возникающие не сразу, предотвращая каскадные падения при запуске неисправных версий.

### Метка pod-template-hash

При работе через **Deployment**, к каждому `ReplicaSet` автоматически добавляется метка `pod-template-hash`.
*   **Назначение:** Гарантирует, что конкретный RS управляет только теми подами, которые соответствуют именно этой ревизии кода/конфигурации.
*   **Механизм:** Deployment вычисляет хеш от `PodTemplate` и добавляет его в селектор RS и метки подов. Это предотвращает конфликты, если два разных Deployment-а используют одинаковые метки (например, `app: my-app`).

### Алгоритм удаления подов (Downscaling)

При уменьшении `replicas` контроллер выбирает жертв в следующем приоритете:
1.  Поды в состоянии `Terminating`.
2.  Поды с наименьшим количеством готовых контейнеров.
3.  Поды, не прошедшие Readiness Probe.
4.  Поды на узлах с наибольшим количеством реплик этого RS (балансировка по зонам/узлам).
5.  Самые "молодые" поды.

### Механизм владения (OwnerReferences)

Kubernetes использует **Owner References** для каскадного удаления:
*   Удаление ReplicaSet по умолчанию приводит к удалению всех его подов (Garbage Collection).
*   **Orphaning (Осиротение):** При удалении с флагом `--cascade=orphan` поды сохраняются. Это полезно при миграциях или отладке.

## Практические сценарии

### Пример манифеста (v1.30+)

```yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: web-api
  labels:
    app: web
    version: v1
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        ports:
        - containerPort: 80
```

### Диагностика и управление

```bash
# Проверка состояния реплик
kubectl get rs web-api
# NAME      DESIRED   CURRENT   READY   AGE
# web-api   3         3         3       5m
# DESIRED - сколько хотим (spec.replicas)
# CURRENT - сколько уже создано
# READY   - сколько прошли Readiness Probe

# Детальная информация: причины, почему не достигнуто целевое состояние
kubectl describe rs web-api
# В разделе Events хорошо видны ошибки: ImagePullBackOff, FailedCreate
# (нехватка quota), 0/3 nodes available (нехватка ресурсов узла) и т.п.

# Просмотр сырого статуса (Replicas, ReadyReplicas, ObservedGeneration, Conditions)
kubectl get rs web-api -o yaml | grep -A30 '^status:'

# Масштабирование (если не используется HPA — иначе конфликт владельца значения)
kubectl scale rs web-api --replicas=10

# Безопасное масштабирование: отказаться, если текущее число реплик изменилось
# (защита от гонки с HPA/оператором)
kubectl scale rs web-api --replicas=10 --current-replicas=3

# Масштабирование «в ноль» (например, для останова ненужной нагрузки)
kubectl scale rs web-api --replicas=0

# Изоляция пода для отладки (Quarantine)
# Просто измените метку пода, чтобы он перестал попадать под селектор RS,
# — контроллер создаст новый под взамен, а старый останется для изучения
kubectl label pod <pod-name> app=debug --overwrite

# Просмотр принадлежности пода к ReplicaSet и Deployment (ownerReferences)
kubectl get pod <pod-name> -o jsonpath='{.metadata.ownerReferences}'
```

**Важно про `kubectl scale --replicas=0`:** это не «остановка» Deployment, а лишь сокращение числа подов. В связке `Deployment → ReplicaSet` корректнее масштабировать через Deployment, чтобы сохранить целостность истории ревизий.

### Обновление подов, управляемых напрямую ReplicaSet

ReplicaSet не выполняет rolling update. Если вы управляете подами напрямую через RS (например, в кастомном операторе), то изменение `template` не затронет уже запущенные поды — нужно пересоздать их вручную. Самый простой способ — «откат шаблона»:

```bash
# 1. Измените image в шаблоне RS (новые поды будут с новым образом)
kubectl set image rs/web-api nginx=nginx:1.28

# 2. Удалите старые поды — контроллер создаст новые по обновлённому шаблону
kubectl delete pods -l app=web

# 3. Проверьте результат
kubectl get rs web-api
# web-api   3   3   3   6m
```

Такой ручной «rolling restart» приводит к кратковременному простою (все поды удаляются почти одновременно). Для бесшовной смены версии без простоя используйте двухфазную схему (синяя/зелёная):

```bash
# Создаём RS второй версии параллельно со старым
kubectl create -f web-api-v2.yaml        # RS с меткой version: v2

# После проверки зелёных подов переключаем трафик и удаляем старый RS
kubectl delete rs web-api-v1
```

Именно из-за ручного характера обновлений и отсутствия rollback для statless приложений стандартная рекомендация — использовать **Deployment**, который автоматизирует rolling update, откат и хранение истории ревизий. Прямое управление RS уместно только в контроллерах/операторах.

### Взаимодействие с HPA

**Horizontal Pod Autoscaler (HPA)** может изменять `spec.replicas` в ReplicaSet. Однако, если RS управляется Deployment-ом, HPA следует настраивать на **Deployment**. В противном случае, при обновлении приложения (Rollout), HPA может продолжать масштабировать старый (неактивный) ReplicaSet.

**Практические моменты:**

```bash
# Создать HPA на основе CPU для Deployment (рекомендуемый вариант)
kubectl autoscale deployment web-api --cpu-percent=70 --min=2 --max=10

# Просмотр текущих реплик, установленных HPA, и целевых метрик
kubectl get hpa web-api
# NAME      REFERENCE            TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# web-api   Deployment/web-api   45%/70%   2         10        4          10m
```

*   **Конфликт владельца значения:** Если RS управляется HPA, оператор (или человек) не должен параллельно выполнять `kubectl scale` на том же контроллере — оба будут перезаписывать `spec.replicas`. HPA отслеживает изменения и быстро вернёт своё значение, создавая «соревнование» (race) и лишнюю запись в API.
*   **Масштабирование в ноль:** Нативный HPA не умеет масштабировать в `0` (исключение — настройка на основе pod metrics с `scaleTargetRef`). Если нужно выключить нагрузку в нерабочее время, используйте `KEDA` ([обзор](../Autoscaling/keda/keda_concepts.md)) или временно `kubectl scale --replicas=0` с отключением HPA.
*   При использовании `minReadySeconds` HPA корректнее реагирует: новый под считается готовым только после прогрева, что уменьшает ложные срабатывания на нестабильном приложении.

## Операции и диагностика

### Типовые проблемы и их устранение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `replicas` не увеличивается, поды в `Pending` | Недостаточно ресурсов на узлах, либо нехватка квоты/`LimitRange` | `kubectl describe rs` → найти `0/3 nodes available` или `FailedCreate: exceeded quota`. Увеличить квоту или уменьшить requests; проверить taints/tolerations. |
| `ImagePullBackOff` / `ErrImagePull` | Неверный тег образа или нет доступа к registry | Исправить `spec.template.spec.containers[].image`; проверить ImagePullSecrets. См. [пробы и диагностика](../Base/probes.md). |
| Поды создаются и падают (CrashLoopBackOff) | Ошибка в приложении, не проходят readiness | Смотреть `kubectl logs`, `kubectl describe pod`. |
| READY < CURRENT без ошибок | Приложение не становится Ready за отведённое время, срабатывает `minReadySeconds` | Проверить readiness probe, увеличить `minReadySeconds` или исправить приложение. |
| Ошибка при изменении `selector` | Поле `spec.selector` immutable | Создать новый RS (или обновить Deployment) с нужным селектором; нельзя менять существующий. |
| HPA «воюет» с ручным `scale` | Два источника истины для `spec.replicas` | Изменить реплики только через HPA либо удалить HPA. |
| ReplicaSet не «видит» существующие поды с подходящими метками | Подоги не имеют меток из селектора, либо `controller` в ownerReferences | Проверить, что метки подов полностью покрывают `selector`; `kubectl get pods --show-labels`. |

### Диагностика через события и статус

```bash
# События, связанные с RS (создание/удаление подов, ошибки)
kubectl get events --field-selector involvedObject.name=web-api

# Условие ReplicaFailure (например, quota исчерпана)
kubectl get rs web-api -o jsonpath='{.status.conditions}' | python3 -m json.tool

# Поды конкретного RS (по селектору)
kubectl get pods -l app=web --show-labels
```

### Отладка сервисов под ReplicaSet

```bash
# Копирование файла из случайного пода RS (для аудита без входа во все поды)
POD=$(kubectl get pods -l app=web -o jsonpath='{.items[0].metadata.name}')
kubectl cp $POD:/var/log/app.log ./app.log

# Местоположение пода (узел) — для поиска «горячего» узла
kubectl get pods -l app=web -o wide
```

## Мониторинг и алертинг ReplicaSet (SRE/DevOps)

Базовые метрики ReplicaSet предоставляются `kube-state-metrics`:

| Метрика | Назначение |
| :--- | :--- |
| `kube_replicaset_replicas` | Желаемое число реплик (`spec.replicas`). |
| `kube_replicaset_status_replicas` | Текущее число созданных подов. |
| `kube_replicaset_status_ready_replicas` | Число готовых подов (прошли readiness). |
| `kube_replicaset_status_observed_generation` | Поколение, обработанное контроллером (расхождение говорит о задержке контроллера). |
| `kube_replicaset_metadata_generation` | Поколение метаданных объекта. |
| `kube_replicaset_created` | Время создания RS (unix). |

**Ключевой алерт для SRE:** реплики не соответствуют желаемому числу в течение длительного времени.

```yaml
groups:
- name: replicasets
  rules:
  # Под-ы недоступны дольше ожидаемого — вероятно, RS не справляется
  - alert: ReplicaSetHasUnavailableReplicas
    expr: |
      (kube_replicaset_replicas > 0)
        and (kube_replicaset_status_ready_replicas < kube_replicaset_replicas)
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "ReplicaSet {{ $labels.replicaset }} ({{ $labels.namespace }}) не обеспечивает достаточное число готовых подов"
      description: "Число готовых подов ниже желаемого (значение метрики {{ $value }}). Проверьте события (kubectl describe rs) и раздел «Типовые проблемы»."
```

**Практический совет:** самый быстрый способ проверить, что кластер «докрутил» нужное число подов, — сравнить колонки `DESIRED` и `CURRENT/READY` в `kubectl get rs -A`. Для целостного аудита всех ReplicaSet по кластеру:

```bash
# Все RS, где CURRENT != READY (подозрение на проблему)
kubectl get rs -A | awk 'NR==1 || $3 != $4 {print}'

# Развёрнутые без Deployment (т.е. управляемые напрямую)
kubectl get rs -A -o json | python3 -c "
import sys, json
for rs in json.load(sys.stdin)['items']:
    own = rs['metadata'].get('ownerReferences', [])
    if not any(o.get('kind') == 'Deployment' for o in own):
        print(rs['metadata']['namespace'], rs['metadata']['name'])
"
```

Подробнее об архитектуре мониторинга — [Kubernetes Monitoring & Logging](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

## Дополнительная информация

### Сравнение: ReplicaSet vs Deployment

| Функция | ReplicaSet | Deployment |
| :--- | :--- | :--- |
| Поддержка реплик | Да | Да (через RS) |
| Rolling Update | Нет (вручную) | Да (автоматически) |
| Rollback | Нет | Да (`kubectl rollout undo`) |
| История ревизий | Нет | Да |

**Вердикт:** Всегда используйте `Deployment` для stateless приложений. Прямое использование `ReplicaSet` оправдано только при написании кастомных контроллеров или операторов, где логика обновлений реализуется вручную.

### Ловушки и граничные случаи (Edge Cases)

*   **Immutable selector:** `spec.selector` нельзя изменить после создания. Решение — создать новый RS, а старый удалить с `--cascade=orphan`/`--cascade=foreground`, чтобы не потерять нужные поды.
*   **Каскадное удаление против orphaning:** `kubectl delete rs web-api` удалит и поды (garbage collection по `ownerReferences`). `kubectl delete rs web-api --cascade=orphan` оставит поды бесхозными (ad-hoc). Это удобно для миграций, но такие поды больше никто не восстанавливает — при сбое узла они не пересоздаются.
*   **`minReadySeconds` и цена прогрева:** большой `minReadySeconds` задерживает включение новых реплик в балансировку, но защищает от быстрых каскадных падений. Учитывайте при настройке SLA.
*   **ReplicaSet без подходящих подов в селекторе** не создаст их «с запасом» — он строго доводит число до `spec.replicas`. Лишние поды с теми же метками, но созданные вручную, RS не трогает (они ему не принадлежат), пока они не `Ready` и не мешают.
*   **Масштабирование с HPA и KEDA:** см. раздел «Взаимодействие с HPA» — держите единственный источник значения `replicas`.

### Рекомендации (Best Practices)

1.  Для statless подов используйте **Deployment**, а не ReplicaSet напрямую — вы получаете rolling update, rollback и историю ревизий бесплатно.
2.  Всегда задавайте **readiness-пробы** (`readinessProbe`) — без них READY всегда равно CURRENT, но трафик пойдёт на ещё не готовые поды.
3.  Задавайте **resource requests/limits** — иначе качество размещения и поведение HPA непредсказуемы.
4.  Устанавливайте **`kubectl scale --current-replicas`** в скриптах автоскалирования/сопровождения для защиты от «войны» с HPA.
5.  Не редактируйте `spec.selector` в существующем RS — пересоздавайте объект.
6.  Для плановых простоев целого RS используйте `kubectl scale --replicas=0`, а не удаление — это обратимо и не трогает конфигурацию.
7.  Добавляйте алерт на расхождение желаемого и готового числа реплик (см. раздел мониторинга).

### См. также

*   **[Deployment — управление жизненным циклом](./Deployment/index.md)** — производственный слой поверх ReplicaSet.
*   **[Horizontal Pod Autoscaler (HPA)](../Autoscaling/HPA/index.md)** — автоматическое масштабирование.
*   **[Механизмы владения и Garbage Collection](../Concepts/metadata_and_labels.md#поля-метаданных-metadata-fields)** — как работает каскадное удаление.
