# Argo CD: расширение функционала через Custom Tooling (Config Management Plugins v2)

**Актуально для:** Argo CD v3.5+ (CMP v2 sidecar-архитектура; покрывает Argo CD v2.8+ / v3.4–v3.6.x; CMP v1 удален в v2.8)

**Argo CD** обладает встроенной поддержкой стандартных инструментов шаблонизации (Helm, Kustomize, Jsonnet). Однако для расширенных практик GitOps (генерация через Helmfile, Helmwave, QBEC, расшифровка зашифрованных секретов на лету через `helm-secrets`/SOPS, кодогенерация манифестов на Python/Go) предусмотрен декларативный механизм **Custom Tooling** на базе **Config Management Plugins (CMP) v2**.

CMP v2 изолирует исполняемые бинарные файлы и их системные зависимости внутри отдельных sidecar-контейнеров пода `argocd-repo-server`. Взаимодействие между основным процессом `repo-server` и плагинами осуществляется по протоколу gRPC через локальные UNIX domain sockets.

## Предварительные требования

1. **Версия Argo CD:** v2.8+ (для полнофункционального механизма CMP v2 с поддержкой параметров `spec.parameters` и исключений tar stream рекомендуется v3.4–v3.6.x). CMP v1 (конфигурация через глобальный ConfigMap `argocd-cm`) полностью удален в v2.8.
2. **Права доступа в кластере Kubernetes:** Права администратора на модификацию рабочей нагрузки `argocd-repo-server` (Deployment) или управление значениями `values.yaml` официального Helm-чарта `argo-cd` в namespace установки (`argocd`).
3. **Хранилище образов (Container Registry):** Локальный или корпоративный реестр образов (Harbor, Nexus, GitLab Container Registry) при использовании подхода BYOI (Build Your Own Image) для sidecar-контейнеров.
4. **Понимание безопасности Linux и Kubernetes:** Настройка `SecurityContext` (UID 999 `argocd`, `runAsNonRoot: true`), изоляция томов `/tmp` и настройка NetworkPolicy для sidecar-контейнеров.

## Определения

**Config Management Plugin (CMP) v2** — плагин генерации манифестов Argo CD, функционирующий как автономный сервис внутри sidecar-контейнера в составе пода `argocd-repo-server`.

**argocd-cmp-server** — встроенный легковесный gRPC-сервер Argo CD, запускаемый в качестве точки входа (entrypoint) sidecar-контейнера плагина. Он прослушивает UNIX-сокет, принимает tar-поток с исходным кодом репозитория, управляет жизненным циклом плагина и возвращает готовые манифесты.

**Discovery (Обнаружение плагина)** — механизм сопоставления директории в Git-репозитории с подходящим CMP на основе имени файла (`fileName`), расширенной маски поиска (`find.glob`) или shell-команды (`find.command`).

**Tar Stream (Поток архива)** — сжатый поток данных директории приложения, передаваемый по gRPC из файловой системы основного контейнера `repo-server` в sidecar-контейнер CMP через UNIX-сокет без использования общих дисковых разделов репозитория.

**Init Phase (Фаза инициализации)** — этап подготовки локального окружения плагина перед генерацией манифестов (загрузка зависимостей, подмодулей, расшифровка ключей).

**Generate Phase (Фаза генерации)** — выполнение основной команды плагина, поток стандартного вывода (stdout) которой должен содержать строго валидные YAML или JSON манифесты Kubernetes.

**Parameter Announcements** — декларативное описание параметров (статических и динамических), передаваемое плагином в UI и CLI Argo CD для возможности кастомизации генерации через `Application.spec.source.plugin.parameters`.

**ASKPASS (Git Credentials Passthrough)** — механизм безопасной передачи учетных данных Git из хранилища `repo-server` в контейнер плагина по запросу через выделенный UNIX-сокет без предварительного экспорта токенов в переменные окружения.

## Архитектура и принцип работы

### Архитектура CMP v2

