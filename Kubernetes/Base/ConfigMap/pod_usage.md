# Способы использования ConfigMap в подах

## Определения

**ConfigMap** — объект API Kubernetes, предназначенный для предоставления неконфиденциальных данных контейнерам внутри пода (Pod). Он служит мостом между абстрактной конфигурацией и конкретной средой выполнения, реализуя принцип **Separation of Concerns** (разделение ответственности) и обеспечивая переносимость (Portability) образов.

## Основные концепции

### Механизмы доставки данных

Существует три основных механизма передачи данных из ConfigMap в приложение:

1.  **Переменные окружения (`env`, `envFrom`):**
    *   Данные считываются Kubelet и передаются процессу при его старте.
    *   `env` позволяет точечно выбрать конкретный ключ через `valueFrom.configMapKeyRef`.
    *   `envFrom` загружает **все** ключи источника сразу; с помощью `prefix` к именам переменных можно добавить единый префикс.
    *   **Ограничение:** Изменения в ConfigMap не отражаются в уже запущенных процессах. Требуется перезапуск пода (Rollout) для применения новых значений.
2.  **Смонтированные тома (`volumes`):**
    *   ConfigMap монтируется как директория, где каждый ключ становится файлом, а значение — содержимым файла.
    *   **Преимущество:** Поддерживается автоматическое обновление данных без перезапуска пода (Hot Reload).
    *   Поле `items` позволяет выбрать отдельные ключи и переименовать файлы, `defaultMode` задает права доступа.
3.  **Аргументы командной строки (`$(VAR_NAME)` в `command`/`args`):**
    *   Строго говоря, это не самостоятельный механизм, а производная от переменных окружения: Kubelet раскрывает конструкцию `$(VAR_NAME)` из **полного** окружения контейнера перед запуском процесса.
    *   Позволяет передавать значения из ConfigMap в команду запуска без использования shell.

Дополнительно данные из ConfigMap можно объединять с другими источниками (Secret, Downward API) в **projected volumes** — см. [Projected Volumes](../Pod/volume_types/projected_volumes.md).

### Техническая реализация обновлений (Atomic Symlink Swap)

При монтировании ConfigMap как тома Kubelet использует механизм символических ссылок для обеспечения атомарности:
1.  Создается новая директория с данными (например, `..2024_08_05_12_00_00.123456789`).
2.  Обновляется символическая ссылка `..data`, указывающая на актуальную директорию.
3.  Файлы в корне монтирования являются ссылками на файлы внутри `..data`.
Это гарантирует, что приложение не прочитает "частично обновленный" файл. Задержка обновления в контейнере обычно составляет от 60 до 90 секунд — это период синхронизации подов `syncFrequency` (по умолчанию 60 с) плюс случайный «джиттер» (коэффициент 0.5). При стратегии `Cache` к этому добавляется `cacheTTL`; при `Watch` содержимое уже находится в локальном кэше kubelet, однако сама пересборка тома все равно привязана к циклу синхронизации пода (подробнее — в разделе о стратегиях ниже).

**Практическая проверка механизма:**

```bash
# Внутри контейнера видна ссылка ..data и файлы-связки
kubectl exec <pod-name> -- ls -la /etc/config
# → lrwxrwxrwx 1 root root 31 ..data -> ..2024_08_05_12_00_00.123456789
# → drwxr-xr-x 2 root root  6 ..2024_08_05_12_00_00.123456789
# → lrwxrwxrwx 1 root root 17 config.yaml -> ..data/config.yaml

# Чтение «актуального» содержимого через ссылку ..data
kubectl exec <pod-name> -- cat /etc/config/..data/config.yaml
```

После изменения ConfigMap и очередного цикла синхронизации рядом появляется **новая** директория с отметкой времени, а `..data` переключается на нее. Процессы, которые уже открыли файл, продолжат читать старую версию до повторного открытия файла (файловый дескриптор указывает на старый inode).

### Ограничения и область видимости

