# Способы использования ConfigMap в подах

**Актуально для:** Kubernetes 1.28–1.32+

## Определения

**ConfigMap** — объект API Kubernetes (`kind: ConfigMap`), предназначенный для хранения неконфиденциальных параметров конфигурации в виде пар ключ-значение. Реализует принцип разделения исполняемого кода и конфигурации (12-Factor App), обеспечивая переносимость контейнерных образов между средами без пересборки.

**Volume Mount (Монтирование тома)** — механизм подключения содержимого ConfigMap к файловой системе контейнера через спецификацию `spec.volumes[*].configMap` и `spec.containers[*].volumeMounts`. Каждый ключ ConfigMap проецируется в отдельный файл, а значение ключа становится содержимым файла.

**Atomic Symlink Swap (Атомарная замена символических ссылок)** — низкоуровневый механизм Kubelet Volume Manager, обеспечивающий атомарное обновление файлов смонтированного тома на диске узла. Заключается в создании новой директории данных с таймштампом и мгновенном переключении символической ссылки `..data` через системный вызов `renameat`, что предотвращает чтение частично записанных файлов.

**`subPath` / `subPathExpr`** — директива `volumeMounts`, позволяющая смонтировать один конкретный файл или поддиректорию из тома напрямую в путь внутри контейнера без перекрытия родительского каталога. В ядре Linux реализуется через отдельный bind mount на конкретный inode, что блокирует механизм Atomic Symlink Swap и отключает автоматическое обновление файла (Hot Reload).

**`env` / `envFrom`** — механизмы инъекции ключей ConfigMap в переменные окружения процесса контейнера. `env` выполняет точечную передачу через `valueFrom.configMapKeyRef`, а `envFrom` импортирует все допустимые ключи объекта с возможностью добавления префикса (`prefix`).

**`defaultMode`** — поле спецификации тома ConfigMap, задающее права доступа (POSIX file permissions) в восьмеричном формате (например, `0440`, `0644`) для всех проецируемых файлов. По умолчанию равно `0644` (десятичное `420`).

**`Kubelet Volume Manager`** — внутренний управляющий контур Kubelet, отвечающий за сверку желаемого состояния томов (DesiredStateOfWorld) с фактическим состоянием на узле (ActualStateOfWorld), монтирование каталогов и фоновую синхронизацию содержимого.

**`syncFrequency` и `configMapAndSecretChangeDetectionStrategy`** — параметры конфигурации Kubelet (`KubeletConfiguration`), регулирующие частоту цикла периодической синхронизации подов (по умолчанию 60 секунд) и стратегию отслеживания изменений в API-сервере (`Watch`, `Get`, `Cache`).

**Projected Volume** — специализированный тип тома Kubernetes, объединяющий проекцию нескольких разнородных источников (ConfigMap, Secret, Downward API, ServiceAccountToken) в единое дерево каталогов контейнера.

---

## Архитектура и принципы работы

### Механизмы передачи данных в Pod

Kubernetes предоставляет три фундаментальных способа потребления данных ConfigMap контейнерами:

```
                                 ┌─────────────────────────┐
                                 │   ConfigMap (etcd)      │
                                 └────────────┬────────────┘
                                              │
                      ┌───────────────────────┼───────────────────────┐
                      ▼                       ▼                       ▼
           ┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
           │ Переменные env      │ │ Том Volume Mount    │ │ Аргументы command   │
           │ (env / envFrom)     │ │ (директория / файлы)│ │ ($(VAR) в args)     │
           └──────────┬──────────┘ └──────────┬──────────┘ └──────────┬──────────┘
                      │                       │                       │
                      ▼                       ▼                       ▼
            Старт процесса          Файловая система узла   Разворачивание Kubelet
            (не обновляется         (Atomic Symlink Swap,   до старта процесса
             без рестарта)           Hot Reload доступен)    (статично)
```

1. **Переменные окружения (`env`, `envFrom`):**
   - Значения считываются Kubelet при подготовке контейнера и передаются в процесс при запуске (в Linux-структуру `environ`).
   - `env` подключает конкретные ключи через `valueFrom.configMapKeyRef`.
   - `envFrom` импортирует все ключи ConfigMap через `configMapRef`.
   - **Ограничение:** Переменные окружения процесса в ОС Linux фиксируются при вызове `execve()`. Изменение объекта ConfigMap в кластере **не отражается** в работающих контейнерах. Для применения требуется полный перезапуск пода.

2. **Смонтированные тома (`volumes` и `volumeMounts`):**
   - ConfigMap монтируется как директория на файловой системе контейнера.
   - Поддерживает автоматическое обновление данных без перезапуска пода (Hot Reload).
   - Поле `items` позволяет проецировать только выбранные ключи и менять имена целевых файлов; поле `defaultMode` управляет POSIX-маской прав доступа.

3. **Аргументы командной строки (`$(VAR_NAME)` в `command`/`args`):**
   - Kubelet выполняет макроподстановку `$(VAR_NAME)` на основе сформированного списка переменных окружения контейнера до старта процесса.
   - Позволяет передавать конфигурационные флаги напрямую в бинарный файл без участия командного интерпретатора (`/bin/sh`).

4. **Проекция томов (Projected Volumes):**
   - Объединяет несколько ConfigMap, Secret и Downward API в единую файловую структуру без ограничений `subPath`. Подробно разобран в [Projected Volumes](../Pod/volume_types/projected_volumes.md).

---

### Архитектура Kubelet Volume Manager и механизм Atomic Symlink Swap

При монтировании тома ConfigMap процесс `kubelet` не копирует файлы напрямую в корень контейнера. Для предотвращения состояния гонки (Race Condition), когда приложение считывает файл в момент неполной записи на диск, ядро Kubelet использует каскадную структуру символических ссылок:

```
/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~configmap/<volume-name>/
├── ..2026_10_13_16_00_00.123456789/          <-- Фактическая директория с данными
│   ├── app.conf
│   └── database.json
├── ..data -> ..2026_10_13_16_00_00.123456789  <-- Промежуточная симлинк (атомарный swap)
├── app.conf -> ..data/app.conf                <-- Стабильная симлинк для контейнера
└── database.json -> ..data/database.json      <-- Стабильная симлинк для контейнера
```

#### Алгоритм обновления тома Kubelet

1. **Создание теневой директории:** Kubelet получает новую версию ConfigMap от API-сервера и создает в каталоге тома на узле директорию с временной меткой: `..<timestamp>` (например, `..2026_10_13_16_05_00.987654321`).
2. **Запись данных:** Внутри созданной директории формируются файлы, соответствующие ключам ConfigMap, и выставляются права доступа согласно `defaultMode`.
3. **Создание временной ссылки:** Создается вспомогательная символическая ссылка `..data_tmp`, указывающая на новую директорию `..<timestamp>`.
4. **Атомарный системный вызов:** Выполняется системный вызов ядра Linux `renameat(..., "..data_tmp", ..., "..data")`. В рамках POSIX этот вызов является строго атомарным: ссылка `..data` мгновенно переключается на новую директорию.
5. **Очистка старых данных:** Предыдущая директория `..<old_timestamp>` удаляется асинхронно после завершения переключения.