В CMP v2 плагины отделены от основного контейнера `repo-server`. Это предотвращает конфликт библиотек (например, разных версий Helm или Python), исключает загрязнение файловой системы и минимизирует риски компрометации ядра Argo CD.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Pod: argocd-repo-server                                │
│                                                                                        │
│  ┌─────────────────────────┐                            ┌───────────────────────────┐  │
│  │   Container: main       │                            │   Container: cmp-sidecar  │  │
│  │   (argocd-repo-server)  │                            │   (my-custom-plugin)      │  │
│  │                         │   gRPC over UNIX Socket    │                           │  │
│  │  1. Git clone / fetch   │   /var/run/argocd/*.sock   │  4. argocd-cmp-server     │  │
│  │  2. MatchRepository()   │◄──────────────────────────►│     - Читает plugin.yaml  │  │
│  │  3. Передача Tar-stream │                            │     - Распаковывает в /tmp│  │
│  │     директории в сокет  │                            │  5. Выполняет init.command│  │
│  │                         │                            │  6. Выполняет generate    │  │
│  │  7. Прием YAML-потока   │                            │  7. YAML/JSON stdout      │  │
│  │     stdout от плагина   │                            │     отправляется в сокет  │  │
│  └───────────┬─────────────┘                            └─────────────┬─────────────┘  │
│              │                                                        │                │
│              ▼                                                        ▼                │
│    ┌──────────────────────────────────────────────────────────────────────────┐        │
│    │  Volume (emptyDir): var-files                                            │        │
│    │  MountPath: /var/run/argocd                                              │        │
│    │  - argocd-cmp-server (бинарный файл, скопированный init-контейнером)    │        │
│    │  - *.sock (gRPC сокеты каждого sidecar-плагина)                          │        │
│    └──────────────────────────────────────────────────────────────────────────┘        │
│                                                                                        │
│    ┌───────────────────────────┐                        ┌───────────────────────────┐  │
│    │  Volume (emptyDir): tmp   │                        │  Volume (emptyDir):       │  │
│    │  MountPath: /tmp (main)   │                        │  cmp-tmp (изолированный!) │  │
│    │  (Кэш Git-репозиториев)   │                        │  MountPath: /tmp (sidecar)│  │
│    └───────────────────────────┘                        └───────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Поток данных и жизненный цикл обработки

1. **Клонирование и сопоставление:**
   - Основной контейнер `argocd-repo-server` выполняет `git fetch`/`clone` целевой ревизии во временную директорию.
   - `repo-server` опрашивает все активные UNIX-сокеты в директории `/var/run/argocd/` gRPC-вызовом `MatchRepository`.
   - Если в `Application.spec.source.plugin.name` явно указано имя, `repo-server` направляет запрос целевому сокету. Если имя не указано, активируется механизм автоматического обнаружения (Discovery).
2. **Передача данных (Tar Stream):**
   - `repo-server` архивирует директорию приложения (указанную в `Application.spec.source.path`) в потоковый tar-архив и передает его через сокет.
   - **Важно:** Общий дисковый том для исходных текстов между контейнерами **не требуется**. Это исключает гонки файлов (race conditions) при параллельной сборке нескольких ревизий.
3. **Распаковка и инициализация (Init Phase):**
   - Внутри sidecar-контейнера процесс `argocd-cmp-server` распаковывает полученный tar-поток в изолированный рабочий каталог внутри своего тома `/tmp`.
   - Выполняется команда `spec.init.command` в корне распакованного каталога. Ненулевой код возврата прерывает генерацию.
4. **Генерация манифестов (Generate Phase):**
   - Выполняется `spec.generate.command`.
   - Процесс обязан передать валидный поток YAML/JSON в `stdout`.
   - Все отладочные сообщения и логирование обязаны направляться в `stderr` (они отображаются в логах sidecar и передаются в UI при ошибках).
   - Вывод потока манифестов возвращается в `repo-server`, который выполняет парсинг и передает объекты в контроллер приложения.
5. **Очистка:**
   - Временная директория в `/tmp` внутри sidecar удаляется сразу после завершения gRPC-вызова.

### Спецификация конфигурационного файла `plugin.yaml`

Конфигурация плагина описывается документом вида `ConfigManagementPlugin` (не является CustomResourceDefinition в Kubernetes API, а представляет собой внутреннюю структуру Argo CD):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ConfigManagementPlugin
metadata:
  name: my-custom-plugin
spec:
  # Версия плагина (опционально). При наличии версии имя в Application задается как <name>-<version>
  version: v1.0

  # Фаза инициализации (выполняется перед generate)
  init:
    command: [sh, -c]
    args: ["echo 'Preparing environment...' && helm repo update"]

  # Фаза генерации манифестов (вывод строго в stdout)
  generate:
    command: [sh, -c]
    args:
      - |
        set -eo pipefail
        helmfile -e $ARGOCD_ENV_ENVIRONMENT template

  # Правила автоматического обнаружения (оцениваются в порядке: fileName, find.glob, find.command)
  discover:
    # 1. Поиск по имени/маске в корне директории приложения
    fileName: "helmfile.yaml"
    find:
      # 2. Поиск с поддержкой рекурсивных масок (double-star)
      glob: "**/helmfile.yaml"
      # 3. Выполнение команды в корне репозитория (успех, если exit code 0 и stdout не пуст)
      command: [sh, -c, "test -f helmfile.yaml && grep -q 'environments:' helmfile.yaml"]

  # Декларация параметров для интерфейса (UI) и CLI
  parameters:
    static:
      - name: release-name
        title: "Release Name"
        tooltip: "Override target Helm release name"
        required: false
        itemType: string
        collectionType: string
        string: "default-app"
      - name: additional-values
        title: "Values Files"
        collectionType: array
        array: ["values-default.yaml"]
    dynamic:
      # Команда возвращает JSON со списком параметров в stdout
      command: [sh, -c, "helmfile list-values-as-json"]

  # Сохранять оригинальные права доступа Unix-файлов (false по умолчанию для безопасности)
  preserveFileMode: false

  # Разрешить плагину запрашивать Git-токены через ASKPASS сокет
  provideGitCreds: false
