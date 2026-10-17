# Управление секретами в Helm

**Актуально для:** Kubernetes 1.30–1.34+, Helm 3.14–3.17+, helm-secrets v4.6.x, Mozilla/getsops SOPS v3.9–v3.13.x, age v1.2.x, HashiCorp Vault 1.18–1.21 / OpenBao 2.x (On-Premise / Bare-Metal)

## Определения

- **Helm** — пакетный менеджер для Kubernetes, шаблонизирующий манифесты через Go-шаблоны и управляющий версионированием релизов кластера.
- **helm-secrets** — плагин для CLI Helm (`jkroepke/helm-secrets`), обеспечивающий расшифровку файлов значений (`values.yaml`) и манифестов «на лету» перед вызовом команд шаблонизации и деплоя (`template`, `upgrade`, `install`, `diff`).
- **SOPS (Secrets OPerationS)** — редактор зашифрованных файлов от CNCF/Mozilla, поддерживающий частичное шифрование структурированных форматов (YAML, JSON, ENV). В файлах шифруются только значения полей, а структура ключей остается открытой.
- **age** — современный инструмент асимметричного шифрования файлов с открытым исходным кодом, использующий криптографию X25519/ChaCha20-Poly1305. Является стандартом де-факто для локальных и GitOps-сред без привязки к внешним сервисам.
- **existingSecret** — архитектурный паттерн проектирования Helm-чартов, при котором манифест пода ссылается на уже существующий в кластере объект `Secret`, созданный внешней доверенной системой или оператором, минуя механизм рендеринга секретов самим чартом.
- **Helm Release Storage (Релизный бэкенд Helm)** — механизм хранения состояния релизов Helm внутри кластера Kubernetes в виде объектов `Secret` (или `ConfigMap`) формата `sh.helm.release.v1.<RELEASE_NAME>.v<REVISION>`.
- **Downloader Plugin Protocol (`secrets://`)** — встроенный в Helm 3 интерфейс перехвата URI-схем, позволяющий плагину `helm-secrets` прозрачно расшифровывать файлы значений по ссылке вида `-f secrets://path/to/secrets.yaml` без использования префикса `helm secrets` в основной команде.

---

## Архитектура и базовые концепции

### Проблема открытых секретов в Helm и релизный бэкенд

Хранение секретов в открытом виде внутри `values.yaml` или их передача через аргумент `--set` представляет собой критическую угрозу безопасности по нескольким векторам:

```
[Разработчик / CI/CD] 
       │
       ├── (1) git push values.yaml ───────────► [Git-репозиторий: утечка в git log]
       │
       ├── (2) helm upgrade --set pass=... ────► [Процессы ОС / CI логи: ps aux, bash_history]
       │
       ▼
 [Helm CLI Client]
       │
       ├── Рендеринг шаблона Secret
       │
       ▼
[Kubernetes API / etcd]
       │
       ├── (3) etcd: Secret приложения (нативный объект в namespace)
       │
       └── (4) etcd: sh.helm.release.v1.app.v1 (gzip + base64 манифест релиза со всеми секретами!)
```

1. **Компрометация истории Git:** Значения, однажды закоммиченные в репозиторий, навсегда сохраняются в истории коммитов Git.
2. **Утечка через журналы CI/CD и память процессов:** Флаги `--set secret=value` отображаются в выводе терминалов, журналах пайплайнов, таблицах системных процессов (`ps aux`) и файлах истории оболочки (`.bash_history`).
3. **Хранилище релизов Helm (`sh.helm.release.v1.*`):** При генерации объекта `Secret` через шаблон чарта полный текст манифеста сериализуется, сжимается алгоритмом `gzip`, кодируется в `Base64` и сохраняется в релизном объекте `Secret` пространства имен. Любой пользователь или сервисный аккаунт, имеющий RBAC-права на чтение релизных секретов Helm или доступ к командам `helm get manifest` / `helm get values`, получает доступ ко всем секретам в открытом виде.