#### Низкоуровневые нюансы Linux VFS и Inode

* **Кеширование открытых файловых дескрипторов (File Descriptors):**
  Если приложение открыло файл (`fd = open("/etc/config/app.conf", O_RDONLY)`) и удерживает дескриптор, системные вызовы `read(fd, ...)` продолжают обращаться к **старому inode** на диске, даже если `..data` переключилась на новую директорию. Файл физически не удаляется из файловой системы, пока счетчик ссылок (inode link count) или открытых дескрипторов не станет равен нулю. Приложение увидит обновленный файл только после вызова `close(fd)` и повторного `open()`.
* **Специфика Linux `inotify`:**
  Приложение, установившее inotify-watch непосредственно на файл `/etc/config/app.conf`, при переключении ссылки `..data` получит событие `IN_DELETE_SELF` или `IN_MOVE_SELF`, после чего дескриптор наблюдения перестает отслеживать новый файл!
  **Решение для разработчиков и SRE:** Отслеживать inotify-события родительской директории (`/etc/config`) на события `IN_CREATE` или `IN_MOVED_TO` относительно ссылки `..data`, либо использовать готовые sidecar-релоадеры.

---

### Анатомия ограничения subPath (Linux bind mount semantics)

Директива `subPath` решает задачу монтирования отдельного файла из ConfigMap в существующую директорию без затирания остальных файлов каталога:

```yaml
volumeMounts:
- name: config-volume
  mountPath: /etc/nginx/nginx.conf
  subPath: nginx.conf
```

#### Почему subPath блокирует Hot Reload

1. **Семантика Bind Mount ядра Linux:**
   Когда Kubelet выполняет монтирование с `subPath`, он разыменовывает путь до целевого файла на хосте и вызывает системный вызов ядра `mount(source_path, target_path, NULL, MS_BIND, NULL)`.
2. **Привязка к Inode:**
   В отличие от монтирования каталога целиком (где контейнер видит симлинки и разрешает их при каждом открытии), `MS_BIND` связывает точку монтирования контейнера **напрямую с физическим inode** исходного файла в директории `..<timestamp>`.
3. **Разрыв цепочки симлинков:**
   Когда Kubelet позже выполняет Atomic Symlink Swap и переключает `..data`, точка bind mount внутри контейнера остается привязанной к старому inode. Контейнер изолирован в своем mount namespace и никогда не увидит изменений без полного перезапуска пода.

```
Монтирование каталога (Hot Reload работает):
Контейнер -> /etc/config/app.conf -> ..data/app.conf -> ..<new_timestamp>/app.conf (Inode 2002)

Монтирование subPath (Hot Reload заблокирован):
Контейнер -> /etc/nginx/nginx.conf ──[Linux Bind Mount]──► Inode 1001 (Заморожен навсегда)
```

> **SRE-правило:** Никогда не используйте `subPath` для конфигурационных файлов, которые должны обновляться без перезапуска пода. Для подмены одиночных файлов без потери автообновления используйте Projected Volumes либо генерируйте результирующий конфиг через Init/Sidecar контейнеры.

---

### Механизм синхронизации Kubelet и задержки доставки

Синхронизация данных между Control Plane (`etcd` / `kube-apiserver`) и рабочей нодой выполняется демоном `kubelet`.

```
kube-apiserver ◄───[ Watch / Get / Cache ]───► Kubelet ConfigMap Manager
                                                       │
                                            Обновление локального кеша
                                                       │
                                         Период syncFrequency (60s + jitter)
                                                       │
                                                       ▼
                                            Volume Manager (Pod Worker)
                                                       │
                                            Atomic Symlink Swap на диске
                                                       ▼
                                            Файловая система контейнера
```

#### Стратегии обнаружения изменений (`configMapAndSecretChangeDetectionStrategy`)

Параметр задается в файле конфигурации Kubelet (`/var/lib/kubelet/config.yaml`):

| Стратегия | Описание механизма | Нагрузка на kube-apiserver / etcd | Скорость реакции на узле |
| :--- | :--- | :--- | :--- |
| `Watch` (по умолчанию) | Kubelet устанавливает постоянное HTTP/2 gRPC Watch-соединение на каждый используемый ConfigMap | Высокая (пропорциональна количеству уникальных ConfigMap * число узлов) | Мгновенная доставка в локальный кеш Kubelet |
| `Cache` | Kubelet кэширует ответы API-сервера в памяти на период `cacheTTL` (по умолчанию 1 минута) | Низкая (фиксированные периодические GET-запросы) | Добавляет задержку `cacheTTL` к обновлению |
| `Get` | Kubelet запрашивает актуальный объект у API-сервера при каждом вызове синхронизации | Средняя (запросы по требованию без длинных соединений) | Зависит от момента срабатывания pod sync worker |

#### Результирующая задержка доставки (60–90 секунд)

Даже при стратегии `Watch`, когда Kubelet узнает об изменении ConfigMap за доли секунды, файлы на диске обновляются не сразу:
1. Физическая пересборка тома привязана к периодическому циклу `syncFrequency` рабочего воркера пода (по умолчанию `60s`).
2. Для предотвращения синхронного шторма дискового ввода-вывода (Thundering Herd) Kubelet добавляет к периоду псевдослучайный джиттер с коэффициентом до 0.5.
3. Суммарная типовая задержка между выполнением `kubectl apply` и появлением новых файлов в контейнере составляет **от 60 до 90 секунд**.

---

### Правила разрешения и приоритеты переменных окружения

При формировании окружения контейнера действуют строгие приоритеты разрешения коллизий:

```
[Системные переменные K8s] 
           │
           ▼
[envFrom: источники по порядку] ◄─── Поздний источник переопределяет ранний
           │
           ▼
[env: явные переменные]          ◄─── ВСЕГДА переопределяют значения из envFrom
```

1. **Явные `env` имеют наивысший приоритет:** Если ключ определен и в `envFrom`, и в блоке `env` (включая `valueFrom.configMapKeyRef`), значение из `env` гарантированно переопределяет `envFrom`.
2. **Порядок следования `envFrom`:** Если несколько ConfigMap/Secret в `envFrom` содержат одинаковые ключи, итоговым значением станет значение из **последнего** объявленного источника в списке.
3. **Параметр `prefix`:** Добавляет префикс ко всем ключам конкретного `configMapRef`. Предотвращает случайные коллизии (например, `prefix: "DB_"` трансформирует ключ `PORT` в переменную `DB_PORT`).

#### Валидация имен переменных окружения

