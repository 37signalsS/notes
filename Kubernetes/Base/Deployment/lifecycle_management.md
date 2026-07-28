# Управление жизненным циклом Deployment в Kubernetes

## 1. Определения

**Управление жизненным циклом (Lifecycle Management)** — это совокупность декларативных и императивных процессов по контролю состояния приложения в Kubernetes. Оно охватывает этапы развертывания (Rollout), обновления конфигурации, мониторинга готовности, отката к предыдущим ревизиям (Rollback), а также оперативного управления (пауза, возобновление и принудительный перезапуск).

Общие концепции и описание полей манифеста см. в разделах:
- **[Kubernetes Deployment: Обзор](./index.md)**
- **[Манифест и лучшие практики](./deployment_manifest.md)**

## 2. Базовые концепции

### Иерархия объектов и механизм владения

Управление осуществляется по цепочке:
`Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

Deployment не создает поды напрямую. Он управляет наборами реплик (`ReplicaSet`), которые, в свою очередь, обеспечивают работу нужного количества подов. Механизм `ownerReferences` в метаданных позволяет Kubernetes автоматически отслеживать связи и выполнять каскадное удаление (Garbage Collection).

### Механизм Rolling Update на уровне ReplicaSet

Критически важно понимать, что процесс обновления не «редактирует» существующие поды. Вместо этого происходит подмена одного ReplicaSet другим:

1.  Создается **новый** ReplicaSet с обновленным шаблоном пода (`pod-template-hash`).
2.  Начинается постепенная миграция трафика:
    ```
    Старый RS: N → N-1 → ... → 0
    Новый RS:  0 → 1   → ... → N
    ```
3.  Параметры `maxSurge` (дополнительные поды) и `maxUnavailable` (допустимая потеря мощности) определяют «шаг» этого процесса.
4.  Старый ReplicaSet сохраняется в системе, но масштабируется в 0 реплик. Это позволяет выполнить мгновенный откат (`rollout undo`), просто поменяв количество реплик между старым и новым RS.

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

### Параметры контроля стабильности

Для предотвращения деградации сервиса при обновлениях используются следующие параметры:

- **`minReadySeconds`**: Время (в секундах), которое под должен проработать без сбоев, прежде чем он будет считаться «готовым» (available). Если приложение падает через 10 секунд после старта, этот параметр не даст Deployment продолжить убивать старые поды.
- **`progressDeadlineSeconds`**: Лимит времени (по умолчанию 600с) на выполнение обновления. Если за это время новый RS не смог стать доступным (например, из-за `ImagePullBackOff`), статус Deployment пометится как `Failed`.
- **`revisionHistoryLimit`**: Количество старых ReplicaSet, сохраняемых для отката. Рекомендуемое значение: 3–5 (вместо дефолтных 10) для снижения нагрузки на etcd.

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

Каждый запуск Rollout создает новую ревизию в истории. Развертывания сохраняют историю изменений, что позволяет легко выполнять откат — эта возможность является важнейшей «сетью безопасности» (safety net) для производственных операций.

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

- **Пауза и возобновление:** Позволяет внести серию изменений в конфигурацию (например, сменить образ и ресурсы), не запуская обновление после каждой правки.
  ```bash
  kubectl rollout pause deployment/nginx-deployment
  # ... выполнение манипуляций (set image, set resources) ...
  kubectl rollout resume deployment/nginx-deployment
  ```
- **Перезапуск (Restart):** Применяется для пересоздания подов без изменения манифеста. Полезно, когда нужно заставить приложение перечитать внешние данные (ConfigMap, Secret) или при утечках памяти.
  ```bash
  kubectl rollout restart deployment/nginx-deployment
  ```

### Диагностика и алгоритм при сбоях

Если обновление «зависло», старые поды продолжают работать, пока новые не пройдут проверку готовности.

**Алгоритм отладки:**
1.  **События Deployment:** `kubectl describe deployment <name>` — смотрим блок `Conditions`.
2.  **Анализ ReplicaSets:** `kubectl get rs` — проверяем, какой именно RS не может набрать нужное количество реплик.
3.  **Детализация пода:** `kubectl describe pod -l app=<label>` — ищем ошибки уровня контейнера (`ImagePullBackOff`, `CrashLoopBackOff`, неудачные пробы).

## 4. Дополнительная информация

### Анализ полей ReplicaSet

Команда `kubectl get rs` дает важную информацию о ходе жизненного цикла:

| Поле | Назначение |
| :--- | :--- |
| **DESIRED** | Сколько подов должно быть согласно ревизии. |
| **CURRENT** | Сколько подов фактически создано в данный момент. |
| **READY** | Сколько подов прошли `readinessProbe` и готовы к трафику. |

### Экспорт и очистка манифеста

При извлечении текущей конфигурации для повторного использования:
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
- [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)
