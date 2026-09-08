# Хуки и тестирование в Helm

Хуки (Hooks) позволяют вмешиваться в жизненный цикл релиза Helm для выполнения вспомогательных задач (миграции, бэкапы, уведомления), а механизм тестирования обеспечивает автоматизированную проверку работоспособности развёрнутого приложения.

---

## Определения

| Термин | Описание |
|--------|----------|
| **Hook (Хук)** | Ресурс Kubernetes, помеченный аннотацией `helm.sh/hook`, который запускается Helm на определённых этапах жизненного цикла релиза. |
| **Test (Тест)** | Специализированный хук с аннотацией `helm.sh/hook: test`, предназначенный для проверки состояния приложения после установки или обновления. |
| **Hook Weight (Вес)** | Параметр `helm.sh/hook-weight`, определяющий порядок выполнения нескольких хуков на одном этапе (от меньшего к большему). Допускает отрицательные значения. |
| **Delete Policy (Политика удаления)** | Аннотация `helm.sh/hook-delete-policy`, управляющая моментом автоматического удаления ресурсов хука из кластера. |
| **Resource Policy (Политика ресурсов)** | Аннотация `helm.sh/resource-policy: keep`, указывающая Helm не удалять ресурс (например, PVC) при удалении всего релиза. |

---

## Базовые концепции

### Точки входа в жизненный цикл (Lifecycle Events)

Helm выполняет хуки синхронно. Если хук завершается с ошибкой (Exit Code != 0 для Job или Pod), Helm прерывает операцию и переводит релиз в статус `failed`. В версии **v4** при использовании SSA ресурсы хуков также попадают под управление `field ownership`, но обычно удаляются согласно политикам.

| Событие | Момент запуска |
|---------|----------------|
| `pre-install` | После рендеринга шаблонов, но до создания каких-либо ресурсов в кластере. |
| `post-install` | После того, как все основные ресурсы релиза были созданы и подтверждены. |
| `pre-delete` | Перед удалением любых ресурсов из релиза. |
| `post-delete` | После завершения удаления всех ресурсов релиза. |
| `pre-upgrade` | Перед обновлением существующих ресурсов. |
| `post-upgrade` | После успешного обновления всех ресурсов. |
| `pre-rollback` | Перед началом процесса отката на предыдущую ревизию. |
| `post-rollback` | После завершения процесса отката. |

### Взаимодействие с другими командами Helm

| Команда | Какие хуки срабатывают |
|---------|------------------------|
| `helm install` | `pre-install` -> основные ресурсы -> `post-install` |
| `helm upgrade` | `pre-upgrade` -> обновление ресурсов -> `post-upgrade` |
| `helm rollback` | `pre-rollback` -> восстановление ресурсов -> `post-rollback` |
| `helm uninstall` | `pre-delete` -> удаление ресурсов -> `post-delete` |
| `helm test` | Только ресурсы с аннотацией `helm.sh/hook: test` |

**Важно:** Хуки не выполняются при `helm template` (рендеринг без деплоя) и при `--dry-run`.

### Управление порядком и ожиданием

#### Веса хуков (Hook Weight)
Порядок выполнения хуков на одном этапе определяется весом:
- Значение должно быть строкой, представляющей целое число (например, `"10"`, `"-5"`).
- Хуки с меньшим весом запускаются первыми.
- Если веса равны, Helm сортирует ресурсы по имени.
- Helm дожидается успешного завершения текущего хука (Job завершён, Pod перешёл в Ready), прежде чем запустить следующий.

#### Политики удаления хуков (Hook Delete Policy)
Для экономии ресурсов или сохранения логов используются следующие политики:
- `before-hook-creation`: (по умолчанию) удаление старого ресурса хука непосредственно перед запуском нового.
- `hook-succeeded`: удаление ресурса сразу после его успешного выполнения.
- `hook-failed`: сохранение ресурса при ошибке для последующей отладки (удаление только вручную или при следующем запуске).