```

### Переменные окружения плагина

В процесс выполнения команд CMP передаются четыре категории переменных окружения:

1. **Системные переменные контейнера:** все переменные, объявленные в секции `env` sidecar-контейнера.
2. **Стандартный контекст сборки Argo CD:**
   - `ARGOCD_APP_NAME` — имя приложения (санитизировано).
   - `ARGOCD_APP_NAMESPACE` — целевой namespace в управляемом кластере.
   - `ARGOCD_APP_REVISION` — целевой хэш коммита или тег.
   - `ARGOCD_APP_SOURCE_PATH` — относительный путь к директории приложения в Git.
   - `ARGOCD_APP_SOURCE_REPO_URL` — URL Git/Helm репозитория.
   - `ARGOCD_APP_SOURCE_TARGET_REVISION` — ветка, тег или ревизия из `Application.spec.source.targetRevision`.
   - `KUBE_VERSION` — версия Kubernetes целевого кластера (например, `1.30`).
   - `KUBE_API_VERSIONS` — список поддерживаемых API групп и версий кластера (разделенный запятыми).
3. **Пользовательские переменные из Application (`spec.source.plugin.env`):**
   - Все переданные пользователем переменные **принудительно получают префикс `ARGOCD_ENV_`**.
   - Пример: определение `- name: CLUSTER_ENV, value: prod` доступно в скрипте как `$ARGOCD_ENV_CLUSTER_ENV`. Это предотвращает перезапись системных переменных среды процесса (`PATH`, `HOME`, `KUBECONFIG`).
4. **Параметры из `spec.source.plugin.parameters`:**
   - Полный JSON со списком параметров доступен в переменной `ARGOCD_APP_PARAMETERS`.
   - Отдельные переменные транслируются по шаблону:
     - Строки: `PARAM_<UPPERCASE_NAME>=<value>` (например, `PARAM_RELEASE_NAME=prod-app`).
     - Массивы: `PARAM_<UPPERCASE_NAME>_<INDEX>=<value>` (например, `PARAM_ADDITIONAL_VALUES_0=values.yaml`).
     - Словари: `PARAM_<UPPERCASE_NAME>_<KEY>=<value>` (например, `PARAM_HELM_SET_IMAGE_TAG=v1.2.3`).

### Кэширование, таймауты и управление процессами

- **Redis-кэширование ошибок:** `argocd-repo-server` кэширует сгенерированные манифесты и ошибки генерации в Redis (по умолчанию на 3 минуты или до нового коммита). Если плагин завершился ошибкой из-за временного сетевого сбоя или опечатки в скрипте, перезапуск пода `repo-server` **не сбрасывает кэш ошибки**. Для принудительной повторной генерации требуется выполнить `Hard Refresh` приложения в UI или CLI (`argocd app get <app> --hard-refresh`).
- **Таймауты выполнения:**
  - `server.repo.server.timeout.seconds` и `controller.repo.server.timeout.seconds` в ConfigMap `argocd-cmd-params-cm` (по умолчанию 60 секунд). Определяют максимальное время ожидания ответа от `repo-server`.
  - `ARGOCD_EXEC_TIMEOUT` — переменная среды sidecar-контейнера CMP (по умолчанию 90 секунд). Если генерация комплексных чартов (например, Helmfile с 15 релизами) занимает больше времени, необходимо увеличить оба значения.
  - `ARGOCD_EXEC_FATAL_TIMEOUT` — дополнительный таймаут перед принудительным завершением процесса через SIGKILL, если graceful shutdown по истечении `ARGOCD_EXEC_TIMEOUT` не завершился.

---

## Настройка и конфигурация

### Механизм поставки бинарного файла `argocd-cmp-server`

Так как sidecar-контейнеры запускаются из произвольных образов (Alpine, Ubuntu, образы с Helmfile/QBEC), в них изначально отсутствует бинарный файл `argocd-cmp-server`.

Существует два стандартных подхода:

#### Способ 1: Использование `initContainer: copyutil` (Рекомендуемый для гибкости)
Официальный образ Argo CD монтирует общий том `emptyDir: var-files` и копирует бинарный файл `argocd` (который выступает в роли `argocd-cmp-server`) в `/var/run/argocd/argocd-cmp-server`.

```yaml
initContainers:
  - name: copyutil
    image: quay.io/argoproj/argocd:v3.5.4
    command: [cp, -n, /usr/local/bin/argocd, /var/run/argocd/argocd-cmp-server]
    volumeMounts:
      - mountPath: /var/run/argocd
        name: var-files
```

#### Способ 2: Собственный образ контейнера (BYOI)
При сборке собственного образа бинарник копируется напрямую из официального образа на этапе мультистейдж сборки:

```dockerfile
FROM quay.io/argoproj/argocd:v3.5.4 AS argocd-source
FROM alpine:3.20
COPY --from=argocd-source /usr/local/bin/argocd /usr/local/bin/argocd-cmp-server
```

---

## Практические сценарии

### Сценарий 1: Установка CMP через официальный Helm-чарт Argo CD

Для продакшн-установок настройка выполняется через `values.yaml` чарта `argo-cd`.

Создадим плагин для работы с **Helmfile v0.169.2**:

```yaml
# values.yaml для argo-cd Helm Chart
repoServer:
  # 1. Добавляем initContainer для копирования бинарника CMP-сервера
  initContainers:
    - name: copyutil
      image: quay.io/argoproj/argocd:v3.5.4
      command: [cp, -n, /usr/local/bin/argocd, /var/run/argocd/argocd-cmp-server]
      volumeMounts:
        - mountPath: /var/run/argocd
          name: var-files

  # 2. Подключаем ConfigMap с описанием плагина
  extraContainers:
    - name: helmfile-plugin
      image: ghcr.io/helmfile/helmfile:v0.169.2
      command: [/var/run/argocd/argocd-cmp-server]
      env:
        - name: ARGOCD_EXEC_TIMEOUT
          value: "180s"
        - name: HELM_CACHE_HOME
          value: /tmp/helm/cache
        - name: HELM_CONFIG_HOME
          value: /tmp/helm/config
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        readOnlyRootFilesystem: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - mountPath: /var/run/argocd
          name: var-files
        - mountPath: /home/argocd/cmp-server/plugins
          name: plugins
        - mountPath: /home/argocd/cmp-server/config/plugin.yaml
          subPath: plugin.yaml
          name: helmfile-cmp-config
        - mountPath: /tmp
          name: cmp-tmp

  # 3. Объявляем изолированные тома
  volumes:
    - name: helmfile-cmp-config
      configMap:
        name: helmfile-cmp-config
    - name: cmp-tmp
      emptyDir: {}
