# Использование Secret в Pod

**Актуально для:** Kubernetes 1.30–1.32+ / kubectl 1.30+

## Определения

**Потребление Secret (Secret Consumption)** — процесс доставки конфиденциальных данных (паролей, токенов, сертификатов, конфигурационных файлов) из хранилища etcd в контейнеры Pod для обеспечения функционирования рабочих нагрузок в изолированной среде выполнения.

**Монтирование в Volume (tmpfs Secret Volume)** — механизм проецирования данных объекта Secret в файловую систему контейнера в виде набора файлов, размещенных на виртуальном RAM-диске (`tmpfs`) рабочего узла. Исключает запись чувствительной информации на физические дисковые накопители хоста.

**Атомарная ротация симлинков (Atomic Symlink Swapping)** — внутренняя реализация обновления смонтированных секретов в Kubelet через создание промежуточных директорий с временными метками (`..timestamp`) и переключение символической ссылки `..data` с помощью атомарного системного вызова ядра Linux `rename(2)`.

**Переменные окружения (Environment Variables / secretKeyRef, envFrom)** — внедрение значений ключей Secret непосредственно в окружение процессов контейнера во время их инициализации рантаймом контейнеризации (CRI / `containerd`) через системный вызов `execve(2)`.

**Ловушка subPath (subPath Inode Binding)** — архитектурное ограничение Linux bind-монтирования отдельного файла из тома: контейнер привязывается к первичному дескриптору `inode` файла, что полностью блокирует автоматическое обновление содержимого при ротации секрета Kubelet'ом.

**Проецируемый том (Projected Volume)** — тип тома Kubernetes (`volumes.projected`), объединяющий данные из нескольких источников (Secret, ConfigMap, Downward API, ServiceAccountToken) в единую файловую иерархию внутри одного каталога монтирования.

**Секреты скачивания образов (imagePullSecrets / dockerconfigjson)** — специализированные секреты типа `kubernetes.io/dockerconfigjson`, содержащие учетные данные для авторизации агента Kubelet и CRI в приватных реестрах контейнеров (Container Registry).

**Спецификация прав доступа (defaultMode, item mode, fsGroup)** — набор параметров манифеста Pod, определяющих числовую POSIX-маску разрешений (permissions) и групповое владение файлами секрета для безопасного чтения процессами, запущенными от непривилегированных пользователей (`runAsNonRoot: true`).

**Kubelet SecretManager** — компонент агента Kubelet на worker-узле, отвечающий за локальное кэширование, валидацию прав Node Authorization, создание виртуальных файловых систем `tmpfs` и контроль жизненного цикла секретов для запущенных на узле подов.

---

## Основные концепции и архитектура доставки

### Сравнительный анализ методов доставки секретов

Выбор способа передачи секретов в приложение определяет архитектурную безопасность, возможность ротации учетных данных без простоя (Zero-Downtime) и устойчивость к утечкам через дамп памяти или журналы.

| Критерий | Монтирование в Volume (`volumes.secret`) | Переменные окружения (`secretKeyRef`, `envFrom`) | Проецируемый том (`volumes.projected`) |
| :--- | :--- | :--- | :--- |
| **Механизм доставки** | Виртуальная файловая система `tmpfs` в RAM | Инъекция в массив `envp` при вызове `execve` | Агрегированный `tmpfs` из нескольких источников |
| **Динамическое обновление** | **Да** (атомарное переключение симлинка `..data`) | **Нет** (значения статичны до перезапуска контейнера) | **Да** (атомарное переключение симлинков) |
| **Реакция приложения** | Inotify, периодическое чтение или SIGHUP | Требуется полный перезапуск Pod (`rollout restart`) | Inotify, периодическое чтение или SIGHUP |
| **Риск утечки в логах и трассировках** | **Минимальный** (файл читается по требованию) | **Высокий** (дамп окружения при сбоях, APM-агенты) | **Минимальный** (файл читается по требованию) |
| **Доступность в `/proc`** | Защищено стандартными правами POSIX-каталога | Открыто в `/proc/<pid>/environ` для того же UID | Защищено стандартными правами POSIX-каталога |
| **Поддержка бинарных данных** | Полная (DER, PKCS12, JKS, бинарные ключи) | Ограничена (проблемы с null-byte `\0`, кодировками) | Полная (включая динамические токены SA) |
| **Гранулярность прав доступа** | Высокая (`defaultMode`, `items.mode`, `fsGroup`) | Отсутствует (доступны всем процессам контейнера) | Высокая (индивидуальный режим для источников) |
| **Влияние на cgroup память** | Занимает память в cgroup Pod (`memory.current`) | Незначительное (память стека процесса) | Занимает память в cgroup Pod (`memory.current`) |

### Архитектура Kubelet SecretManager и монтирование tmpfs

Kubelet на каждом worker-узле изолированно обрабатывает секреты, необходимые исключительно для подов, назначенных планировщиком (kube-scheduler) на данный конкретный узел.

