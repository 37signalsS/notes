# Renovate: автоматизация обновлений в GitOps-репозиториях

**Актуально для:** Renovate CLI v38.x – v39.x (образ `ghcr.io/renovatebot/renovate`), GitLab CE/EE 16.x–17.x, Gitea 1.22+, Harbor v2.10+, Kubernetes 1.28–1.32+

Renovate — инструмент декларативного управления зависимостями и автоматизации обновлений через Pull/Merge Request (PR/MR). В инфраструктурных и GitOps-репозиториях Renovate сканирует декларативные манифесты (Kubernetes YAML, Kustomize, Helm, Dockerfile, Compose, CI-пайплайны), отслеживает появление новых версий в реестрах артефактов и формирует атомарные коммиты с обновленными версиями и криптографическими дайджестами (digest pinning).

В отличие от кластерных контроллеров прямой записи, Renovate замыкает цикл через Git: изменение версий проходит стандартные гейты валидации (линтеры, валидацию схем, dry-run, проверки политик безопасности), фиксируется в истории версий и доставляется в кластер целевым GitOps-оператором (Argo CD или Flux).

## Определения

- **Renovate** — кроссплатформенный бот и CLI-раннер для поиска, сопоставления и автоматического обновления внешних зависимостей в исходном коде и инфраструктурных репозиториях.
- **Manager (Менеджер зависимостей)** — внутренний модуль Renovate, отвечающий за синтаксический разбор конкретного формата конфигураций (`kustomize`, `helmv3`, `dockerfile`, `docker-compose`, `gitlabci`, `ansible`, `regex`).
- **Datasource (Источник версий)** — провайдер метаданных версий (`docker`, `helm`, `git-tags`, `gitlab-releases`, `github-releases`), опрашивающий внешние или локальные реестры артефактов.
- **packageRule** — декларативное правило маршрутизации и фильтрации обновлений, задающее расписание, назначение ревьюеров, поведение automerge, группировку и фиксацию дайджестов по маскам путей, типов версий и имен пакетов.
- **Automerge** — автоматическое слияние PR/MR ботом при удовлетворении всех обязательных проверок качества (зеленые статус-чеки CI, прохождение approval-политик, соблюдение минимального возраста релиза).
- **Minimum Release Age (`minimumReleaseAge`)** — временной порог (кулдаун) перед созданием PR с момента публикации новой версии артефакта; выполняет функцию «supply-chain diode» для защиты от отравленных свежих релизов (zero-day malware).
- **Digest Pinning (`pinDigests`)** — замена или дополнение мутабельного тега неизменяемым SHA256-хешем (`image:tag@sha256:...`) для соблюдения абсолютной неизменяемости артефактов в GitOps.
- **Dependency Dashboard** — мастер-тикет (Issue) в репозитории, генерируемый Renovate для визуализации открытых, ожидающих, заблокированных по расписанию и rate-limit обновлений с возможностью ручного перезапуска через интерактивные чекбоксы.
- **Custom Manager (Regex Manager)** — механизм извлечения и сопоставления зависимостей с помощью регулярных выражений для нестандартных файлов конфигураций и параметров `values.yaml`.
- **Host Rules (`hostRules`)** — параметры аутентификации и сопоставления учетных данных (токены, пароли, заголовки) для конкретных сетевых узлов (Harbor, внутренний GitLab, Git-серверы).
- **Repository Cache (`repositoryCache`)** — механизм сохранения локальных метаданных клонов Git и результатов резолвинга пакетов между запусками (на диск или в Redis) для предотвращения rate-limit и ускорения работы.

## Предварительные требования

| Компонент | Требование | Проверка | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| **Раннер Renovate** | Docker/Podman хост либо кластер Kubernetes 1.28+ для запуска CronJob | `podman --version \|\| kubectl version --client` | Наличие контейнерного runtime или доступ к API кластера |
| **Git-сервер (On-Premises)** | GitLab CE/EE 16.x+, Gitea 1.22+ или Bitbucket Server с сервисным аккаунтом | `curl -sSf -H "PRIVATE-TOKEN: $BOT_TOKEN" https://gitlab.internal/api/v4/user \| jq .username` | `renovate-bot` |
| **Права доступа токена** | Токен с правами `api`, `read_repository`, `write_repository` | `git ls-remote https://oauth2:${BOT_TOKEN}@gitlab.internal/platform/fleet-infra.git` | Хеши веток репозитория |
| **Реестр артефактов** | Harbor v2.10+ с robot-аккаунтом для чтения тегов образов и OCI Helm-чартов | `skopeo login --username "robot$renovate" --password "$HARBOR_TOKEN" harbor.internal` | `Login Succeeded!` |
| **Корпоративный PKI CA** | Корневой сертификат удостоверяющего центра для инспекции внутреннего TLS | `openssl s_client -CAfile /etc/ssl/certs/corp-ca.crt -connect harbor.internal:443 </dev/null` | `Verify return code: 0 (ok)` |
| **CI-гейты валидации** | Пайплайн проверки PR: `kubeconform`, `conftest`, `kustomize build`, `helm lint` | Запуск CI-джобы валидации в тестовой ветке | `Exit code 0` |
| **GitOps-контроллер** | Argo CD v3.x или Flux v2.x, синхронизирующий кластер с веткой `main` | `argocd app list \|\| flux get kustomizations` | Список работающих приложений |

---

## Архитектура и базовые концепции

### Место Renovate в цикле GitOps

