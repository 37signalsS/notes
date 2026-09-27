# Helmwave: декларативный оркестратор для Helm

Helmwave — это современный декларативный инструмент на языке Go, предназначенный для управления множеством Helm-релизов в рамках концепции "Инфраструктура как код" (IaC). В отличие от классических решений, Helmwave предлагает полную шаблонизацию всей конфигурации, нативную поддержку параллельного развертывания через DAG и встроенные инструменты мониторинга состояния ресурсов в реальном времени (kubedog) и пост-деплойные проверки готовности (monitors).

Текущая актуальная версия — **0.44.4** (2026 год).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Helmwave** | Декларативный оркестратор Helm-релизов с полной поддержкой Go-шаблонизации конфигурационного файла и детерминированным планом развертывания. |
| **Plan (План)** | Детерминированный артефакт (директория `.helmwave/`), содержащий отрендеренные манифесты, загруженные чарты, значения и метаданные, готовые к применению. |
| **DAG (Directed Acyclic Graph)** | Направленный ациклический граф, автоматически выстраиваемый на основе зависимостей между релизами (`depends_on`). |
| **kubedog** | Встроенная библиотека для потокового отслеживания логов и событий Kubernetes в процессе развертывания. |
| **Monitors (Мониторы)** | Правила пост-деплойной проверки готовности релиза (Prometheus / HTTP) с автоматическим откатом при провале. |
| **Lifecycle Hooks** | Скрипты или команды (`pre_build`, `post_build`, `pre_up`, `post_up`, `pre_down`, `post_down`, `pre_rollback`, `post_rollback`), выполняемые на ключевых этапах жизненного цикла. |
| **Tags (Теги)** | Метки релизов, позволяющие изолированно собирать и применять подмножество релизов (`--tags`). |
| **Каталог плана (Plan Directory)** | Локальная директория плана (`.helmwave/` по умолчанию). Для командной работы план передаётся как артефакт CI/CD, а исходные файлы можно получить по `--remote-source` (go-getter: Git, HTTP, S3, GCP). |

---

## Базовые концепции

### Архитектура и принцип работы

Helmwave — это единый бинарник на Go, который работает как посредник между декларативным описанием желаемого состояния (`helmwave.yml` / `helmwave.yml.tpl`) и CLI Helm. В отличие от Helmfile, где шаблонизация ограничена `values`-файлами и блоками `templates`, Helmwave шаблонизирует **весь** конфигурационный файл, что позволяет генерировать список релизов динамически.

Жизненный цикл работы Helmwave состоит из четырёх фаз:

1.  **Рендеринг (`yml`)**: `helmwave.yml.tpl` → `helmwave.yml` через движок Go-шаблонов (Sprig или Gomplate). На этом этапе доступны переменные окружения, функции Sprig и чтение внешних файлов.
2.  **Сборка плана (`build`)**: загрузка чартов, рендеринг `values`, генерация манифестов для каждого релиза, построение DAG и вычисление diff. Результат — неизменяемый план в `.helmwave/`.
3.  **Применение (`up`)**: последовательное (с учётом DAG) или параллельное применение релизов из плана с отслеживанием готовности через kubedog и monitors.
4.  **Интроспекция/откат (`ls`, `status`, `rollback`, `down`)**: управление и диагностика уже развёрнутых релизов.

Принцип **детерминированности**: план собирается один раз и применяется многократно — это устраняет расхождения между сборкой и деплоем, характерные для «прямого» применения из `helmfile.yaml`.

### Полная шаблонизация конфигурации

Helmwave позволяет использовать Go templates непосредственно внутри `helmwave.yml.tpl`. Это радикально расширяет возможности по сравнению с Helmfile:
*   Динамическая генерация списка релизов на основе внешних YAML/JSON файлов (`readFile`, `fromYaml`).
*   Использование логики `if/else` и `range` для выбора репозиториев и параметров в зависимости от окружения.
*   Доступ к функциям Sprig и переменным окружения на этапе формирования конфига.
*   Поддержка двух движков шаблонизации: **Sprig** (по умолчанию) и **Gomplate** (`--templater gomplate`), а также per-values рендерер (`sprig`, `gomplate`, `copy`, `sops`).

### Управление зависимостями (DAG) и параллелизм

Поле `depends_on` позволяет указывать зависимости между релизами (включая зависимости между разными пространствами имен). Поддерживается два синтаксиса:

*   Короткий: `redis@infra` (универсальное имя `<release-name>@<namespace>`).
*   Объектный: `name`, `tag`, `optional` — позволяет добавить все релизы с заданным тегом или пометить зависимость как необязательную.

Helmwave:
1.  Строит граф зависимостей.
2.  Запускает независимые релизы параллельно (ограничение параллелизма — `--parallel-limit`).
3.  Гарантирует, что зависимый релиз начнёт развертывание только после того, как все его «родители» перейдут в состояние `Ready` (благодаря kubedog и monitors).
4.  Обнаруживает циклические зависимости и завершает сборку с ошибкой.

### Двухфазная модель развертывания

*   **Этап 1: Build (`helmwave build`)**: рендеринг шаблонов и создание неизменяемого плана. План содержит `manifest.yaml` для каждого релиза, что позволяет провести аудит изменений перед их внесением в кластер. По умолчанию вычисляется diff против живого кластера (`--diff-mode live`); для офлайн-сборки используйте `--diff-mode none` или `--diff-mode local` вместе с `offline_kube_version`.
*   **Этап 2: Up (`helmwave up`)**: применение плана. В GitOps-пайплайнах рекомендуется разделять эти шаги: `build` на этапе проверки PR, `up` на этапе слияния.

```mermaid
flowchart LR step0["step 0: helmwave.yml.tpl"] -- yml --> step1["step 1: helmwave.yml"] -- build --> step2["step 2: .helmwave/planfile"]
step2 --> up("up")
step2 --> down("down")
step2 --> ls("ls")
step2 --> s("status")
step2 --> r("rollback")
step2 --> g("graph")
step2 --> v("validate")
step2 --> diff("diff")
```

### Система мониторинга и проверок готовности

#### kubedog

kubedog — встроенный трекер ресурсов Kubernetes, отслеживающий в реальном времени статус Pod-ов, Deployment, StatefulSet, DaemonSet, Job и контейнерных логов. В отличие от `helm wait`, kubedog использует Kubernetes Watch API и выводит потоковые логи, что критично для отладки долгих rollouts в production.

```yaml
releases:
  - name: myapp
    namespace: apps
    chart: myrepo/myapp
    wait: watcher            # рекомендуемый режим (вместо true/false, изменено в v0.44.4)
    timeout: 10m
    wait_for_jobs: true
```

Флаги kubedog (глобально или на этапе `up`/`rollback`): `--kubedog`, `--kubedog-timeout`, `--kubedog-status-interval`, `--kubedog-log-width`, `--kubedog-track-all` (отслеживание почти всех ресурсов, экспериментально).

#### Monitors (пост-деплойные проверки)

Monitors — это правила пост-деплойной валидации, запускаемые после успешного развёртывания всех зависимых релизов. Каждый монитор итеративно опрашивает источник (Prometheus или HTTP-endpoint) и срабатывает, когда набирается порог успехов (`success_threshold`) или достигается порог провалов (`failure_threshold`) / общий таймаут (`total_timeout`).

Поддерживаемые типы:
*   **`prometheus`** — запрос к Prometheus; итерация считается успешной, если запрос возвращает ≥1 строку.
*   **`http`** — HTTP-запрос; успех, если код ответа входит в `expected_codes`.

При провале монитора выполняется действие `action` релиза: `""` (ничего), `rollback` или `uninstall`.

```yaml
monitors:
  - name: app-up-metric
    type: prometheus
    total_timeout: 10m
    iteration_timeout: 5s
    interval: 10s
    success_threshold: 3
    failure_threshold: 3
    prometheus:
      url: http://prometheus.monitoring.svc:9090
      expr: up{job="myapp"} == 1
releases:
  - name: myapp
    namespace: apps
    chart: myrepo/myapp
    monitors:
      - name: app-up-metric
      - action: rollback            # откатить релиз, если монитор провален
        ...
```

### Теги и селекторы релизов

Теги (`tags`) позволяют группировать релизы и изолированно собирать/применять подмножества инфраструктуры:

```yaml
releases:
  - name: redis
    tags: [infra, storage, critical]
    ...
  - name: api-server
    tags: [app, backend]
    ...
```

```bash
# Сборка и деплой только инфраструктурных релизов
helmwave build --tags infra && helmwave up
# Сборка по нескольким тегам (ИЛИ, если без --match-all-tags)
helmwave build -t app -t infra
# Требовать совпадение всех тегов (--match-all-tags / -tt)
helmwave build -t app -t backend --match-all-tags
```

