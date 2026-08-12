# Управление жизненным циклом Deployment в Kubernetes

Декларативные и императивные процессы контроля состояния приложения: от развертывания и масштабирования до отката и диагностики.

## 1. Определения

**Управление жизненным циклом (Lifecycle Management)** — совокупность процессов по контролю состояния приложения в Kubernetes. Оно охватывает этапы развертывания (Rollout), обновления конфигурации, мониторинга готовности, отката к предыдущим ревизиям (Rollback), а также оперативного управления (пауза, возобновление и принудительный перезапуск).

Общие концепции и описание полей манифеста см. в разделах:
- **[Kubernetes Deployment: Обзор](./index.md)**
- **[Манифест и лучшие практики](./deployment_manifest.md)**

## 2. Базовые концепции

### Иерархия объектов и механизм владения

Управление осуществляется по цепочке:
`Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

Deployment не создает поды напрямую. Он управляет наборами реплик (`ReplicaSet`), которые, в свою очередь, обеспечивают работу нужного количества подов. Механизм `ownerReferences` в метаданных ресурсов обеспечивает каскадное управление и автоматическое удаление зависимых объектов (Garbage Collection).

### Механизм Rolling Update на уровне ReplicaSet

Процесс обновления (Rollout) не редактирует существующие поды. Вместо этого происходит постепенная подмена одного ReplicaSet другим:

1.  **Создание новой ревизии:** При изменении `spec.template` контроллер Deployment создает **новый** ReplicaSet с обновленным шаблоном пода и уникальным хешем в метке `pod-template-hash`.
2.  **Миграция реплик:** Начинается постепенное изменение количества реплик в старом и новом RS:
    - Старый RS: N → N-1 → ... → 0
    - Новый RS:  0 → 1   → ... → N
3.  **Контроль шага:** Параметры `maxSurge` (дополнительные поды) и `maxUnavailable` (допустимая потеря мощности) определяют «размер шага» этой миграции.
4.  **Хранение истории:** Старый ReplicaSet сохраняется в системе, но масштабируется в 0 реплик. Это позволяет выполнить мгновенный откат (`rollout undo`), просто поменяв количество реплик между старым и новым RS.

### Поведение ReplicaSet при масштабировании (Scaling)

В отличие от Rollout, операция масштабирования (`kubectl scale` или изменение `spec.replicas`) не создает новую ревизию и не инициирует создание нового ReplicaSet.

- **Активный процесс:** Контроллер Deployment напрямую обновляет поле `replicas` в **текущем активном** ReplicaSet (том, который соответствует текущему `pod-template-hash`).
- **Масштабирование во время обновления:** Если масштабирование происходит в момент активного Rolling Update, контроллер пропорционально распределяет новые реплики между всеми задействованными ReplicaSet, чтобы соблюсти ограничения `maxSurge` и `maxUnavailable`, при этом приоритет отдается самому новому RS.

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

### Параметры контроля стабильности и Zero-Downtime

Для предотвращения деградации сервиса и обеспечения выката без потерь (Zero-Downtime) используются следующие параметры:

- **`maxUnavailable: 0` и `maxSurge: 1`**: При дефолтных настройках Deployment может вывести часть подов из строя до того, как поднимутся новые. Если сервис работает на пределе мощности, это вызовет перегрузку и ошибки 504. Установка `maxUnavailable: 0` гарантирует, что старые поды не будут удалены, пока новые не станут `Ready`.
- **`minReadySeconds`**: Время ожидания после того, как под перешел в состояние `Ready` (согласно `readinessProbe`), прежде чем он будет считаться действительно рабочим (Available). 
  - **Назначение:** Позволяет приложению «прогреться» (Warm-up), накатить кеши или выявить ошибки, которые возникают не сразу после старта.
- **`progressDeadlineSeconds`**: Время, в течение которого контроллер Deployment ожидает прогресса. Если за это время новый ReplicaSet не смог стать доступным, обновление помечается как проваленное (`Failed`).
- **`terminationGracePeriodSeconds`**: Должен быть больше суммы времени `preStop sleep` и реального времени дренажа запросов приложением.

#### Выбор Readiness Probe для Zero-Downtime
Типовая ошибка — использование **TCP-пробы** вместо HTTP. TCP-сокет открывается ОС сразу при старте процесса, часто задолго до того, как приложение реально готово отвечать (прогреты пулы соединений, загружены кеши). Трафик идет на «холодный» под, что вызывает ошибки. Использование **HTTP-пробы** на эндпоинт (например, `/readyz`), который проверяет внутреннюю готовность, является обязательным для стабильного выката.

## 3. Практические сценарии

### Основные команды управления

```bash
# Обновление образа приложения
kubectl set image deployment/nginx-deployment nginx=nginx:1.28.1-alpine
# → deployment.apps/nginx-deployment image updated