В контуре непрерывной доставки Renovate выполняет роль связующего звена между реестрами опубликованных артефактов и Git-репозиторием инфраструктуры:

```text
 ┌────────────────┐        ┌──────────────────┐
 │ CI сборки ПО   │───────►│ Harbor OCI Реестр│
 │ (новый digest) │        │ (образы, чарты)  │
 └────────────────┘        └────────┬─────────┘
                                    │ Опрос тегов/дайджестов
                                    ▼
 ┌────────────────────────────────────────────────────────┐
 │ Renovate Self-Hosted Runner (Kubernetes CronJob / CI)  │
 │  1. Анализ файлов манифестов (Kustomize/Helm/Compose)  │
 │  2. Сравнение версий с Harbor (datasource: docker/helm)│
 │  3. Применение политик (minimumReleaseAge, расписание) │
 └──────────────────────────┬─────────────────────────────┘
                            │ Push ветки + создание PR/MR
                            ▼
 ┌────────────────────────────────────────────────────────┐
 │ Git-сервер (GitLab / Gitea): Инфраструктурный репозиторий│
 │  ┌──────────────────────────────────────────────────┐  │
 │  │ Pull Request: bump image:tag@sha256              │  │
 │  └───────────────────────┬──────────────────────────┘  │
 └──────────────────────────┼─────────────────────────────┘
                            │ Триггер CI-гейтов в PR
                            ▼
 ┌────────────────────────────────────────────────────────┐
 │ CI-валидация: kubeconform → conftest → dry-run         │
 └──────────────────────────┬─────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
         [Зеленый CI]                [Красный CI]
              │                           │
              ▼                           ▼
      Automerge в main            PR заблокирован,
              │                   ожидает исправления
              ▼
 ┌────────────────────────────────────────────────────────┐
 │ GitOps-оператор (Argo CD / Flux) в кластере Kubernetes │
 │ Реконсиляция: выкатка проверенного артефакта           │
 └────────────────────────────────────────────────────────┘
```

Главное архитектурное преимущество перед контроллерами прямой модификации (Direct Cluster-to-Git Write-Back) — **наличие изолированной стадии проверки (PR Quality Gates)**. Если новый образ содержит несовместимую схему конфигурации или сломанный chart dependencies, CI-пайплайн в PR завершится ошибкой, и слияние в `main` не произойдет.

### Архитектура Self-Hosted раннера

В закрытых корпоративных контурах (On-Premises) запуск облачных приложений невозможен по требованиям безопасности. Раннер Renovate функционирует как периодическая задача (batch job), проходящая фиксированный жизненный цикл:

```text
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                      Фазы исполнения Renovate CLI                       │
 │                                                                         │
 │  1. Инициализация (Init & Auth)                                         │
 │     Чтение /etc/renovate/config.js, загрузка токенов, CA-сертификатов   │
 │     Проверка подключения к GitLab/Gitea и реестрам                     │
 │                                                                         │
 │  2. Обнаружение (Autodiscovery / Repo Selection)                        │
 │     Получение списка проектов по фильтру (RENOVATE_AUTODISCOVER_FILTER) │
 │                                                                         │
 │  3. Извлечение (Extract Phase)                                          │
 │     Клонирование репозитория в локальный кеш                            │
 │     Сканирование менеджерами: kustomize, helmv3, dockerfile, gitlabci   │
 │                                                                         │
 │  4. Резолвинг версий (Lookup Phase)                                     │
 │     Запросы метаданных к datasources (Harbor, OCI-реестры, git tags)    │
 │     Проверка кеша метаданных пакетов (Redis / локальный диск)           │
 │                                                                         │
 │  5. Оценка политик (Policy Evaluation)                                  │
 │     Фильтрация по packageRules, minimumReleaseAge, schedule, lockfile   │
 │                                                                         │
 │  6. Внесение изменений (Branch & Commit)                                │
 │     Создание Git-веток, модификация файлов, подписание коммита (GPG/SSH)│
 │                                                                         │
 │  7. Создание PR и Automerge (PR & Merge Phase)                          │
 │     Открытие/обновление MR/PR, обновление Dependency Dashboard          │
 │     Проверка статусов CI; если проверки пройдены — автомерж             │
 └─────────────────────────────────────────────────────────────────────────┘
```

### Сравнение инструментов автоматизации обновлений в On-Premises GitOps

| Инструмент | Архитектурный механизм | Область изменений | Наличие PR-гейтов | Совместимость с On-Premises | Когда выбирать |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Renovate CLI** | Внешний раннер (CronJob/CI) через REST API Git | Образы, Helm-чарты, Kustomize, CI-компоненты, Dockerfile | Да (через PR/MR) | Полная (любой Git-сервер и OCI-реестр) | Единый корпоративный стандарт для всех манифестов и зависимостей |
| **Argo CD Image Updater** | Kubernetes-контроллер внутри кластера | Только теги образов в параметрах Argo CD Application | Опционально (при Git write-back) | Полная (внутри K8s) | Динамические dev/preview-окружения с частым релизным циклом |
| **Flux Image Automation** | Нативные контроллеры Flux (`image-reflector`, `image-automation`) | Теги и дайджесты образов по маркерам в Git | Нет (прямой коммит в ветку) | Полная (во Flux-стеке) | Полностью автономный кластер под управлением Flux без внешних раннеров |
| **Kargo** | Kubernetes-контроллер цепочек промоушена | Продвижение наборов Freight (образы + чарты + git) | Да (через шаги верификации и PR) | Полная (CRD-driven) | Сложные многоступенчатые контуры (`dev` → `stage` → `prod`) с контролем релизов |
| **Dependabot (Core)** | CLI-скрипты / self-hosted dry-run | Языковые пакеты, Dockerfile, GitHub Actions | Да | Ограниченная (заточен под экосистему GitHub) | Проекты с фокусом исключительно на коде приложений внутри GitHub |