### Жизненный цикл и хуки (Lifecycle)

Хуки бывают **глобальными** (корень `helmwave.yml`) и **локальными** (внутри `releases[].lifecycle`). Порядок выполнения:

```text
global pre_build → release pre_build → [build] → global post_build → global pre_up → release pre_up → up → release post_up → global post_up
global post_build → global pre_down → release pre_down → down → release post_down → global post_down
global post_build → global pre_rollback → release pre_rollback → rollback → release post_rollback → global post_rollback
```

Каждому хуку доступен словарь env: `${HELMWAVE_LIFECYCLE_TYPE}` (тип стадии) и `${HELMWAVE_LIFECYCLE_RELEASE_UNIQNAME}` (`release@namespace`, только для локальных хуков).

```yaml
lifecycle:
  pre_build:
    - cmd: "ls"
      args: ["-l", "-a"]
    - cmd: bash
      args:
        - -c
        - echo "global ${HELMWAVE_LIFECYCLE_TYPE}"
  post_up:
    - echo "глобальный post_up: инфраструктура готова"
releases:
  - name: api
    namespace: apps
    lifecycle:
      pre_up:
        - echo "проверка БД перед деплоем api"
      post_up:
        - ./scripts/register-service.sh "{{ .Release.Name }}"
```

### Нативная поддержка OCI

Helmwave полностью поддерживает установку чартов из OCI-реестров. Аутентификация выполняется через блок `registries[]` (host, username, password, insecure) или `helm registry login`. Для гарантии неизменности артефактов используйте дигесты (`@sha256:...`).

### Офлайн-сборка и air-gapped

Для изолированных сетей без доступа к Kubernetes ApiServer используется `offline_kube_version` в сочетании с `--diff-mode none`/`local`. Для получения исходников по расписанию или из закрытого хранилища применяется `--remote-source` (go-getter URL: Git, HTTP, S3, GCP).

---

## Установка

### Предварительные требования

*   **Kubernetes cluster**: v1.24+ (рекомендуется v1.29+ для полной поддержки SSA и kstatus).
*   **kubectl**: версия не старше minor, чем у кластера.
*   **kubeconfig**: права `create/update/delete` на целевые namespace.

### Linux / macOS (бинарник)

```bash
export VERSION=0.44.4
export ARCH=$(uname -m)   # amd64 / arm64
wget -c "https://github.com/helmwave/helmwave/releases/download/v${VERSION}/helmwave_${VERSION}_linux_${ARCH}.tar.gz" -O - | tar -xz
mv helmwave /usr/local/bin/
helmwave version
# → helmwave version 0.44.4
```

### Homebrew (macOS)

```bash
brew install helmwave/tap/helmwave
```

### Debian / RedHat / Alpine

```bash
export VERSION=0.44.4
export ARCH=$(uname -m)
# Debian/Ubuntu
wget -c "https://github.com/helmwave/helmwave/releases/download/v${VERSION}/helmwave_${VERSION}_linux_${ARCH}.deb" -O helmwave.deb
sudo apt install ./helmwave.deb
# RHEL/CentOS
wget -c "https://github.com/helmwave/helmwave/releases/download/v${VERSION}/helmwave_${VERSION}_linux_${ARCH}.rpm" -O helmwave.rpm
sudo yum localinstall ./helmwave.rpm
# Alpine
wget -c "https://github.com/helmwave/helmwave/releases/download/v${VERSION}/helmwave_${VERSION}_linux_${ARCH}.apk" -O helmwave.apk
apk add --allow-untrusted ./helmwave.apk
```

### Контейнер

```bash
# GitHub Container Registry (рекомендуется)
docker pull ghcr.io/helmwave/helmwave:0.44.4
# Docker Hub
docker pull diamon/helmwave:0.44.4
```