```

Манифест ConfigMap с конфигурацией плагина:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: helmfile-cmp-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: helmfile
    spec:
      version: v1.0
      discover:
        fileName: "helmfile.yaml"
      init:
        command: [sh, -c]
        args: ["helmfile deps"]
      generate:
        command: [sh, -c]
        args:
          - |
            set -eo pipefail
            ENV_ARG=""
            if [ -n "$ARGOCD_ENV_ENVIRONMENT" ]; then
              ENV_ARG="-e $ARGOCD_ENV_ENVIRONMENT"
            fi
            helmfile $ENV_ARG template --include-crds
```

### Сценарий 2: Расшифровка секретов на лету через helm-secrets и SOPS

При использовании SOPS для шифрования `secrets.yaml` в Git манифесты расшифровываются непосредственно во время фазы генерации, не сохраняя открытые секреты на диске `repo-server`.

> Архитектурное примечание: Для шифрования секретов см. подробнее [Управление секретами (SOPS)](../../Security/Tools/sops_overview.md). Для интеграции с HashiCorp Vault см. [Интеграция с Vault](./argocd_vault_integration.md).

**Конфигурация `plugin.yaml` для SOPS / helm-secrets:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: helm-secrets-cmp-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: helm-secrets
    spec:
      discover:
        find:
          glob: "**/secrets.yaml"
      init:
        command: [sh, -c]
        args: ["helm dependency build"]
      generate:
        command: [sh, -c]
        args:
          - |
            set -eo pipefail
            VALUES_ARGS=""
            if [ -f "values.yaml" ]; then
              VALUES_ARGS="-f values.yaml"
            fi
            if [ -f "secrets.yaml" ]; then
              VALUES_ARGS="$VALUES_ARGS -f secrets.yaml"
            fi
            helm secrets template "$ARGOCD_APP_NAME" . \
              --namespace "$ARGOCD_APP_NAMESPACE" \
              --kube-version "$KUBE_VERSION" \
              $VALUES_ARGS
```

Подключение GPG/Age ключей для расшифровки:
Ключи монтируются в sidecar-контейнер через секрет:

```yaml
volumeMounts:
  - mountPath: /home/argocd/.gnupg
    name: gpg-keyring
    readOnly: true
volumes:
  - name: gpg-keyring
    secret:
      secretName: argocd-gpg-keys
      defaultMode: 0400
```

### Сценарий 3: Плагин с передачей параметров (Parameters UI & CLI)

Создадим плагин шаблонизации `kustomize-envsubst`, который принимает параметры из `Application.spec.source.plugin.parameters` и отображает их в интерфейсе Argo CD.

**1. ConfigMap с объявлением параметров:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: envsubst-cmp-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: kustomize-envsubst
    spec:
      version: v1.0
      discover:
        fileName: "kustomization.yaml"
      parameters:
        static:
          - name: cluster-domain
            title: "Internal Cluster Domain"
            tooltip: "Root DNS domain for service ingress"
            required: true
            itemType: string
            collectionType: string
            string: "cluster.local"
          - name: replica-count
            title: "Default Replica Count"
            collectionType: string
            string: "2"
      generate:
        command: [sh, -c]
        args:
          - |
            set -eo pipefail
            export CLUSTER_DOMAIN="${PARAM_CLUSTER_DOMAIN:-cluster.local}"
            export REPLICA_COUNT="${PARAM_REPLICA_COUNT:-2}"
            kustomize build . | envsubst '${CLUSTER_DOMAIN} ${REPLICA_COUNT}'
```

**2. Декларация приложения `Application`:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo-service
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.internal.corp/infra/apps.git
    targetRevision: main
    path: overlays/production
    plugin:
      name: kustomize-envsubst-v1.0
      parameters:
        - name: cluster-domain
          string: "corp.example.internal"
        - name: replica-count
          string: "5"
  destination:
    server: https://kubernetes.default.svc
    namespace: production
```

### Сценарий 4: Сборка собственного образа (Production BYOI Dockerfile)

Для обеспечения неизменяемости инфраструктуры (immutability) и исключения сетевых загрузок во время старта пода рекомендуется собирать единый образ с бинарниками плагинов и запеченным `plugin.yaml`.

```dockerfile
# Multi-stage сборка для получения argocd-cmp-server
FROM quay.io/argoproj/argocd:v3.5.4 AS argocd-base

FROM alpine:3.20 AS builder
RUN apk add --no-cache curl tar gzip