> [!IMPORTANT]
> **Принцип одного владельца строки:** Никогда не настраивайте два разных автоматизатора на изменение одного и того же файла или параметра (например, Renovate и Argo CD Image Updater на `values.yaml`). Это вызывает гонку коммитов, конфликты слияния и циклическую перезапись конфигурации.

### Ключевые параметры политики обновлений

| Параметр | Назначение | Рекомендация для On-Premises Production |
| :--- | :--- | :--- |
| `schedule` | Расписание создания и обновления PR | Вне пиковых часов нагрузки, например: `["after 10pm and before 5am every weekday"]` |
| `automerge` / `automergeType` | Автоматическое слияние (`pr` или `branch`) | Включать только для `patch`/`minor` в некритичных окружениях при наличии обязательных CI-проверок |
| `minimumReleaseAge` | Задержка перед созданием PR после релиза артефакта | `"3 days"` для продакшена (фильтр скомпрометированных сборок и быстрых отозванных релизов) |
| `pinDigests` | Фиксация криптографического sha256-дайджеста рядом с тегом | `true` для всех контейнерных образов в продакшене |
| `separateMajorMinorPatch` | Разделение типов обновлений на независимые PR | `true` — предотвращает маскировку major breaking changes внутри мелких патчей |
| `groupName` | Объединение связанных зависимостей в один PR | Группировать однотипные платформенные аддоны (Prometheus stack, Envoy) для снижения шума |
| `prHourlyLimit` / `prConcurrentLimit` | Лимиты на генерацию PR | `prHourlyLimit: 5`, `prConcurrentLimit: 10` — защита от rate-limit Git-сервера и перегрузки CI |
| `dependencyDashboard` | Генерация сводного Issue со статусом зависимостей | `true` — обеспечивает прозрачность для SRE-команды |
| `rebaseWhen` | Стратегия актуализации ветки PR | `"conflicted"` (обновлять только при конфликтах) либо `"behind-base-branch"` |

---

## Практические сценарии и конфигурация

### Сценарий 1: Базовая конфигурация инфраструктурного репозитория (`renovate.json`)

Файл помещается в корень репозитория или в `.gitlab/renovate.json` / `.github/renovate.json`. Конфигурация включает строгую схему валидации, семантические коммиты, часовой пояс инфраструктуры и фиксацию дайджестов:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended",
    ":semanticCommits",
    ":timezone(Europe/Moscow)"
  ],
  "dependencyDashboard": true,
  "dependencyDashboardTitle": "Renovate: Панель управления зависимостями",
  "labels": ["dependencies", "gitops"],
  "schedule": ["after 9am and before 4pm on tuesday"],
  "prHourlyLimit": 3,
  "prConcurrentLimit": 8,
  "rebaseWhen": "conflicted",
  "commitMessagePrefix": "chore(deps):",
  "docker": {
    "pinDigests": true
  },
  "packageRules": [
    {
      "description": "Автоматическая маркировка и изоляция major-релизов",
      "matchUpdateTypes": ["major"],
      "labels": ["breaking-change", "manual-audit"],
      "automerge": false,
      "minimumReleaseAge": "7 days"
    }
  ]
}
```

После применения конфигурации Renovate создаст инициализирующий коммит или Issue «Dependency Dashboard», отображающий обнаруженные манифесты.

---

### Сценарий 2: Сегрегация сред в монорепозитории (Digest Pinning в Prod, Automerge в Dev)

В типичном GitOps-монорепозитории с Kustomize директории разделены по контурам. Требуется разный уровень автоматизации:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "packageRules": [
    {
      "description": "PROD: обязательный digest pinning, строгий карантин релизов, только ручной мерж",
      "matchFileNames": ["apps/**/overlays/prod/**", "clusters/prod/**"],
      "pinDigests": true,
      "automerge": false,
      "minimumReleaseAge": "3 days",
      "reviewers": ["platform-lead", "sre-duty"],
      "labels": ["target:production", "risk:high"]
    },
    {
      "description": "STAGE: digest pinning, кулдаун 24 часа, автомерж патчей",
      "matchFileNames": ["apps/**/overlays/stage/**", "clusters/stage/**"],
      "pinDigests": true,
      "matchUpdateTypes": ["patch"],
      "automerge": true,
      "automergeType": "pr",
      "minimumReleaseAge": "1 day",
      "labels": ["target:staging"]
    },
    {
      "description": "DEV: автомерж patch и minor обновлений после зеленых CI-гейтов",
      "matchFileNames": ["apps/**/overlays/dev/**", "clusters/dev/**"],
      "pinDigests": false,
      "matchUpdateTypes": ["patch", "minor"],
      "automerge": true,
      "automergeType": "pr",
      "minimumReleaseAge": "2 hours",
      "labels": ["target:development", "automerge"]
    },
    {
      "description": "Группировка платформенных утилит мониторинга в единый PR",
      "matchPackageNames": ["prom/prometheus", "prom/alertmanager", "grafana/grafana"],
      "groupName": "observability-stack"
    }
  ]
}
```