### Модели доставки секретов в Helm-чартах

В локальной инфраструктуре (on-premise / bare-metal) без использования внешних облачных провайдеров применяются две основные архитектурные стратегии:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Подход 1: helm-secrets + SOPS / age (Шифрование на этапе рендеринга)             │
│                                                                                 │
│  [Git: secrets.yaml] ──► [helm secrets] ──► [Расшифровка в RAM] ──► [K8s API]   │
│     (зашифрован)          (SOPS + age)       (файл в /dev/shm)      (etcd)      │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│ Подход 2: existingSecret + Внешний оператор (Полное разделение ответственности) │
│                                                                                 │
│  [Git: ExternalSecret] ──► [ESO / Vault Operator] ──► [K8s Secret в etcd]       │
│                                                              ▲                  │
│  [Git: Helm Chart] ──────► [helm upgrade] ───────────────────┘ (ссылка по имени)│
│    (только ссылка)          (без секретов в values)                             │
└─────────────────────────────────────────────────────────────────────────────────┘
```

| Характеристика | `helm-secrets` + SOPS | Паттерн `existingSecret` |
| :--- | :--- | :--- |
| **Точка расшифровки** | Клиентский агент (CI/CD runner, рабочая станция, Argo CD repo-server) | Внутри кластера (оператором) либо предварительно администратором |
| **Хранение в Git** | Зашифрованные файлы `secrets.yaml` (SOPS) | Декларативные ссылки или внешние ресурсы (`ExternalSecret`) |
| **Секреты в манифесте релиза Helm** | **Да** (если чарт генерирует объект `Secret`) | **Нет** (в релизе хранится только имя целевого ресурса) |
| **Инфраструктурные зависимости** | Утилиты `sops`, `age`, плагин `helm-secrets` | Внешний оператор (Vault, ESO, Sealed Secrets) или внешнее хранилище |
| **Сложность внедрения** | Низкая (не требует контроллеров в кластере) | Средняя / Высокая (требует развертывания контроллеров) |

### Принцип работы плагина helm-secrets

Плагин `helm-secrets` поддерживает два режима взаимодействия:

1. **Режим обертки (CLI Wrapper):**
   Команда `helm secrets <subcommand> [flags]` перехватывает аргументы, определяет зашифрованные файлы (по умолчанию с расширениями `.yaml`, `.yml`, если они зашифрованы SOPS), расшифровывает их во временную защищенную директорию (`HELM_SECRETS_DEC_DIR`) с расширением `.dec`, передает полученные пути в нативный бинарный файл `helm`, а после завершения команды гарантированно удаляет расшифрованные копии.
2. **Режим загрузчика (Downloader Plugin Protocol `secrets://`):**
   Начиная с Helm 3, плагин регистрирует кастомную схему URL `secrets://`. При указании пути `-f secrets://path/to/secrets.yaml` Helm вызывает обработчик плагина, который на лету читает поток данных, выполняет расшифровку через выбранный бэкенд (SOPS/Vals) и возвращает поток открытого YAML непосредственно в стандартный ввод парсера Helm без создания временных файлов на жестком диске.

### Безопасность временных файлов в памяти (SRE / Sysadmin)

По умолчанию утилиты могут создавать расшифрованные файлы на локальной дисковой подсистеме хоста в каталоге чарта или `/tmp`. В многопользовательских средах и на общих раннерах CI/CD это создает риск утечки данных через swap, дампы дисков или соседние процессы.

**Инженерные требования к изоляции:**
- Использование оперативной памяти через монтирование `tmpfs` (каталог `/dev/shm` в Linux).
- Установка переменной окружения `HELM_SECRETS_DEC_DIR=/dev/shm`.
- Настройка жестких масок доступа (`umask 077`), исключающих чтение файлов посторонними локальными пользователями.
- Изоляция рабочих процессов параллельных сборок через динамические суффиксы каталогов (`HELM_SECRETS_DEC_DIR=/dev/shm/build-$CI_JOB_ID`).