**Рекомендации по комбинациям политик:**
- **Миграции БД:** `before-hook-creation,hook-succeeded` — чистит старые Job'ы и удалит успешные. При ошибке Job остаётся для анализа логов.
- **Pre-flight проверки:** `before-hook-creation,hook-succeeded` — временные ресурсы, не нужны после проверки.
- **Очистка внешних ресурсов:** `hook-succeeded` — удалять только после подтверждения успеха.

### Механизм тестирования (Helm Test)

Тесты — это поды (Pod) или задания (Job), расположенные в директории `templates/tests/`. Они запускаются только вручную командой `helm test <release_name>`.

*   **Изоляция:** Ресурсы тестов не устанавливаются при обычном `helm install`.
*   **Результат:** Тест считается успешным, если контейнер завершился с кодом 0.
*   **Очистка:** Используйте флаг `helm test --cleanup` для автоматического удаления подов после завершения тестов.
*   **Повторный запуск:** При повторном `helm test` поды пересоздаются (аналогично `before-hook-creation`).

#### Типы тестов

| Тип | Описание | Пример |
|-----|----------|--------|
| **Smoke test** | Минимальная проверка доступности сервиса | HTTP-запрос к `/health` |
| **Integration test** | Проверка взаимодействия между компонентами | Запрос к API, чтение/запись в БД |
| **E2E test** | Полный сценарий использования | Регистрация пользователя, оформление заказа |

---

## Практические сценарии

### Миграция базы данных (pre-upgrade)

Использование `Job` для выполнения миграций перед обновлением кода приложения. Если миграция упадет, приложение не будет обновлено, что предотвратит рассинхронизацию схемы данных.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-db-migrate"
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: migration-tool
          image: my-app:{{ .Values.image.tag }}
          command: ["/app/migrate", "--env=prod"]
          envFrom:
            - secretRef:
                name: {{ include "mychart.fullname" . }}-db-creds
      restartPolicy: Never
  backoffLimit: 0 # Блокировать релиз сразу при первой ошибке
```

**Идемпотентность миграций:** Убедитесь, что скрипт миграции проверяет текущую версию схемы перед применением. Это гарантирует, что повторный запуск (например, при тайм-ауте) не приведёт к дублированию данных.

```bash
# Пример проверки версии в скрипте миграции
CURRENT_VERSION=$(psql -t -c "SELECT version FROM schema_migrations ORDER BY id DESC LIMIT 1")
if [ "$CURRENT_VERSION" = "20240101" ]; then
  echo "Миграция уже применена"
  exit 0
fi
```

### Комплексный тест работоспособности API (API Connectivity)

Проверка работоспособности сервиса после деплоя.

**`templates/tests/test-api.yaml`:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "mychart.fullname" . }}-test-connection"
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: wget
      image: busybox
      command: ['wget']
      args: ['{{ include "mychart.fullname" . }}:{{ .Values.service.port }}/health']
  restartPolicy: Never
```

### Очистка внешних ресурсов (pre-delete)

Удаление временных файлов в S3 или внешних кэшей перед удалением приложения.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-cleanup"
  annotations:
    "helm.sh/hook": pre-delete
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: cleanup-script
          image: alpine:latest
          command: ["sh", "-c", "rm -rf /data/cache/{{ .Release.Name }}"]
      restartPolicy: Never
```

**Предупреждение:** `post-delete` хук выполняется на удалении и не может быть откачен. Не размещайте в нём код, изменяющий внешние системы без подтверждения пользователя.

### Сохранение данных (resource-policy: keep)

Использование аннотации для предотвращения удаления критических ресурсов (например, PVC) при очистке релиза.

```yaml
kind: PersistentVolumeClaim
metadata:
  name: {{ .Release.Name }}-postgres-pvc
  annotations:
    "helm.sh/resource-policy": keep
```

### Pre-flight проверки перед деплоем (pre-install)

Проверка доступности внешних зависимостей перед установкой приложения. Если зависимость недоступна, Helm прервёт установку.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-preflight"
  annotations:
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: {{ .Release.Name }}-preflight
      containers:
      - name: preflight
        image: "{{ .Values.tools.image }}:{{ .Values.tools.tag }}"
        command: ["sh", "-c", |
          # Проверка доступности PostgreSQL
          pg_isready -h $POSTGRES_HOST -p 5432 || exit 1
          # Проверка доступности Redis
          redis-cli -h $REDIS_HOST -p 6379 ping || exit 1
          # Проверка наличия CRD
          kubectl get crd certificates.cert-manager.io || exit 1
        ]
        envFrom:
          - secretRef:
              name: {{ include "mychart.fullname" . }}-db-creds
```