* **Стандарт POSIX:** Имена переменных окружения должны соответствовать регулярному выражению `^[A-Za-z_][A-Za-z0-9_]*$`.
* **Поведение `envFrom`:** Ключи ConfigMap, содержащие дефисы (`-`), точки (`.`) или начинающиеся с цифр (например, `app-config.yaml`, `service.port`), **молча пропускаются Kubelet**. Процесс запускается, но переменные в окружение не попадают!
* **Kubernetes 1.32+ (`RelaxedEnvironmentVariableValidation`):** Функция ослабленной валидации разрешает почти все печатные ASCII-символы кроме `=`. Однако стандартные оболочки Linux (`/bin/sh`, `/bin/bash`) все равно не могут корректно адресовать переменные с точками и дефисами через синтаксис `$VAR`.
* **Правило SRE:** Для использования с `envFrom` именуйте ключи ConfigMap только в стиле `SCREAMING_SNAKE_CASE` или `lower_snake_case`. Ключи с точками и расширениями файлов предназначены исключительно для монтирования томов (`volumes`).

#### Подстановка `$(VAR)` в command и args

* Kubelet выполняет замену выражений `$(VAR_NAME)` в полях `command` и `args` на основе переменных, определенных в контейнере.
* **Строгий порядок зависимостей:** Переменная, используемая в `$(VAR)`, должна быть объявлена в списке `env` **выше** строки, где она используется.
* **Неопределенные переменные:** Если переменная отсутствует, Kubelet не заменяет ее на пустую строку, а оставляет литерал `$(UNKNOWN_VAR)`. Это частая причина сбоев запуска бинарных файлов.
* **Экранирование (`$$`):** Для передачи литерального знака доллара (актуально для регулярных выражений, переменных shell-скрипта или синтаксиса `$((...))`) необходимо использовать двойной знак: `$$(MY_LITERAL)`.

---

### Безопасность, права доступа и Linux UID/GID

По умолчанию Kubelet создает смонтированные файлы тома ConfigMap с правами доступа `0644` (`-rw-r--r--`) и владельцем `root:root` (`uid=0, gid=0`).

#### Взаимодействие с непривилегированными контейнерами (Non-Root)

Если контейнер запускается от непривилегированного пользователя согласно Best Practices безопасности:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
```

* **Чтение файлов:** При стандартном `defaultMode: 0644` процесс с `uid=10001` успешно читает файлы через права `Others` (`r--`).
* **Ловушка с `defaultMode: 0400` / `0440`:** Если администратор задает ужесточенные права `0400` (только владелец) без настройки групп, процесс с `uid=10001` получит ошибку `Permission denied`, так как владелец файла на диске узла — `root` (`uid=0`).
* **Решение через `fsGroup`:** При указании `pod.spec.securityContext.fsGroup: 10001` Kubelet монтирует том с групповым владением `gid=10001`. В сочетании с `defaultMode: 0440` непривилегированный процесс безопасно читает конфигурацию.

---

### Поведение флага optional

Флаг `optional: true` управляет отказоустойчивостью старта пода при отсутствии ConfigMap или конкретного ключа:

| Место использования | `optional: false` (по умолчанию) | `optional: true` |
| :--- | :--- | :--- |
| `env.valueFrom.configMapKeyRef` | Под зависает в `CreateContainerConfigError`, если нет ConfigMap или ключа | Переменная пропускается, под успешно стартует |
| `envFrom.configMapRef` | Под зависает в `CreateContainerConfigError`, если ConfigMap отсутствует | Ни одна переменная не добавляется, под успешно стартует |
| `volumes.configMap` | Ошибка монтирования `FailedMount`, контейнеры не создаются | Создается пустая директория тома, под успешно стартует |
| `volumes.configMap.items` | `FailedMount`, если хотя бы один ключ из `items` отсутствует в ConfigMap | Ключи, которых нет в объекте, просто не создаются на диске тома |

---

### Системные ограничения платформы

* **Лимит размера в 1 MiB:** Размер объекта ConfigMap в etcd жестко ограничен 1 MiB (`RequestEntityTooLarge`). Для конфигураций свыше 1 MiB используйте сжатие `binaryData` или внешние тома (подробно: [Работа с большими конфигурациями](./large_configs.md)).
* **Изоляция пространств имен (Namespaces):** ConfigMap и потребляющий его Pod обязаны находиться в одном Namespace. Межпространственные ссылки не поддерживаются ядром Kubernetes.
* **Размещение на диске узла:** Тома ConfigMap размещаются в локальной файловой системе хоста по пути `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~configmap/<volume-name>/`. Они потребляют дисковое пространство и inodes раздела `/var/lib/kubelet`, а не оперативную память (tmpfs не используется).

---

## Практические сценарии

### Сценарий 1: Базовая передача переменных окружения (`env`, `configMapKeyRef`, `optional`)

**Контекст:** Передача скалярных настроек приложения (порт, режим отладки) с защитой от сбоя при отсутствии второстепенных параметров.

#### Манифест ConfigMap и Pod

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-scalar-config
  namespace: default
data:
  APP_PORT: "8080"
  LOG_LEVEL: "info"
---
apiVersion: v1
kind: Pod
metadata:
  name: scalar-env-pod
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: backend
    image: alpine:3.20
    command: ["/bin/sh", "-c", "env | grep -E 'APP_PORT|LOG_LEVEL|FEATURE_FLAG'; sleep 3600"]
    env:
    - name: APP_PORT
      valueFrom:
        configMapKeyRef:
          name: app-scalar-config
          key: APP_PORT
    - name: LOG_LEVEL
      valueFrom:
        configMapKeyRef:
          name: app-scalar-config
          key: LOG_LEVEL
    - name: FEATURE_FLAG
      valueFrom:
        configMapKeyRef:
          name: app-scalar-config
          key: NON_EXISTENT_KEY
          optional: true # Предотвращает CreateContainerConfigError
```

#### Проверка выполнения

```bash
# Применение манифестов
kubectl apply -f app-scalar-config.yaml
# → configmap/app-scalar-config created
# → pod/scalar-env-pod created

# Проверка переменных внутри контейнера
kubectl exec scalar-env-pod -c backend -- env | grep -E 'APP_PORT|LOG_LEVEL|FEATURE_FLAG'
# → APP_PORT=8080
# → LOG_LEVEL=info
```

---

### Сценарий 2: Массовая инъекция через envFrom с префиксом и разрешением коллизий

**Контекст:** Импорт базовых настроек и функциональных флагов с исключением пересечения имен переменных через префиксы и переопределение значений.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: base-system-config
  namespace: default
data:
  HTTP_TIMEOUT: "30s"
  MAX_RETRIES: "3"
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: feature-flags-config
  namespace: default
data:
  NEW_CHECKOUT: "true"
  BETA_DASHBOARD: "false"
---
apiVersion: v1
kind: Pod
metadata:
  name: envfrom-collision-pod
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: app
    image: alpine:3.20
    command: ["/bin/sh", "-c", "env | grep -E 'HTTP_TIMEOUT|MAX_RETRIES|FF_'; sleep 3600"]
    envFrom:
    - configMapRef:
        name: base-system-config
    - configMapRef:
        name: feature-flags-config
      prefix: "FF_" # Добавит префикс ко всем ключам этого ConfigMap
    env:
    - name: HTTP_TIMEOUT # Явный env переопределяет значение из base-system-config
      value: "60s"
```

#### Проверка выполнения

```bash
kubectl apply -f envfrom-pod.yaml
# → configmap/base-system-config created
# → configmap/feature-flags-config created
# → pod/envfrom-collision-pod created