---

### Сценарий 3: Развертывание Self-Hosted Renovate в Kubernetes как CronJob

Для периодического запуска внутри On-Premises кластера создается изолированный `CronJob` с монтированием корпоративного корневого сертификата, постоянного диска для кеша (PVC) и секретов аутентификации.

#### 1. Секрет и конфигурационный файл (`renovate-config`)

```yaml
# configmap.yaml — глобальная конфигурация раннера
apiVersion: v1
kind: ConfigMap
metadata:
  name: renovate-config
  namespace: platform-automation
data:
  config.js: |
    module = module || {};
    module.exports = {
      platform: 'gitlab',
      endpoint: 'https://gitlab.internal/api/v4',
      gitAuthor: 'Renovate Bot <renovate-bot@corp.internal>',
      onboarding: false,
      requireConfig: 'required',
      optimizeForDisabled: true,
      repositoryCache: 'enabled',
      persistRepoData: true,
      binarySource: 'install',
      executionMode: 'container',
      autodiscover: true,
      autodiscoverFilter: ['platform/*', 'gitops/*'],
      prHourlyLimit: 10,
      prConcurrentLimit: 20
    };
```

```yaml
# secret.yaml — токены доступа и приватный ключ подписи коммитов
apiVersion: v1
kind: Secret
metadata:
  name: renovate-secrets
  namespace: platform-automation
type: Opaque
stringData:
  RENOVATE_TOKEN: "glpat-xxxxxxxxxxxxxxxxxxxx"
  GITHUB_COM_TOKEN: "ghp_xxxxxxxxxxxxxxxxxxxx" # Для преодоления rate-limit при получении changelog с github.com
```

#### 2. Манифест CronJob с hardening-настройками

```yaml
# cronjob.yaml — периодический запуск раз в час
apiVersion: batch/v1
kind: CronJob
metadata:
  name: renovate-runner
  namespace: platform-automation
spec:
  schedule: "15 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  jobTemplate:
    spec:
      backoffLimit: 1
      template:
        metadata:
          labels:
            app.kubernetes.io/name: renovate
        spec:
          restartPolicy: Never
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            runAsGroup: 1000
            fsGroup: 1000
            seccompProfile:
              type: RuntimeDefault
          volumes:
            - name: config-volume
              configMap:
                name: renovate-config
            - name: cache-volume
              persistentVolumeClaim:
                claimName: renovate-cache-pvc
            - name: corp-ca-volume
              configMap:
                name: corp-root-ca
            - name: tmp-volume
              emptyDir: {}
          containers:
            - name: renovate
              image: ghcr.io/renovatebot/renovate:39.195.0
              imagePullPolicy: IfNotPresent
              args: []
              env:
                - name: RENOVATE_CONFIG_FILE
                  value: "/opt/renovate/config.js"
                - name: RENOVATE_CACHE_DIR
                  value: "/tmp/renovate/cache"
                - name: NODE_EXTRA_CA_CERTS
                  value: "/etc/ssl/certs/corp-ca.crt"
                - name: SSL_CERT_FILE
                  value: "/etc/ssl/certs/corp-ca.crt"
                - name: LOG_LEVEL
                  value: "info"
                - name: RENOVATE_TOKEN
                  valueFrom:
                    secretKeyRef:
                      name: renovate-secrets
                      key: RENOVATE_TOKEN
                - name: GITHUB_COM_TOKEN
                  valueFrom:
                    secretKeyRef:
                      name: renovate-secrets
                      key: GITHUB_COM_TOKEN
              resources:
                requests:
                  cpu: "500m"
                  memory: "1Gi"
                limits:
                  cpu: "2000m"
                  memory: "4Gi"
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities:
                  drop:
                    - ALL
              volumeMounts:
                - name: config-volume
                  mountPath: /opt/renovate/config.js
                  subPath: config.js
                  readOnly: true
                - name: cache-volume
                  mountPath: /tmp/renovate/cache
                - name: corp-ca-volume
                  mountPath: /etc/ssl/certs/corp-ca.crt
                  subPath: ca.crt
                  readOnly: true
                - name: tmp-volume
                  mountPath: /tmp
```

---

### Сценарий 4: Запуск через Scheduled Pipeline в GitLab CI (Self-Managed)

Если инфраструктура запускается на базе GitLab CI Runner, Renovate запускается по расписанию через отдельный сервисный проект `ops/renovate-runner`:

```yaml
# .gitlab-ci.yml
stages:
  - maintenance

renovate:
  stage: maintenance
  image: ghcr.io/renovatebot/renovate:39.195.0
  variables:
    RENOVATE_PLATFORM: gitlab
    RENOVATE_ENDPOINT: "${CI_SERVER_URL}/api/v4"
    RENOVATE_TOKEN: "${RENOVATE_BOT_TOKEN}"           # Masked & Protected Variable
    RENOVATE_AUTODISCOVER: "true"
    RENOVATE_AUTODISCOVER_FILTER: "platform/*"
    RENOVATE_BASE_DIR: "${CI_PROJECT_DIR}/cache"
    RENOVATE_CACHE_DIR: "${CI_PROJECT_DIR}/cache/renovate"
    RENOVATE_REPOSITORY_CACHE: "enabled"
    NODE_EXTRA_CA_CERTS: "/etc/gitlab-runner/certs/corp-ca.crt"
    LOG_LEVEL: "info"
  cache:
    key: "${CI_JOB_NAME}"
    paths:
      - cache/renovate/
  before_script:
    - mkdir -p cache/renovate
  script:
    - renovate
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
    - if: '$CI_PIPELINE_SOURCE == "web"'
```