> **Примечание для Windows-пользователей:** нативный `helmwave.exe` имеет проблемы с TTY [#809](https://github.com/helmwave/helmwave/issues/809). Рекомендуется использовать WSL.

### Установка через менеджер бинарных файлов

```bash
bin install github.com/helmwave/helmwave
```

### Проверка конфигурации

```bash
helmwave version          # → helmwave version 0.44.4
helmwave completion bash  # автодополнение
source <(helmwave completion bash)   # добавить в ~/.bashrc
```

---

## Командный интерфейс и селекторы

| Команда | Описание |
|---------|----------|
| `helmwave yml` | Рендеринг `helmwave.yml.tpl` → `helmwave.yml`. |
| `helmwave build` | Сборка плана: загрузка чартов, рендеринг values, генерация манифестов, diff. По умолчанию diff против живого кластера (`--diff-mode live`). |
| `helmwave up` | Применение плана с отслеживанием готовности (kubedog/monitors). `--build` автоматически собирает план перед применением. |
| `helmwave down` | Удаление всех релизов из плана (`helm uninstall`). |
| `helmwave ls` | Список релизов из плана (NAME / NAMESPACE / REVISION / STATUS). |
| `helmwave status` | Детальный статус каждого релиза (revision, chart, last deployed). |
| `helmwave rollback --revision N` | Откат всех релизов плана к ревизии N (иначе — к последней). |
| `helmwave graph` | Визуализация DAG зависимостей в терминале (asciigraph). |
| `helmwave diff live` | Diff плана против живого кластера. |
| `helmwave diff plan` | Diff двух планов (локальных). |
| `helmwave validate` | Валидация плана (выполняется автоматически перед каждой командой). |
| `helmwave schema` | Генерация JSON Schema для `helmwave.yml` (автодополнение и валидация в IDE). |
| `helmwave completion [bash|zsh]` | Генерация скрипта автодополнения оболочки. |
| `helmwave version` | Печать версии. |

### Ключевые флаги

| Флаг | Описание | Применимо к |
|------|----------|-------------|
| `--tags, -t` | Сборка/применение только релизов с заданным тегом. | `build`, `up`, `ls`, ... |
| `--match-all-tags` / `-tt` | Требовать совпадения всех указанных тегов (И). | `build`, `up`, ... |
| `--diff-mode [live\|local\|none]` | Режим diff: против кластера / против локального плана / отключить. | `build`, `up` |
| `--plandir, -p` | Путь к каталогу плана (по умолчанию `.helmwave/`). | все |
| `--parallel-limit` | Ограничение количества параллельных операций. | `up`, `build` |
| `--remote-source` | go-getter URL для загрузки исходников сборки (Git/HTTP/S3/GCP). | `build`, `up`, ... |
| `--graph-width` | Формат графа: 1 — выкл., 0 — полные имена, N — обрезка. | `build`, `up`, `graph` |
| `--suppress` | Подавление kind'ов из вывода diff (напр. `Secret`). | `build`, `diff` |
| `--3-way-merge` | Использовать 3-way merge в diff. | `build`, `diff` |
| `--show-secret` | Показать Secret-значения в diff. | `build`, `diff` |
| `--skip-unchanged` | Пропускать неизменные релизы. | `build`, `up` |
| `--kubedog` | Включить трекер kubedog. | `up`, `rollback` |
| `--progress` | Выводить DEBUG-лог Helm. | `up` |

**Логирование:** `--log-level [debug\|info\|warn\|error\|trace]`, `--log-format [text\|json\|pad\|emoji]`, `--log-color`, `--log-timestamps`. Переменные окружения: `HELMWAVE_LOG_LEVEL`, `HELMWAVE_LOG_FORMAT`, `HELMWAVE_PARALLEL_LIMIT`, `HELMWAVE_PLANDIR`.

---

## Практические сценарии

### Комплексный пример helmwave.yml.tpl

Ниже — пример проекта `core-infrastructure` с динамической подстановкой окружения, тегами, зависимостями и хуками:

```yaml
version: 0.44.4
project: core-infrastructure

# Динамическая загрузка конфигурации окружения
{{ $env := env "ENVIRONMENT" | default "development" }}
{{ $config := readFile (printf "configs/%s.yaml" $env) | fromYaml }}

registries:
  - host: registry.example.com       # OCI registry
    username: {{ env "OCI_USER" }}
    password: {{ env "OCI_PASS" }}

repositories:
  - name: bitnami
    url: https://charts.bitnami.com/bitnami
  - name: my-oci-repo
    url: oci://registry.example.com/charts

releases:
  # Инфраструктурный слой (Redis)
  - name: redis
    namespace: infra
    tags: [infra, storage]
    chart:
      name: bitnami/redis
      version: 17.13.0
    create_namespace: true
    wait: watcher
    timeout: 10m
    values:
      - values/redis/common.yaml
      - values/redis/{{ $env }}.yaml

  # Слой приложений с зависимостью от Redis
  - name: api-server
    namespace: apps
    tags: [app, backend]
    chart:
      name: my-oci-repo/api-server
      version: 1.2.3
    depends_on:
      - redis@infra
    create_namespace: true
    wait: watcher
    timeout: 10m
    allow_failure: true              # приложение не должно блокировать infra
    lifecycle:
      pre_up:
        - echo "Checking DB connectivity for {{ $env }}..."
      post_up:
        - ./scripts/register-service.sh "{{ .Release.Name }}"
    values:
      - replicas: {{ $config.api.replicas }}
```

### Динамическая конфигурация по окружениям

В отличие от Helmfile, где окружения описываются блоком `environments:`, в Helmwave окружение выбирается через переменную и динамически подставляется в пути к values:

```bash
# configs/production.yaml содержит: api: { replicas: 5 }
ENVIRONMENT=production helmwave up --build
```

```yaml
# configs/production.yaml
api:
  replicas: 5
db:
  host: postgres.prod.local
```

Для каждого окружения можно иметь отдельный набор values, а переключение между ними выполняется одной переменной окружения.

### Теги и изолированное развертывание

```yaml
releases:
  - name: cert-manager
    namespace: cert-manager
    tags: [infra]
    chart:
      name: jetstack/cert-manager
      version: v1.14.3
  - name: grafana
    namespace: monitoring
    tags: [infra, monitoring]
    chart:
      name: grafana/grafana
  - name: webapp
    namespace: apps
    tags: [app]
    chart:
      name: myrepo/webapp
    depends_on:
      - cert-manager@cert-manager
```

Развёртывание только мониторинга:

```bash
helmwave build -t monitoring && helmwave up
```

### Шифрование секретов через SOPS

Helmwave умеет автоматически дешифровать значения, зашифрованные SOPS, на этапе сборки плана (renderer `sops`):

```yaml
releases:
  - name: api-server
    namespace: apps
    chart:
      name: myrepo/api-server
    values:
      - src: values/secrets.yaml
        renderer: sops       # дешифрование через sops (v0.32.0+)
      - values/api.yaml
```

```yaml
# values/secrets.yaml (зашифровано SOPS)
dbPassword: ENC[AES256_GCM,data:...,iv:...,tag:...,type:str]
sops:
  ...
```

Требования: `sops` установлен в PATH на хосте сборки; ключи (GPG/age/Vault/KMS) доступны в CI.

### Жизненный цикл и хуки

Подробный пример глобальных и локальных хуков со служебными переменными:

```yaml
version: 0.44.4
project: myapp

lifecycle:
  pre_build:
    - cmd: bash
      args:
        - -c
        - |
          echo "pre_build: готовим артефакты (${HELMWAVE_LIFECYCLE_TYPE})"
          ./scripts/fetch-artifacts.sh
  post_up:
    - echo "Вся инфраструктура развёрнута и проверена"

releases:
  - name: backend
    namespace: apps
    chart: bitnami/nats
    lifecycle:
      pre_up:
        - echo "pre_up для backend@${HELMWAVE_LIFECYCLE_RELEASE_UNIQNAME}"
      post_up:
        - ./scripts/register-service.sh backend
```

### Мониторинг готовности через monitors (Prometheus / HTTP)

```yaml
monitors:
  - name: app-health
    type: prometheus
    total_timeout: 10m
    iteration_timeout: 5s
    interval: 5s
    success_threshold: 3
    failure_threshold: 3
    prometheus:
      url: http://prometheus.operations.svc:9090
      expr: |
        sum(rate(http_requests_total{job="app",code=~"5.."}[1m])) == 0

releases:
  - name: app
    namespace: apps
    chart: myrepo/app
    monitors:
      - name: app-up-metric
        action: rollback          # при провале монитора — откатить релиз
```

HTTP-монитор:

```yaml
monitors:
  - name: app-liveness
    type: http
    total_timeout: 5m
    interval: 10s
    success_threshold: 2
    failure_threshold: 3
    http:
      url: https://app.example.com/healthz
      method: GET
      expected_codes: [200]
```

### Откат релизов (rollback)

```bash
# Просмотр истории ревизий
helmwave status
# Откат к конкретной ревизии
helmwave rollback --revision 3
# Откат с включением kubedog и автоматическим сбором при необходимости
helmwave rollback --build --kubedog
```

Для релизов в «зависшем» статусе (`pending-install`/`pending-upgrade`/`pending-rollback`) используйте `pending_release_strategy`:

```yaml
releases:
  - name: app
    namespace: apps
    chart: myrepo/app
    pending_release_strategy: rollback   # rollback | uninstall | "" (do nothing, default)
```

### Визуализация графа зависимостей

```bash
helmwave build --graph-width 0     # полные имена узлов
helmwave graph --build            # отрисовка DAG в терминале
```

Помимо ASCII-графа, Helmwave генерирует mermaid-диаграмму в `.helmwave/` для визуализации в Markdown-отчётах CI.

### Air-gapped / офлайн-развёртывание

В изолированной сети сборка выполняется на машине с доступом к кластеру, а для diff без кластера используется `offline_kube_version`:

```yaml
releases:
  - name: cert-manager
    chart:
      name: jetstack/cert-manager
      version: v1.14.3
    namespace: cert-manager
    offline_kube_version: "1.29.0"   # имитировать версию K8s для схемы
    create_namespace: true
```

```bash
# Офлайн-сборка плана без доступа к ApiServer
helmwave build --diff-mode none
# Перенос каталога .helmwave в закрытую сеть и применение
cp -r .helmwave /to/airgapped/
helmwave up
```

Для получения исходников из закрытого хранилища используется `--remote-source` (go-getter: `s3://`, `git::`, `https://`):

```bash
helmwave build --remote-source "s3://artifacts-bucket/infra-tpl.zip"
```

### Интеграция в CI/CD

Типичный pipeline (GitLab CI / GitHub Actions). Ключевая идея: `build` на этапе проверки, `up` — на этапе применения, а `.helmwave/` передаётся как артефакт.

```yaml
# .gitlab-ci.yml
variables:
  HELMWAVE_LOG_LEVEL: info

.helmwave: &helmwave
  image: ghcr.io/helmwave/helmwave:0.44.4
  entrypoint: [""]
  before_script:
    - '[[ -f "helmwave.yml.tpl" ]] && helmwave yml'

plan:
  stage: build
  extends: .helmwave
  artifacts:
    paths:
      - .helmwave
    expire_in: 1 week
  script:
    - helmwave build --diff-mode local

lint:
  stage: lint
  image: stackrox/kube-linter:0.2.5-alpine
  extends: .helmwave
  script:
    - kube-linter lint .helmwave

deploy:
  stage: deploy
  extends: .helmwave
  when: manual
  needs: ["plan"]
  script:
    - helmwave up --kubedog
```

GitHub Actions:

```yaml
- uses: actions/checkout@v4
- uses: helmwave/setup-action@v0.2.0
  with:
    version: '0.44.4'
- run: '[[ -f "helmwave.yml.tpl" ]] && helmwave yml'
- run: helmwave build
- run: helmwave up --kubedog
```

### Использование плана для командной работы

Для синхронизации планов между участниками команды или шагами CI/CD используйте артефакты пайплайна или блоб-хранилище. План (`--plandir`, по умолчанию `.helmwave/`) содержит все отрендеренные манифесты и загруженные чарты, так что `helmwave up` может выполняться без повторной сборки и без доступа к реестрам.

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|--------|---------|---------|
| `release "X" is in pending-upgrade` | Предыдущая операция не завершилась (конфликт ресурсов, таймаут). | Установите `pending_release_strategy: rollback`/`uninstall` для авто-восстановления; либо очистите secret релиза вручную (`kubectl get secret -n <ns> -l owner=helm,name=<release>`). |
| `another operation is in progress` | Параллельный `helmwave up` на одном релизе. | В CI добавьте mutex/блокировку по имени релиза; дождитесь завершения предыдущей операции. |
| `failed to get release from k8s: release: not found` при `build` | Diff (`--diff-mode live`) выполняется до первого деплоя. | Используйте `--diff-mode none`/`local` для первичной сборки; это warning, а не фатальная ошибка. |
| `circular dependency` / цикл в DAG | Зависимости образуют цикл. | Проверьте `depends_on`; визуализируйте через `helmwave graph`. |
| `monitor triggered failure threshold` | Пост-деплойный монитор не прошёл. | Проверьте выражение/endpoint; увеличьте `success_threshold` или `total_timeout`; `action: rollback` откатит релиз. |
| `kubedog` timeout / `resources are not ready` | Ресурсы не стали Ready за `timeout`. | Увеличьте `timeout`; проверьте `kubectl describe pod`/логи; используйте `--kubedog-track-all` для широкого отслеживания (экспериментально). |
| `chart ... not found` / ошибка загрузки чарта | Реестр недоступен или тег/дигест неверен. | Проверьте `registries[]`/`repositories[]`; используйте пиннинг по дигесту (`@sha256:...`). |
| `context deadline exceeded` при `--remote-source` | S3/HTTP/Git недоступен или токен просрочен. | Проверьте переменные окружения и сеть; используйте кэш (`--cache-dir`). |

---

## Дополнительная информация

### Интеграция с GitOps (Argo CD)

Helmwave используется как генератор манифестов внутри Argo CD через механизм **Config Management Plugins (CMP v2)**. Это обходит ограничения стандартного плагина Helm в Argo CD (например, отсутствие нативного DAG между релизами).

**Настройка Sidecar для Argo CD:**

```yaml
# sidecar в argocd-repo-server (Argo CD v2.4+)
- name: helmwave-plugin
  image: ghcr.io/helmwave/helmwave:0.44.4
  command: [/var/run/argocd/argocd-cmp-server]
  env:
    - name: HELMWAVE_LOG_LEVEL
      value: "info"
    - name: HELMWAVE_DIFF_MODE
      value: "none"
```

Важные нюансы интеграции:
*   **RBAC:** sidecar должен иметь права на чтение ресурсов в целевых namespace (Helmwave проверяет readiness через Kubernetes API и kubedog).
*   **kubeconfig:** убедитесь, что `KUBECONFIG` или `ServiceAccount` с нужными правами доступны в контексте sidecar.
*   **Версии:** образ Helmwave в CMP должен совпадать с версией, используемой локально, чтобы избежать расхождений в поведении.
*   **Сборка на этапе CMP:** Argo CD вызывает `helmwave build`, а затем helmwave передаёт манифесты в `argocd-cmp-server`. Для изолированных сред используйте `offline_kube_version` и `--diff-mode none`.

### Сравнение с Helmfile

| Особенность | Helmfile | Helmwave |
|-------------|----------|----------|
| **Архитектура** | Python (legacy) / Go | Нативно Go (высокая скорость) |
| **Шаблонизация** | Частичная (values, templates) | **Полная** (весь конфиг) |
| **Зависимости** | Линейные / `needs` | Полноценный **DAG** с `optional`/`tag` |
| **Мониторинг** | Внешние плагины | Встроено (**kubedog**) + **monitors** |
| **Планы (State)** | Отсутствуют | **Неизменяемые планы** (`.helmwave/`) |
| **Diff** | `helm-diff` plugin | Встроенный diff (`live`/`local`) |
| **Откат** | `helm rollback` per-release | `helmwave rollback` для всего плана |
| **Граф** | Нет | `helmwave graph` + mermaid |

Helmfile предпочтительнее для:
*   Сред с legacy-инфраструктурой (широкая поддержка Helm v3/v4).
*   Команд, где важнее зрелость экосистемы и документации, чем скорость выполнения.
*   Интеграций через Argo CD CMP, где Helmfile имеет более зрелые механизмы обработки секретов.

Helmwave предпочтительнее для:
*   Высоконагруженных пайплайнов, где время применения критично.
*   Сред, требующих полной аудируемости изменений (детерминированные планы).
*   Сложных графов зависимостей с параллельным развертыванием и пост-деплойными проверками.

### Полезные ссылки

*   [Обзор Helm](./helm_overview.md) — основы v4 и SSA.
*   [Helmfile](./helmfile_overview.md) — классический альтернативный оркестратор.
*   [Паттерны и устранение неисправностей Helm](./Advanced/patterns_troubleshooting.md) — диагностика типовых ошибок Helm.
*   [Безопасность Helm](./Advanced/security_best_practices.md) — управление секретами, подпись и RBAC.
*   [Мониторинг Helm-релизов](./helm_monitoring_observability.md) — Prometheus, Grafana и алертинг для Helm-релизов.
*   [Официальная документация Helmwave](https://helmwave.github.io/docs/0.44.x/) (англ.).
*   [Репозиторий Helmwave](https://github.com/helmwave/helmwave) — релизы и issues.

См. также:
*   [Argo CD: Custom Tooling](../../../GitOps/ArgoCD/argocd_custom_tooling.md) — детали интеграции через CMP.