### Бэкап перед обновлением (pre-upgrade)

Автоматический бэкап базы данных перед обновлением приложения.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-backup"
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
      - name: backup
        image: postgres:16-alpine
        command: ["sh", "-c", |
          pg_dump -h $POSTGRES_HOST -U $POSTGRES_USER $POSTGRES_DB | \
          gzip > /backup/{{ .Release.Name }}-$(date +%Y%m%d%H%M%S).sql.gz
        ]
        envFrom:
          - secretRef:
              name: {{ include "mychart.fullname" . }}-db-creds
        volumeMounts:
        - name: backup-volume
          mountPath: /backup
      volumes:
      - name: backup-volume
        persistentVolumeClaim:
          claimName: {{ .Release.Name }}-backup-pvc
      restartPolicy: Never
  backoffLimit: 0
```

### Мульти-тест с разными уровнями проверки

Комплексный набор тестов для проверки различных аспектов работоспособности приложения.

**`templates/tests/test-smoke.yaml`:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "mychart.fullname" . }}-smoke"
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-weight": "1"
spec:
  containers:
  - name: smoke-test
    image: curlimages/curl:latest
    command: ['curl', '-f', 'http://{{ include "mychart.fullname" . }}:{{ .Values.service.port }}/health']
  restartPolicy: Never
```

**`templates/tests/test-integration.yaml`:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "mychart.fullname" . }}-integration"
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-weight": "2"
spec:
  containers:
  - name: integration-test
    image: curlimages/curl:latest
    command: ['sh', '-c', |
      # Проверка API
      curl -f http://{{ include "mychart.fullname" . }}:{{ .Values.service.port }}/api/health || exit 1
      # Проверка БД
      curl -f http://{{ include "mychart.fullname" . }}:{{ .Values.service.port }}/api/db-check || exit 1
      # Проверка Redis
      curl -f http://{{ include "mychart.fullname" . }}:{{ .Values.service.port }}/api/cache-check || exit 1
    ]
  restartPolicy: Never
```

**`templates/tests/test-e2e.yaml`:**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ include "mychart.fullname" . }}-e2e"
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-weight": "3"
    "helm.sh/hook-delete-policy": hook-succeeded,hook-failed
spec:
  template:
    spec:
      containers:
      - name: e2e-test
        image: my-app-e2e:{{ .Values.image.tag }}
        command: ["npm", "run", "test:e2e"]
        env:
        - name: API_URL
          value: "http://{{ include "mychart.fullname" . }}:{{ .Values.service.port }}"
      restartPolicy: Never
  backoffLimit: 0
```

---

## Диагностика и устранение неполадок

### Просмотр логов хуков

```bash
# Найти Job хука по метке
kubectl get jobs -n <namespace> -l "helm.sh/hook=pre-upgrade"

# Посмотреть логи конкретного пода
kubectl logs -n <namespace> <pod-name>

# Посмотреть логи завершившегося пода (если pod deleted)
kubectl logs -n <namespace> --previous <pod-name>
```

### Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `helm release failed` при хуке | Хук завершился с Exit Code != 0 | Проверьте логи пода: `kubectl logs <pod>` |
| `timed out waiting for the condition` | Хук не завершился вовремя | Увеличьте `--timeout` или оптимизируйте хук |
| ` Helm release failed: a release named X already exists` | Конфликт имён при повторном запуске | Используйте `before-hook-creation` policy |
| `forbidden: violates PodSecurity` | Namespace запрещает привилегированные поды | Добавьте необходимые лейблы PSA или используйте `restricted` профиль |
| Миграция применяется повторно | Скрипт миграции не идемпотентен | Добавьте проверку версии схемы перед применением |
| Хук не выполняется при `helm template` | `helm template` — только рендеринг, без деплоя | Используйте `helm install --dry-run` для проверки |
| `Job.batch "xxx" is invalid` | Некорректный манифест Job | Проверьте `restartPolicy: Never` и `backoffLimit` |