kubectl exec envfrom-collision-pod -- env | grep -E 'HTTP_TIMEOUT|MAX_RETRIES|FF_' | sort
# → FF_BETA_DASHBOARD=false
# → FF_NEW_CHECKOUT=true
# → HTTP_TIMEOUT=60s
# → MAX_RETRIES=3
```

---

### Сценарий 3: Передача конфигурации в command и args контейнера с экранированием

**Контекст:** Запуск процесса утилиты с аргументами CLI, сформированными из ConfigMap, и передача сложных строковых шаблонов с символом `$`.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: job-runtime-config
  namespace: default
data:
  TARGET_HOST: "database.internal.local"
  METRIC_PORT: "9100"
---
apiVersion: v1
kind: Pod
metadata:
  name: args-expansion-pod
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: worker
    image: alpine:3.20
    command: ["/bin/sh", "-c"]
    # $$(LITERAL) экранируется в $(LITERAL), $(TARGET_HOST) раскрывается Kubelet
    args:
    - 'echo "Connecting to $(TARGET_HOST):$(METRIC_PORT) with template: $$(PID_EXPR)" && sleep 3600'
    env:
    - name: TARGET_HOST
      valueFrom:
        configMapKeyRef:
          name: job-runtime-config
          key: TARGET_HOST
    - name: METRIC_PORT
      valueFrom:
        configMapKeyRef:
          name: job-runtime-config
          key: METRIC_PORT
```

#### Проверка выполнения

```bash
kubectl apply -f args-expansion-pod.yaml
# → configmap/job-runtime-config created
# → pod/args-expansion-pod created

kubectl logs args-expansion-pod
# → Connecting to database.internal.local:9100 with template: $(PID_EXPR)
```

---

### Сценарий 4: Монтирование тома с выборочной проекцией ключей (items) и правами (defaultMode)

**Контекст:** Монтирование сложного конфигурационного файла в `/etc/nginx/conf.d` с переименованием ключа в валидное имя файла и строгими правами доступа `0440`.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-vhost-config
  namespace: default
data:
  raw_vhost_template: |
    server {
        listen 8080;
        server_name localhost;
        location /healthz {
            return 200 'OK';
        }
    }
  unused_notes.txt: "Вспомогательные заметки разработчика"
---
apiVersion: v1
kind: Pod
metadata:
  name: nginx-custom-volume-pod
  namespace: default
spec:
  containers:
  - name: web
    image: nginx:1.27-alpine
    ports:
    - containerPort: 8080
    volumeMounts:
    - name: conf-volume
      mountPath: /etc/nginx/conf.d
      readOnly: true
  volumes:
  - name: conf-volume
    configMap:
      name: nginx-vhost-config
      defaultMode: 0440 # Read-only для владельца и группы
      items:
      - key: raw_vhost_template
        path: default.conf # Переименование ключа в имя файла на диске
```

#### Проверка выполнения

```bash
kubectl apply -f nginx-volume.yaml
# → configmap/nginx-vhost-config created
# → pod/nginx-custom-volume-pod created

# Проверка файлов в директории монтирования
kubectl exec nginx-custom-volume-pod -- ls -la /etc/nginx/conf.d
# → lrwxrwxrwx 1 root root 19 Oct 13 16:10 ..data -> ..2026_10_13_16_10_00.111111111
# → lrwxrwxrwx 1 root root 19 Oct 13 16:10 default.conf -> ..data/default.conf

# Проверка прав доступа к конечному файлу (0440 = -r--r-----)
kubectl exec nginx-custom-volume-pod -- ls -la /etc/nginx/conf.d/..data/default.conf
# → -r--r----- 1 root root 120 Oct 13 16:10 /etc/nginx/conf.d/..data/default.conf
```

---

### Сценарий 5: Монтирование в контейнер с непривилегированным пользователем (Non-Root, fsGroup)

**Контекст:** Запуск процесса с жесткими ограничениями безопасности (`runAsNonRoot: true`, `readOnlyRootFilesystem: true`) с сохранением возможности чтения конфигурации процессом с `uid=10001`.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: secure-app-config
  namespace: default
data:
  appsettings.json: |
    {
      "Environment": "Production",
      "CacheTtlSeconds": 300
    }
---
apiVersion: v1
kind: Pod
metadata:
  name: nonroot-secure-pod
  namespace: default
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001 # Kubelet передаст владение томом группе 10001
  containers:
  - name: secure-service
    image: alpine:3.20
    command: ["/bin/sh", "-c", "cat /etc/app/appsettings.json && sleep 3600"]
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
    volumeMounts:
    - name: config-vol
      mountPath: /etc/app
      readOnly: true
  volumes:
  - name: config-vol
    configMap:
      name: secure-app-config
      defaultMode: 0440 # Владелец и fsGroup могут читать
```

#### Проверка выполнения

```bash
kubectl apply -f nonroot-secure-pod.yaml
# → configmap/secure-app-config created
# → pod/nonroot-secure-pod created

# Проверка чтения файла процессом
kubectl logs nonroot-secure-pod
# → {
# →   "Environment": "Production",
# →   "CacheTtlSeconds": 300
# → }

# Проверка UID/GID владельца на диске
kubectl exec nonroot-secure-pod -- ls -ld /etc/app/..data
# → drwxr-xr-x 2 root 10001 4096 Oct 13 16:15 /etc/app/..data
```

---

### Сценарий 6: Монтирование одиночного файла без затирания каталога (subPath vs Projected Volume)

**Контекст:** Внедрение одного конфигурационного файла в каталог `/etc/pam.d/` или `/etc/`, где уже находятся критические системные файлы контейнера, без их уничтожения.

#### Вариант A: subPath (Статичный файл, Hot Reload НЕ требуется)

```yaml
volumeMounts:
- name: single-config-volume
  mountPath: /etc/custom_daemon.conf
  subPath: custom_daemon.conf # Не затирает /etc, но замораживает inode
volumes:
- name: single-config-volume
  configMap:
    name: daemon-config
```

#### Вариант B: Обход ловушки subPath через Projected Volume + Симлинк при старте

Если файлу требуется автообновление, но каталог контейнера нельзя перезаписывать целиком:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: safe-reloadable-mount-pod
  namespace: default
spec:
  containers:
  - name: app
    image: alpine:3.20
    command:
    - /bin/sh
    - -c
    - |
      # Создаем симлинк на файл из изолированного тома в целевую директорию
      ln -sfn /var/run/configs/app.conf /etc/app.conf
      while true; do
        cat /etc/app.conf
        sleep 10
      done
    volumeMounts:
    - name: isolated-config-vol
      mountPath: /var/run/configs # Изолированная директория (Hot Reload работает)
      readOnly: true
  volumes:
  - name: isolated-config-vol
    configMap:
      name: app-live-config