*   **Namespace:** ConfigMap и Pod должны находиться в одном и том же пространстве имен. Межnamespace-доступ не поддерживается — для использования в другом namespace объект нужно скопировать.
*   **Состояние запуска:** Если ConfigMap помечен как обязательный (по умолчанию), отсутствие ресурса переведет под в состояние `CreateContainerConfigError`. Диагностика — в разделе [Troubleshooting](../../Troubleshooting/Common_Errors/CreateContainerConfigError/configmap_issues.md).
*   **Размер:** Общий размер объекта ограничен **1 MiB** (лимит etcd, ошибка `RequestEntityTooLarge`). Для больших конфигураций используйте PersistentVolume или разбивайте данные на несколько ConfigMap.
*   **Хранение на узле:** Данные тома ConfigMap размещаются в локальной файловой системе узла (`/var/lib/kubelet/pods/<pod>/volumes/...`), а не на tmpfs, поэтому не занимают оперативную память узла. Доступ к файлам имеют только контейнеры пода и процессы на узле.
*   **Кэширование на узле:** данные кэшируются на узле. Если удалить ConfigMap, смонтированный в работающий под, под продолжит работать с закэшированной копией до перезапуска (после перезапуска последует `FailedMount`). Для переменных окружения аналогично — новые поды уже не запустятся (`CreateContainerConfigError`).

### Детали механизма синхронизации Kubelet

Kubelet отвечает за синхронизацию данных ConfigMap с файловой системой пода. Механизм работы зависит от способа потребления данных:

**Для томов (Volumes):**
1.  Менеджер ConfigMap в kubelet отслеживает изменения объекта (способ обнаружения настраивается, см. раздел ниже)
2.  При обновлении ConfigMap в API-сервере менеджер получает актуальное содержимое
3.  На очередном цикле синхронизации пода (`syncFrequency`, по умолчанию 60 с + джиттер) kubelet создает временную директорию (например, `..2024_08_05_12_00_00.123456789`)
4.  Символическая ссылка `..data` атомарно переключается на новую директорию
5.  Приложение видит обновленные файлы без перезапуска

**Для переменных окружения (env):**
1.  Kubelet читает данные ConfigMap при запуске контейнера
2.  Значения передаются процессу через переменные окружения
3.  При изменении ConfigMap переменные **не обновляются** в работающем процессе
4.  Требуется перезапуск пода для применения изменений

> **Важно:** стратегия обнаружения изменений управляет лишь тем, **как** kubelet получает актуальное содержимое объекта. Сама пересборка тома выполняется в цикле синхронизации пода, поэтому задержка в 60–90 секунд сохраняется даже в режиме `Watch`. Доставка конфигурации в поды при активном управлении жизненным циклом рассмотрена в [Обновление и Rollout](./update_and_rollout.md).

### Стратегии обнаружения изменений (configMapAndSecretChangeDetectionStrategy)

Kubelet поддерживает три стратегии обнаружения изменений ConfigMap и Secret. Поле задается в `KubeletConfiguration`:

| Стратегия | Описание | Нагрузка на API | Характерная задержка доставки |
| :--- | :--- | :--- | :--- |
| `Watch` | Kubelet устанавливает постоянный Watch на каждый используемый объект и всегда имеет актуальную локальную копию | Высокая (соединение на каждый объект на каждом узле) | Низкая (данные уже локальны) |
| `Get` | Kubelet выполняет обычный GET-запрос к API-серверу каждый раз, когда ему нужны данные | Средняя (запрос по требованию) | Зависит от цикла синхронизации пода |
| `Cache` | Kubelet опрашивает API-сервер и кэширует результат на `cacheTTL` (по умолчанию 1 минута) | Низкая (кэш с TTL) | До TTL + цикл синхронизации пода |

**Поведение по умолчанию:**
*   По умолчанию используется `Watch` — оптимальный баланс между скоростью обнаружения изменений и нагрузкой; рекомендуется для большинства кластеров.
*   `Cache` применяют в кластерах с очень большим количеством подов/ConfigMap на узле, где тысячи Watch-соединений создают чрезмерную нагрузку на API-сервер и etcd.
*   `Get` — компромисс без длинных соединений и без кэширования потенциально устаревших данных.

**Пример настройки:**
```bash
# В конфигурации kubelet (--config flag)
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
configMapAndSecretChangeDetectionStrategy: "Watch"
# cacheTTL: 1m   # параметр кэша, релевантен только для стратегии Cache
```

> **Важно:** стратегия влияет только на скорость получения содержимого менеджером ConfigMap. Момент фактического применения данных к томам определяется циклом синхронизации пода (`syncFrequency`), а переменные окружения вообще не обновляются «на лету» ни при одной стратегии.