```
 [ kube-apiserver ]
        │  ▲
        │  │ (Node Authorization: доступ только к секретам локальных Pod)
        ▼  │
 [ Kubelet на Worker-узле ]
        │
        ├─► SecretManager (кэш в RAM: Watch / Cache / Get)
        │
        ├─► Создание каталога на хосте:
        │   /var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~secret/<volume-name>/
        │
        ├─► Системный вызов: mount -t tmpfs tmpfs <путь_к_тому>
        │
        ├─► Запись файлов и формирование дерева атомарных симлинков
        │
        ▼
 [ Контейнер (CRI / containerd) ]
        │
        └─► Mount Namespace: точка монтирования проецируется в /etc/secrets
```

1. **Безопасность Node Authorization:** API Server блокирует попытки узла запросить секрет, если в манифестах локальных подов этого узла нет ссылок на указанный объект. Это локализует ущерб при компрометации отдельного хоста.
2. **Изоляция в памяти (`tmpfs`):** Тома секретов монтируются как `tmpfs`. Данные хранятся исключительно в оперативной памяти (VFS page cache) и никогда не сбрасываются в постоянное блочное хранилище worker-узла.
3. **Учет памяти в Linux cgroups:** Содержимое файловой системы `tmpfs` учитывается ядром Linux в счетчике рабочей памяти контейнера (`container_memory_working_set_bytes`). При монтировании крупных секретов (или множества сертификатов) необходимо учитывать их размер в `resources.limits.memory`, иначе процесс может быть принудительно завершен ядром с сигналом `OOMKilled`.

### Анатомия дерева симлинков Kubelet и атомарное обновление

Kubelet реализует двухуровневую структуру символических ссылок внутри директории монтирования секрета на worker-узле. Это гарантирует, что приложение никогда не прочитает частично записанный файл в момент ротации.

**Структура файлов внутри контейнера в точке монтирования `/etc/secrets`:**

```
/etc/secrets/
├── ..2026_10_17_19_00_00.584930211/        # Каталог версии N (актуальные данные)
│   ├── db-password
│   └── tls.crt
├── ..data -> ..2026_10_17_19_00_00.584930211  # Симлинк верхнего уровня на текущий каталог
├── db-password -> ..data/db-password        # Стабильный симлинк для приложения
└── tls.crt -> ..data/tls.crt                # Стабильный симлинк для приложения
```

**Пошаговый цикл ротации секрета:**

1. Администратор или оператор обновляет объект Secret в API Kubernetes (`kubectl apply` или Server-Side Apply).
2. Kubelet получает уведомление через механизм Watch или регулярный цикл синхронизации (параметр `syncFrequency`, по умолчанию 1 минута).
3. Kubelet создает новый подкаталог с меткой времени: `..2026_10_17_19_15_00.104928174`.
4. Все файлы секрета записываются в новый каталог с сохранением заданных прав (`defaultMode`).
5. Kubelet создает временный симлинк `..data_tmp`, указывающий на новый каталог с меткой времени.
6. Выполняется атомарный системный вызов `rename("..data_tmp", "..data")`. В ядре Linux эта операция выполняется неделимо.
7. Приложения, открывающие файл `/etc/secrets/tls.crt`, мгновенно начинают читать дескриптор новой версии.
8. Старая директория `..2026_10_17_19_00_00.584930211` безопасно удаляется Kubelet'ом.

> [!IMPORTANT]
> **Нюанс работы Inotify:** Поскольку файлы в корне тома (`/etc/secrets/tls.crt`) являются статическими симлинками на `..data/tls.crt`, события ядра `IN_MODIFY` и `IN_CLOSE_WRITE` непосредственно на файле `tls.crt` **не генерируются**. Для отслеживания изменений конфигурации inotify-демоны обязаны следить за событиями `IN_CREATE` / `IN_MOVED_TO` на каталоге монтирования либо реагировать на переключение симлинка `..data`.

### Технический разбор ловушки subPath

Монтирование секрета через директиву `subPath` используется для подстановки одиночного файла в существующую директорию без перезаписи соседних файлов (например, подстановка `nginx.conf` в `/etc/nginx/`).

```yaml
# ПРИМЕР ЛОВУШКИ: subPath блокирует обновление
volumeMounts:
- name: secret-volume
  mountPath: /etc/ssl/certs/server.crt
  subPath: server.crt
```

**Физика проблемы на уровне ядра Linux:**
- При использовании `subPath` Kubelet на этапе инициализации Pod выполняет прямое bind-монтирование конкретного файла из хостового пути в Mount Namespace контейнера:
  ```bash
  mount --bind /var/lib/kubelet/pods/<uid>/volumes/.../server.crt /rootfs/etc/ssl/certs/server.crt
  ```
- Системный вызов `mount --bind` связывается с конкретным номером **inode** файла в файловой системе.
- Когда Kubelet обновляет Secret, он создает новый каталог с новыми файлами и новыми inode. Симлинк `..data` переключается на них.
- Однако точка монтирования внутри контейнера продолжает удерживать старый inode исходного файла.
- **Итог:** Содержимое файла внутри контейнера навсегда остается в состоянии на момент старта Pod. Внешние ротации сертификатов или паролей не доходят до приложения, что приводит к внезапным отказам по истечении срока действия ключей (Silent Drift).

### Переменные окружения: жизненный цикл и векторы утечек

Передача учетных данных через переменные окружения (`env` и `envFrom`) поддерживается большинством legacy-приложений, но несет критические риски информационной безопасности.