```

---

### Сценарий 7: Реализация Hot Reload конфигурации через inotify/SIGHUP без перезапуска пода

**Контекст:** Процесс Nginx или Prometheus должен перечитывать измененные правила конфигурации при срабатывании фонового триггера без рестарта контейнера.

#### Манифест с Sidecar-релоадером на базе inotify

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dynamic-nginx-conf
  namespace: default
data:
  nginx.conf: |
    events { worker_connections 1024; }
    http {
        server {
            listen 80;
            location / { return 200 "Version 1\n"; }
        }
    }
---
apiVersion: v1
kind: Pod
metadata:
  name: hot-reload-nginx-pod
  namespace: default
spec:
  shareProcessNamespace: true # Позволяет sidecar отправлять сигналы основному контейнеру
  containers:
  - name: nginx
    image: nginx:1.27-alpine
    volumeMounts:
    - name: config-dir
      mountPath: /etc/nginx
      readOnly: true
  - name: config-watcher
    image: alpine:3.20
    command:
    - /bin/sh
    - -c
    - |
      apk add --no-cache inotify-tools procps
      echo "Monitoring /etc/nginx for changes..."
      # Отслеживаем смену ссылки ..data в родительской директории
      while inotifywait -e create,moved_to /etc/nginx; do
        echo "Detected ConfigMap rotation! Sending SIGHUP to nginx..."
        pkill -HUP nginx || true
      done
    volumeMounts:
    - name: config-dir
      mountPath: /etc/nginx
      readOnly: true
  volumes:
  - name: config-dir
    configMap:
      name: dynamic-nginx-conf
```

#### Проверка Hot Reload

```bash
# 1. Запуск пода и проверка ответа
kubectl apply -f hot-reload-nginx.yaml
kubectl exec hot-reload-nginx-pod -c nginx -- wget -qO- http://localhost:80
# → Version 1

# 2. Обновление ConfigMap
kubectl patch configmap dynamic-nginx-conf --type merge \
  -p '{"data":{"nginx.conf":"events { worker_connections 1024; } http { server { listen 80; location / { return 200 \"Version 2\\n\"; } } }"}}'
# → configmap/dynamic-nginx-conf patched

# 3. Ожидание цикла syncFrequency (60-90 сек) и проверка логов watcher
kubectl logs hot-reload-nginx-pod -c config-watcher
# → Detected ConfigMap rotation! Sending SIGHUP to nginx...

# 4. Проверка нового ответа Nginx без рестарта пода
kubectl exec hot-reload-nginx-pod -c nginx -- wget -qO- http://localhost:80
# → Version 2
```

---

### Сценарий 8: Конфигурация Native Sidecar (restartPolicy: Always) и Init-контейнеров

**Контекст:** Подготовка конфигурационных файлов в `initContainers` и запуск нативного проксирующего sidecar-контейнера (Kubernetes 1.29+) до старта основного сервиса.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: pipeline-config
  namespace: default
data:
  proxy.conf: "upstream_host=127.0.0.1:9000"
  schema_validation.json: '{"version": 2}'
---
apiVersion: v1
kind: Pod
metadata:
  name: native-sidecar-pod
  namespace: default
spec:
  initContainers:
  # 1. Одноразовый init-контейнер для проверки конфига
  - name: validate-config
    image: alpine:3.20
    command: ["/bin/sh", "-c", "test -s /etc/schema/schema_validation.json && echo Config OK"]
    volumeMounts:
    - name: cfg-vol
      mountPath: /etc/schema
  # 2. Native Sidecar: запускается до основного контейнера и работает параллельно
  - name: local-proxy
    image: alpine:3.20
    restartPolicy: Always # Kubernetes 1.29+ Native Sidecar
    command: ["/bin/sh", "-c", "cat /etc/proxy/proxy.conf && sleep 3600"]
    volumeMounts:
    - name: cfg-vol
      mountPath: /etc/proxy
  containers:
  - name: main-application
    image: alpine:3.20
    command: ["/bin/sh", "-c", "echo Main app running; sleep 3600"]
  volumes:
  - name: cfg-vol
    configMap:
      name: pipeline-config
```

#### Проверка выполнения

```bash
kubectl apply -f native-sidecar-pod.yaml
# → pod/native-sidecar-pod created

# Проверка статуса контейнеров пода
kubectl get pod native-sidecar-pod -o jsonpath='{range .status.initContainerStatuses[*]}{.name}: ready={.ready}{"\n"}{end}'
# → validate-config: ready=false
# → local-proxy: ready=true
```

---

### Сценарий 9: Общий ConfigMap для нескольких контейнеров в поде с разделением прав

**Контекст:** Основной контейнер и сборщик логов монтируют один и тот же ConfigMap в разные каталоги файловой системы с различными правами доступа.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: multi-container-config
  namespace: default
data:
  app.yaml: "service: payment-gateway"
  fluent_forward.conf: "forward_port: 24224"
---
apiVersion: v1
kind: Pod
metadata:
  name: shared-cm-pod
  namespace: default
spec:
  containers:
  - name: app
    image: alpine:3.20
    command: ["/bin/sh", "-c", "cat /etc/app/app.yaml && sleep 3600"]
    volumeMounts:
    - name: shared-storage
      mountPath: /etc/app
      readOnly: true
  - name: logger
    image: alpine:3.20
    command: ["/bin/sh", "-c", "cat /etc/fluent/fluent_forward.conf && sleep 3600"]
    volumeMounts:
    - name: shared-storage
      mountPath: /etc/fluent
      readOnly: true
  volumes:
  - name: shared-storage
    configMap:
      name: multi-container-config
      defaultMode: 0444
```

#### Проверка выполнения

```bash
kubectl apply -f shared-cm-pod.yaml
# → pod/shared-cm-pod created

kubectl exec shared-cm-pod -c app -- cat /etc/app/app.yaml
# → service: payment-gateway

kubectl exec shared-cm-pod -c logger -- cat /etc/fluent/fluent_forward.conf
# → forward_port: 24224
```

---

### Сценарий 10: Агрегация источников конфигурации в единый каталог через Projected Volumes

**Контекст:** Объединение открытых настроек (ConfigMap), учетных данных (Secret) и метаданных кластера (Downward API) в одну директорию `/etc/unified/`.

#### Манифест

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: public-settings
  namespace: default
data:
  cluster_name: "prod-dc1-k8s"
---
apiVersion: v1
kind: Secret
metadata:
  name: private-keys
  namespace: default
stringData:
  api_token: "secret-token-9988"
---
apiVersion: v1
kind: Pod
metadata:
  name: projected-unification-pod
  namespace: default
spec:
  containers:
  - name: service
    image: alpine:3.20
    command: ["/bin/sh", "-c", "ls -la /etc/unified && sleep 3600"]
    volumeMounts:
    - name: unified-volume
      mountPath: /etc/unified
      readOnly: true
  volumes:
  - name: unified-volume
    projected:
      defaultMode: 0400
      sources:
      - configMap:
          name: public-settings
          items:
          - key: cluster_name
            path: env/cluster.txt
      - secret:
          name: private-keys
          items:
          - key: api_token
            path: auth/token.key
      - downwardAPI:
          items:
          - path: pod_labels
            fieldRef:
              fieldPath: metadata.labels
```

#### Проверка выполнения

```bash
kubectl apply -f projected-pod.yaml
# → pod/projected-unification-pod created