### Поведение флага optional

Флаг `optional: true` в секциях `env`, `envFrom` и `volumes` определяет поведение при отсутствии ConfigMap:

**Для `env` и `envFrom`:**
```yaml
env:
- name: MY_CONFIG
  valueFrom:
    configMapKeyRef:
      name: my-config
      key: my-key
      optional: true  # Под запустится без ошибки
```

**Для `volumes`:**
```yaml
volumes:
- name: config-volume
  configMap:
    name: my-config
    items:
    - key: app.yaml
      path: config.yaml
    optional: true  # Том будет пустым, под запустится
```

**Поведение:**
- `optional: false` (по умолчанию): Под не запустится, если ConfigMap отсутствует
- `optional: true`: Под запустится, даже если ConfigMap отсутствует
- **Важно:** При `optional: true` и отсутствии ConfigMap:
  - Для `env`: переменная не будет установлена, под запустится без ошибки
  - Для `envFrom`: ни одна переменная не будет добавлена, под запустится
  - Для `volumes`: том будет пустой директорией
- **Детали с `items`:** если ConfigMap существует, но в нем нет ключа из `items`, и `optional: true` — соответствующий **путь просто не будет создан**, под запустится. Если `optional: false` — под не запустится.
- Флаг `optional` в `configMapKeyRef` распространяется и на отсутствие ключа: при `optional: true` переменная молча пропускается, если нет ни объекта, ни требуемого ключа.

### Правила разрешения переменных окружения (envFrom, prefix и $(VAR))

При одновременном использовании нескольких источников переменных действуют строгие правила приоритета:

**Порядок приоритета:**
1.  Явные `env` (включая `valueFrom.configMapKeyRef`) **переопределяют** одноименные ключи из `envFrom`.
2.  Несколько блоков `envFrom`: при дублировании ключа побеждает источник, указанный **позже** в списке.
3.  `envFrom` загружает все ключи; поле `prefix` добавляет префикс к имени каждой переменной.

**Пример:**
```yaml
envFrom:
- configMapRef:
    name: base-config
- configMapRef:
    name: feature-flags
  prefix: FF_          # Все ключи из feature-flags получат префикс FF_
- secretRef:
    name: app-secrets  # envFrom работает и с Secret
env:
- name: LOG_LEVEL      # env переопределяет значение из base-config
  valueFrom:
    configMapKeyRef:
      name: base-config
      key: log_level
```

**Невалидные имена переменных:**
Ключи ConfigMap, недопустимые как имена переменных окружения (например, `my.key`, `my-key` или начинающиеся с цифры), через `envFrom` **молча пропускаются** — под запускается, но такие переменные отсутствуют. На старых версиях факт пропуска фиксировался событием `InvalidEnvironmentVariableNames` в Events пода. После GA флага `RelaxedEnvironmentVariableValidation` (Kubernetes 1.35+) допустимы почти все печатные ASCII-символы, кроме `=`, однако **POSIX-совместимые оболочки** все равно могут не отображать подобные переменные.

**Практический вывод:** если планируется `envFrom`, используйте в ключах только `[A-Za-z0-9_]` (без точек и дефисов). Для ключей с точками/дефисами применяйте `configMapKeyRef` с явным `name` либо монтируйте ConfigMap как тома (в именах файлов точки и дефисы допустимы).

**Подстановка `$(VAR)` в command/args:**
*   Kubelet разворачивает `$(VAR_NAME)` из полного окружения контейнера (включая переменные из ConfigMap). Ссылка на переменную обязана идти **после** ее определения в списке `env`.
*   Если переменная не определена, `$(VAR_NAME)` остается литералом (не превращается в пустую строку) — это частая причина неожиданного поведения команд.
*   Для передачи литерала `$(VAR_NAME)` используйте экранирование `$$(VAR_NAME)` (синтаксис в стиле make: каждая `$$` сворачивается в один `$`). Крайне актуально для shell-скриптов в `args`, где `$$` в heredoc и арифметике `$((...))` некорректно поглощается Kubernetes.

**Пример экранирования:**
```yaml
command: ["/bin/sh", "-c"]
args:
- "echo literal: $$(NOT_A_VAR) and expanded: $(REAL_VAR)"
env:
- name: REAL_VAR
  valueFrom:
    configMapKeyRef:
      name: job-config
      key: task_type
```