---

### Сценарий 5: Запуск через Systemd Timer + Podman на выделенной Linux-ВМ

Для системных администраторов, управляющих инфраструктурным хостом без Kubernetes:

#### 1. Конфигурация окружения `/etc/renovate/renovate.env`

```ini
RENOVATE_PLATFORM=gitea
RENOVATE_ENDPOINT=https://gitea.corp.internal/api/v1
RENOVATE_TOKEN=99887766554433221100aabbccddeeff12345678
RENOVATE_AUTODISCOVER=false
RENOVATE_REPOSITORIES=infrastructure/fleet-gitops,infrastructure/k8s-apps
RENOVATE_GIT_AUTHOR=Renovate Bot <bot@corp.internal>
RENOVATE_CACHE_DIR=/var/cache/renovate
RENOVATE_REPOSITORY_CACHE=enabled
NODE_EXTRA_CA_CERTS=/etc/ssl/certs/corp-ca.crt
LOG_LEVEL=info
```

#### 2. Юнит сервиса `/etc/systemd/system/renovate.service`

```ini
[Unit]
Description=Renovate Bot Self-Hosted Runner
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=renovate
Group=renovate
EnvironmentFile=/etc/renovate/renovate.env
ExecStart=/usr/bin/podman run --rm \
    --name renovate-run \
    --env-file /etc/renovate/renovate.env \
    -v /var/cache/renovate:/var/cache/renovate:Z \
    -v /etc/ssl/certs/corp-ca.crt:/etc/ssl/certs/corp-ca.crt:ro,Z \
    ghcr.io/renovatebot/renovate:39.195.0
StandardOutput=journal
StandardError=journal
TimeoutSec=1800

[Install]
WantedBy=multi-user.target
```

#### 3. Юнит таймера `/etc/systemd/system/renovate.timer`

```ini
[Unit]
Description=Hourly Renovate Execution Timer

[Timer]
OnCalendar=*-*-* 02..23:15:00
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
```

Активация таймера в ОС:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now renovate.timer
systemctl list-timers renovate.timer
# → NEXT                         LEFT     LAST PASSED UNIT           ACTIVATES
# → Tue 2026-10-13 17:15:00 MSK  24min    -    -      renovate.timer renovate.service
```

---

### Сценарий 6: Обновление Helm-чартов и OCI-артефактов из корпоративного Harbor

При зеркалировании внешних репозиториев (Bitnami, ingress-nginx) в корпоративный Harbor Renovate настраивается через `hostRules`:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "hostRules": [
    {
      "matchHost": "harbor.internal",
      "hostType": "docker",
      "username": "robot$renovate-reader",
      "password": "{{ secrets.HARBOR_ROBOT_SECRET }}"
    }
  ],
  "packageRules": [
    {
      "description": "Обновление Helm v3 зависимостей в Chart.yaml",
      "matchManagers": ["helmv3"],
      "registryUrls": ["oci://harbor.internal/charts"],
      "pinDigests": false
    }
  ],
  "helmv3": {
    "fileMatch": ["(^|/)Chart\\.yaml$"]
  }
}
```

Манифест `Chart.yaml`:

```yaml
apiVersion: v2
name: payment-gateway
version: 1.4.0
dependencies:
  - name: postgresql
    version: 15.5.3          # ← Renovate предложит обновление до 15.5.4
    repository: oci://harbor.internal/charts/bitnami
  - name: redis
    version: 19.6.1          # ← Renovate обновляет только тег чарта
    repository: oci://harbor.internal/charts/bitnami
```

---

### Сценарий 7: Нестандартные форматы через Custom Manager (Regex)

Когда версии образов хранятся в кастомных структурах `values.yaml`, параметрах Terraform или Ansible playbook, штатные парсеры могут их пропустить. Используется `customManagers` с синтаксисом регулярных выражений:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "customManagers": [
    {
      "customType": "regex",
      "description": "Поиск образов в кастомных блоках values.yaml",
      "fileMatch": ["(^|/)apps/.+/values\\.yaml$"],
      "matchStrings": [
        "#\\s*renovate:\\s*datasource=(?<datasource>\\S+)\\s+depName=(?<depName>\\S+)\\s+versioning=(?<versioning>\\S+)\\n\\s*imageTag:\\s*\"?(?<currentValue>[^\"\\s]+)\"?",
        "repository:\\s*\"?(?<depName>[^\"\\s]+)\"?\\n\\s*tag:\\s*\"?(?<currentValue>[^\"\\s]+)\"?"
      ],
      "datasourceTemplate": "{{#if datasource}}{{datasource}}{{else}}docker{{/if}}",
      "versioningTemplate": "{{#if versioning}}{{versioning}}{{else}}semver{{/if}}"
    }
  ]
}
```

Пример аннотированного `values.yaml`:

```yaml
backendService:
  # renovate: datasource=docker depName=harbor.internal/apps/backend versioning=semver
  imageTag: "v2.14.1"

database:
  repository: "harbor.internal/docker-hub/postgres"
  tag: "16.4-alpine"