kubectl exec projected-unification-pod -- find /etc/unified -type f -exec ls -la {} +
# → -r-------- 1 root root 15 Oct 13 16:30 /etc/unified/..data/auth/token.key
# → -r-------- 1 root root 12 Oct 13 16:30 /etc/unified/..data/env/cluster.txt
# → -r-------- 1 root root 32 Oct 13 16:30 /etc/unified/..data/pod_labels
```

---

### Сценарий 11: Анализ структуры тома, проверка симлинков и аудит inodes

**Контекст:** Задача SRE/Sysadmin — проверить доставку ревизии конфигурации на уровне ядра Linux и убедиться в атомарной ротации inodes.

#### Команды аудита

```bash
# 1. Просмотр структуры каталога и проверка целевого каталога ..data
kubectl exec scalar-env-pod -- ls -la /etc/config 2>/dev/null || \
kubectl exec nginx-custom-volume-pod -- ls -la /etc/nginx/conf.d
# → lrwxrwxrwx 1 root root 31 Oct 13 16:10 ..data -> ..2026_10_13_16_10_00.111111111
# → lrwxrwxrwx 1 root root 20 Oct 13 16:10 default.conf -> ..data/default.conf

# 2. Вывод текущего Inode физического файла
kubectl exec nginx-custom-volume-pod -- stat -c "File: %n, Inode: %i, Links: %h" /etc/nginx/conf.d/default.conf
# → File: /etc/nginx/conf.d/default.conf, Inode: 1045231, Links: 1

# 3. Проверка контрольной суммы до и после обновления
kubectl exec nginx-custom-volume-pod -- sha256sum /etc/nginx/conf.d/default.conf
# → a1b2c3d4e5...  /etc/nginx/conf.d/default.conf
```

---

### Сценарий 12: Императивное управление переменными через kubectl set env

**Контекст:** Ad-hoc отладка и быстрое тестирование в dev/stage окружении без ручного редактирования Deployment манифестов.

#### Команды

```bash
# 1. Добавление всех ключей ConfigMap как переменных в Deployment с dry-run
kubectl set env deployment/payment-api --from=configmap/app-scalar-config --dry-run=client -o yaml
# → deployment.apps/payment-api configured (dry run)

# 2. Реальное применение импорта с префиксом
kubectl set env deployment/payment-api --from=configmap/app-scalar-config --prefix=SVC_
# → deployment.apps/payment-api env updated

# 3. Просмотр текущих настроенных переменных окружения в объекте
kubectl set env deployment/payment-api --list
# → # deployments/payment-api, container payment-api
# → # app-scalar-config from configmap (prefix 'SVC_')

# 4. Удаление инжектированной переменной
kubectl set env deployment/payment-api SVC_LOG_LEVEL-
# → deployment.apps/payment-api env updated
```

---

## Операции и команды

### Сводная таблица команд управления и диагностики

| Операция | Команда | Назначение / Описание |
| :--- | :--- | :--- |
| **Поиск потребителей томов** | `kubectl get pods -A -o jsonpath='{...}'` | Найти все поды, монтирующие указанный ConfigMap как Volume |
| **Поиск потребителей env** | `kubectl get pods -A -o jsonpath='{...}'` | Найти все поды, использующие ConfigMap в блоке `env` или `envFrom` |
| **Инспекция структуры тома** | `kubectl exec <pod> -- ls -la <mountPath>` | Проверить симлинки `..data` и структуру файлов в контейнере |
| **Проверка ссылки ..data** | `kubectl exec <pod> -- readlink <mountPath>/..data` | Вывести имя актуальной временной директории данных |
| **Аудит переменных окружения** | `kubectl exec <pod> -- env \| sort` | Вывести фактические переменные процесса контейнера |
| **Императивный импорт env** | `kubectl set env deploy/<name> --from=cm/<cm>` | Добавить все ключи ConfigMap в Deployment |
| **Проверка директории на хосте** | `ls -la /var/lib/kubelet/pods/<uid>/volumes/...` | (Sysadmin на ноде) Проверить физическое состояние тома Kubelet |
| **Логи Volume Manager** | `journalctl -u kubelet -g "kubernetes.io~configmap"` | (Sysadmin на ноде) Проверить синхронизацию томов Kubelet |

### Практические команды с ожидаемым выводом

```bash
# 1. Поиск всех подов в Namespace, монтирующих ConfigMap 'nginx-vhost-config' как том
kubectl get pods -n default -o json | jq -r \
  '.items[] | select(.spec.volumes[]?.configMap.name == "nginx-vhost-config") | .metadata.name'
# → nginx-custom-volume-pod

# 2. Поиск подов, ссылающихся на ConfigMap через env или envFrom
kubectl get pods -n default -o json | jq -r \
  '.items[] | select(
    (.spec.containers[].env[]?.valueFrom.configMapKeyRef.name == "app-scalar-config") or
    (.spec.containers[].envFrom[]?.configMapRef.name == "app-scalar-config")
  ) | .metadata.name'
# → scalar-env-pod

# 3. Проверка фактической ссылки ..data внутри контейнера
kubectl exec nginx-custom-volume-pod -- readlink /etc/nginx/conf.d/..data
# → ..2026_10_13_16_10_00.111111111

# 4. Проверка событий Kubelet, связанных с ошибками монтирования томов
kubectl get events --field-selector reason=FailedMount --sort-by='.lastTimestamp'
# → LAST SEEN   TYPE      REASON        OBJECT            MESSAGE
# → 45s         Warning   FailedMount   pod/broken-pod    MountVolume.SetUp failed for volume "cfg": configmap "missing-cm" not found

# 5. Проверка директории тома на узле кластера (для администраторов узла / SSH)
# Получаем UID пода:
POD_UID=$(kubectl get pod nginx-custom-volume-pod -o jsonpath='{.metadata.uid}')
# На рабочей ноде:
ls -la /var/lib/kubelet/pods/${POD_UID}/volumes/kubernetes.io~configmap/conf-volume/
# → drwxr-xr-x 3 root root 4096 Oct 13 16:10 .
# → drwxr-xr-x 3 root root 4096 Oct 13 16:10 ..
# → drwxr-xr-x 2 root root 4096 Oct 13 16:10 ..2026_10_13_16_10_00.111111111
# → lrwxrwxrwx 1 root root   31 Oct 13 16:10 ..data -> ..2026_10_13_16_10_00.111111111
# → lrwxrwxrwx 1 root root   19 Oct 13 16:10 default.conf -> ..data/default.conf
```

---

## Диагностика и устранение неполадок

### Алгоритм локализации проблем

```
                         Проблема при использовании ConfigMap в Pod
                                            │
               ┌────────────────────────────┴────────────────────────────┐
               ▼                                                         ▼
      Под не запускается                                      Под запущен, но конфиг не тот
               │                                                         │
       ┌───────┴───────┐                                         ┌───────┴───────┐
       ▼               ▼                                         ▼               ▼