### Отладка хуков

```bash
# Рендер шаблонов с включёнными хуками (проверка YAML)
helm template my-release ./mychart --show-only templates/hooks/db-migrate.yaml

# Dry-run с проверкой API (проверка валидности в кластере)
helm install my-release ./mychart --dry-run --debug

# Проверка конкретного хука через kubectl
kubectl describe job -n <namespace> <job-name>

# Проверка статуса Job
kubectl get job -n <namespace> <job-name> -o yaml
```

---

## Дополнительная информация

### Важные нюансы

- **Job против Pod:** Для хуков всегда рекомендуется использовать `Job`, так как они обеспечивают лучшую управляемость жизненным циклом и автоматическую очистку.
- **Тайм-ауты:** Выполнение хуков ограничено параметром `--timeout`. Если хук не завершился вовремя, релиз пометится как `failed`.
- **Логи:** Если используется политика `hook-succeeded`, логи хука будут удалены вместе с подом. Для отладки в CI рекомендуется временно отключать политику удаления.
- **ArgoCD:** При использовании ArgoCD стандартные хуки Helm могут конфликтовать с [ArgoCD Hooks](../../GitOps/ArgoCD/synchronization/scenarios/sync_waves_hooks.md). Рекомендуется придерживаться одного механизма.
- **Безопасность хуков:** Job-хуки должны использовать отдельные ServiceAccount с минимальными правами. Никогда не выполняйте миграции от имени администратора кластера. Запрещайте `hostNetwork: true` в hook-шаблонах.
- **Helm 4 и SSA:** В версии v4 ресурсы хуков управляются через Server-Side Apply (SSA). Учитывайте это при работе с `field ownership` в мульти-инструментальных средах.
- **Порядок выполнения:** Хуки выполняются синхронно в порядке весов. Helm дожидается завершения текущего хука перед запуском следующего. Это важно для цепочек зависимостей (например, миграция -> проверка -> деплой).

### Antipatterns (Чего следует избегать)

- **Монолитные хуки:** Не объединяйте несколько несвязанных операций в один Job. Разделяйте на отдельные хуки с разными весами.
- **Длинные хуки:** Хук, выполняющийся дольше 5 минут, может привести к тайм-ауту. Разбивайте на этапы.
- **Хуки без идемпотентности:** Каждый хук должен быть безопасен для повторного запуска.
- **Отсутствие `restartPolicy: Never` для Job:** Без этого параметра Pod будет перезапускаться, что может привести к бесконечному циклу.

### Best Practices для CI/CD

```bash
# 1. Валидация шаблонов с хуками
helm lint ./mychart --strict
helm template my-release ./mychart --debug | kubeconform --strict

# 2. Тестирование хуков в CI (dry-run)
helm install my-release ./mychart --dry-run --debug --timeout 5m

# 3. Запуск тестов после деплоя
helm test my-release --timeout 10m

# 4. Проверка хуков через кubectl
kubectl get jobs -n <namespace> -l "helm.sh/hook"
```

### Интеграция с инструментами

| Инструмент | Особенности использования |
|------------|---------------------------|
| **ArgoCD** | Используйте вместо хуков Sync Hooks и Waves для совместимости |
| **Flux** | Хуки не поддерживаются, используйте Health Checks и Alerts |
| **helmfile** | Оркестрирует выполнение хуков через `lifecycle` в `helmfile.yaml` |
| **chart-testing (ct)** | Автоматически запускает `helm test` при проверке чартов |

---

## См. также

- **[Обзор Helm](./helm_overview.md)** — архитектура v4 и базовые принципы.
- **[Структура Helm-чарта](./helm_chart_structure.md)** — организация файлов в репозитории.
- **[Команды и рабочий процесс Helm](./helm_commands_and_workflow.md)** — управление жизненным циклом релизов.
- **[Официальная документация Helm Hooks](https://helm.sh/docs/topics/charts_hooks/)** (англ.).