---

## Практические сценарии и настройка

### 1. Установка инструментария (On-Premise / Linux)

Все утилиты развертываются на сборочных узлах (CI/CD Runners, bastion-хостах или рабочих станциях инженеров) в виде скомпилированных статически бинарных файлов без привязки к внешним сетевым репозиториям.

```bash
# 1. Установка age (криптографический бэкенд)
export AGE_VERSION="v1.2.1"
curl -fsSL -o /tmp/age.tar.gz "https://github.com/FiloSottile/age/releases/download/${AGE_VERSION}/age-${AGE_VERSION}-linux-amd64.tar.gz"
tar -xzf /tmp/age.tar.gz -C /tmp
sudo mv /tmp/age/age /tmp/age/age-keygen /usr/local/bin/
rm -rf /tmp/age*

# Проверка установки age
age --version
# → age v1.2.1

# 2. Установка SOPS
export SOPS_VERSION="v3.9.4"
curl -fsSL -o /usr/local/bin/sops "https://github.com/getsops/sops/releases/download/${SOPS_VERSION}/sops-${SOPS_VERSION}.linux.amd64"
chmod +x /usr/local/bin/sops

# Проверка установки SOPS
sops --version
# → sops 3.9.4 (latest)

# 3. Установка плагина helm-secrets
helm plugin install https://github.com/jkroepke/helm-secrets --version v4.6.3
# → Installed plugin: secrets

# Проверка установки плагина
helm secrets --version
# → 4.6.3
```

### 2. Управление ключевыми парами age

Для асимметричного шифрования генерируется пара ключей: открытый ключ (recipient, начинается с `age1...`) коммитится в конфигурационный файл `.sops.yaml`, а закрытый ключ (identity, начинается с `AGE-SECRET-KEY-1...`) хранится в защищенном хранилище и подключается через переменные окружения.

```bash
# Генерация ключевой пары для контура Production
mkdir -p ~/.config/sops/age
umask 077
age-keygen -o ~/.config/sops/age/production.agekey
# → Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p

# Просмотр созданного открытого ключа
age-keygen -y ~/.config/sops/age/production.agekey
# → age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p
```

### 3. Конфигурация `.sops.yaml` для репозитория

Файл `.sops.yaml` размещается в корне репозитория чартов или инфраструктурного монорепозитория. Правила `creation_rules` определяют, какими публичными ключами шифруются файлы по регулярным выражениям путей.

```yaml
# .sops.yaml
creation_rules:
  # Секреты для production-окружения
  - path_regex: .*/secrets-prod\.yaml$
    age: "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"
  
  # Секреты для stage/dev-окружений (несколько получателей: админ + CI)
  - path_regex: .*/secrets-stage\.yaml$
    age: >-
      age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p,
      age1y2h7k98t02d64xwtl56c5q9870tqu70z5sww4y0f7v3j99n82y3q432xyz
  
  # Шифрование через on-premise HashiCorp Vault / OpenBao Transit Engine
  - path_regex: .*/vault-transit-secrets\.yaml$
    hc_vault_transit_uri: "https://vault.internal.corp:8200/v1/transit/keys/sops-helm-key"
```

> **Безопасность:** В файле `.sops.yaml` хранятся исключительно открытые ключи или пути к URI транзитного движка Vault. Файл полностью безопасен для коммита в систему контроля версий.

### 4. Жизненный цикл зашифрованных файлов значений

#### Создание и первичное шифрование