# Загрузка проверенной версии Helmfile
ARG HELMFILE_VERSION=0.169.2
RUN curl -fsSL -o /tmp/helmfile.tar.gz \
    https://github.com/helmfile/helmfile/releases/download/v${HELMFILE_VERSION}/helmfile_${HELMFILE_VERSION}_linux_amd64.tar.gz && \
    tar -xzf /tmp/helmfile.tar.gz -C /usr/local/bin helmfile && \
    chmod 755 /usr/local/bin/helmfile

# Загрузка Helm v3.16.2
ARG HELM_VERSION=v3.16.2
RUN curl -fsSL -o /tmp/helm.tar.gz \
    https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz && \
    tar -xzf /tmp/helm.tar.gz -C /tmp && \
    mv /tmp/linux-amd64/helm /usr/local/bin/helm && \
    chmod 755 /usr/local/bin/helm

# Финальный легковесный образ
FROM alpine:3.20
RUN apk add --no-cache git bash jq gettext-envsubst

# Создаем системного пользователя argocd с UID 999
RUN addgroup -g 999 argocd && \
    adduser -u 999 -G argocd -D -s /bin/bash argocd

# Копируем бинарные файлы
COPY --from=argocd-base /usr/local/bin/argocd /var/run/argocd/argocd-cmp-server
COPY --from=builder /usr/local/bin/helmfile /usr/local/bin/helmfile
COPY --from=builder /usr/local/bin/helm /usr/local/bin/helm

# Подготавливаем директорию конфигурации CMP
WORKDIR /home/argocd/cmp-server/config
COPY plugin.yaml ./plugin.yaml

# Назначаем права доступа
RUN chown -R argocd:argocd /home/argocd && \
    mkdir -p /home/argocd/cmp-server/plugins && \
    chown -R argocd:argocd /home/argocd/cmp-server

USER 999
ENTRYPOINT ["/var/run/argocd/argocd-cmp-server"]
```

Сборка и доставка в локальный реестр:

```bash
docker build -t harbor.internal.corp/argocd/cmp-helmfile:v1.0.0 .
# → [+] Building ... FINISHED

docker push harbor.internal.corp/argocd/cmp-helmfile:v1.0.0
# → The push refers to repository [harbor.internal.corp/argocd/cmp-helmfile]
# → v1.0.0: digest: sha256:7b1e4c... size: 1420
```

### Сценарий 5: Оптимизация монорепозиториев (Tar Stream Exclusions и Paths)

В монорепозиториях передача всего архива репозитория в sidecar на каждое изменение коммита создает значительную нагрузку на CPU и диск `repo-server`.

#### 1. Исключение тяжелых директорий (.git, node_modules)
Настройте исключения для генератора tar-потока в ConfigMap `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Перечисление масок исключений через точку с запятой
  reposerver.plugin.tar.exclusions: ".git/*;.github/*;node_modules/*;docs/*;tests/*"
```

Либо через переменную окружения `argocd-repo-server`:
`ARGOCD_REPO_SERVER_PLUGIN_TAR_EXCLUSIONS: ".git/*;node_modules/*"`

#### 2. Ограничение генерации путями манифестов (`manifest-generate-paths`)
Включите поддержку избирательной генерации:

```yaml
# argocd-cmd-params-cm
data:
  reposerver.plugin.use.manifest.generate.paths: "true"
```

В манифесте `Application` укажите аннотацию, определяющую файлы, изменение которых действительно требует перезапуска генерации:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  annotations:
    argocd.argoproj.io/manifest-generate-paths: "services/payment;shared/helm/base"
spec:
  source:
    path: services/payment
    plugin:
      name: helmfile
```

### Сценарий 6: Мульти-плагинная конфигурация и предотвращение конфликтов обнаружения

Когда в кластере одновременно развернуто несколько CMP-плагинов (например, один для Helmfile, другой для QBEC, третий для Jsonnet), критически важно исключить пересечение правил `spec.discover`.

**Принцип работы селектора Discovery:**
Если каталог репозитория удовлетворяет правилам нескольких плагинов, Argo CD выбирает **первый ответивший плагин** (порядок сокетов в файловой системе не гарантирован). Это приводит к плавающим ошибкам генерации (flapping errors).

**Правила предотвращения конфликтов:**
1. **Детализируйте `discover.fileName` и `find.command`:** Избегайте общих масок вида `*.yaml`. Используйте сигнатурные файлы (`helmfile.yaml`, `qbec.yaml`).
2. **Используйте инспекцию содержимого:**
   ```yaml
   discover:
     find:
       command: [sh, -c, "grep -q 'apiVersion: qbec.io' qbec.yaml 2>/dev/null"]
   ```
3. **Явная привязка по имени:** В критических окружениях не полагайтесь на автоматический Discovery, а явно фиксируйте имя плагина в манифесте `Application`:
   ```yaml
   spec:
     source:
       plugin:
         name: helmfile-v1.0
   ```

### Сценарий 7: Доступ к приватным Git-зависимостям (Git Credentials Passthrough via ASKPASS)

Если плагину во время `init` необходимо загрузить сабмодули или приватные чарты из другого Git-репозитория, доступного в Argo CD, используется механизм безопасного проброса кредов:

**1. Включение в `plugin.yaml`:**
```yaml
spec:
  provideGitCreds: true
```

**2. Настройка общего сокета ASKPASS в Deployment `argocd-repo-server`:**
```yaml
containers:
  - name: argocd-repo-server
    env:
      - name: ARGOCD_ASK_PASS_SOCK
        value: /shared/askpass/askpass.sock
    volumeMounts:
      - name: askpass-socket
        mountPath: /shared/askpass

  - name: my-cmp-plugin
    env:
      - name: ARGOCD_ASK_PASS_SOCK
        value: /shared/askpass/askpass.sock
    volumeMounts:
      - name: askpass-socket
        mountPath: /shared/askpass
volumes:
  - name: askpass-socket
    emptyDir: {}
```

Когда плагин выполняет `git clone https://git.internal.corp/shared-modules.git`, Git обращается к скрипту `askpass`, который через сокет `/shared/askpass/askpass.sock` запрашивает временные учетные данные у `repo-server`.

---

### Сценарий 8: KSOPS (Mozilla SOPS + age) — прозрачная расшифровка секретов через CMP v2

В организациях без централизованного кластера HashiCorp Vault основным методом защиты конфиденциальных данных является шифрование в Git через **Mozilla SOPS** с асимметричными ключами **age** (см. детальное руководство по криптографии в [Управление секретами и шифрование в GitOps](../secrets_encryption.md)). 

Для прозрачной расшифровки файлов секретов непосредственно в процессе рендеринга Kustomize используется плагин **KSOPS** (Kustomize SOPS Plugin), разворачиваемый как CMP v2 sidecar.

#### 1. Создание секрета с приватным ключом age в кластере:
```bash
# Приватный ключ age создается утилитой age-keygen и регистрируется в namespace argocd
kubectl create secret generic sops-age-key -n argocd \
  --from-file=key.txt=/etc/security/age/keys.txt
# → result: secret/sops-age-key created
```

#### 2. Описание спецификации плагина в ConfigMap (`ksops-cmp-cm.yaml`):
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ksops-plugin-cm
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: ksops-plugin
    spec:
      version: v1.0
      discover:
        find:
          command: ["sh", "-c", "grep -rq 'ksops' . 2>/dev/null"]
      generate:
        command: ["kustomize", "build", "--enable-alpha-plugins", "--enable-exec", "."]
```

#### 3. Подключение sidecar-контейнера KSOPS в `values.yaml` чарта `argo-cd`:
```yaml
repoServer:
  extraContainers:
    - name: ksops-plugin
      image: viaductoss/ksops:v4.3.3
      command: ["/var/run/argocd/argocd-cmp-server"]
      env:
        - name: SOPS_AGE_KEY_FILE
          value: /var/run/secrets/age/key.txt
      volumeMounts:
        - mountPath: /var/run/argocd
          name: var-files
        - mountPath: /tmp
          name: cmp-tmp
        - mountPath: /home/argocd/cmp-server/config/plugin.yaml
          subPath: plugin.yaml
          name: ksops-plugin-config
        - mountPath: /var/run/secrets/age
          name: sops-age-key-volume
          readOnly: true
      securityContext:
        runAsNonRoot: true
        runAsUser: 999
        readOnlyRootFilesystem: true
  volumes:
    - name: ksops-plugin-config
      configMap:
        name: ksops-plugin-cm
    - name: sops-age-key-volume
      secret:
        secretName: sops-age-key
        defaultMode: 0400
    - name: cmp-tmp
      emptyDir: {}
```

#### 4. Использование KSOPS в репозитории приложения:
В файле `kustomization.yaml` объявляется генератор `ksops`:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml

generators:
  - secret-generator.yaml
```

Генератор `secret-generator.yaml`:
```yaml
apiVersion: viaduct.ai/v1
kind: ksops
metadata:
  name: app-secrets-generator
files:
  - ./secrets.enc.yaml
```

В момент выполнения `kustomize build` бинарник KSOPS внутри sidecar-контейнера считывает приватный ключ из `/var/run/secrets/age/key.txt`, расшифровывает значения из `secrets.enc.yaml` в оперативной памяти и возвращает чистый `Secret` в stdout gRPC-потока без сохранения на диск.

---

## Сравнение CMP v1 и CMP v2

| Характеристика | CMP v1 (Legacy, удален в v2.8) | CMP v2 (Современный стандарт) |
| :--- | :--- | :--- |
| **Архитектура** | Процессы запускались внутри основного контейнера `repo-server`. | Изолированные sidecar-контейнеры для каждого плагина. |
| **Место конфигурации** | Глобальный ConfigMap `argocd-cm` (`configManagementPlugins`). | Отдельный файл `plugin.yaml` в ConfigMap или запеченный в образ. |
| **Изоляция зависимостей** | Отсутствовала. Все утилиты (helm, yq, helmfile) боролись за одну файловую систему и библиотеки. | Полная. Каждый контейнер имеет свой базовый образ, бинарники и runtime. |
| **Безопасность** | Общие привилегии с `repo-server`. Доступ к корневым секретам репозиториев. | Индивидуальный `SecurityContext`, непривилегированный пользователь (UID 999), изолированный `/tmp`. |
| **Обновление конфигурации** | Изменение `argocd-cm` приводило к перезапуску всего `repo-server`. | Перезапуск только соответствующего sidecar при обновлении ConfigMap. |
| **Передача репозитория** | Прямой доступ к склонированной папке на диске `repo-server`. | Потоковая передача через gRPC Tar Stream по UNIX-сокету. |
| **Параметры в UI** | Не поддерживались. | Поддерживаются через `spec.parameters` (статические и динамические). |