*Примечание: правила приоритета env/envFrom едины для ConfigMap и Secret.*

### Взаимодействие с Downward API

ConfigMap может комбинироваться с Downward API для передачи метаданных Pod вместе с конфигурацией:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-metadata
spec:
  containers:
  - name: app
    image: my-app:latest
    env:
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: APP_CONFIG
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: config.yaml
    volumeMounts:
    - name: pod-metadata
      mountPath: /etc/podinfo
      readOnly: true
  volumes:
  - name: pod-metadata
    downwardAPI:
      items:
      - path: "labels"
        fieldRef:
          fieldPath: metadata.labels
```

## Практические сценарии

### Сценарий 1: Переменные окружения и флаг необязательности

Используется для простых параметров (порты, уровни логирования).

```yaml
spec:
  containers:
    - name: app
      image: my-app:1.0
      env:
        # Инъекция конкретного ключа
        - name: LOG_LEVEL
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: log_level
              optional: true # Позволяет поду запуститься, если CM или ключ отсутствуют
      # Массовая инъекция всех ключей
      envFrom:
        - configMapRef:
            name: feature-flags
            # prefix: "FF_"  # Добавляет префикс FF_ ко всем ключам feature-flags
```

### Сценарий 2: Монтирование файлов и управление правами

Используется для сложных конфигов (nginx, prometheus). Поле `items` позволяет выбрать конкретные ключи и переименовать их.

```yaml
spec:
  containers:
    - name: nginx
      image: nginx:1.25
      volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/conf.d
          readOnly: true
  volumes:
    - name: config-volume
      configMap:
        name: nginx-config
        defaultMode: 0440 # Права доступа в восьмеричном формате
        items:
          - key: "vhost.conf"
            path: "mysite.conf" # Файл будет доступен как /etc/nginx/conf.d/mysite.conf
```

### Сценарий 3: Использование в командной строке (command/args)

Значения из ConfigMap могут определять логику запуска контейнера.

```yaml
spec:
  containers:
    - name: batch-job
      image: alpine
      command: ["/bin/sh", "-c"]
      args: ["echo Starting task: $(TASK_NAME)"] # Значение берется из env
      env:
        - name: TASK_NAME
          valueFrom:
            configMapKeyRef:
              name: job-config
              key: task_type
```

### Сценарий 4: Native Sidecars (Kubernetes 1.29+)

Нативные sidecar-контейнеры (init-контейнеры с `restartPolicy: Always`) могут использовать ConfigMap для подготовки окружения или предоставления прокси-сервисов до запуска основного приложения.

```yaml
spec:
  initContainers:
    - name: auth-proxy
      image: oauth2-proxy:v7.0
      restartPolicy: Always
      envFrom:
        - configMapRef:
            name: proxy-settings
  containers:
    - name: main-app
      image: app:v2
```

### Сценарий 5: Множественные контейнеры с общей конфигурацией

Один ConfigMap может использоваться несколькими контейнерами в Pod с разными уровнями доступа:

```yaml
spec:
  containers:
  - name: web-server
    image: nginx:1.25
    volumeMounts:
    - name: shared-config
      mountPath: /etc/nginx/conf.d
      readOnly: true
  - name: log-collector
    image: fluentd:latest
    volumeMounts:
    - name: shared-config
      mountPath: /etc/fluent/config
      readOnly: true
  volumes:
  - name: shared-config
    configMap:
      name: app-config
      defaultMode: 0440
```

### Сценарий 6: ConfigMap с Init-контейнерами

Init-контейнеры могут использовать ConfigMap для подготовки данных перед запуском основного приложения:

```yaml
spec:
  initContainers:
  - name: config-validator
    image: busybox
    command: ['sh', '-c', 'cat /etc/config/app.yaml | grep -q "valid: true"']
    volumeMounts:
    - name: config-volume
      mountPath: /etc/config
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: config-volume
      mountPath: /etc/config
      readOnly: true
  volumes:
  - name: config-volume
    configMap:
      name: app-config
```

### Сценарий 7: ConfigMap в DaemonSet

DaemonSet автоматически создает Pod на каждом узле, используя ConfigMap для узловой конфигурации:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      containers:
      - name: exporter
        image: prom/node-exporter:latest
        volumeMounts:
        - name: node-config
          mountPath: /etc/node-exporter
          readOnly: true
      volumes:
      - name: node-config
        configMap:
          name: node-exporter-config
```