```bash
# Шаг 1: Создание исходного файла с чувствительными данными
cat << 'EOF' > secrets-prod.yaml
database:
  user: "pg_master_app"
  password: "SuperSecretProductionDatabasePassword2026!"
apiToken: "sec-tok-98421894719827391823719"
EOF

# Шаг 2: Шифрование файла на месте через helm secrets
helm secrets enc secrets-prod.yaml
# → Encrypting secrets-prod.yaml

# Шаг 3: Проверка структуры зашифрованного файла
cat secrets-prod.yaml
# → database:
# →     user: ENC[AES256_GCM,data:wU2v8zH8KxQ=,iv:...,tag:...,type:str]
# →     password: ENC[AES256_GCM,data:qW0d3...,iv:...,tag:...,type:str]
# → sops:
# →     age:
# →       - recipient: age1ql3z...
# →         enc: ...
```

#### Просмотр и редактирование

Для внесения изменений не требуется вручную расшифровывать файл на диск:

```bash
# Экспорт пути к закрытому ключу для SOPS
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/production.agekey"

# Просмотр содержимого в расшифрованном виде (stdout)
helm secrets view secrets-prod.yaml
# → database:
# →   user: "pg_master_app"
# →   password: "SuperSecretProductionDatabasePassword2026!"
# → apiToken: "sec-tok-98421894719827391823719"

# Редактирование файла в интерактивном редакторе (nano/vim)
# Файл временно расшифровывается в память, а при сохранении автоматически перезашифровывается
EDITOR=vim helm secrets edit secrets-prod.yaml
```

### 5. Деплой приложений и шаблонизация

#### Деплой через CLI Wrapper

```bash
# Использование оперативной памяти для временных файлов
export HELM_SECRETS_DEC_DIR="/dev/shm"

# Проверка рендеринга шаблонов без отправки в Kubernetes
helm secrets template my-release ./my-chart \
  -f ./my-chart/values.yaml \
  -f ./my-chart/secrets-prod.yaml
# → ---
# → # Source: my-chart/templates/secret.yaml
# → apiVersion: v1
# → kind: Secret
# → ...

# Деплой релиза в кластер
helm secrets upgrade --install my-release ./my-chart \
  --namespace production \
  --create-namespace \
  -f ./my-chart/values.yaml \
  -f ./my-chart/secrets-prod.yaml
# → Release "my-release" has been upgraded. Happy Helming!
```

#### Деплой через Downloader Plugin (`secrets://`)

Использование схемы `secrets://` поддерживается стандартным бинарным файлом `helm` без префикса `secrets`:

```bash
# Helm вызывает downloader-плагин для расшифровки на лету
helm upgrade --install my-release ./my-chart \
  --namespace production \
  -f ./my-chart/values.yaml \
  -f secrets://./my-chart/secrets-prod.yaml
# → Release "my-release" has been upgraded. Happy Helming!
```

### 6. Реализация эталонного паттерна existingSecret в Helm-чарте

Для высокозащищенных сред рекомендуется не сохранять значения секретов в манифесте релиза Helm, а использовать паттерн `existingSecret`. Чарт либо использует уже существующий объект `Secret`, либо создает собственный, если задан флаг `secret.create: true`.

#### Структура `values.yaml`

```yaml
# values.yaml
replicaCount: 2

image:
  repository: registry.internal.corp/apps/backend
  tag: "v1.4.2"
  pullPolicy: IfNotPresent

secret:
  # Если false — чарт не создает Secret, а ожидает внешне созданный объект
  create: false
  # Имя внешнего Secret в том же namespace
  existingSecret: "production-app-secrets"
  # Ключи, ожидаемые внутри Secret
  dbPasswordKey: "db-password"
  apiTokenKey: "api-token"
  # Используется только при create: true (для локальных dev/test сред)
  data: {}
```

#### Шаблон `templates/secret.yaml`

```yaml
{{- if .Values.secret.create -}}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "my-chart.fullname" . }}-credentials
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
type: Opaque
stringData:
  {{- range $key, $val := .Values.secret.data }}
  {{ $key }}: {{ $val | quote }}
  {{- end }}
{{- end }}
```