```
[ Kubelet ] ──► CRI Container Runtime (containerd)
                       │
                       ├─► Чтение данных Secret из API
                       ├─► Формирование спецификации OCI (config.json: process.env)
                       │
                       ▼  execve(path, argv, envp)
                [ Процесс в контейнере ]
                       │
                       ├─► Статичный массив окружения в памяти процесса
                       └─► Доступен через /proc/<PID>/environ
```

**Критические векторы утечек:**

1. **Неизменяемость процесса:** Массив `envp` фиксируется ядром Linux при создании процесса. Обновление объекта Secret в Kubernetes невозможно доставить в запущенный процесс без перезапуска всего Pod.
2. **Утечки в дампы и трассировки стека:** При аварийных завершениях (crash dumps), исключениях и сбоях языковые среды (Java, Python, PHP, Node.js) выводят переменные окружения в журналы ошибок `stderr`, отправляя секреты в открытом виде в системы агрегации логов (Loki, Elasticsearch).
3. **Утечки через псевдофайловую систему `/proc`:** Любой вспомогательный процесс или скомпрометированная утилита внутри контейнера, запущенная с тем же UID, имеет прямой доступ к чтению `/proc/1/environ` или `/proc/self/environ`.
4. **Наследование дочерними процессами:** Любые команды, вызываемые приложением через `fork/exec` (например, вызовы утилит shell, curl, tar), автоматически наследуют полный набор чувствительных переменных.

### Управление правами доступа (POSIX Permissions, defaultMode и fsGroup)

По умолчанию Kubelet монтирует секреты с правами `0644` (`-rw-r--r--`) и владельцем `root:root` (UID 0, GID 0).

#### Конфликт runAsNonRoot и defaultMode: 0400

При выполнении требований безопасности (Pod Security Standards Restricted) контейнеры запускаются от непривилегированного пользователя: `runAsUser: 10001`, `runAsNonRoot: true`.

Если администратор указывает в томе строгий режим:
```yaml
volumes:
- name: cert-vol
  secret:
    secretName: app-tls
    defaultMode: 0400 # ОШИБКА ДЛЯ NON-ROOT!
```
- Файл создается с владельцем `UID: 0, GID: 0` и маской `0400` (`-r--------`).
- Читать файл разрешено **исключительно владельцу (root)**.
- Процесс с `UID: 10001` при попытке чтения получает фатальную системную ошибку ядра `EACCES (Permission denied)`, что переводит Pod в состояние `CrashLoopBackOff`.

#### Корректная конфигурация для non-root контейнеров

Для обеспечения безопасного доступа non-root процессов используется связка `fsGroup` и маски `0440`:

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    fsGroup: 10001                     # Kubelet назначает владение томом группе 10001
    fsGroupChangePolicy: "OnRootMismatch"
  containers:
  - name: app
    volumeMounts:
    - name: cert-vol
      mountPath: /etc/ssl/certs
      readOnly: true
  volumes:
  - name: cert-vol
    secret:
      secretName: app-tls
      defaultMode: 0440                # -r--r----- (чтение владельцу и группе fsGroup)
```

#### Ловушка восьмеричного формата YAML

В спецификации YAML числа с ведущим нулем без кавычек интерпретируются как восьмеричные (octal).
- `defaultMode: 0440` преобразуется в десятичное `288` (корректно).
- Если записать `defaultMode: 440` (случайно опустив `0`), парсер YAML воспримет это как десятичное число `440`, что соответствует восьмеричным правам `0670` (`-rw-rwx---`). В результате файл получит опасные права на исполнение группой.
- **Рекомендация:** Указывайте права в явном восьмеричном виде с ведущим нулем `0440` либо используйте строковый литерал `"0440"` или десятичный эквивалент `288`.

### Неизменяемые секреты (Immutable Secrets)

Поле `immutable: true` в объекте Secret сообщает Kubelet, что содержимое секрета зафиксировано навсегда.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: static-db-keys
immutable: true
data:
  api-key: dGVzdC1rZXk=
```

**Преимущества для SRE и производительности кластера:**
1. **Снижение нагрузки на Control Plane:** Kubelet перестает поддерживать Watch-соединения и запрашивать обновления объекта Secret у `kube-apiserver`. В кластерах с тысячами подов это предотвращает деградацию etcd и API Server.
2. **Защита от случайных изменений:** API Server отклоняет любые попытки изменения полей `data` и `stringData`.
3. **Паттерн версионирования в GitOps:** Для изменения ключа создается новый объект `static-db-keys-v2`, на который обновляется ссылка в манифесте Deployment. Это обеспечивает детерминированный скользящий перезапуск (RollingUpdate) с возможностью мгновенного отката.

---

## Практические сценарии и конфигурации

### Сценарий 1: Защищенное монтирование тома (Volume Mount) для Non-Root нагрузок