### Сценарий 8: ConfigMap в StatefulSet

StatefulSet обеспечивает стабильные имена и хранилище для Pod, используя ConfigMap для конфигурации:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16
        env:
        - name: POSTGRES_DB
          valueFrom:
            configMapKeyRef:
              name: postgres-config
              key: database
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: postgres-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

### Сценарий 9: Projected Volumes с ConfigMap

Projected volumes позволяют объединить ConfigMap с другими источниками (Secret, Downward API) в одной директории:

```yaml
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: combined-config
      mountPath: /etc/app
      readOnly: true
  volumes:
  - name: combined-config
    projected:
      sources:
      - configMap:
          name: app-config
          items:
          - key: "config.yaml"
            path: "config.yaml"
      - secret:
          name: app-secrets
          items:
          - key: "db-password"
            path: "secrets/db-pass"
      - downwardAPI:
          items:
          - path: "metadata/labels"
            fieldRef:
              fieldPath: metadata.labels
```

### Сценарий 10: Проверка актуальности и атомарности смонтированных файлов

Практическая задача SRE — убедиться, что в под доставлена именно нужная версия конфига и что механизм симлинков работает.

```bash
# 1. Проверка структуры тома (ссылка ..data и файлы-связки)
kubectl exec <pod-name> -- ls -la /etc/config

# 2. Целевой путь, на который указывает ..data (актуальная ревизия данных)
kubectl exec <pod-name> -- readlink /etc/config/..data

# 3. Фактическое содержимое «живого» файла через ссылку ..data
kubectl exec <pod-name> -- cat /etc/config/..data/config.yaml

# 4. Контрольная сумма файла (сравните до и после обновления ConfigMap)
kubectl exec <pod-name> -- sha256sum /etc/config/config.yaml
```

**Интерпретация результата:**
*   Если в каталоге присутствует `..data` и несколько директорий `..<timestamp>`, а приложение не перечитало конфиг после обновления — файлы доставлены корректно, проблема в отсутствии Hot Reload либо в невалидности нового конфига (приложение откатилось на старый).
*   Если `..data` отсутствует, а файлы лежат напрямую — том смонтирован через `subPath` (автообновление не работает) либо на узле старый kubelet.

### Сценарий 11: Императивная инъекция переменных окружения (kubectl set env)

Удобный способ для ad-hoc операций, отладки и прототипирования без правки YAML:

```bash
# Импорт ВСЕХ ключей ConfigMap как переменных в Deployment
kubectl set env deployment/my-app --from=configmap/app-config

# Импорт с префиксом (аналог envFrom.prefix)
kubectl set env deployment/my-app --from=configmap/app-config --prefix=APP_

# Импорт только отдельного ключа
kubectl set env deployment/my-app --keys=log_level --from=configmap/app-config

# Просмотр результирующего манифеста без применения (dry-run)
kubectl set env deployment/my-app --from=configmap/app-config -o yaml --dry-run=client

# Просмотр текущих переменных, включая ссылки на ConfigMap/Secret
kubectl set env deployment/my-app --list

# Удаление переменной
kubectl set env deployment/my-app LOG_LEVEL-
```

**Внимание:** команда изменяет шаблон пода, что триггерит Rolling Update. Для production-процессов предпочитайте декларативные манифесты (GitOps); `kubectl set env` удобен для отладки и разовых операций.

## Дополнительная информация

### Сравнение способов подключения

| Аспект | Переменные окружения (`env`) | Тома (`volumes`) |
| :--- | :--- | :--- |
| **Обновление** | Требует перезапуска (Rollout) | Автоматически (Hot Reload) |
| **Размер данных** | Ограничен лимитами ОС на env | До 1 MiB (лимит etcd) |
| **Сложные структуры** | Неудобно (только плоские ключи) | Идеально (вложенные файлы) |
| **subPath** | N/A | Блокирует Hot Reload |
| **Производительность** | Быстрый доступ при старте | Небольшая задержка синхронизации |
| **Безопасность** | Виден в `/proc/<pid>/environ` | Файлы на диске с правами доступа |

### Типичные ошибки и диагностика

#### Ошибка 1: `CreateContainerConfigError`

**Причина:** ConfigMap не найден или отсутствует ключ.