CreateContainer   FailedMount                              Способ доставки?  Права доступа?
  ConfigError          │                                         │               │
       │         Том не найден /                           ┌─────┴─────┐   Permission denied
       │         неверный ключ                             ▼           ▼         │
 Отсутствует CM        │                                  env        volume  Проверить fsGroup
 или ключ в env   Проверить имя                         Нужен      Проверить и defaultMode
                  ConfigMap в volumes                  Rollout     subPath /
                                                                   inode кэш
```

---

### Анализ типовых неисправностей

#### Ошибка 1: `CreateContainerConfigError` при старте пода

**Симптомы:** Под находится в статусе `CreateContainerConfigError`, контейнеры не создаются.

```bash
kubectl describe pod <pod-name>
# → Events:
# → Error: configmap "app-config" not found
# → Error: couldn't find key APP_PORT in ConfigMap default/app-scalar-config
```

**Причина:** В блоке `env` или `envFrom` указан несуществующий ConfigMap или отсутствующий ключ при `optional: false` (по умолчанию).

**Диагностика и решение:**
```bash
# 1. Проверяем наличие ConfigMap в том же Namespace
kubectl get configmap <cm-name> -n <namespace>

# 2. Проверяем точный состав ключей в объекте
kubectl get configmap <cm-name> -n <namespace> -o jsonpath='{.data}' | jq 'keys'

# 3. Если параметр необязателен — добавьте флаг optional: true в манифест пода:
# valueFrom:
#   configMapKeyRef:
#     name: app-config
#     key: APP_PORT
#     optional: true
```

---

#### Ошибка 2: Файлы в томе обновились на диске, но приложение использует старую конфигурацию

**Симптомы:** `cat /etc/config/app.conf` в контейнере показывает актуальные данные, но приложение продолжает работать по старым правилам.

**Причина:**
1. Приложение не поддерживает Hot Reload (конфигурация считывается только один раз при старте процесса).
2. Приложение удерживает открытый файловый дескриптор (кеширование inode ядра Linux).
3. inotify-вотчер приложения упал из-за `IN_DELETE_SELF` при смене симлинка `..data`.

**Диагностика и решение:**
```bash
# 1. Проверяем, какой inode открыт процессом (через lsof/procfs)
kubectl exec <pod-name> -- ls -l /proc/1/fd/
# Если дескриптор указывает на (deleted) или старый путь ..<old_timestamp> — процесс не закрывал файл

# 2. Решение:
# А) Если процесс поддерживает сигнал (SIGHUP) — отправить сигнал (например, pkill -HUP <process>)
# Б) Если процесс не поддерживает Hot Reload — выполнить рестарт пода:
kubectl rollout restart deployment/<deployment-name>
```

---

#### Ошибка 3: Файл тома не обновляется при изменении ConfigMap (ловушка subPath)

**Симптомы:** ConfigMap обновлен в кластере, прошло более 10 минут, но файл внутри контейнера остается старым, а в директории отсутствует ссылка `..data`.

**Причина:** Файл смонтирован с использованием директивы `subPath`. Созданный Linux `bind mount` жестко зафиксировал первоначальный inode.

**Диагностика и решение:**
```bash
# 1. Проверяем манифест пода на наличие subPath
kubectl get pod <pod-name> -o yaml | grep -B 2 -A 5 "subPath"
# → volumeMounts:
# → - mountPath: /etc/nginx/nginx.conf
# →   name: conf
# →   subPath: nginx.conf

# 2. Решение:
# Убрать subPath и смонтировать директорию целиком, либо вынести файл в изолированный каталог
# и создать симлинк при старте контейнера (см. Сценарий 6).
```

---

#### Ошибка 4: `CrashLoopBackOff` из-за нераскрытых `$(VAR)` переменных в command/args

**Симптомы:** Контейнер падает при старте, в логах ошибка вида: `Error: cannot connect to host $(DB_HOST)`.

**Причина:**
1. Имя переменной в `$(VAR)` объявлено **ниже** по списку `env`, чем место ее вызова.
2. Имя переменной написано с опечаткой (регистрозависимо).
3. Использован одиночный символ `$` в shell-скрипте, и Kubelet попытался развернуть его как несуществующую переменную.

**Диагностика и решение:**
```bash
# 1. Проверяем итоговую команду контейнера
kubectl get pod <pod-name> -o json | jq '.spec.containers[0].command, .spec.containers[0].args'

# 2. Решение:
# Переместите определение env выше в списке.
# Для литералов shell замените $ на $$ (например, $$(PID) вместо $(PID)).
```

---

#### Ошибка 5: `Permission denied` при чтении файлов в non-root контейнере

**Симптомы:** Приложение завершается с ошибкой `open /etc/config/app.json: permission denied`.

**Причина:** Контейнер запускается от `runAsUser: 10001`, а том смонтирован со слишком строгими правами (например, `defaultMode: 0400`), из-за чего доступ имеет только `root`.

**Диагностика и решение:**
```bash
# 1. Проверяем права на файлы в контейнере
kubectl exec <pod-name> -- ls -la /etc/config/..data

# 2. Решение:
# Установите defaultMode: 0440 или 0444 в спецификации тома:
# volumes:
# - name: config-vol
#   configMap:
#     name: app-config
#     defaultMode: 0444
# Либо настройте fsGroup в securityContext пода (см. Сценарий 5).
```

---

#### Ошибка 6: Переменные из envFrom молча отсутствуют в контейнере

**Симптомы:** ConfigMap подключен через `envFrom`, но `env` внутри контейнера не содержит ожидаемых ключей.

**Причина:** Ключи в ConfigMap содержат недопустимые символы для имен переменных окружения в стандарте POSIX: точки (`.`) или дефисы (`-`) (например, `database.url` или `service-port`). Kubelet молча игнорирует такие ключи при импорте через `envFrom`.

**Диагностика и решение:**
```bash
# 1. Выводим список ключей объекта ConfigMap
kubectl get configmap <cm-name> -o jsonpath='{.data}' | jq 'keys'