Эталонная конфигурация для On-Premise Production. Обеспечивает монтирование тома в режиме `readOnly`, защиту non-root процесса через `fsGroup: 2000`, гранулярное переименование ключей и явное назначение прав `0440`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secured-api-service
  namespace: production
  labels:
    app.kubernetes.io/name: api-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: api-service
  template:
    metadata:
      labels:
        app: api-service
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 2000
        runAsGroup: 2000
        fsGroup: 2000
        fsGroupChangePolicy: "OnRootMismatch"
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: application
        image: internal-harbor.corp.local/apps/backend:v2.4.1
        imagePullPolicy: IfNotPresent
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        volumeMounts:
        - name: tls-credentials
          mountPath: /etc/ssl/app
          readOnly: true
        - name: tmp-volume
          mountPath: /tmp
      volumes:
      - name: tls-credentials
        secret:
          secretName: api-tls-certs
          defaultMode: 0440
          items:
          - key: tls.crt
            path: server.crt
            mode: 0440
          - key: tls.key
            path: server.key
            mode: 0400 # Будет доступен пользователю 2000 при совпадении с UID
      - name: tmp-volume
        emptyDir: {}
```

### Сценарий 2: Инъекция переменных окружения с префиксом (env и envFrom)

Использование `envFrom` с обязательным префиксом (`prefix`) исключает случайную перезапись стандартных переменных окружения Linux (`PATH`, `HOME`, `USER`) и наглядно разделяет источники секретов в коде приложения.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: env-injection-demo
  namespace: production
spec:
  containers:
  - name: worker
    image: internal-harbor.corp.local/apps/worker:v1.12.0
    env:
      # Точечная инъекция обязательного ключа (optional: false по умолчанию)
      - name: DATABASE_MASTER_PASSWORD
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: master-password
            optional: false
      # Точечная инъекция опционального ключа (Pod запустится, даже если ключа нет)
      - name: SENTRY_DSN
        valueFrom:
          secretKeyRef:
            name: telemetry-secrets
            key: sentry-dsn
            optional: true
    # Массовый импорт всех ключей секрета с безопасным изолирующим префиксом
    envFrom:
      - prefix: "REDIS_SEC_"
        secretRef:
          name: redis-access-keys
          optional: false
```

> [!WARNING]
> Если в объекте `redis-access-keys` содержался ключ `PASSWORD`, внутри контейнера переменная получит имя `REDIS_SEC_PASSWORD`. Если один и тот же параметр объявлен и в `env`, и в `envFrom`, значение из прямого блока `env` обладает наивысшим приоритетом.

### Сценарий 3: Агрегация данных через Projected Volume

Проектируемый том позволяет консолидировать секреты, общие параметры конфигурации, метаданные пода и кратковременные токены ServiceAccount в единую структуру директории, минимизируя количество точек монтирования.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: unified-workload-pod
  namespace: production
spec:
  containers:
  - name: service
    image: internal-harbor.corp.local/apps/auth-service:v1.0.5
    volumeMounts:
    - name: runtime-configs
      mountPath: /var/run/app/context
      readOnly: true
  volumes:
  - name: runtime-configs
    projected:
      defaultMode: 0440
      sources:
      # 1. Секрет: TLS-сертификаты
      - secret:
          name: auth-tls
          items:
          - key: tls.crt
            path: tls/cert.pem
          - key: tls.key
            path: tls/key.pem
      # 2. ConfigMap: конфигурационный файл сервиса
      - configMap:
          name: auth-config
          items:
          - key: settings.yaml
            path: config/settings.yaml
      # 3. Downward API: имя пода и пространство имен
      - downwardAPI:
          items:
          - path: metadata/pod_name
            fieldRef:
              fieldPath: metadata.name
          - path: metadata/namespace
            fieldRef:
              fieldPath: metadata.namespace
      # 4. Bound ServiceAccount Token для локального Vault / Auth API
      - serviceAccountToken:
          audience: "vault-internal"
          expirationSeconds: 7200
          path: tokens/vault-token
```

### Сценарий 4: Аутентификация в приватных реестрах (imagePullSecrets) в On-Premise

Для развертывания контейнеров из защищенного корпоративного реестра (Harbor, Nexus, локальный Distribution Registry) требуется предоставление учетных данных агенту Kubelet.

#### 1. Создание секрета `docker-registry` через CLI

Команда генерирует валидную структуру `.dockerconfigjson` без сохранения пароля в истории shell:

```bash
kubectl create secret docker-registry harbor-corp-creds \
  --docker-server=internal-harbor.corp.local \
  --docker-username=robot-deployer \
  --docker-password='ExtremelySecurePassword123!' \
  --docker-email=devops-alerts@corp.local \
  --namespace=production \
  --dry-run=client -o yaml | kubectl apply -f -
```

#### 2. Декларативный манифест секрета

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: harbor-corp-creds
  namespace: production
type: kubernetes.io/dockerconfigjson
data:
  # Base64-представление файла ~/.docker/config.json
  .dockerconfigjson: eyJhdXRocyI6eyJpbnRlcm5hbC1oYXJib3IuY29ycC5sb2NhbCI6eyJ1c2VybmFtZSI6InJvYm90LWRlcGxveWVyIiwicGFzc3dvcmQiOiJFeHRyZW1lbHlTZWN1cmVQYXNzd29yZDEyMyEiLCJlbWFpbCI6ImRldm9wcy1hbGVydHNAY29ycC5sb2NhbCJ9fX0=
```

#### 3. Наследование через ServiceAccount (Best Practice для SRE)