**Диагностика:**
```bash
# Проверка существования ConfigMap
kubectl get configmap <configmap-name> -n <namespace>

# Проверка ключей в ConfigMap
kubectl get configmap <configmap-name> -o jsonpath='{.data}' | jq 'keys'

# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 10 "Events:"
```

**Решение:**
```bash
# Убедитесь, что ConfigMap существует
kubectl get configmap <configmap-name> -n <namespace>

# Проверьте правильность имени и ключа в манифесте
```

#### Ошибка 2: `FailedMount` при монтировании

**Причина:** Конфликт путей монтирования или неправильные права доступа.

**Диагностика:**
```bash
# Проверьте, не используется ли subPath
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes[*].configMap}'

# Проверьте права доступа к файлам
kubectl exec <pod-name> -- ls -la /etc/config
```

**Решение:**
```yaml
# Правильное монтирование с указанием прав
volumeMounts:
- name: config-volume
  mountPath: /etc/config
  readOnly: true
volumes:
- name: config-volume
  configMap:
    name: my-config
    defaultMode: 0440
```

#### Ошибка 3: Данные не обновляются

**Причина:** Используется `subPath` или переменные окружения.

**Диагностика:**
```bash
# Проверьте, используется ли subPath
kubectl get pod <pod-name> -o json | jq '.spec.volumes[].configMap'

# Проверьте, используется ли env вместо volumes
kubectl get pod <pod-name> -o json | jq '.spec.containers[].env'
```

**Решение:**
```yaml
# Используйте volumes вместо subPath для Hot Reload
volumeMounts:
- name: config-volume
  mountPath: /etc/config
  # НЕ используйте subPath для обновляемых данных
```

#### Ошибка 4: `optional: true` не работает

**Причина:** ConfigMap существует, но ключ отсутствует.

**Диагностика:**
```bash
# Проверьте все ключи в ConfigMap
kubectl get configmap <configmap-name> -o jsonpath='{.data}' | jq 'keys'

# Проверьте, какой ключ ожидается в манифесте
kubectl get pod <pod-name> -o json | jq '.spec.containers[].env[].valueFrom.configMapKeyRef.key'
```

**Решение:**
```bash
# Добавьте недостающий ключ в ConfigMap
kubectl edit configmap <configmap-name>
# или
kubectl patch configmap <configmap-name> --type merge -p '{"data":{"my-key":"my-value"}}'
```

#### Ошибка 5: Переменные из envFrom не появились в контейнере

**Причина:** Ключи ConfigMap содержат символы, недопустимые для имен переменных окружения (точки, дефисы, начало с цифры) — такие ключи молча пропускаются, под запускается.

**Диагностика:**
```bash
# Проверка ключей ConfigMap
kubectl get configmap <cm-name> -o jsonpath='{.data}' | jq 'keys'

# Проверка событий пода на предмет InvalidEnvironmentVariableNames (старые версии)
kubectl get events --field-selector involvedObject.name=<pod-name> | grep -i invalid

# Список переменных, реально попавших в контейнер
kubectl exec <pod-name> -- env | sort
```

**Решение:**
- Переименуйте ключи в underscore-стиле (`log_level` вместо `log.level`)
- Либо переключитесь на явный `env[].valueFrom.configMapKeyRef`, где имя переменной задается отдельно
- Либо монтируйте ConfigMap как тома — в именах файлов точки и дефисы допустимы

#### Ошибка 6: `$(VAR)` в command/args не подставился

**Причина:** Переменная не определена к моменту развертывания, ссылка расположена **раньше** определения в списке `env`, либо используется одиночный `$` вместо `$$` для передачи литерала.

**Диагностика:**
```bash
# Команда, которая реально будет выполнена (до подстановки)
kubectl get pod <pod-name> -o json | jq '.spec.containers[0].command, .spec.containers[0].args'

# Наличие переменной в окружении контейнера
kubectl exec <pod-name> -- env | grep <VAR>
```

**Решение:**
```bash
# Напишите имя переменной ТОЧНО как в env (с учетом регистра)
kubectl get configmap <cm-name> -o jsonpath='{.data.<key>}'
# Для литерала $(...) используйте $$(...), а не $...
```

### Диагностические команды