# 2. Решение:
# А) Переименовать ключи в формат C-идентификаторов (DATABASE_URL, SERVICE_PORT).
# Б) Либо использовать явную привязку через env[].valueFrom.configMapKeyRef с валидным name.
```

---

#### Ошибка 7: Затирание существующего содержимого целевого каталога

**Симптомы:** При монтировании тома в `/etc/nginx` исчезли стандартные файлы (`mime.types`, `fastcgi_params`), сервис не запускается.

**Причина:** Монтирование тома на существующую директорию файловой системы контейнера полностью перекрывает (shadowing) исходное содержимое каталога.

**Диагностика и решение:**
- Монтируйте тома в выделенные подкаталоги (например, `/etc/nginx/conf.d/` вместо `/etc/nginx/`).
- Либо используйте Projected Volumes / Init-контейнеры.

---

#### Ошибка 8: Ошибка `FailedMount` при удалении или повреждении ConfigMap

**Симптомы:** Под не может перезапуститься после падения ноды или рестарта контейнера со статусом `FailedMount`.

```bash
kubectl describe pod <pod-name>
# → Warning FailedMount 12s kubelet MountVolume.SetUp failed for volume "cfg": configmap "deleted-cm" not found
```

**Причина:** Объект ConfigMap был удален из кластера, пока под работал. Работающий под продолжал использовать закешированную версию, но при перезапуске Kubelet не смог смонтировать том.

**Решение:**
- Восстановить ConfigMap из GitOps-репозитория.
- Настроить мониторинг удаления критических объектов через метрику `kube_configmap_created`.

---

## Рекомендации и лучшие практики

### Чек-лист выбора метода доставки конфигурации

| Критерий / Требование | Рекомендуемый метод | Обоснование |
| :--- | :--- | :--- |
| **Простые скалярные значения** (порты, флаги отладки) | `env` / `envFrom` | Минимальный оверхед, нативная поддержка во всех фреймворках |
| **Сложные конфигурации** (YAML, JSON, XML, Nginx vhost) | `volumes` (каталог целиком) | Поддержка Atomic Symlink Swap, Hot Reload без перезапуска |
| **Агрегация нескольких источников** (CM + Secret + Token) | `projected` volumes | Единый каталог без накладных расходов множественных томов |
| **Подмена одного файла в заполненном каталоге** | Изолированный том + symlink | Обход ловушки `subPath` с сохранением автообновления |
| **Статичные неизменяемые конфигурации** | `volumes` + `immutable: true` | Снятие Watch-нагрузки с `kube-apiserver` и etcd |

---

### Безопасность и минимизация привилегий (Least Privilege)

1. **Защита от записи (`readOnly: true`):**
   Всегда указывайте `readOnly: true` в блоке `volumeMounts`. Контейнеры никогда не должны иметь права на запись в смонтированный том конфигурации.
2. **Ограничение прав доступа (`defaultMode`):**
   Устанавливайте минимально необходимые права на файлы тома:
   - `0440` — для работы в связке с `fsGroup` непривилегированного пользователя.
   - `0400` — если чтение требуется только UID владельца процесса.
   - Избегайте использования прав по умолчанию `0644`, если в конфигурациях содержатся закрытые инфраструктурные схемы.
3. **Запрет конфиденциальных данных в ConfigMap:**
   ConfigMap хранится в etcd в открытом виде и не шифруется механизмом Encryption at Rest (если он не настроен для всех ресурсов). Токены, пароли, приватные ключи и сертификаты должны размещаться исключительно в [Secret](../secrets/secrets_basics.md).
4. **Запуск от непривилегированного пользователя:**
   Всегда используйте `securityContext.runAsNonRoot: true` и `securityContext.fsGroup` для корректного доступа к томам ConfigMap без повышения привилегий до `root`.

---

### Отказоустойчивость и непрерывность

1. **Принцип Fail-Fast (`optional: false`):**
   Оставляйте `optional: false` для всех критических конфигураций. Если ConfigMap отсутствует, под должен гарантированно упасть в `CreateContainerConfigError` на этапе развертывания, а не начать работу с некорректными дефолтными значениями в продакшене.
2. **Контроль целостности через GitOps:**
   Любое изменение ConfigMap должно проходить через Git-репозиторий и CI-валидацию (схемы `kubeconform` / `conftest`). Ручные правки через `kubectl edit configmap` в production-кластерах категорически запрещены.
3. **Хеширование имен конфигураций при Rollout:**
   Для приложений, не поддерживающих Hot Reload, используйте версионирование имен ConfigMap (например, через Kustomize `configMapGenerator` или Helm `checksum/config`). Это обеспечивает гарантированный Rolling Update подов и исключает рассинхронизацию между репликами. Подробно разобрано в [Обновление и Rollout](./update_and_rollout.md).

---

## Дополнительная информация

### Сводное сравнение способов потребления ConfigMap

| Характеристика | Переменные окружения (`env`) | Массовый импорт (`envFrom`) | Тома (`volumes`) | subPath тома |
| :--- | :--- | :--- | :--- | :--- |
| **Hot Reload (автообновление)** | Нет (нужен рестарт) | Нет (нужен рестарт) | **Да** (симлинки 60-90 с) | **Нет** (bind mount freeze) |
| **Ограничение по размеру** | Лимит окружения ОС (ARG_MAX) | Лимит окружения ОС | До 1 MiB (лимит etcd) | До 1 MiB |
| **Сложные древовидные конфиги** | Не поддерживаются | Не поддерживаются | **Идеально** | Поддерживаются |
| **Влияние на FS контейнера** | Отсутствует | Отсутствует | Перекрывает целевой каталог | Заменяет одиночный файл |
| **Видимость в `/proc`** | Видны в `/proc/<pid>/environ` | Видны в `/proc/<pid>/environ` | Только в виде файлов на диске | Только в виде файла |
| **Валидация имен ключей** | Любое имя для `name` | Только POSIX `[A-Za-z0-9_]` | Любые имена файлов | Любые имена файлов |

---

### Интеграция со смежными инструментами экосистемы

* **Stakater Reloader:**
  Контроллер Kubernetes, отслеживающий изменения в ConfigMap/Secret и автоматически инициирующий скользящий перезапуск (`rollout restart`) зависимых Deployment/StatefulSet через аннотации:
  ```yaml
  metadata:
    annotations:
      reloader.stakater.com/auto: "true"
  ```
  Подробнее: [Reloader (оператор перезапусков)](../../ToolsUtilities/reloader/reloader_overview.md).

* **Helm и шаблонизация:**
  Автоматический перезапуск подов при изменении содержимого ConfigMap с помощью аннотации SHA256-хеша:
  ```yaml
  kind: Deployment
  spec:
    template:
      metadata:
        annotations:
          checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
  ```
  Подробнее: [Helm: перезапуск при изменении конфига](../../ToolsUtilities/Helm/templating/scenarios/restart_on_change.md).

* **Service Mesh (Istio / Envoy):**
  Хотя конфигурация Service Mesh в основном управляется через CRD (`VirtualService`, `DestinationRule`), кастомные параметры bootstrap-инициализации прокси-контейнеров Envoy инжектируются через ConfigMap с последующим отслеживанием через операторы перезапуска. Детали архитектуры прокси: [Service Mesh concepts](../../../Service_Mesh/service_mesh_concepts.md).

---

### Связанные документы базы знаний

* [Создание ConfigMap](./creation.md) — декларативные и императивные подходы к созданию объектов.
* [Неизменяемые ConfigMap](./immutable.md) — оптимизация нагрузки на API-сервер через `immutable: true`.
* [Обновление и Rollout](./update_and_rollout.md) — детальный анализ Config Skew Window и стратегий выкатки.
* [Работа с большими конфигурациями](./large_configs.md) — паттерны обхода лимита 1 MiB в etcd.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — продакшен-шаблоны для Nginx, Prometheus, Redis.
* [Лучшие практики ConfigMap](./best_practices.md) — архитектурные стандарты и рекомендации CNCF.
* [Projected Volumes](../Pod/volume_types/projected_volumes.md) — агрегация источников конфигурации в один том.
* [Диагностика ошибок ConfigMap](../../Troubleshooting/Common_Errors/CreateContainerConfigError/configmap_issues.md) — углубленный траблшутинг `CreateContainerConfigError`.