Вместо дублирования секции `imagePullSecrets` во всех манифестах Pod и Helm-чартах, учетные данные привязываются к сервисному аккаунту неймспейса:

```bash
# Привязка секрета к стандартному ServiceAccount неймспейса
kubectl patch serviceaccount default -n production \
  -p '{"imagePullSecrets": [{"name": "harbor-corp-creds"}]}'
# → result: serviceaccount/default patched
```

Любой Pod, создаваемый с `serviceAccountName: default`, автоматически получит блок `imagePullSecrets` при прохождении через Admission Controller ServiceAccount.

### Сценарий 5: Автоматическая ротация секретов без простоя (Hot-Reloading и Reloader)

#### Паттерн А: Автоматический перезапуск Pod контроллером Stakater Reloader

Если приложение не поддерживает динамическое перечитывание файлов конфигурации, используется On-Premise контроллер [Stakater Reloader](../../ToolsUtilities/reloader/reloader_usage_scenarios.md). Контроллер перехватывает событие изменения Secret и запускает `RollingUpdate` связанного Deployment.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-gateway
  namespace: production
  annotations:
    # Отслеживать конкретный секрет
    secret.reloader.stakater.com/reload: "payment-db-secret,payment-api-keys"
    # Либо отслеживать все секреты, смонтированные в Pod:
    # reloader.stakater.com/auto: "true"
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: gateway
        image: internal-harbor.corp.local/apps/payment:v1.9.0
        volumeMounts:
        - name: db-sec
          mountPath: /etc/secrets/db
          readOnly: true
      volumes:
      - name: db-sec
        secret:
          secretName: payment-db-secret
```

#### Паттерн Б: Динамическое перечитывание симлинка `..data` (Inotify Hot-Reload)

Для приложений с поддержкой перезагрузки на лету (Nginx, Envoy, приложения на Go/Rust) создается sidecar-контейнер либо внутренний поток (goroutine), отслеживающий изменение симлинка:

```bash
#!/bin/sh
# Пример логики легковесного sidecar для перезагрузки конфигурации Nginx
SECRETS_DIR="/etc/ssl/app"
while true; do
  # Ожидание атомарного перемещения симлинка ..data
  inotifywait -e moved_to -e create "$SECRETS_DIR"
  echo "[$(date)] Зафиксировано переключение симлинка ..data. Отправка SIGHUP в Nginx..."
  pkill -HUP -f nginx || true
done
```

### Сценарий 6: Обработка бинарных секретов (JKS, PKCS12, Keystores)

Секреты Kubernetes нативно поддерживают бинарные артефакты (Java KeyStore, mTLS P12 сертификаты, файлы лицензий).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: java-microservice
  namespace: production
spec:
  containers:
  - name: java-app
    image: internal-harbor.corp.local/apps/java-service:v11.0.2
    env:
      - name: JAVA_OPTS
        value: "-Djavax.net.ssl.trustStore=/var/run/secrets/java/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"
    volumeMounts:
    - name: keystore-vol
      mountPath: /var/run/secrets/java
      readOnly: true
  volumes:
  - name: keystore-vol
    secret:
      secretName: java-tls-keystore
      defaultMode: 0440
      items:
      - key: truststore.jks
        path: truststore.jks
```

> [!CAUTION]
> Никогда не передавайте бинарные данные через переменные окружения. При экранировании управляющих символов и нулевых байтов (`\0`) данные необратимо повреждаются, вызывая фатальные ошибки `Invalid keystore format` при старте JVM.

---

## Операции и команды управления

Все команды содержат параметры выполнения и репрезентативный вывод для аудита и отладки инфраструктуры.

### 1. Проверка смонтированной файловой системы tmpfs внутри Pod

Команда проверяет, что секрет действительно размещен в оперативной памяти (tmpfs), а не на корневом накопителе:

```bash
kubectl exec -it secured-api-service-7598c9f59b-2xk8l -n production -c application -- mount | grep /etc/ssl/app
# → result: tmpfs on /etc/ssl/app type tmpfs (ro,relatime,size=1048576k,mode=755)
```

### 2. Аудит структуры симлинков Kubelet и метки времени

Просмотр текущего активного каталога с меткой времени и привязки симлинка `..data`:

```bash
kubectl exec -it secured-api-service-7598c9f59b-2xk8l -n production -c application -- ls -la /etc/ssl/app
# → result:
# total 0
# drwxr-xr-x 3 root 2000 120 Oct 17 19:15 .
# drwxr-xr-x 3 root root  40 Oct 17 19:00 ..
# drwxr-xr-x 2 root 2000  80 Oct 17 19:15 ..2026_10_17_19_15_00.104928174
# lrwxrwxrwx 1 root 2000  31 Oct 17 19:15 ..data -> ..2026_10_17_19_15_00.104928174
# lrwxrwxrwx 1 root 2000  17 Oct 17 19:15 server.crt -> ..data/server.crt
# lrwxrwxrwx 1 root 2000  17 Oct 17 19:15 server.key -> ..data/server.key
```

### 3. Верификация POSIX-прав и владельца файлов секрета

Проверка числовой маски прав доступа, UID владельца и GID группы:

```bash
kubectl exec -it secured-api-service-7598c9f59b-2xk8l -n production -c application -- stat -c '%a %u %g %n' /etc/ssl/app/..data/*
# → result:
# 440 0 2000 /etc/ssl/app/..data/server.crt
# 400 0 2000 /etc/ssl/app/..data/server.key
```

### 4. Безопасная инспекция окружения процесса без вывода в командную строку

Просмотр переменных процесса через `/proc` целевого контейнера:

```bash
kubectl exec -it env-injection-demo -n production -c worker -- strings /proc/1/environ | grep -E '^(DATABASE_|REDIS_)'
# → result:
# DATABASE_MASTER_PASSWORD=Sup3rS3cr3tP@ssw0rd!
# REDIS_SEC_CLUSTER_AUTH=Red!sClust3rAuthToken99
# REDIS_SEC_PORT=6379
```

### 5. Проверка прав RBAC сервисного аккаунта на чтение секретов

Верификация прав доступа ServiceAccount к ресурсам секретов в целевом пространстве имен:

```bash
kubectl auth can-i get secrets/api-tls-certs \
  --namespace=production \
  --as=system:serviceaccount:production:default
# → result: no
```

```bash
kubectl auth can-i list secrets \
  --namespace=production \
  --as=system:serviceaccount:production:default
# → result: no
```

### 6. Мониторинг синхронизации секретов в журнале Kubelet на worker-узле

Просмотр действий SecretManager и монтирования томов на рабочем узле хоста:

```bash
journalctl -u kubelet --no-pager -n 50 | grep -E 'MountVolume.SetUp succeeded.*secret'
# → result:
# Oct 17 19:15:02 k8s-worker-02 kubelet[1842]: I1017 19:15:02.128491 1842 reconciler.go:374] "MountVolume.SetUp succeeded for volume \"tls-credentials\" (UniqueName: \"kubernetes.io/secret/5b68f9a2-9701-443b-8211-e6308bb87d89-tls-credentials\") pod \"secured-api-service-7598c9f59b-2xk8l\" (UID: \"5b68f9a2-9701-443b-8211-e6308bb87d89\")"
```

### 7. Аудит привязок imagePullSecrets в ServiceAccount

Проверка наличия секретов для вытягивания образов у учетной записи:

```bash
kubectl get serviceaccount default -n production -o jsonpath='{.imagePullSecrets[*].name}'
# → result: harbor-corp-creds
```

---

## Диагностика и устранение неполадок

### Сводная матрица типовых инцидентов

| Симптом / Ошибка | Первопричина | Команда первичной диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `CreateContainerConfigError` | Секрет или ключ не существует (`optional: false`) | `kubectl describe pod <pod-name>` | Создать недостающий Secret / ключ либо выставить `optional: true` |
| `CrashLoopBackOff` (`Permission denied`) | Конфликт `runAsNonRoot` и `defaultMode: 0400` | `kubectl logs <pod-name>` | Задать `fsGroup: <GID>` и перевести `defaultMode` в `0440` |
| Секрет обновлен, но приложение видит старые данные | Использование директивы `subPath` либо переменных окружения | `kubectl get pod <pod-name> -o yaml \| grep -E 'subPath\|envFrom'` | Отказаться от `subPath`, перейти на Volume Mount или настроить Stakater Reloader |
| `ImagePullBackOff` / `ErrImagePull` | Отсутствует `imagePullSecrets` или неверный пароль в реестре | `kubectl get events -n <ns> --field-selector reason=Failed` | Пересоздать секрет `docker-registry` и привязать к ServiceAccount |
| Опасные или неверные права на файлах тома (`0670`) | Запись `defaultMode: 440` в YAML как десятичного числа | `stat -c '%a' /path/to/secret/*` | Исправить манифест: указать `defaultMode: 0440` с ведущим нулем |

---

### Детальные сценарии устранения инцидентов

#### Инцидент 1: Pod зависает в статусе CreateContainerConfigError

**Симптом:**
Новый Pod не запускается, переходя в состояние ошибки:
```bash
kubectl get pods -n production
# → result:
# NAME                         READY   STATUS                       RESTARTS   AGE
# backend-api-5c4d799f-7m4pl   0/1     CreateContainerConfigError   0          42s
```

**Диагностика:**
1. Проверка событий жизненного цикла Pod:
   ```bash
   kubectl describe pod backend-api-5c4d799f-7m4pl -n production | grep -A 4 Events:
   # → result:
   # Events:
   #   Type     Reason   Age                From               Message
   #   ----     ------   ----               ----               -------
   #   Warning  Failed   12s (x6 over 54s)  kubelet            Error: secret "database-auth" not found
   ```
2. Проверка существования секрета в целевом пространстве имен:
   ```bash
   kubectl get secret database-auth -n production
   # → result: Error from server (NotFound): secrets "database-auth" not found
   ```

**Решение:**
1. Если имя секрета было указано с опечаткой, исправьте манифест Deployment.
2. Если секрет еще не создан пайплайном, создайте его:
   ```bash
   kubectl create secret generic database-auth \
     --from-literal=password='ClusterInitPassword2026' \
     -n production
   # → result: secret/database-auth created
   ```
3. Kubelet автоматически перепроверит наличие секрета и запустит контейнер без необходимости удаления Pod.