#### Шаблон `templates/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "my-chart.fullname" . }}
  labels:
    {{- include "my-chart.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "my-chart.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "my-chart.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ ternary (printf "%s-credentials" (include "my-chart.fullname" .)) .Values.secret.existingSecret .Values.secret.create }}
                  key: {{ .Values.secret.dbPasswordKey }}
            - name: API_TOKEN
              valueFrom:
                secretKeyRef:
                  name: {{ ternary (printf "%s-credentials" (include "my-chart.fullname" .)) .Values.secret.existingSecret .Values.secret.create }}
                  key: {{ .Values.secret.apiTokenKey }}
```

### 7. Автоматизация в CI/CD (GitLab CI на Bare-Metal Runner)

Пайплайн на изолированном корпоративном runner'е использует переменную `SOPS_AGE_KEY` (тип `File` или `Variable` с атрибутами `Protected` и `Masked`).

```yaml
# .gitlab-ci.yml
stages:
  - test
  - deploy

variables:
  HELM_SECRETS_DEC_DIR: "/dev/shm/${CI_JOB_ID}"
  HELM_SECRETS_QUIET: "true"

before_script:
  # Проверка наличия закрытого ключа age
  - test -n "$SOPS_AGE_KEY" || { echo "ERROR: SOPS_AGE_KEY is not defined!"; exit 1; }
  - mkdir -p -m 0700 "$HELM_SECRETS_DEC_DIR"

after_script:
  # Принудительная очистка RAM-диска после сборки
  - rm -rf "$HELM_SECRETS_DEC_DIR"

helm:lint-and-template:
  stage: test
  image: registry.internal.corp/devops/helm-ci:v3.17-sops
  script:
    - helm secrets lint ./charts/my-app -f ./charts/my-app/secrets-prod.yaml
    - helm secrets template my-app ./charts/my-app -f ./charts/my-app/secrets-prod.yaml > /dev/null
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

deploy:production:
  stage: deploy
  image: registry.internal.corp/devops/helm-ci:v3.17-sops
  script:
    - helm secrets upgrade --install my-app ./charts/my-app
        --namespace production
        --atomic
        --timeout 5m
        -f ./charts/my-app/values.yaml
        -f ./charts/my-app/secrets-prod.yaml
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

### 8. Интеграция с GitOps: Argo CD и Helmfile

#### Настройка Helmfile (`helmfile.yaml`)

Утилита `helmfile` поддерживает `helm-secrets` нативно через декларативную директиву `secrets:`:

```yaml
# helmfile.yaml
repositories:
  - name: internal-charts
    url: https://charts.internal.corp/repository

releases:
  - name: payment-gateway
    namespace: billing
    chart: internal-charts/payment-service
    version: 2.11.0
    values:
      - ./environments/production/values.yaml
    # Helmfile автоматически вызывает helm-secrets для расшифровки
    secrets:
      - ./environments/production/secrets.yaml
```

```bash
# Применение конфигурации через helmfile
helmfile -e production apply
# → Upgrading release=payment-gateway, chart=internal-charts/payment-service
```

#### Настройка Argo CD через Config Management Plugins (CMP v2)

В GitOps-контроллере Argo CD расшифровка выполняется в изолированном sidecar-контейнере пода `argocd-repo-server`.

```yaml
# argocd-cmp-helm-secrets.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmp-helm-secrets
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
          glob: "**/secrets*.yaml"
      init:
        command: ["helm", "dependency", "build"]
      generate:
        command: ["sh", "-c"]
        args:
          - |
            set -euo pipefail
            ARGS=""
            if [ -f "values.yaml" ]; then
              ARGS="$ARGS -f values.yaml"
            fi
            for sec in secrets*.yaml; do
              if [ -f "$sec" ]; then
                ARGS="$ARGS -f $sec"
              fi
            done
            helm secrets template "$ARGOCD_APP_NAME" . \
              --namespace "$ARGOCD_APP_NAMESPACE" \
              --kube-version "$KUBE_VERSION" \
              $ARGS
```

---

## Операции и команды

### Справочник команд плагина helm-secrets

| Команда | Назначение | Пример использования |
| :--- | :--- | :--- |
| `helm secrets enc <file>` | Зашифровать открытый файл на месте по правилам `.sops.yaml` | `helm secrets enc secrets.yaml` |
| `helm secrets dec <file>` | Расшифровать файл на диск с созданием `<file>.dec` | `helm secrets dec secrets.yaml` |
| `helm secrets view <file>` | Расшифровать файл и направить содержимое в `stdout` без записи на диск | `helm secrets view secrets.yaml \| jq .database` |
| `helm secrets edit <file>` | Открыть файл в `$EDITOR` с автоматической перезашифровкой при сохранении | `EDITOR=nano helm secrets edit secrets.yaml` |
| `helm secrets clean [dir]` | Рекурсивно удалить все остаточные расшифрованные файлы `*.dec` | `helm secrets clean .` |
| `helm secrets template` | Выполнить рендеринг чарта Helm с предварительной расшифровкой значений | `helm secrets template rel ./chart -f secrets.yaml` |
| `helm secrets upgrade` | Выполнить обновление/установку релиза с зашифрованными значениями | `helm secrets upgrade --install rel ./chart -f secrets.yaml` |
| `helm secrets diff` | Показать дифференциал манифестов (требует плагин `helm-diff`) | `helm secrets diff upgrade rel ./chart -f secrets.yaml` |

### Переменные окружения для управления поведением

| Переменная | Назначение | Значение по умолчанию / Рекомендуемое |
| :--- | :--- | :--- |
| `HELM_SECRETS_DRIVER` | Драйвер шифрования (`sops`, `vals`, `vault`) | `sops` |
| `HELM_SECRETS_DEC_DIR` | Каталог для размещения временных расшифрованных файлов | Каталог чарта / `/dev/shm` (SRE recommendation) |
| `HELM_SECRETS_DEC_PREFIX` | Префикс/суффикс расшифрованных файлов | `.dec` |
| `HELM_SECRETS_QUIET` | Подавление информационного вывода о расшифровке | `false` / `true` (для чистых пайплайнов CI) |
| `SOPS_AGE_KEY` | Строка, содержащая закрытый ключ age | Отсутствует (передается через переменные CI) |
| `SOPS_AGE_KEY_FILE` | Путь к локальному файлу identity age | `~/.config/sops/age/keys.txt` |
| `HELM_SECRETS_SOPS_PATH` | Кастомный путь к бинарному файлу `sops` | Поиск в `$PATH` |

---

## Диагностика и устранение неполадок

### Матрица типовых проблем

| Симптом / Ошибка | Первопричина | Команда диагностики | Метод устранения |
| :--- | :--- | :--- | :--- |
| `sops metadata not found` | Попытка расшифровать файл, который не был зашифрован через SOPS | `head -n 20 secrets.yaml` | Проверьте, содержит ли файл секцию `sops:`. Выполните `helm secrets enc secrets.yaml` |
| `no identity matched any of the recipients` | В `SOPS_AGE_KEY` или ключевом файле нет закрытого ключа, соответствующего открытому ключу в файле | `age-keygen -y key.txt` и сравнение с секцией `sops.age` в файле | Добавьте корректный закрытый ключ age в окружение или обновите ключи получателей через `sops updatekeys` |
| `Permission denied (/dev/shm/...)` | У процесса сборки нет прав на запись в целевую директорию RAM-диска | `ls -ld /dev/shm` | Настройте маску каталога или изолируйте путь под идентификатор сборки: `HELM_SECRETS_DEC_DIR=/dev/shm/$USER` |
| В Git случайно закоммичен файл `secrets.yaml.dec` | Отсутствие защитных правил в `.gitignore` или сбой выполнения `helm secrets clean` | `git status --ignored` | Немедленно добавьте `*.dec` в `.gitignore`, удалите файл из индекса `git rm --cached *.dec` и выполните ротацию скомпрометированных паролей |
| `secrets "xxx" is forbidden: User cannot get resource` | Сервисный аккаунт Helm/CI/CD не имеет прав RBAC на чтение или создание `Secret` | `kubectl auth can-i get secrets --as=system:serviceaccount:prod:deployer` | Назначьте `Role` / `RoleBinding` с ресурсом `secrets` и глаголами `get`, `list`, `create`, `update`, `patch` |
| `secrets://: protocol not supported` | Плагин `helm-secrets` не установлен или повреждена регистрация схемы в Helm 3 | `helm env HELM_PLUGINS` | Переустановите плагин: `helm plugin install https://github.com/jkroepke/helm-secrets` |
| Секреты видны в выводе `helm get values` | Секреты переданы через флаг `--values` в открытом виде или чарт сохраняет их в `values.yaml` релиза | `helm get values <release-name> -n <ns>` | Используйте `existingSecret` либо шифруйте значения через `helm-secrets` и ограничьте доступ к Helm CLI |

### Процедура аудита релизных секретов Helm

Проверка наличия незашифрованных учетных данных в базе состояний Helm (`etcd`):

```bash
# 1. Поиск последнего секретного объекта релиза Helm в namespace
kubectl get secrets -n production -l "owner=helm,name=my-release" --sort-by='.metadata.creationTimestamp'
# → NAME                           TYPE                 DATA   AGE
# → sh.helm.release.v1.my-release.v1   helm.sh/release.v1   1      2d
# → sh.helm.release.v1.my-release.v2   helm.sh/release.v1   1      1h

# 2. Извлечение и расшифровка манифеста релиза напрямую из etcd/K8s API
kubectl get secret sh.helm.release.v1.my-release.v2 -n production -o jsonpath='{.data.release}' | \
  base64 -d | base64 -d | gzip -d | jq -r '.manifest' | grep -A 10 "kind: Secret"
# → kind: Secret
# → metadata:
# →   name: my-release-credentials
# → data:
# →   password: ...
```

> **Вывод SRE:** Если команда выше отображает чувствительные данные приложения, значит, чарт генерирует манифест `Secret` через шаблоны. Для полного исключения секретов из релизного манифеста переведите приложение на паттерн `existingSecret`.

---

## Рекомендации и Best Practices

### 1. Безопасность и изоляция ключей (DevOps / SRE)

- **Принцип наименьших привилегий:** Никогда не используйте единый мастер-ключ age для всех окружений. Создавайте независимые пары ключей минимум для контуров `production`, `staging` и `development`.
- **Изоляция в оперативной памяти:** Всегда определяйте переменную `HELM_SECRETS_DEC_DIR=/dev/shm` (или путь к разделу `tmpfs`) в CI/CD раннерах. Это исключает запись открытых секретов на физические дисковые накопители.
- **Маскирование в журналах:** Обязательно активируйте флаги маскирования (`Masked`) для переменных `SOPS_AGE_KEY` в GitLab CI / GitHub Actions / Jenkins, чтобы предотвратить их попадание в stdout пайплайнов при аварийном завершении скриптов.

### 2. Защита репозиториев от утечек

- **Строгие правила `.gitignore`:** Добавьте следующие шаблоны в корневой `.gitignore` каждого репозитория:
  ```gitignore
  # Расшифрованные файлы helm-secrets
  *.dec
  *.yaml.dec
  *.yml.dec
  .dec/
  
  # Локальные ключи age
  *.agekey
  key.txt
  ```
- **Pre-commit хуки:** Используйте статические сканеры (например, `trufflehog`, `detect-secrets` или `gitleaks`) на этапе локального коммита для обнаружения незашифрованных значений полей паролей и токенов.

### 3. Регулярная ротация ключей шифрования (Key Rotation)

При компрометации закрытого ключа или плановой смене сотрудников выполняется смена получателей без расшифровки и повторного ручного ввода паролей:

```bash
# 1. Обновление открытых ключей в файле .sops.yaml (замена старого recipient на новый)
# 2. Выполнение команды перезашифровки всех файлов чарта
sops updatekeys ./charts/my-app/secrets-prod.yaml
# → The following changes were made to the recipients of the file:
# → - Added: age1newrecipientkey...
# → - Removed: age1oldcompromisedkey...
# → File was re-encrypted with the new keys.

# 3. Фиксация изменений в Git
git commit -am "chore(security): rotate SOPS encryption key for production"
```

### 4. Контроль доступа к релизам Helm (RBAC)

Для предотвращения извлечения секретов через утилиту `helm`:
- Ограничьте права разработчиков в производственных пространствах имен: запретите доступ к чтению ресурсов `secrets` с типом `helm.sh/release.v1`.
- Запретите запуск `helm get values --all` пользователям без роли `cluster-admin`.

---

## Дополнительная информация

### Сравнительный анализ подходов к секретам в Kubernetes (On-Premise)

| Критерий | `helm-secrets` + SOPS | Паттерн `existingSecret` | External Secrets Operator (ESO) | Bitnami Sealed Secrets |
| :--- | :--- | :--- | :--- | :--- |
| **Основной источник секрета** | Git (зашифрован SOPS) | Внешнее хранилище / K8s | Внешний Vault / OpenBao / HSM | Git (зашифрован kubeseal) |
| **Где происходит расшифровка** | Клиентский агент (CI/CD) | Вне зоны ответственности Helm | Контроллер ESO в кластере | Контроллер в кластере |
| **Секрет в истории Helm (`sh.helm.*`)** | **Присутствует** (если создан чартом) | **Отсутствует** | **Отсутствует** | **Присутствует** (как `SealedSecret`) |
| **Требует контроллеров в кластере** | Нет | Зависит от поставщика | Да (ESO CRD и оператор) | Да (контроллер Sealed Secrets) |
| **Автоматическая ротация данных** | Нет (только через повторный деплой) | Да (средствами внешнего сервиса) | Да (параметр `refreshInterval`) | Нет (только перезаписью в Git) |
| **Применимость в GitOps (Argo CD)** | Да (через CMP v2 plugin) | Идеально подходит | Идеально подходит | Да (нативно как манифест K8s) |

### Смотрите также

- [Основы Secret](secrets_basics.md) — базовые типы, назначение и архитектура объектов `Secret` в Kubernetes.
- [Создание Secret](creating_secrets.md) — декларативные и императивные методы генерации секретов.
- [Безопасность Secret](security.md) — шифрование данных в etcd на уровне узлов control plane.
- [Внешние системы управления секретами](external_managers.md) — интеграция Kubernetes с HashiCorp Vault, OpenBao и External Secrets Operator.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — управление асимметрично зашифрованными секретами в GitOps.
- [SOPS (Secrets OPerationS)](../../../Security/Tools/sops_overview.md) — архитектура утилиты SOPS, конвертное шифрование и форматы метаданных.
- [Плагины Helm](../../ToolsUtilities/Helm/helm_plugins.md) — расширение функциональности Helm-клиента и работа с `helm-diff`.
- [Helmfile](../../ToolsUtilities/Helm/helmfile_overview.md) — декларативное управление мульти-релизными инсталляциями Helm.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — сравнение моделей хранения и доставки конфиденциальных данных.
- [Argo CD: Custom Tooling (CMP v2)](../../../GitOps/ArgoCD/argocd_custom_tooling.md) — настройка sidecar-плагинов для расшифровки секретов на лету в Argo CD.