# Отслеживание статуса развертывания
kubectl rollout status deployment/nginx-deployment
# → Waiting for deployment "nginx-deployment" rollout to finish: 1 of 3 updated replicas are available...
# → deployment "nginx-deployment" successfully rolled out
```

### Управление ревизиями и Rollback

Каждый запуск Rollout создает новую ревизию в истории. Это важнейшая «сеть безопасности» (safety net) для производственных операций.

```bash
# Просмотр истории изменений
kubectl rollout history deployment/nginx-deployment
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         Обновление до v1.28.1-alpine

# Детальный просмотр конкретной ревизии
kubectl rollout history deployment/nginx-deployment --revision=2

# Откат к предыдущей стабильной версии
kubectl rollout undo deployment/nginx-deployment
# → deployment.apps/nginx-deployment rolled back

# Откат к определенной ревизии по номеру
kubectl rollout undo deployment/nginx-deployment --to-revision=1
```

### Документирование изменений (change-cause)

Для того чтобы в истории ревизий вместо `<none>` отображалась причина, используйте аннотацию `kubernetes.io/change-cause`.

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

### Оперативное управление (Pause/Restart)

- **Пауза и возобновление:** Позволяет внести серию изменений в конфигурацию (образ, ресурсы, переменные), не запуская обновление после каждой правки. Это экономит ресурсы и предотвращает создание промежуточных «битых» ревизий.
  ```bash
  kubectl rollout pause deployment/nginx-deployment
  # ... выполнение манипуляций (set image, set resources) ...
  kubectl rollout resume deployment/nginx-deployment
  ```
- **Перезапуск (Restart):** Применяется для пересоздания подов без изменения манифеста. Полезно для перечитывания внешних данных (ConfigMap/Secret из томов) или при обнаружении утечек памяти.
  ```bash
  kubectl rollout restart deployment/nginx-deployment
  ```

### Анализ событий: Rollout против Scaling

Различие между процессами можно отследить по системным событиям (`Events`):

| Процесс | Основные события (Events) | Источник (Source) |
| :--- | :--- | :--- |
| **Scaling** | `ScalingReplicaSet`: Scaled replica set <rs-name> to X | `deployment-controller` |
| **Rollout** | `ScalingReplicaSet`: Scaled replica set <old-rs> to X<br>`ScalingReplicaSet`: Scaled replica set <new-rs> to Y | `deployment-controller` |

При Rollout события всегда затрагивают как минимум два ReplicaSet (уменьшение старого и увеличение нового), тогда как при обычном масштабировании изменяется только текущий активный RS.

### Диагностика и алгоритм при сбоях

Если обновление «зависло», старые поды продолжают работать, пока новые не пройдут проверку готовности.

**Алгоритм отладки:**
1.  **События Deployment:** `kubectl describe deployment <name>` — смотрим блок `Conditions`. Ищите записи вида `ProgressDeadlineExceeded` или `ReplicaFailure`.
2.  **Анализ ReplicaSets:** `kubectl get rs` — проверяем, какой именно RS (обычно самый новый) не может набрать нужное количество реплик.
3.  **Детализация пода:** `kubectl describe pod -l app=<label>` — ищем ошибки уровня контейнера (`ImagePullBackOff`, `CrashLoopBackOff`, неудачные пробы).
4.  **Логи:** `kubectl logs <pod-name> --previous` — критически важно для анализа причин падения контейнера в `CrashLoopBackOff`.

### Анализ полей ReplicaSet

Команда `kubectl get rs` предоставляет информацию о статусе ревизий:

| Поле | Назначение |
| :--- | :--- |
| **DESIRED** | Желаемое количество реплик для данной ревизии (результат работы алгоритма Rollout). |
| **CURRENT** | Сколько подов фактически создано в данный момент для этой ревизии. |
| **READY** | Сколько подов прошли `readinessProbe` и готовы к приему трафика. |

### Экспорт и очистка манифеста

При извлечении текущей конфигурации:
```bash
kubectl get deployment nginx-deployment -o yaml > deployment.yaml
```
**Важно:** Перед применением файла в другом окружении ОБЯЗАТЕЛЬНО удалите:
- Поля `uid`, `resourceVersion`, `creationTimestamp` и `selfLink`.
- Весь блок `status`, так как он генерируется кластером автоматически.
- Системные аннотации (например, `kubectl.kubernetes.io/last-applied-configuration`).

### См. также

- [Kubernetes Deployment: Манифест и лучшие практики](./deployment_manifest.md)
- [Проверки состояния (Probes)](../probes.md)
- [Сине-зеленое развертывание (Blue-Green)](../../../CI-CD/Deployment_Strategies/blue_green_deployment.md)
- [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)