```bash
# Просмотр всех ConfigMap в Namespace
kubectl get configmap -n <namespace>

# Просмотр содержимого ConfigMap
kubectl get configmap <configmap-name> -o yaml

# Проверка, какие Pod используют ConfigMap
kubectl get pods -n <namespace> -o json | jq '.items[] | select(.spec.volumes[]?.configMap.name == "<configmap-name>") | .metadata.name'

# Проверка переменных окружения в Pod
kubectl exec <pod-name> -- env | grep <CONFIG_NAME>

# Просмотр событий Pod
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'

# Проверка использования ConfigMap в env
kubectl get pods -n <namespace> -o json | jq '.items[] | select(.spec.containers[].env[].valueFrom.configMapKeyRef.name == "<configmap-name>") | .metadata.name'

# Ссылки на ConfigMap в шаблоне Deployment (env, envFrom, volumes)
kubectl get deploy <app> -n <namespace> -o json | \
  jq '.spec.template.spec.containers[0] | {env: .env, envFrom: .envFrom}'

# Структура смонтированного тома (проверка ..data)
kubectl exec <pod-name> -- ls -la /etc/config

# Реальные переменные окружения внутри контейнера
kubectl exec <pod-name> -- env | sort

# Список переменных, объявленных через refs, в шаблоне пода
kubectl set env deploy/<app> --list
```

### Производительность и оптимизация

**Влияние на производительность:**
- В режиме `Watch` каждый узел с подами, потребляющими ConfigMap, устанавливает Watch-соединение на **каждый** используемый объект (не по одному на ConfigMap в целом, а на уровне kubelet узла)
- В больших кластерах (тысячи узлов и объектов) это создает значительную нагрузку на API-сервер и etcd
- Используйте `immutable: true` для статических конфигураций — Kubelet выполняет одноразовый GET и не держит Watch; подробнее см. [Неизменяемые ConfigMap](./immutable.md)
- Для узлов с очень большим числом подов/ConfigMap можно перевести kubelet в стратегию `Cache` или `Get` (компромисс скорости и нагрузки)

**Оптимизации:**
```yaml
# Используйте неизменяемые ConfigMap для статических данных
apiVersion: v1
kind: ConfigMap
metadata:
  name: static-config
immutable: true
data:
  config.yaml: |
    # Статическая конфигурация
```

**Мониторинг:**
Отслеживать изменения ConfigMap по метрикам kube-state-metrics следует аккуратно: `kube_configmap_info` — это статичная метрика-маркер (значение всегда 1, состав меток: namespace, name, immutable, labels), поэтому выражение `changes(kube_configmap_info[...])` **не сработает**. Корректные сигналы:

*   **Удаление/пересоздание объекта:** метрика `kube_configmap_created` несет время создания (.Value). Сравнение интервалов выявляет удаленные ConfigMap:
    ```yaml
    # Срабатывает, если ConfigMap, существовавший 10 минут назад, теперь отсутствует
    - alert: ConfigMapDeleted
      expr: |
        (kube_configmap_created offset 10m) unless kube_configmap_created
      for: 0m
      labels:
        severity: warning
      annotations:
        summary: "ConfigMap {{ $labels.namespace }}/{{ $labels.name }} удален"
    ```
*   **Изменение содержимого:** kube-state-metrics не экспортирует значения `data`, поэтому полагайтесь на GitOps-конвейер (diff в CI/CD), Watch-события API или метрики sidecar-reloader'а (например, `configmap_reload_success_total` у `configmap-reload`).
*   **Hot Reload приложений:** контролируйте метрики reloader'а и частоту пересборок томов через события пода (`kubectl get events --watch`).

### Безопасность при использовании

**RBAC-ограничения:**
```yaml
# Role для ограничения доступа к ConfigMap
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: configmap-reader
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]
  resourceNames: ["allowed-configmap"]  # Ограничьте конкретными именами
```

**Практические меры:**
*   **Неизменяемость:** Для стабильных конфигураций используйте `immutable: true`. Это отключает Watch со стороны Kubelet, существенно снижая нагрузку на API-сервер, и защищает от случайных ручных правок. Подробнее см. [Неизменяемые ConfigMap](./immutable.md).
*   **Валидация в CI:** Используйте `kubeconform` или `conftest` для проверки манифестов перед применением (размер, обязательные поля, `readOnly`).
*   **Мониторинг:** Настройте алерты на удаление критических ConfigMap (через `kube_configmap_created`) и на деградацию reloader-ов (Prometheus).
*   **Секреты:** ConfigMap не шифруется и доступен любому субъекту с правами чтения в namespace. Пароли, токены и ключи храните исключительно в [Secret](../secrets/secrets_basics.md).