```

---

### Сценарий 8: Подписание коммитов бота (GPG Commit Signing)

В защищенных GitOps-репозиториях включено правило `Reject unsigned commits` (требование подписанных коммитов). Для этого в окружение Renovate передается ASCII-armored приватный ключ:

В конфигурационном файле `config.js` или переменных окружения:

```javascript
module.exports = {
  gitPrivateKey: process.env.RENOVATE_GIT_PRIVATE_KEY,
  gitAuthor: 'Renovate Bot <bot-gpg@corp.internal>',
};
```

Экспорт переменной в пайплайне или CronJob:

```bash
export RENOVATE_GIT_PRIVATE_KEY="$(cat /etc/renovate/bot_gpg_key.asc)"
```

Коммиты бота будут иметь статус `Verified` в интерфейсе GitLab/Gitea.

---

## Операции и команды

### Валидация синтаксиса конфигурации

Перед коммитом `renovate.json` проверяется утилитой `renovate-config-validator`:

```bash
# Проверка локального файла конфигурации через контейнер
podman run --rm -v "$(pwd):/usr/src/app:Z" -w /usr/src/app \
    ghcr.io/renovatebot/renovate:39.195.0 renovate-config-validator
# → INFO: Validating renovate.json
# → OK: renovate.json is valid
```

```bash
# Проверка с детализацией включенных пресетов
podman run --rm -v "$(pwd):/usr/src/app:Z" -w /usr/src/app \
    ghcr.io/renovatebot/renovate:39.195.0 renovate-config-validator --strict
# → INFO: Validating renovate.json
# → INFO: Configuration check passed with 0 warnings
```

---

### Режимы симуляции и отладки (Dry-Run)

Флаг `--dry-run` позволяет проверить решения бота без создания веток и Pull Request в Git:

| Режим `--dry-run` | Что выполняется | Для чего используется |
| :--- | :--- | :--- |
| `extract` | Только синтаксический разбор файлов манифестов | Быстрая проверка, находит ли менеджер нужные зависимости |
| `lookup` | Разбор файлов + опрос реестров артефактов (lookup версий) | Проверка доступности Harbor и версионирования пакетов |
| `full` | Полный цикл: поиск, lookup, генерация тела PR, проверка automerge | Полный аудит перед боевым включением (без записи в Git) |

Команда тестового прогона для конкретного репозитория:

```bash
podman run --rm -it \
    -e RENOVATE_PLATFORM=gitlab \
    -e RENOVATE_ENDPOINT=https://gitlab.internal/api/v4 \
    -e RENOVATE_TOKEN="$BOT_TOKEN" \
    -e LOG_LEVEL=debug \
    ghcr.io/renovatebot/renovate:39.195.0 \
    renovate --dry-run=full --schedule="" platform/fleet-infra
# → DEBUG: Package releases retrieved (package=prom/prometheus, releases=45)
# → INFO: Dry run: PR would be created (branch=renovate/prom-prometheus-3.x, title=Update prom/prometheus to v3.2.1)
# → INFO: Repository summary: 1 to create, 0 to update, 0 to close
```

Принудительный запуск в обход установленного расписания (`schedule`):

```bash
renovate --schedule="" platform/fleet-infra
# → INFO: Forcing schedule execution for repo: platform/fleet-infra
```

---

### Справочник переменных окружения раннера

| Переменная | Тип | Описание | Значение по умолчанию |
| :--- | :--- | :--- | :--- |
| `RENOVATE_PLATFORM` | String | Тип Git-хостинга: `gitlab`, `gitea`, `bitbucket-server` | `github` |
| `RENOVATE_ENDPOINT` | URL | URL API сервера Git (например, `https://gitlab.internal/api/v4`) | Зависит от платформы |
| `RENOVATE_TOKEN` | String | Персональный токен или Project Access Token бота | — (обязательный) |
| `RENOVATE_AUTODISCOVER` | Boolean | Автоматический поиск всех доступных проектов | `false` |
| `RENOVATE_AUTODISCOVER_FILTER` | String/List | Маска выбора проектов (например, `infra/*`, `platform/*`) | `*` |
| `RENOVATE_DRY_RUN` | String | Режим симуляции: `extract`, `lookup`, `full` | `null` (боевой режим) |
| `RENOVATE_CACHE_DIR` | Path | Каталог для локального файлового кеша | `/tmp/renovate/cache` |
| `RENOVATE_REDIS_URL` | URL | Подключение к Redis для распределенного кеша (`redis://host:6379/0`) | `null` |
| `RENOVATE_REPOSITORY_CACHE` | String | Использование кеша репозитория: `enabled`, `disabled`, `reset` | `disabled` |
| `RENOVATE_GIT_AUTHOR` | String | Автор коммитов (`Имя <email>`) | `Renovate Bot <bot@renovateapp.com>` |
| `RENOVATE_GIT_PRIVATE_KEY` | String | Приватный PGP/SSH ключ для подписания коммитов | `null` |
| `NODE_EXTRA_CA_CERTS` | Path | Путь к бандлу корпоративных корневых сертификатов для Node.js | `null` |
| `SSL_CERT_FILE` | Path | Путь к CA для встроенных подпроцессов Git и OpenSSL | `null` |
| `LOG_LEVEL` | String | Уровень детализации логов: `trace`, `debug`, `info`, `warn`, `error` | `info` |

---

### Обслуживание и очистка кеша

При сбоях в Git-дереве или повреждении локальной базы версий кеш сбрасывается:

```bash
# Сброс файлового кеша на хосте раннера
rm -rf /var/cache/renovate/*
# → Очистка завершена

# Принудительный сброс кеша для одного запуска через CLI
renovate --repository-cache=reset platform/fleet-infra
# → INFO: Repository cache reset requested: clearing local cache for platform/fleet-infra
```