---

#### Инцидент 2: Фатальная ошибка доступа (Permission Denied) в Non-Root контейнере

**Симптом:**
Контейнер аварийно завершается сразу после старта:
```bash
kubectl logs backend-worker-6789b9d88-k8zlw -n production
# → result:
# 2026/10/17 19:22:10 [FATAL] Failed to open TLS private key /etc/ssl/app/server.key: open /etc/ssl/app/server.key: permission denied
```

**Диагностика:**
1. Проверка контекста безопасности контейнера:
   ```bash
   kubectl get pod backend-worker-6789b9d88-k8zlw -n production -o jsonpath='{.spec.securityContext}'
   # → result: {"fsGroup":3000,"runAsNonRoot":true,"runAsUser":3000}
   ```
2. Инспекция прав на смонтированном томе:
   ```bash
   kubectl get pod backend-worker-6789b9d88-k8zlw -n production -o jsonpath='{.spec.volumes[?(@.name=="tls-vol")]}'
   # → result: {"name":"tls-vol","secret":{"defaultMode":256,"secretName":"app-tls"}}
   ```
   *Примечание:* Десятичное `256` соответствует восьмеричному `0400` (`-r--------`). Владельцем является `root (0)`. Пользователь `3000` не имеет прав на чтение файла.

**Решение:**
1. Обновите спецификацию тома, установив права группового чтения `defaultMode: 0440`:
   ```yaml
   volumes:
   - name: tls-vol
     secret:
       secretName: app-tls
       defaultMode: 0440 # Разрешает чтение членам группы fsGroup: 3000
   ```
2. Примените манифест. После пересоздания пода контейнер успешно прочитает ключи.

---

#### Инцидент 3: Секрет обновлен в Kubernetes, но приложение использует старые учетные данные

**Симптом:**
Администратор выполнил ротацию пароля базы данных в объекте Secret, но приложение в подах продолжает слать старый пароль и получает ошибку `401 Unauthorized` от СУБД.

**Диагностика:**
1. Проверка содержимого секрета в API:
   ```bash
   kubectl get secret db-pass -n production -o jsonpath='{.data.password}' | base64 -d
   # → result: NewUltraSecurePass2026!
   ```
2. Проверка способа монтирования секрета в Pod:
   ```bash
   kubectl get pod backend-service-59bc74966d-x2m4z -n production -o yaml | grep -B 2 -A 2 subPath
   # → result:
   # volumeMounts:
   # - mountPath: /app/config/db.password
   #   name: db-volume
   #   subPath: db.password
   ```
   *Анализ:* Наличие директивы `subPath` отключает механизм обновления через симлинки Kubelet. Файл привязан к старому `inode`.

**Решение:**
1. **Экстренное решение (SRE Hotfix):** Перезапустите деплоймент для принудительного пересоздания подов со свежими `inode`:
   ```bash
   kubectl rollout restart deployment/backend-service -n production
   # → result: deployment.apps/backend-service restarted
   ```
2. **Системное решение:** Избавьтесь от `subPath`. Смонтируйте секрет целиком в отдельную служебную директорию (например, `/var/run/secrets/db`), а приложение настройте на чтение из этого каталога. Если требуется авторестарт, подключите контроллер Stakater Reloader.

---

#### Инцидент 4: ImagePullBackOff при скачивании из приватного On-Premise реестра

**Симптом:**
Pod зависает при скачивании базового образа:
```bash
kubectl get pod secure-app-7b9f56477b-df42k -n production
# → result:
# NAME                          READY   STATUS             RESTARTS   AGE
# secure-app-7b9f56477b-df42k   0/1     ImagePullBackOff   0          90s
```

**Диагностика:**
1. Проверка описания ошибки в событиях Pod:
   ```bash
   kubectl describe pod secure-app-7b9f56477b-df42k -n production | grep -E 'Failed.*image'
   # → result:
   # Warning  Failed  45s (x2 over 78s)  kubelet  Failed to pull image "internal-harbor.corp.local/prod/api:v1": rpc error: code = Unknown desc = failed to pull and unpack image: failed to resolve reference: unexpected status from HEAD request to https://internal-harbor.corp.local/v2/prod/api/manifests/v1: 401 Unauthorized
   ```
2. Проверка наличия секции `imagePullSecrets` в манифесте Pod:
   ```bash
   kubectl get pod secure-app-7b9f56477b-df42k -n production -o jsonpath='{.spec.imagePullSecrets}'
   # → result: []
   ```
   *Анализ:* Pod не передает учетные данные для авторизации в Harbor.

**Решение:**
1. Добавьте секрет в ServiceAccount неймспейса:
   ```bash
   kubectl patch serviceaccount default -n production \
     -p '{"imagePullSecrets": [{"name": "harbor-corp-creds"}]}'
   # → result: serviceaccount/default patched
   ```
2. Удалите сбойный Pod, чтобы контроллер ReplicaSet пересоздал его с унаследованными `imagePullSecrets`:
   ```bash
   kubectl delete pod secure-app-7b9f56477b-df42k -n production
   # → result: pod "secure-app-7b9f56477b-df42k" deleted
   ```

---

## Рекомендации (Best Practices)

### 1. Архитектурная безопасность доставки данных