> Подробнее о readOnly, defaultMode, fsGroup и Admission Control: [Лучшие практики ConfigMap](./best_practices.md)

### Интеграция с инструментами

**Helm:**
```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  config.yaml: |
    {{- .Files.Get "configs/config.yaml" | nindent 4 }}
```

**Kustomize:**
```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  files:
    - configs/config.yaml
  options:
    immutable: true
```

**ArgoCD/Flux:**
```yaml
# Автоматическое обновление при изменении ConfigMap
apiVersion: argoproj.io/v1alpha1
kind: Application
spec:
  syncPolicy:
    automated:
      prune: true
```

**Автоматические перезапуски при изменении конфигурации** подробно рассмотрены в [Helm: перезапуск при изменении конфига](../../ToolsUtilities/Helm/templating/scenarios/restart_on_change.md) и [Reloader (оператор перезапусков)](../../ToolsUtilities/reloader/reloader_overview.md).

### ConfigMap и HorizontalPodAutoscaler (HPA)

HPA **не использует ConfigMap напрямую** для своей конфигурации — спецификация HPA определяется полностью в её собственном CRD-манифесте. Однако есть важные пересечения:

1. **GitOps-конфликт:** HPA управляет `spec.replicas` Deployment, а ArgoCD/Flux управляет манифестом из Git. Без настройки `ignoreDifferences` ArgoCD будет постоянно откатывать количество реплик. Решение: в ArgoCD укажите `jsonPointers: ["/spec/replicas"]` в `ignoreDifferences`.

2. **Cluster Autoscaler + ConfigMap:** Cluster Autoscaler использует ConfigMap `cluster-autoscaler-priority-expander` для определения приоритетов node group при масштабировании, которое запускается, когда HPA создаёт поды без возможности размещения.

3. **Ресурсные лимиты:** При `autoscaling.enabled=true` в Helm, `replicas` в Deployment опускается, а управление количеством реплик передаётся HPA. Убедитесь, что `minReplicas` в HPA >= `minAvailable` в PDB.

> Подробнее: [HPA](../../Autoscaling/HPA/index.md), [HPAAdvanced](../../Autoscaling/HPA/hpa_advanced.md), [HPA scenarios](../../Autoscaling/HPA/hpa_scenarios.md)

### ConfigMap и Service Mesh (Istio/Envoy)

Istio **не использует ConfigMap** для своей основной конфигурации. Конфигурация Istio управляется через CRDs:

| CRD | Назначение | Аналогия |
|---|---|---|
| `Sidecar` | Управление scope envoy sidecar | Фильтрация доступа к сервисам |
| `PeerAuthentication` | mTLS политики | Security context |
| `AuthorizationPolicy` | L4/L7 авторизация | Network Policy |
| `VirtualService` | Маршрутизация трафика | Ingress rules |
| `DestinationRule` | Circuit breaking,负载均衡 | Connection policy |
| `Telemetry` | Метрики, логи, трейсы | Monitoring config |

**Единственное пересечение ConfigMap + Service Mesh:** Stakater Reloader может следить за ConfigMap, используемым для sidecar-конфигурации (например, кастомный envoy bootstrap), и инициировать rollout при изменении:

```yaml
annotations:
  configmap.reloader.stakater.com/reload: "envoy-sidecar-config"
```

> Подробнее: [Service Mesh concepts](../../../../Service_Mesh/service_mesh_concepts.md), [Istio architecture](../../../../Service_Mesh/istio_architecture.md), [Proxy sidecar](../../../../Service_Mesh/proxy_sidecar.md)

**См. также:**

* [Создание ConfigMap](./creation.md) — декларативные и императивные подходы.
* [Неизменяемые ConfigMap](./immutable.md) — оптимизация производительности.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии обновления конфигураций.
* [Projected Volumes](../Pod/volume_types/projected_volumes.md) — агрегация данных из нескольких источников.
* [Работа с большими конфигурациями](./large_configs.md) — обход лимита 1 MiB.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — шаблоны для Nginx, Prometheus, Postgres.