При использовании Redis:

```bash
# Инспекция и удаление ключей кеша Renovate в Redis
redis-cli -h redis.internal -p 6379 KEYS "renovate:*" | xargs redis-cli -h redis.internal DEL
# → (integer) 142
```

---

## Диагностика и устранение неполадок

| Симптом / Ошибка | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `UNABLE_TO_VERIFY_LEAF_SIGNATURE` или `CERT_HAS_EXPIRED` | Node.js не доверяет внутреннему CA корпоративного GitLab или Harbor | В логах: `request to https://harbor.internal failed, reason: unable to verify leaf signature` | Смонтировать корневой CA и задать `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/corp-ca.crt` и `SSL_CERT_FILE=/etc/ssl/certs/corp-ca.crt` |
| `401 Unauthorized` / `403 Forbidden` при обращении к API | Истек срок действия токена, либо токену не хватает прав | Запрос `curl -H "PRIVATE-TOKEN: $RENOVATE_TOKEN" https://gitlab.internal/api/v4/user` возвращает 401 | Перевыпустить PAT бота с областями `api`, `read_repository`, `write_repository` |
| `Push rejected: Commits must be signed` | В репозитории включено обязательное требование подписанных коммитов | В логах: `remote: GitLab: Commit must be signed with GPG` | Настроить `gitPrivateKey` в `config.js` и импортировать открытый ключ в профиль бота |
| `HTTP 429 Too Many Requests` к реестрам | Превышение лимитов запросов к внешним реестрам или GitLab | Логи показывают частые запросы к `registry-1.docker.io` или GitLab API | 1. Настроить локальное зеркалирование в Harbor.<br>2. Включить `RENOVATE_REPOSITORY_CACHE=enabled`.<br>3. Указать `GITHUB_COM_TOKEN` для получения релиз-ноутов. |
| Automerge не срабатывает, PR остается открытым | Названия required status-checks в branch protection не совпадают с фактическими job'ами | В логах: `automerge: false (pr has failing/pending checks)` | Сверить имена проверок в GitLab Protected Branches / GitHub Branch Protection с контекстами CI |
| Конфликты коммитов («MR wars») | Два инструмента (Renovate и Argo CD Image Updater) пишут в один файл | В Git-истории чередуются коммиты бота Renovate и коммиты оператора | Разделить зоны ответственности: кластерный Image Updater правит `dev`-оверлеи, Renovate — базовые чарты и `prod` |
| Падение раннера с ошибкой `OOMKilled` (Exit code 137) | Всплеск потребления памяти при сборке AST и клонировании монорепозиториев | `kubectl describe pod renovate-runner-...` показывает `Last State: Terminated, Reason: OOMKilled` | 1. Увеличить `limits.memory` до 4–6 GiB.<br>2. Установить `prConcurrentLimit: 5`.<br>3. Задать `RENOVATE_PERSIST_REPO_DATA=false`. |
| Regex Manager выдает `ReDoS potential issue` | Избыточный backtracking в регулярном выражении `matchStrings` | В логах: `WARN: Regex manager pattern matches too many lines or causes catastrophic backtracking` | Упростить регулярное выражение, исключить жадные операторы `.*`, использовать конкретные классы `[^"\\s]+` |
| Renovate создает PR с несовместимой версией | Неверно определена схема версионирования (например, helm вместо semver) | В PR предлагается переход с `1.10.0` на `01.10.0` или нестандартный тег | Явно указать `versioning: "semver"` или `versioning: "docker"` в `packageRules` |

---

## Рекомендации и Best Practices

### Безопасность цепочки поставок (Supply Chain Security)

1. **Supply-Chain Diode (`minimumReleaseAge`):** Всегда устанавливайте задержку в 3–7 дней для продуктовых сред:
   ```json
   "minimumReleaseAge": "3 days"
   ```
   Большинство вредоносных пакетов и отравленных тегов выявляются сообществом и отзываются в первые 48–72 часа после публикации.
2. **Digest Pinning:** Для контейнерных образов используйте исключительно фиксацию дайджеста (`pinDigests: true`). Тег `v1.2.3` может быть перезаписан в реестре без ведома инженера, в то время как `sha256:4b22...` математически гарантирует неизменяемость содержимого контейнера.
3. **Принцип наименьших привилегий для токена:** Не используйте учетные записи администраторов GitLab/Gitea. Создавайте отдельного сервисного пользователя `renovate-bot` и добавляйте его только в те группы и проекты, где требуется автоматизация, с ролью `Developer` (или `Maintainer`, если требуется слияние в защищенные ветки).
4. **Контроль выполнения бинарников (`executionMode: container`):** Никогда не запускайте Renovate с `trustLevel: high` на недоверенных репозиториях. Сторонний код в `package.json` или `Makefile` не должен исполнять произвольные команды на хосте раннера.

### SRE и операционная стабильность

1. **Шумоподавление и батчинг:**
   - Ограничивайте параллелизм: `prHourlyLimit: 5`, `prConcurrentLimit: 10`.
   - Группируйте обновления второстепенных библиотек (`groupName: "minor-patches"`).
   - Задавайте технологические окна: PR создаются в рабочее время дежурной смены, чтобы алерты CI не срабатывали ночью.