1. **Volume Mount вместо переменных окружения:** Передавайте чувствительные данные (пароли, TLS-ключи, API-токены) исключительно через монтирование томов (`tmpfs`). Полностью исключите переменные окружения для долгоживущих паролей, чтобы предотвратить их утечку в дампы памяти, дампы стека при сбоях и логирование через `/proc/<pid>/environ`.
2. **Исключение директивы `subPath`:** Откажитесь от монтирования секретов через `subPath`. Если приложению требуется конкретный файл, монтируйте том целиком с директивой `items` либо настраивайте путь к каталогу в конфигурации сервиса.
3. **Обязательный `readOnly: true`:** Все точки монтирования томов секретов обязаны содержать директиву `readOnly: true` в секции `volumeMounts`. Контейнер не должен иметь технической возможности модифицировать файлы в оперативной памяти тома.

### 2. Права доступа и изоляция рабочих нагрузок

4. **Стандарт Non-Root контейнеров:** Контейнеры должны функционировать под управлением непривилегированных пользователей (`runAsNonRoot: true`). Используйте комбинацию параметров:
   ```yaml
   securityContext:
     runAsUser: 10001
     runAsGroup: 10001
     fsGroup: 10001
     fsGroupChangePolicy: "OnRootMismatch"
   ```
5. **Строгие POSIX-права `defaultMode: 0440`:** Для non-root нагрузок задавайте режим `0440` (`-r--r-----`). Права `0400` приводят к ошибкам `Permission Denied`, а права по умолчанию `0644` предоставляют доступ на чтение посторонним процессам внутри контейнера.
6. **Контроль формата YAML:** Всегда указывайте числовую маску прав доступа с явным ведущим нулем `0440` либо заключайте значение в кавычки `"0440"`. Запись без нуля (`440`) преобразуется парсером в десятичное число и присвоит файлу некорректные разрешения `0670`.

### 3. SRE-эксплуатация и управление ресурсами

7. **Учет tmpfs в cgroup Limits:** Файлы томов `tmpfs` аллоцируются в оперативной памяти хоста и тарифицируются ядром в лимит памяти Pod (`resources.limits.memory`). При проектировании подов, монтирующих объемные хранилища сертификатов или ключей, закладывайте буфер памяти не менее 50–100 МиБ сверх потребностей процесса приложения.
8. **Автоматическая ротация без участия человека:** Если приложение не умеет динамически перечитывать сертификаты с диска по сигналу или через inotify, интегрируйте в On-Premise кластер оператор **Stakater Reloader**. Аннотируйте манифесты `Deployment` и `StatefulSet`, чтобы изменения Secret автоматически приводили к скользящему перезапуску без простоя сервиса.
9. **Применение `immutable: true` в GitOps:** Для стабильных версий релизов помечайте секреты как неизменяемые. Это защищает конфигурации от дрейфа (drift), снимает нагрузку опроса с API Server и Kubelet, а ротацию переводит в безопасное русло создания новых версий объектов (`secret-v1` -> `secret-v2`).

---

## Дополнительная информация

### Системные ограничения и лимиты ядра

- **Максимальный размер секрета:** Физический лимит на объект Secret в хранилище etcd составляет **1 МиБ** (1048576 байт). Попытка смонтировать секрет большего объема будет отклонена API-сервером на этапе валидации.
- **Ограничение Inode в tmpfs:** По умолчанию размер файловой системы `tmpfs`, создаваемой Kubelet'ом для секрета, равен 50% доступной RAM узла (если не задан параметр `medium: Memory` с лимитом размера), но квотируется памятью cgroup Pod.
- **Поддержка User Namespaces (Kubernetes 1.30+ GA/Beta):** При активации пространства имен пользователей (User Namespaces) сопоставление UID хоста и UID внутри контейнера смещается. Механизм `fsGroup` автоматически адаптирует права владения каталогов тома с учетом `subuid` и `subgid` контейнера.

### Смотрите также

- [Основы Kubernetes Secret](secrets_basics.md) — базовые структуры, кодирование Base64, архитектура и жизненный цикл.
- [Создание Secret](creating_secrets.md) — декларативные и императивные сценарии создания типизированных секретов.
- [Безопасность Secret](security.md) — модель угроз, шифрование в etcd, аудит и политики доступа.
- [Pod Security Standards и Secret](pod_security_and_secrets.md) — влияние профилей безопасности Restricted/Baseline на доставку секретов.
- [Секреты в StatefulSet](statefulset_secrets.md) — шаблоны доставки учетных данных для распределенных баз данных и репликации.
- [Внешние менеджеры секретов](external_managers.md) — интеграция с HashiCorp Vault, OpenBao и External Secrets Operator.
- [Секреты в Helm](helm_secrets.md) — шаблонизация и версионирование секретов в чартах.
- [Хранение секретов в etcd](etcd_storage.md) — внутренняя структура хранения и шифрование данных в покое.
- [Projected Volumes](../Pod/volume_types/projected_volumes.md) — архитектура и применение проецируемых томов.
- [Сценарии использования Reloader](../../ToolsUtilities/reloader/reloader_usage_scenarios.md) — автоматический перезапуск рабочих нагрузок при обновлении Secret.