---

## Операции и диагностика

### Проверка состояния компонентов

```bash
# Проверка готовности pod repo-server (должно быть 2/2 или более контейнеров в статусе Running)
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-repo-server
# → NAME                                  READY   STATUS    RESTARTS   AGE
# → argocd-repo-server-5757d54b8d-2k8l9   2/2     Running   0          45m

# Список контейнеров в поде repo-server
kubectl get pod -n argocd -l app.kubernetes.io/name=argocd-repo-server \
  -o jsonpath='{.items[0].spec.containers[*].name}'
# → argocd-repo-server helmfile-plugin

# Проверка наличия активных UNIX domain сокетов плагинов
kubectl exec -n argocd deployment/argocd-repo-server -c helmfile-plugin -- ls -la /var/run/argocd/
# → total 8
# → drwxrwxrwx 2 argocd argocd 4096 Oct 11 18:20 .
# → -rwxr-xr-x 1 argocd argocd 54200112 Oct 11 18:15 argocd-cmp-server
# → srwxr-xr-x 1 argocd argocd        0 Oct 11 18:20 helmfile.sock
```

### Просмотр логов sidecar-плагина

```bash
# Логирование процесса обнаружения и генерации плагина в реальном времени
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c helmfile-plugin -f
# → time="2026-10-11T18:25:01Z" level=info msg="Generating manifests for repo https://git.internal.corp/infra/apps.git"
# → time="2026-10-11T18:25:02Z" level=info msg="Executing: helmfile -e production template"
# → time="2026-10-11T18:25:05Z" level=info msg="Manifest generation completed successfully"
```

### Принудительный сброс Redis-кэша ошибок (Hard Refresh)

Если плагин был исправлен, но Argo CD продолжает выдавать предыдущую ошибку генерации:

```bash
# Принудительная очистка кэша генератора для конкретного приложения
argocd app get payment-service --hard-refresh
# → Name:               argocd/payment-service
# → Project:            default
# → Server:             https://kubernetes.default.svc
# → Namespace:          production
# → URL:                https://argocd.corp/applications/payment-service
# → Repo:               https://git.internal.corp/infra/apps.git
# → Target:             main
# → Path:               services/payment
# → Sync Status:        Synced
# → Health Status:      Healthy

# Альтернатива через kubectl (установка аннотации обновления)
kubectl annotate application payment-service -n argocd argocd.argoproj.io/refresh=hard --overwrite
# → application.argoproj.io/payment-service annotated
```

### Перезапуск пода после изменения ConfigMap плагина

Если `plugin.yaml` смонтирован из ConfigMap, изменения не подхватываются процессом `argocd-cmp-server` на лету:

```bash
kubectl rollout restart deployment/argocd-repo-server -n argocd
# → deployment.apps/argocd-repo-server restarted

kubectl rollout status deployment/argocd-repo-server -n argocd
# → deployment "argocd-repo-server" successfully rolled out
```

---

## Диагностика и устранение неполадок

### Типовые проблемы и их решения

| Ошибка / Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Пустой вывод манифестов удаляет ресурсы в кластере** (`Pruned all resources`) | Команда `generate` завершилась с ошибкой внутри конвейера (pipe), но вернула exit code 0; `prune: true` удалил все ресурсы. | **Критично:** всегда указывайте `set -eo pipefail` в начале shell-скрипта генерации. Проверяйте вывод: `generate: command: [sh, -c, "set -eo pipefail; helm template . \| grep -v '^\s*#'"]`. |
| `exec: "/var/run/argocd/argocd-cmp-server": no such file or directory` | В sidecar-контейнере отсутствует бинарный файл CMP-сервера. | Добавьте `initContainers: copyutil` в под или соберите собственный образ (BYOI), скопировав `/usr/local/bin/argocd` из официального образа `argoproj/argocd`. |
| `no matches for kind "ConfigManagementPlugin" in version "argoproj.io/v1alpha1"` | Попытка применить `plugin.yaml` напрямую в кластер через `kubectl apply -f plugin.yaml`. | `ConfigManagementPlugin` — внутренняя структура Argo CD, а не CRD в etcd. Она должна храниться в ConfigMap под ключом `plugin.yaml` или в образе контейнера. |
| `rpc error: code = DeadlineExceeded desc = context deadline exceeded` | Выполнение фаз `init` или `generate` превысило установленный таймаут (по умолчанию 60–90 с). | Увеличьте `ARGOCD_EXEC_TIMEOUT: "300s"` в контейнере плагина и параметры `server.repo.server.timeout.seconds: "300"` в `argocd-cmd-params-cm`. |
| `Permission denied` при записи во временные файлы | Контейнер плагина запущен с `readOnlyRootFilesystem: true`, но `/tmp` не смонтирован как `emptyDir`. | Добавьте volumeMount для `/tmp` с томом `emptyDir: {}` специально для контейнера плагина. Не монтируйте общий `/tmp` с `repo-server`! |
| Старая ошибка не исчезает после коммита в Git | `repo-server` закэшировал результат ошибки в Redis. | Выполните `argocd app get <app> --hard-refresh` или перезапустите под Redis: `kubectl rollout restart statefulset/argocd-redis-ha-server -n argocd`. |
| `Application uses plugin X, but X is not registered` | Имя плагина в Application не совпадает с `metadata.name` или `metadata.name-spec.version` в `plugin.yaml`. | Проверьте регистрацию сокета в `/var/run/argocd/*.sock` и соответствие поля `spec.source.plugin.name`. Если версия указана, формат имени: `<name>-<version>`. |
| Пересечение правил (Non-deterministic plugin selection) | Два разных CMP-плагина используют перекрывающиеся маски `fileName` (например, `*.yaml`). | Сделайте правила обнаружения максимально узкими (проверяйте конкретные файлы шаблонизаторов) либо жестко фиксируйте `plugin.name` в манифесте `Application`. |