2. **Обязательные гейты в PR перед Automerge:**
   - Никакой automerge не должен происходить без предварительной валидации манифестов. Минимальный набор проверок в CI-пайплайне GitOps:
     - `kubeconform -strict -schema-location default`
     - `kustomize build apps/... > /dev/null`
     - `helm lint charts/...`
     - `conftest test` (проверка политик Open Policy Agent / Gatekeeper)
3. **Мониторинг исполнения раннера:**
   - Настройте оповещения Alertmanager на статус завершения `CronJob` в Kubernetes:
   ```yaml
   - alert: RenovateRunnerFailed
     expr: kube_job_status_failed{job_name=~"renovate-runner.*"} > 0
     for: 15m
     labels:
       severity: warning
     annotations:
       summary: "Сбой периодического выполнения Renovate runner"
       description: "Под Renovate завершился с ошибкой. Проверьте логи пода на наличие проблем с токенами или сетевым доступом."
   ```

---

## Дополнительная информация

### Связанные материалы

- [Обзор архитектуры GitOps](../GitOps_overview.md) — декларативное управление инфраструктурой и стратегии продвижения версий.
- [Пример полного GitOps-пайплайна](../gitops_pipeline_example.md) — построение CI/CD гейтов качества, обеспечивающих безопасность automerge.
- [Управление жизненным циклом и хранением образов](./containerization_and_image_storage.md) — организация Harbor OCI, неизменяемые артефакты и digest pinning.
- [Kargo: promotion-пайплайны](./kargo_promotion_pipelines.md) — многоступенчатое продвижение проверенных наборов версий между контурами.
- [Argo CD Image Updater](../ArgoCD/argocd_image_updater.md) — кластерный контроллер обновления тегов для сред разработки.
- [Flux: Image Automation](../flux.md) — встроенные механизмы автоматизации образов во Flux-стеке.
- [Автоматизация Git в Kustomize](../../Kubernetes/ToolsUtilities/kustomize/kustomize_git_automation.md) — особенности работы Renovate и Kustomize edit.
- [Безопасность цепочки поставок контейнеров](../../Security/Supply_Chain_Security/container_image_supply_chain.md) — защита от атак на зависимости и вредоносных тегов.
- [DORA-метрики в GitOps](./dora_metrics_gitops.md) — учет влияния коммитов ботов автоматизации на частоту развертываний и стабильность.

---

## Вопросы для собеседования

### 1. В чем ключевое отличие Renovate от специализированных инструментов обновления образов, таких как Argo CD Image Updater или Flux Image Automation?
**Ответ:** Argo CD Image Updater и Flux Image Automation работают как контроллеры внутри кластера и ориентированы исключительно на отслеживание реестров контейнеров. Их функционал ограничен правкой тега образа в YAML. **Renovate** — это полноценная платформа управления зависимостями уровня всего репозитория. Он анализирует не только Docker-образы, но и зависимости Helm-чартов (`Chart.yaml`), оверлеи Kustomize, базовые манифесты, Ansible-роли и GitHub/GitLab Actions. Кроме того, Renovate предоставляет глубокую систему группировки PR, учет графиков расписания (Schedules), автоматический мердж (Automerge) при успешном CI и валидацию Changelog.

### 2. Как защитить GitOps-репозиторий и кластер от «шторма PR» (PR Storm), когда выходит обновление базовых библиотек или популярных чартов?
**Ответ:** По умолчанию бот может создать 30–50 отдельных PR, что парализует работу ревьюеров и перегрузит CI-раннеры. Для защиты настраиваются:
1. **Троттлинг:** параметры `prConcurrentLimit: 5` (не более 5 одновременно открытых PR) и `prHourlyLimit: 2` (ограничение скорости открытия новых PR в час).
2. **Батчинг (Группировка):** правило `packageRules` с директивой `groupName: "all non-major dependencies"` объединяет все минорные и патч-обновления в один единый PR.
3. **Расписания (Schedules):** директива `schedule: ["before 6am on monday"]` смещает создание PR на нерабочие часы, чтобы обновления не мешали ежедневным деплоям фичей.

### 3. Какие риски безопасности несет включение автоматического слияния (Automerge) в GitOps и как их митигировать?
**Ответ:** Главный риск — атака на цепочку поставок (Supply Chain Attack) через компрометацию публичного пакета или тега образа (typosquatting, публикация вредоносного патча в зависимости). Если включен слепой automerge, уязвимый или вредоносный код автоматически попадет в production-кластер.
**Митигации:**
- Запретить automerge для мажорных обновлений (`matchUpdateTypes: ["major"]` $\to$ `automerge: false`).
- Обязательные CI-гейты: запуск сканеров уязвимостей (`trivy image`, `grype`) и проверка криптографической подписи Cosign в пайплайне перед мерджем.
- Использование опции `minimumReleaseAge: "3 days"` (Renovate ждет 3 дня после выхода нового релиза перед созданием PR, давая сообществу время обнаружить отозванные или скомпрометированные релизы).

### 4. Почему в корпоративном GitOps для Renovate обязательно требовать Digest Pinning?
**Ответ:** Теги в контейнерных реестрах мутабельны: разработчик может перезалить образ с тем же тегом (например, `v1.2.3`), изменив бинарный состав. Если манифест ссылается только на тег, контроллер GitOps не зафиксирует изменение в Git, и аудит будет нарушен. Renovate при помощи опции `pinDigests: true` преобразует ссылки вида `image:tag` в строгую пару `image:tag@sha256:...`. Это гарантирует абсолютную воспроизводимость деплоя и защиту от подмены артефакта.