---

## Рекомендации и лучшие практики

### Безопасность (Hardening)

- **Непривилегированный пользователь:** Запускайте sidecar строго под пользователем с UID 999 (`argocd`):
  ```yaml
  securityContext:
    runAsNonRoot: true
    runAsUser: 999
    readOnlyRootFilesystem: true
    allowPrivilegeEscalation: false
    capabilities:
      drop: ["ALL"]
  ```
- **Изоляция томов `/tmp`:** Начиная с версии v2.4, **запрещено монтировать один и тот же том `/tmp`** между основным контейнером `repo-server` и sidecar-контейнерами CMP. Совместное использование разделов `/tmp` открывает вектор атак обхода директорий (Path Traversal) и неконтролируемого перетирания кэша Git.
- **Предотвращение инъекций параметров:** Пользовательские параметры передаются через переменные окружения `$PARAM_*`. Никогда не подставляйте параметры напрямую в shell через конкатенацию `eval`. Используйте экранирование:
  ```bash
  # Правильно:
  helm template . --set "replicaCount=${PARAM_REPLICA_COUNT}"
  # Неправильно:
  eval "helm template . $PARAM_ARGS"
  ```
- **Защита от утечки секретов в UI:** Поток стандартного вывода ошибок `stderr` из команды `generate` передается в веб-интерфейс Argo CD при сбое сборки. Следите за тем, чтобы команды плагина не выводили расшифрованные секреты, токены и приватные ключи в `stderr`.
- **Контроль `preserveFileMode`:** Оставляйте параметр `preserveFileMode: false` (по умолчанию), если плагину не требуется запуск исполняемых скриптов, хранящихся внутри пользовательских репозиториев.

### Производительность и SRE

- **Минимизация образов (Distroless / Alpine):** Храните образы CMP минималистичными. Большие образы (более 500 МБ) замедляют горизонтальное масштабирование `repo-server` (HPA) при пиковых нагрузках на синхронизацию.
- **Исключения Tar-потока в монорепозиториях:** Обязательно активируйте `reposerver.plugin.tar.exclusions` для исключения директорий `.git`, `node_modules`, тестовых файлов и бинарных артефактов.
- **Мониторинг метрик Prometheus:**
  - `argocd_repo_server_exec_duration_seconds` — гистограмма длительности выполнения внешних команд плагинов (позволяет выявлять деградацию генерации манифестов).
  - `argocd_repo_server_exec_total` — общее количество вызовов утилит с разбивкой по кодам возврата.
  - `argocd_app_reconcile` — время полной сверки приложений (включая работу CMP).

---

## Дополнительная информация

### Связанные документы

- [Обзор архитектуры Argo CD](./argocd_overview.md) — базовые компоненты, контроллеры и принципы работы.
- [Интеграция с Vault (AVP)](./argocd_vault_integration.md) — детальная архитектура подстановки секретов из HashiCorp Vault.
- [Интеграция с Helm](./helm_integration.md) — встроенная работа с Helm-чартами и сравнение с CMP.
- [Синхронизация и политики](./synchronization.md) — фазы синхронизации, Sync Waves и хуки жизненного цикла.
- [RBAC в Argo CD](./argocd_rbac_deep.md) — разграничение прав доступа к приложениям и репозиториям.
- [Hardening и безопасность](./argocd_security_hardening.md) — изоляция сети, SecurityContext и аудит.
- [Disaster Recovery](./argocd_disaster_recovery.md) — резервное копирование и восстановление состояния.
- [Управление секретами (SOPS)](../../Security/Tools/sops_overview.md) — работа с зашифрованными секретами в Git.
- [Helmfile Overview](../../Kubernetes/ToolsUtilities/Helm/helmfile_overview.md) — декларативное управление несколькими Helm-чартами.
- [Helmwave Overview](../../Kubernetes/ToolsUtilities/Helm/helmwave_overview.md) — оркестрация релизов Helm с зависимостями.

### Официальная документация

- [Argo CD Documentation: Config Management Plugins](https://argo-cd.readthedocs.io/en/stable/operator-manual/config-management-plugins/)
- [Argo CD Example Plugins Repository](https://github.com/argoproj/argo-cd/tree/master/examples/plugins)
- [Helmfile Documentation](https://helmfile.readthedocs.io/)
- [Helmwave Documentation](https://helmwave.github.io/)
- [QBEC Documentation](https://qbec.io/)
