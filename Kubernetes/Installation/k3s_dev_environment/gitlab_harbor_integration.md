# Интеграция GitLab с Harbor

Руководство по настройке GitLab для работы с внешним реестром артефактов Harbor (OCI Registry) в dev-окружении K3s. Описывает процедуру полного отключения встроенного реестра GitLab, использование нативной интеграции, OIDC-аутентификации и централизованное управление секретами.

> **Контекст:** Часть серии по созданию dev-окружения в K3s. Harbor используется как единый реестр для Docker-образов и Helm-чартов. См. [Архитектура K3s](./k3s_architecture.md), [Обзор Harbor](../../../Docker/Docker_registries/Harbor/overview.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **GitLab Registry** | Встроенный Docker-реестр в GitLab. Требует явного отключения при использовании внешних решений для избежания конфликтов маршрутизации и ресурсов. |
| **Harbor** | Внешний реестр OCI с функциями сканирования уязвимостей (Trivy), репликации и управления жизненным циклом (v2.15+ использует Valkey как backend). |
| **Нативная интеграция Harbor** | Функция GitLab (17.x+), позволяющая просматривать репозитории Harbor в UI GitLab и автоматически заполнять переменные авторизации. |
| **GitLab Secrets Manager** | Встроенное решение (GA с v19.2), позволяющее централизованно хранить секреты с привязкой к ролям и аудитом, заменяя обычные CI/CD переменные. |
| **OIDC Federation** | Метод беспарольной аутентификации, при котором GitLab выступает провайдером личности для Harbor через JWT-токены (`id_tokens`). |
| **Kaniko / Buildah** | Инструменты для сборки OCI-образов внутри Kubernetes без использования привилегированного режима (Docker-in-Docker). |
| **Robot Account** | Изолированная учетная запись в Harbor для автоматизации CI/CD. Имеет ограниченный TTL, ограниченный набор прав (push/pull) и привязку к конкретному проекту. Не зависит от личных учетных записей сотрудников. |
| **Retention Policy** | Политика очистки артефактов в Harbor по времени жизни или количеству тегов. Предотвращает переполнение хранилища. |
| **Garbage Collection (GC)** | Фоновый процесс Harbor, удаляющий неиспользуемые слои образов и метаданные после удаления тегов. Освобождает дисковое пространство. |
| **Project Quota** | Лимит дискового пространства и количества образов на уровне проекта в Harbor. Предотвращает злоупотребление ресурсами. |
| **Cosign / Notation** | Инструменты для создания и верификации цифровых подписей OCI-артефактов. Гарантируют целостность и происхождение образа (Supply Chain Security). |
| **SBOM (Software Bill of Materials)** | Спецификация состава пакетов образа (CycloneDX/SPDX). Автоматически генерируется Harbor для каждого образа. |
| **Proxy Cache** | Режим проекта Harbor, при котором он выступает прозрачным прокси для внешних реестров (Docker Hub), кэшируя образы локально для обхода Rate Limits. |
| **Push/Pull Replication** | Механизм синхронизации артефактов между инстансами Harbor (или между Harbor и другим OCI-реестром) по расписанию или событию (push). |
| **Trivy** | Встроенный сканер уязвимостей в Harbor. Анализирует образы на наличие CVE, генерирует отчеты и может блокировать pull при превышении порога критичности. |

**Навигация:** [Обзор Harbor](../../../Docker/Docker_registries/Harbor/overview.md) | [Основы GitLab CI](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) | [Интеграция GitLab с K8s](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)

---

## Основные концепции

### Преимущества внешнего Harbor перед GitLab Registry

Выбор в пользу Harbor (v2.15+) в связке с GitLab (v19.x) обусловлен расширенными возможностями безопасности:

| Критерий | GitLab Registry | Harbor |
|----------|-----------------|--------|
| **Сканирование уязвимостей** | Ограничено / требует платной версии | Встроено (Trivy v0.72+), блокировка Pull при наличии CVE |
| **Управление доступом** | Привязано к правам проекта | Гибкая RBAC, робот-аккаунты с TTL, OIDC-федерация |
| **Репликация** | Сложная настройка | Нативная поддержка Push/Pull репликации между реестрами |
| **Helm-чарты** | Поддержка OCI | Нативная поддержка OCI и Helm Chart Repository API |
| **Подпись артефактов** | — | Поддержка Cosign/Notation для верификации цепочки поставок |
| **SBOM** | Требует настройки пайплайна | Автоматическая генерация и хранение SBOM (CycloneDX/SPDX) |
| **Прокси-кэширование** | — | Режим Proxy Cache (Valkey backend) для ускорения Docker Hub |
| **Квоты и лимиты** | Ограничены | Гибкие квоты на уровне проекта (дисковое пространство, количество образов) |

### Архитектура интеграции в K3s

В данной схеме Harbor развернут внутри кластера K3s и является единственной точкой хранения артефактов.

```text
┌─────────────────────────────────────────────────────────────┐
│                      GitLab (v19.2+)                         │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────────────────────┐  │
│  │  GitLab CI/CD   │    │   GitLab Registry (отключен)    │  │
│  │   Pipelines     │◀──▶│   global.registry.enabled: false│  │
│  │  (Secrets Mgr)  │    └─────────────────────────────────┘  │
│  └────────┬────────┘                                         │
│           │                                                  │
│           │ Native Integration / OIDC / Robot Token          │
└───────────┼──────────────────────────────────────────────────┘
            │ HTTPS (с монтированием CA-сертификата)
            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Harbor (v2.15+)                           │
│  ┌─────────────────┐    ┌─────────────────────────────────┐  │
│  │  OCI Artifacts  │    │      Security Gate              │  │
│  │  (Images, SBOM) │    │      (Trivy, Cosign)            │  │
│  └─────────────────┘    └─────────────────────────────────┘  │
│  ┌─────────────────┐    ┌─────────────────────────────────┐  │
│  │  Proxy Cache    │    │      Retention & GC             │  │
│  │  (Docker Hub)   │    │      (автоочистка)              │  │
│  └─────────────────┘    └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Проблема конфликта встроенного и внешнего реестров

При использовании официального Helm-чарта GitLab (`gitlab/gitlab`) критически важно отключить компонент Registry в **двух независимых секциях** конфигурации.

**Причина:** Параметр `global.registry.enabled: false` отключает отображение реестра в UI и логику Rails, но сам микросервис `registry` может продолжать запускаться и занимать ресурсы, если не указано `registry: { enabled: false }`.

**Симптомы некорректной настройки:**
- Ошибки аутентификации в пайплайнах (Runner пытается обратиться к `registry.gitlab.svc`).
- Конфликты в Ingress-контроллере при совпадении доменов.
- Бесполезное потребление CPU/RAM подом реестра.

### Жизненный цикл артефакта в Harbor

Понимание жизненного цикла важно для правильной настройки пайплайнов и политик очистки:

```text
Build (Kaniko) → Push to Harbor → Trivy Scan → SBOM Generation →
Cosign Signing → Pull (CI/CD или K8s) → Retention Policy → Garbage Collection
```

| Этап | Описание | Кто выполняет |
| :--- | :--- | :--- |
| **Build** | Сборка OCI-образа из Dockerfile | Kaniko (в CI) |
| **Push** | Публикация образа в Harbor | CI Pipeline |
| **Scan** | Анализ уязвимостей через Trivy | Harbor (автоматически) |
| **SBOM** | Генерация спецификации состава пакетов | Harbor (автоматически) |
| **Sign** | Подпись образа для верификации целостности | CI Pipeline (Cosign) |
| **Pull** | Загрузка образа в K8s-кластер | Kubelet / ArgoCD |
| **Retention** | Удаление старых тегов по политике | Harbor (по расписанию) |
| **GC** | Очистка неиспользуемых слоев с диска | Harbor (по расписанию) |

### OIDC-аутентификация: архитектура взаимодействия

OIDC Federation позволяет GitLab выступать в роли Identity Provider для Harbor, исключая необходимость хранения статических паролей:

```text
┌──────────────┐  1. CI Job запускается  ┌──────────────┐
│  GitLab CI   │ ──────────────────────▶ │  GitLab CI   │
│  (Runner)    │                         │  (id_tokens) │
└──────────────┘                         └──────┬───────┘
                                                │
                              2. GitLab генерирует JWT (id_token)
                                 с aud: harbor.example.com
                                                │
                                                ▼
┌──────────────┐  3. Harbor проверяет   ┌──────────────┐
│    Harbor    │ ◀──JWT через JWKS──── │  GitLab JWKS │
│  (OIDC Auth) │                        │  (pub keys)  │
└──────────────┘                        └──────────────┘
```

**Ключевые моменты:**
- GitLab генерирует `id_token` с указанием аудитории (`aud`), которая должна совпадать с настройкой Harbor.
- Harbor проверяет подпись JWT через публичные ключи GitLab (эндпоинт `/-/jwks`).
- Токен содержит claims: `sub` (пользователь), `groups` (группы GitLab), `aud` (целевой сервис).
- Токен временный (обычно 1 час), автоматически обновляется Runner'ом.

### Компоненты Harbor в контексте K3s

Внутри K3s Harbor работает как набор подов с определенными ресурсами:

| Компонент | Назначение | Рекомендуемые ресурсы |
| :--- | :--- | :--- |
| **harbor-core** | Основная логика: API, аутентификация, вебхуки | 512 МБ RAM, 0.5 CPU |
| **harbor-registry** | Хранение слоев и манифестов образов | 512 МБ RAM, 0.5 CPU |
| **harbor-database** | PostgreSQL для метаданных | 512 МБ RAM, 0.5 CPU |
| **harbor-redis** | Кэширование и очереди заданий (Valkey в v2.15+) | 256 МБ RAM, 0.25 CPU |
| **harbor-trivy** | Сканер уязвимостей | 1 ГБ RAM, 1 CPU |
| **harbor-portal** | Веб-интерфейс | 128 МБ RAM, 0.1 CPU |
| **harbor-jobservice** | Фоновые задачи (репликация, GC) | 256 МБ RAM, 0.25 CPU |
| **harbor-notary** | Подпись образов (Notation) | 256 МБ RAM, 0.25 CPU |

---

## Требования и предварительная подготовка

### Программные зависимости

| Компонент | Минимальная версия | Рекомендация | Назначение |
| :--- | :--- | :--- | :--- |
| **K3s** | v1.28+ | v1.36.3+k3s1 | Оркестратор |
| **Harbor** | v2.12+ | v2.15.2+ | OCI реестр |
| **GitLab** | v17.0+ | v19.2+ | CI/CD платформа |
| **GitLab Runner** | v17.0+ | v17.9+ | Выполнение пайплайнов в K3s |
| **Helm** | v3.12+ | v4.2.3 | Управление чартами |
| **cert-manager** | v1.14+ | v1.17+ | Управление TLS-сертификатами |

### Требования к GitLab Runner в K3s

Для корректной работы пайплайнов с Harbor Runner должен иметь доступ к Harbor через внутреннюю сеть кластера и поддерживать сборку образов без Docker-in-Docker.

| Компонент | Назначение | Примечание |
| :--- | :--- | :--- |
| **Kubernetes Executor** | Создание пода для каждой задачи | Рекомендуется вместо Docker-исполнителя |
| **ServiceAccount** | Идентификация Runner в K8s | Должен иметь права на создание подов в namespace `gitlab-runner` |
| **Registry Mirror** | Проксирование запросов к Harbor | Ускоряет загрузку базовых образов и снижает нагрузку на Harbor |
| **Resource Limits** | Лимиты CPU/RAM для задач | Kaniko требует минимум 512 МБ RAM, Trivy — 1 ГБ |

### Требования к сети в K3s

Harbor и GitLab взаимодействуют через внутренние сервисы кластера и Ingress Controller:

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| **CNI** | Flannel (VXLAN) | Встроенный в K3s, обеспечивает связность между подов |
| **Ingress** | NGINX | Маршрутизация HTTPS-трафика от Runner и пользователей к Harbor |
| **DNS** | CoreDNS | Разрешение `harbor.dev.local` и `gitlab.dev.local` внутри кластера |
| **CoreDNS rewriting** | `harbor.dev.local` → `harbor.harbor.svc.cluster.local` | Рекомендуется для снижения задержек внутри кластера |

### Предварительные шаги

1. **Harbor установлен и работает:**
```bash
kubectl -n harbor get pods
# → NAME                                READY   STATUS    AGE
# → harbor-core-xxx                     1/1     Running   5m
# → harbor-database-0                   1/1     Running   5m
# → harbor-registry-xxx                 1/1     Running   5m
# → harbor-redis-0                      1/1     Running   5m
# → harbor-trivy-xxx                    1/1     Running   5m
```

2. **GitLab установлен и работает:**
```bash
kubectl -n gitlab get pods
# → NAME                                            READY   STATUS    AGE
# → gitlab-gitaly-0                                 1/1     Running   10m
# → gitlab-webservice-xxx                           1/1     Running   10m
```

3. **DNS настроен** (Harbor доступен по имени):
```bash
curl -s -o /dev/null -w "%{http_code}" https://harbor.dev.local
# → 200
```

4. **CA-сертификат Harbor доступен** (для самоподписанных сертификатов):
```bash
kubectl get secret harbor-ca-tls -n harbor \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > harbor-ca.crt
```

---

## Практические сценарии

### 1. Отключение встроенного GitLab Registry

Внесите следующие изменения в ваш `values.yaml` для Helm-чарта GitLab:

```yaml
# gitlab-values.yaml

global:
  registry:
    # 1. Отключает интеграцию на уровне Rails (UI, API)
    enabled: false
    # Опционально: URL для ссылок в интерфейсе
    externalUrl: https://harbor.dev.local

# 2. Полностью отключает развертывание пода Registry
registry:
  enabled: false
```

**Применение конфигурации:**

```bash
# Обновление GitLab
helm upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f gitlab-values.yaml \
  --timeout 10m \
  --wait

# Проверка отсутствия пода registry
kubectl -n gitlab get pods | grep registry
# → (пустой вывод = registry отключен)

# Валидация: UI GitLab не содержит ссылок на Registry
curl -sk -o /dev/null -w "%{http_code}" https://gitlab.dev.local/explore
# → 200

# Валидация: попытка доступа к registry.gitlab.svc.cluster.local возвращает 404
curl -sk -o /dev/null -w "%{http_code}" http://registry.gitlab.svc.cluster.local/v2/
# → 404
```

**Восстановление (Revert):**

```bash
# Возврат к встроенному реестру
helm upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  --set global.registry.enabled=true \
  --set registry.enabled=true \
  --timeout 10m \
  --wait

# Проверка наличия пода registry
kubectl -n gitlab get pods | grep registry
# → gitlab-registry-xxx   1/1     Running
```

### 2. Централизованная настройка доступа к Harbor

#### Вариант А: Нативная интеграция (Рекомендуется)

1. В Harbor: создайте **Robot Account** (Project level) с правами `push` и `pull`.
2. В GitLab: **Settings > Integrations > Harbor**.
3. Укажите URL Harbor, имя проекта и данные робот-аккаунта.
4. В пайплайнах автоматически станут доступны переменные: `$HARBOR_HOST`, `$HARBOR_USERNAME`, `$HARBOR_PASSWORD`.

**Валидация:**

```bash
# Проверка в пайплайне: тестовый джоб с выводом переменных
cat <<'EOF' > .gitlab-ci.yml
validate_harbor:
  stage: test
  script:
    - echo "Harbor host: $HARBOR_HOST"
    - echo "Harbor user: $HARBOR_USERNAME"
    - echo "Password length: ${#HARBOR_PASSWORD}"
    - curl -sk -u "$HARBOR_USERNAME:$HARBOR_PASSWORD" "https://$HARBOR_HOST/api/v2.0/projects" | jq '.[0].name'
EOF
# → запустите пайплайн и убедитесь, что API Harbor отвечает
```

#### Вариант Б: GitLab Secrets Manager (GitLab 19.2+)

Если требуется более строгий аудит и контроль:
1. **Settings > Secrets > Add Secret**.
2. Ключ: `HARBOR_CI_TOKEN`, значение: `<пароль_робота>`.
3. В `.gitlab-ci.yml` подключите секрет:

```yaml
build:
  secrets:
    HARBOR_PASSWORD:
      vault: HARBOR_CI_TOKEN
```

**Валидация:**

```bash
# В пайплайне секрет инжектируется как переменная окружения
validate_secrets:
  stage: test
  secrets:
    HARBOR_PASSWORD:
      vault: HARBOR_CI_TOKEN
  script:
    - test -n "$HARBOR_PASSWORD"
    - echo "Secret length: ${#HARBOR_PASSWORD}"
    - curl -sk -u "$HARBOR_USERNAME:$HARBOR_PASSWORD" "https://$HARBOR_HOST/api/v2.0/projects" | jq '.[0].name'
```

#### Вариант В: Group-level Variables (Традиционный)

Для обратной совместимости или простых окружений. Настройте в **Group -> Settings -> CI/CD -> Variables**.

| Ключ | Значение | Тип | Опции | Описание |
|------|----------|-----|-------|----------|
| `DEV_REGISTRY` | `harbor.dev.local` | `Variable` | — | FQDN адрес Harbor |
| `DEV_REGISTRY_USER` | `robot$ci-pipeline` | `Variable` | `Masked` | Робот-аккаунт Harbor |
| `DEV_REGISTRY_PASSWORD` | `<token>` | `Variable` | `Masked`, `Protected` | Пароль робота |
| `DEV_CA_CERT` | (содержимое `ca.crt`) | `File` | — | Root CA Harbor |

**Валидация:**

```bash
# Проверка, что переменные корректно прокинуты в пайплайн
validate_variables:
  stage: test
  script:
    - test -n "$DEV_REGISTRY"
    - test -n "$DEV_REGISTRY_USER"
    - test -n "$DEV_REGISTRY_PASSWORD"
    - test -f "$DEV_CA_CERT"
    - echo "Registry: $DEV_REGISTRY"
```

### 3. Полный CI/CD пайплайн: сборка -> сканирование -> подпись -> пуш

```yaml
# .gitlab-ci.yml — полный пайплайн с интеграцией Harbor
stages:
  - build
  - scan
  - sign
  - deploy

variables:
  DOCKER_IMAGE: $HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME:$CI_COMMIT_SHORT_SHA

# Этап 1: Сборка через Kaniko
build-image:
  stage: build
  image:
    name: osscontainertools/kaniko:v1.28.2-debug
    entrypoint: [""]
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$HARBOR_HOST\":{\"auth\":\"$(echo -n $HARBOR_USERNAME:$HARBOR_PASSWORD | base64)\"}}}" > /kaniko/.docker/config.json
    - |
      if [ -f "$DEV_CA_CERT" ]; then
        cp "$DEV_CA_CERT" /kaniko/ssl/certs/ca-certificates.crt
      fi
    - /kaniko/executor
        --context "$CI_PROJECT_DIR"
        --dockerfile "$CI_PROJECT_DIR/Dockerfile"
        --destination "$DOCKER_IMAGE"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

# Этап 2: Проверка уязвимостей через Trivy
scan-image:
  stage: scan
  image:
    name: aquasec/trivy:0.52.0
    entrypoint: [""]
  script:
    # Сканирование на критические уязвимости
    - trivy image --exit-code 1 --severity CRITICAL "$DOCKER_IMAGE"
    # Сканирование с выводом отчета
    - trivy image --format json --output trivy-report.json "$DOCKER_IMAGE"
  artifacts:
    paths:
      - trivy-report.json
    expire_in: 7 days
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

# Этап 3: Подпись образа через Cosign
sign-image:
  stage: sign
  image:
    name: gcr.io/projectsigstore/cosign:v2.4.0
    entrypoint: [""]
  script:
    # Keyless подпись через OIDC (GitLab id_token)
    - cosign sign --yes "$DOCKER_IMAGE"
    # Верификация подписи
    - cosign verify --certificate-identity "$CI_PROJECT_URL" --certificate-oidc-issuer "$GITLAB_URL" "$DOCKER_IMAGE"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

# Этап 4: Деплой в K3s
deploy-image:
  stage: deploy
  image: harbor.dev.local/library/kubeutils:v1.36.3
  script:
    - helm upgrade --install $CI_PROJECT_NAME ./chart
        --namespace dev-workspaces
        --set image.repository=$HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME
        --set image.tag=$CI_COMMIT_SHORT_SHA
        --atomic
        --wait
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

**Валидация пайплайна:**

```bash
# 1. Проверка синтаксиса YAML
glab ci lint
# → CI/CD config file is valid

# 2. Проверка доступности Harbor из пайплайна
kubectl -n gitlab-runner run harbor-test --image=curlimages/curl:latest --rm -it -- \
  curl -sk -o /dev/null -w "%{http_code}" https://harbor.dev.local/api/v2.0/health
# → 200

# 3. Проверка, что Kaniko может записывать в Harbor
# Запустите джоб с dry-run и проверьте наличие образа:
kubectl -n harbor get pods -w
# → harbor-registry-xxx должен быть Running
```

**Очистка артефактов:**

```bash
# Удаление тегов старше 7 дней через Harbor API (запускайте через cron)
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"action":"delete","olderThan":"7d"}' \
  https://harbor.dev.local/api/v2.0/projects/1/artifacts/delete
```

### 4. Настройка GitLab Runner для работы с Harbor

#### 4.1 Установка GitLab Runner через Helm

Для работы с Harbor Runner должен быть развернут внутри кластера K3s с Kubernetes Executor:

```bash
helm repo add gitlab https://charts.gitlab.com/
helm repo update

helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  --create-namespace \
  --set gitlabUrl=https://gitlab.dev.local \
  --set runnerToken="glrt-XXXXXXXXXXXXXXXXXXXX" \
  --set rbac.create=true \
  --set runners.namespace=gitlab-runner \
  --set runners.defaultTerminationGracePeriodSeconds=30 \
  --set runners.cache.dir=/cache \
  --set runners.cache.type=s3 \
  --set runners.cache.s3.server_address=minio.minio.svc.cluster.local:9000 \
  --set runners.cache.s3.bucket_name=runner-cache \
  --set runners.cache.s3.insecure=true \
  --set runners.cache.s3.credentials.accesskey=$(kubectl -n minio get secret minio -o jsonpath='{.data.root-user}' | base64 -d) \
  --set runners.cache.s3.credentials.secretkey=$(kubectl -n minio get secret minio -o jsonpath='{.data.root-password}' | base64 -d)
```

**Параметры:**
- `runnerToken`: токен регистрации Runner (создается в GitLab Admin -> Operations -> CI/CD Settings -> Runners)
- `rbac.create=true`: создает ServiceAccount, Role и RoleBinding автоматически
- `runners.namespace`: namespace для рабочих подов (должен отличаться от namespace самого Runner)

**Валидация:**

```bash
# Проверка подов Runner
kubectl -n gitlab-runner get pods
# → NAME                                   READY   STATUS    AGE
# → gitlab-runner-xxx                      1/1     Running   30s

# Проверка регистрации в GitLab
# Admin -> Operations -> CI/CD Settings -> Runners -> should show "online"
# Или через API:
curl -sk -H "PRIVATE-TOKEN: <admin_token>" "https://gitlab.dev.local/api/v4/runners" | jq '.[].status'
# → "online"
```

#### 4.2 Регистрация раннера в GitLab

```bash
# Получение токена регистрации (в GitLab UI: Admin -> Operations -> CI/CD Settings -> Runners)
REGISTRATION_TOKEN="glrt-XXXXXXXXXXXXXXXXXXXX"

# Регистрация раннера
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  --reuse-values \
  --set gitlabUrl=https://gitlab.dev.local \
  --set runnerRegistrationToken="$REGISTRATION_TOKEN" \
  --set runners.tags="k3s,kaniko,trivy"

# Валидация
curl -sk -H "PRIVATE-TOKEN: <admin_token>" "https://gitlab.dev.local/api/v4/runners" | jq '.[].tag_list'
# → ["k3s", "kaniko", "trivy"]
```

#### 4.3 Настройка ресурсов для задач

```yaml
# gitlab-runner-values.yaml (дополнение к секции runners)
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        namespace = "gitlab-runner"
        cpu_request = "250m"
        memory_request = "512Mi"
        cpu_limit = "2"
        memory_limit = "4Gi"
        [[runners.kubernetes.volumes.empty_dir]]
          name = "docker-gitlab-runner-cache"
          medium = "Memory"
        [[runners.kubernetes.volumes.host_path]]
          name = "docker-gitlab-runner-cache"
          mount_path = "/cache"
```

Применение:

```bash
helm upgrade gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  -f gitlab-runner-values.yaml \
  --reuse-values
```

**Очистка (удаление Runner):**

```bash
helm uninstall gitlab-runner --namespace gitlab-runner
kubectl delete namespace gitlab-runner
# → namespace "gitlab-runner" deleted
```

**Восстановление (Revert):**

```bash
# Удаление и повторная установка с дефолтными значениями
helm uninstall gitlab-runner --namespace gitlab-runner
kubectl delete namespace gitlab-runner

helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  --create-namespace \
  --set gitlabUrl=https://gitlab.dev.local \
  --set runnerRegistrationToken="<новый_токен>" \
  --set rbac.create=true
```

#### 4.4 Настройка imagePullSecrets для Harbor в Runner

Для работы с Harbor, требующим аутентификации (все приватные проекты), Runner должен иметь секрет `imagePullSecret`, который будет использоваться всеми рабочими подами:

```bash
# Создание секрета с учетными данными робот-аккаунта Harbor
kubectl -n gitlab-runner create secret docker-registry harbor-registry-secret \
  --docker-server=harbor.dev.local \
  --docker-username='robot$ci-pipeline' \
  --docker-password='<robot_token>' \
  --docker-email=ci-pipeline@example.com

# Валидация
kubectl -n gitlab-runner get secret harbor-registry-secret
# → NAME                    TYPE                             DATA   AGE
# → harbor-registry-secret  kubernetes.io/dockerconfigjson   1      10s
```

Обновление `values.yaml` Runner:

```yaml
runners:
  imagePullPolicy: Always
  imagePullSecrets:
    - name: harbor-registry-secret
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "harbor.dev.local/library/gitlab-runner-helper:x86_64-v17.9"
        imagePullPolicy = "Always"
        pull_policy = ["always"]
```

Применение:

```bash
helm upgrade gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  -f gitlab-runner-values.yaml \
  --reuse-values
```

**Валидация:**

```bash
# Проверка, что рабочие поды используют imagePullSecret
kubectl -n gitlab-runner get pods -l app=gitlab-runner -o jsonpath='{.items[*].spec.imagePullSecrets[*].name}'
# → harbor-registry-secret

# Проверка успешного пула образа из Harbor
kubectl -n gitlab-runner logs -l app=gitlab-runner --tail=20 | grep -i "pulling image"
# → Pulling image "harbor.dev.local/library/gitlab-runner-helper:x86_64-v17.9"
# → Image "harbor.dev.local/library/gitlab-runner-helper:x86_64-v17.9" already exists on machine
```

### 5. Настройка Harbor как Proxy Cache для Docker Hub

Proxy Cache позволяет Harbor выступать прозрачным прокси для Docker Hub, кэшируя образы локально и обходя Rate Limits. Это особенно полезно в GitLab CI, где несколько пайплайнов одновременно запрашивают популярные базовые образы (python, node, alpine).

```bash
# 1. Создание проекта для кэша в Harbor
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "docker-hub-proxy",
    "public": false
  }' \
  https://harbor.dev.local/api/v2.0/projects

# 2. Создание Registry Endpoint для Docker Hub
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "name": "docker-hub",
    "endpoint": "https://hub.docker.com",
    "type": "docker-hub"
  }' \
  https://harbor.dev.local/api/v2.0/registries

# 3. Включение Proxy Cache через Harbor API
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X PUT \
  -H "Content-Type: application/json" \
  -d '{
    "cache_refresh_enabled": true,
    "cache_expiration": 168,
    "registry_id": 1
  }' \
  https://harbor.dev.local/api/v2.0/projects/docker-hub-proxy
```

**Настройка в GitLab CI (.gitlab-ci.yml):**

```yaml
variables:
  # Использование Harbor как кэша для базовых образов
  DOCKER_HOST: "harbor.dev.local"
  DOCKER_REGISTRY: "harbor.dev.local/docker-hub-proxy"

stages:
  - build

build-image:
  stage: build
  image: docker.io/library/python:3.12-slim
  script:
    - python --version
    # → Python 3.12.3
    - pip install -r requirements.txt
    # → Collecting flask==2.3.0
    # →   Downloading flask-2.3.0-py3-none-any.whl (96 kB)
    # → Requirement already satisfied: Werkzeug>=2.3.0 in /usr/local/lib/python3.12/site-packages (from flask==2.3.0) (2.3.7)
```

**Валидация:**

```bash
# Проверка кэширования: первый запрос должен быть медленнее
time docker pull harbor.dev.local/docker-hub-proxy/library/python:3.12-slim
# → real 0m8.5s (первый запрос)

# Второй запрос — из кэша
time docker pull harbor.dev.local/docker-hub-proxy/library/python:3.12-slim
# → real 0m0.3s (из кэша)

# Проверка метрик кэша
curl -sk -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  "https://harbor.dev.local/api/v2.0/projects/docker-hub-proxy/repositories" | jq '.[].name'
# → ["library"]
```

### 6. Настройка Retention Policy в Harbor

Retention Policy предотвращает переполнение хранилища, автоматически удаляя старые теги:

```bash
# Через API Harbor: настройка retention policy для проекта
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X PUT \
  -H "Content-Type: application/json" \
  -d '{
    "algorithm": "or",
    "rules": [
      {
        "disabled": false,
        "action": "retain",
        "template": {"kind": "Always", "params": {}},
        "scope": {"level": "project", "ref": 1}
      },
      {
        "disabled": false,
        "action": "delete",
        "template": {"kind": "nthMostRecent", "params": {"mostRecent": 10}},
        "scope": {"level": "project", "ref": 1}
      }
    ]
  }' \
  https://harbor.dev.local/api/v2.0/projects/1/immutabletagrules
```

**Параметры:**
- `kind: Always` — оставить все теги, соответствующие шаблону (например, `v1.*`).
- `kind: nthMostRecent` — оставить N последних тегов, удалить остальные.
- `scope.level: project` — политика на уровне проекта.

**Рекомендации для dev-окружения:**
- Оставляйте последние 10-15 тегов для каждого репозитория.
- Удаляйте теги старше 30 дней для экономии диска.
- Настройте Garbage Collection для запуска ежедневно в ночное время.

**Валидация:**

```bash
# Проверка настроенной политики
curl -sk -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  "https://harbor.dev.local/api/v2.0/projects/1/retentions" | jq '.[].rules[].template.kind'
# → "Always"
# → "nthMostRecent"

# Проверка количества артефактов до и после GC
kubectl -n harbor logs deploy/harbor-jobservice --tail=50 | grep -i "garbage collection"
# → 2026/01/15 10:00:00 [INFO] [GC] start to dry run
# → 2026/01/15 10:00:05 [INFO] [GC] 15 artifacts will be deleted
```

### 7. Настройка сканирования уязвимостей (Trivy)

```bash
# Включение автоматического сканирования при пуше через API Harbor
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X PUT \
  -H "Content-Type: application/json" \
  -d '{"scan_on_push": true}' \
  https://harbor.dev.local/api/v2.0/projects/1/scan_all

# Настройка политики блокировки pull при наличии критических CVE
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X PUT \
  -H "Content-Type: application/json" \
  -d '{
    "severity": {"blocking": true, "unfixable": false}
  }' \
  https://harbor.dev.local/api/v2.0/system/gc/schedule
```

**Валидация:**

```bash
# Отправка тестового образа с уязвимостью
docker push harbor.dev.local/my-project/test-image:latest

# Проверка статуса сканирования
curl -sk -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  "https://harbor.dev.local/api/v2.0/projects/my-project/repositories/test-image/artifacts/latest?with_scan_overview=true" \
  | jq '.scan_overview.items[0].scan_status'
# → "Success" или "Error"

# Попытка pull заблокированного образа
docker pull harbor.dev.local/my-project/vulnerable-image:latest
# → Error response from daemon: manifest unknown: artifact is blocked due to vulnerability policy
```

**Очистка (отключение сканирования):**

```bash
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X PUT \
  -H "Content-Type: application/json" \
  -d '{"scan_on_push": false}' \
  https://harbor.dev.local/api/v2.0/projects/1/scan_all
```

### 8. Извлечение CA-сертификата для GitLab

Если ваш Harbor использует TLS, выданный внутренним `cert-manager` кластера K3s, получите его следующей командой:

```bash
# Для сертификатов, выданных через CA Issuer
kubectl get secret harbor-ca-tls -n harbor \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > harbor-ca.crt

# Проверка сертификата
openssl x509 -in harbor-ca.crt -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After"
# → Subject: CN = harbor.dev.local
# → Issuer: CN = dev-local-ca
# → Not Before: Jan 15 10:00:00 2026 GMT
# → Not After : Jan 15 10:00:00 2027 GMT

# Проверка размера (должен быть > 0)
ls -la harbor-ca.crt
# → -rw-r--r--  1 user  staff  1234 Jan 15 10:00 harbor-ca.crt
```

Скопируйте содержимое `harbor-ca.crt` в переменную `DEV_CA_CERT` типа `File` или загрузите в Secrets Manager.

**Валидация:**

```bash
# Проверка, что Harbor доверяет самому себе
curl -sk https://harbor.dev.local/api/v2.0/health -o /dev/null -w "%{http_code}\n"
# → 200

# Проверка, что GitLab доверяет CA (если настроено)
kubectl -n gitlab get secret gitlab-dev.local-tls -o jsonpath='{.data.ca\.crt}' | base64 -d | openssl x509 -noout -subject
# → subject=CN = harbor.dev.local
```

### 9. Настройка OIDC Federation (GitLab -> Harbor)

1. В Harbor: **Administration -> Configuration -> Authentication**.
2. Выберите **OIDC** как Endpoint Provider.
3. Укажите:
   - **Endpoint URL**: `https://gitlab.dev.local/oauth/oidc` (или `https://gitlab.dev.local`)
   - **Client ID**: создайте OIDC-приложение в GitLab (**Admin -> Applications -> New Application**)
   - **Client Secret**: скопируйте из GitLab
   - **Groups claim**: `groups`
   - **Name**: `GitLab`
4. В GitLab: **Admin -> Applications -> New Application**:
   - **Name**: `Harbor OIDC`
   - **Redirect URI**: `https://harbor.dev.local/c/oidc/callback`
   - **Scopes**: `openid`, `profile`, `email`, `groups`
5. Протестируйте вход через GitLab в Harbor.

**Валидация:**

```bash
# Получение id_token через GitLab API (для тестирования)
TOKEN=$(curl -sk -X POST "https://gitlab.dev.local/oauth/access_token" \
  -d "grant_type=client_credentials" \
  -d "client_id=<client_id>" \
  -d "client_secret=<client_secret>" \
  -d "audience=harbor.dev.local" \
  | jq -r '.id_token')

# Проверка claims в токене
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '.aud, .sub, .groups'
# → {
#     "aud": "harbor.dev.local",
#     "sub": "job_12345678",
#     "groups": ["gitlab-runner"]
#   }

# Проверка входа через Harbor UI (ручная валидация)
# Откройте https://harbor.dev.local и нажмите "Sign In with GitLab"
# → Успешный редирект на UI GitLab и обратно в Harbor
```

### 10. Вспомогательные утилиты для работы с Harbor

#### 8.1 Установка regctl

`regctl` — CLI-утилита для работы с OCI-реестрами без Docker-клиента. Позволяет получать манифесты, теги и информацию об образах:

```bash
# Установка regctl
curl -L "https://github.com/regclient/regclient/releases/latest/download/regctl-linux-amd64" -o /usr/local/bin/regctl
chmod +x /usr/local/bin/regctl

# Валидация установки
regctl version
# → Version: v0.7.x, Git commit: xxx

# Авторизация в Harbor
regctl registry login harbor.dev.local \
  --auth-file ~/.docker/config.json \
  -u 'robot$ci-pipeline' -p '<token>'

# Получение списка тегов образа
regctl tag list harbor.dev.local/my-project/my-app
# → v1.0
# → v1.1
# → latest
# → sha256:abcd1234...

# Получение манифеста образа по дайджесту
DIGEST=$(regctl manifest digest harbor.dev.local/my-project/my-app:v1.0)
regctl manifest get harbor.dev.local/my-project/my-app@$DIGEST --platform linux/amd64
# → config: sha256:config_digest...
# → layers: [sha256:layer1...]

# Проверка digest образа
echo $DIGEST
# → sha256:abcd1234efgh5678...
```

**Использование в пайплайнах:**

```yaml
validate-image:
  stage: verify
  image: ghcr.io/regclient/regctl:latest
  script:
    - regctl registry login $HARBOR_HOST -u $HARBOR_USERNAME -p $HARBOR_PASSWORD
    - |
      DIGEST=$(regctl manifest digest $HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME:$CI_COMMIT_SHORT_SHA)
      echo "Published digest: $DIGEST"
    - |
      SIZE=$(regctl manifest get $HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME:$CI_COMMIT_SHORT_SHA --format '{{.Config.Size}}')
      echo "Config size: $SIZE bytes"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

#### 8.2 Проверка SBOM через Harbor API

```bash
# Получение SBOM образа (если включено в Harbor)
curl -sk -u $HARBOR_USERNAME:$HARBOR_PASSWORD \
  "https://$HARBOR_HOST/api/v2.0/projects/$HARBOR_PROJECT/repositories/$CI_PROJECT_NAME/artifacts/$CI_COMMIT_SHORT_SHA/additions/sbom" \
  | jq '.'
# → [
#     {
#       "id": "SPDX",
#       "digest": "sha256:sbom_digest...",
#       "mediaType": "application/spdx+json"
#     }
#   ]
```

### 11. Использование в пайплайнах (Валидация публикации)

```yaml
# .gitlab-ci.yml — проверка доступности образа в Harbor после пуша
verify-publish:
  stage: verify
  image: harbor.dev.local/library/kubeutils:v1.36.3
  script:
    # Проверка existence образа
    - regctl manifest digest $HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME:$CI_COMMIT_SHORT_SHA
    # Проверка уязвимостей через Harbor API
    - |
      SCAN_STATUS=$(curl -sk -u $HARBOR_USERNAME:$HARBOR_PASSWORD \
        "https://$HARBOR_HOST/api/v2.0/projects/$HARBOR_PROJECT/repositories/$CI_PROJECT_NAME/artifacts/$CI_COMMIT_SHORT_SHA?with_scan_overview=true" \
        | jq -r '.scan_overview.items[] | select(.scanner.name=="Trivy") | .scan_status')
      if [ "$SCAN_STATUS" != "Success" ]; then
        echo "Scan not completed: $SCAN_STATUS"
        exit 1
      fi
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: `unauthorized: authentication required`

**Причина:** Неверные учетные данные или Robot Account не имеет прав на проект.

```bash
# Проверка логина в Harbor
docker login harbor.dev.local -u 'robot$ci-pipeline' -p '<token>'
# → Login Succeeded

# Если ошибка: проверьте права робот-аккаунта в Harbor UI
# Administration -> Robot Accounts -> Edit -> Project Permissions
```

### Ошибка: `x509: certificate signed by unknown authority`

**Причина:** Harbor использует самоподписанный сертификат, а Docker/CI не доверяет CA.

```bash
# Добавление CA в Docker daemon (на хосте)
sudo mkdir -p /etc/docker/certs.d/harbor.dev.local
sudo cp harbor-ca.crt /etc/docker/certs.d/harbor.dev.local/ca.crt
sudo systemctl restart docker

# Или добавление в daemon.json
cat <<EOF | sudo tee /etc/docker/daemon.json
{
  "insecure-registries": ["harbor.dev.local"]
}
EOF
sudo systemctl restart docker
```

**Для K3s containerd (внутри кластера):**

```bash
# Настройка registries.yaml для K3s (все узлы кластера)
sudo mkdir -p /etc/rancher/k3s
cat <<EOF | sudo tee /etc/rancher/k3s/registries.yaml
mirrors:
  "harbor.dev.local":
    endpoint:
      - "https://harbor.dev.local"
configs:
  "harbor.dev.local":
    tls:
      ca_file: "/etc/rancher/k3s/harbor-ca.crt"
EOF

sudo systemctl restart k3s
```

### Ошибка: `name unknown: repository does not exist`

**Причина:** Проект Harbor не существует или имя репозитория указано неверно.

```bash
# Проверка проектов в Harbor
curl -sk -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  https://harbor.dev.local/api/v2.0/projects | jq '.[].name'
# → "library"
# → "my-project"

# Публикация с созданием репозитория (автоматическое создание при push)
docker tag my-app:latest harbor.dev.local/my-project/my-app:v1.0
docker push harbor.dev.local/my-project/my-app:v1.0
```

### Ошибка: `error parsing HTTP 403 response body: invalid character '<' looking for beginning of value`

**Причина:** Harbor возвращает HTML-страницу вместо JSON (ошибка аутентификации или прав).

```bash
# Проверка токена через Harbor API
curl -sk -u 'robot$ci-pipeline:<token>' \
  https://harbor.dev.local/api/v2.0/projects/my-project/repositories \
  | jq '.[].name'
# → Если ошибка 403: Robot Account не имеет прав на этот проект
```

### Ошибка: Trivy не сканирует образы

**Причина:** Trivy-сканер не запущен или не может подключиться к базе уязвимостей.

```bash
# Проверка статуса Trivy
kubectl -n harbor get pods | grep trivy
# → harbor-trivy-xxx   1/1     Running

# Проверка логов Trivy
kubectl -n harbor logs deploy/harbor-trivy -f | grep -i error

# Обновление базы уязвимостей
kubectl -n harbor exec deploy/harbor-trivy -- trivy --download-db-only
```

### Ошибка: `dial tcp: lookup harbor.dev.local: no such host`

**Причина:** DNS не резолвит имя Harbor.

```bash
# Добавление в /etc/hosts (на хосте или в контейнере CI)
echo "192.168.1.100 harbor.dev.local" | sudo tee -a /etc/hosts

# Проверка
nslookup harbor.dev.local
# → Address: 192.168.1.100
```

### Ошибка: `ImagePullBackOff` для образов из Harbor

**Причина:** Секрет `imagePullSecret` отсутствует или содержит неверные данные.

```bash
# Проверка секретов в namespace приложения
kubectl -n dev-workspaces get secrets | grep harbor
# → harbor-registry-secret

# Проверка содержимого секрета
kubectl -n dev-workspaces get secret harbor-registry-secret -o yaml | grep dockerconfigjson
# → echo "<base64>" | base64 -d | jq .
# → {
#     "auths": {
#       "harbor.dev.local": {
#         "username": "robot$ci-pipeline",
#         "password": "<token>"
#       }
#     }
#   }

# Проверка использования секрета в deployment
kubectl -n dev-workspaces get deployment -o jsonpath='{.items[*].spec.template.spec.imagePullSecrets[*].name}'
# → harbor-registry-secret
```

### Ошибка: GitLab Runner не видит Harbor через Ingress

**Причина:** CoreDNS не резолвит `harbor.dev.local` внутри кластера.

```bash
# Проверка DNS из пода Runner
kubectl -n gitlab-runner run dns-test --image=busybox:1.36 --rm -it -- nslookup harbor.dev.local
# → Server:    10.43.0.10
# → Name:      harbor.dev.local
# → Address 1: 10.43.232.47 harbor.harbor.svc.cluster.local

# Если не резолвится: добавьте ConfigMap для CoreDNS
kubectl -n kube-system get configmap coredns -o yaml | grep -A 10 "hosts"
# → hosts {
#      10.43.0.10 harbor.dev.local
#      fallthrough
#   }
```

### Ошибка: `manifest unknown` при pull образа

**Причина:** Образ существует, но указан неверный тег или платформа.

```bash
# Проверка доступных тегов
regctl tag list harbor.dev.local/my-project/my-app
# → latest
# → v1.0

# Проверка манифеста для конкретной платформы
regctl manifest get harbor.dev.local/my-project/my-app@sha256:abcd1234 --platform linux/amd64
# → manifest returned
```

### Ошибка: Harbor Health API возвращает 500

**Причина:** База данных недоступна или превышен лимит соединений.

```bash
# Проверка состояния PostgreSQL
kubectl -n harbor exec -it harbor-database-0 -- psql -U harbor -d registry -c "SELECT count(*) FROM pg_stat_activity;"
# → count
# → 15

# Проверка логов Harbor Core
kubectl -n harbor logs deploy/harbor-core --tail=100 | grep -i "database\|connection"
# → 2025/01/15 10:30:00 [ERROR] [sql] connection refused
```

---

## Мониторинг и наблюдаемость

### Проверка здоровья Harbor

```bash
# Проверка статуса всех подов
kubectl -n harbor get pods
# → NAME                                READY   STATUS    AGE
# → harbor-core-xxx                     1/1     Running   5m
# → harbor-database-0                   1/1     Running   5m
# → harbor-registry-xxx                 1/1     Running   5m
# → harbor-redis-0                      1/1     Running   5m
# → harbor-trivy-xxx                    1/1     Running   5m

# Health check API Harbor
curl -sk -o /dev/null -w "%{http_code}" https://harbor.dev.local/api/v2.0/health
# → 200

# Проверка версии Harbor
curl -sk https://harbor.dev.local/api/v2.0/systeminfo | jq '.with_trivy, .harbor_version'
# → "with_trivy": true
# → "harbor_version": "v2.15.2"
```

### Сбор логов Harbor

```bash
# Логи Core (основная логика)
kubectl -n harbor logs deploy/harbor-core -f --tail=100 | grep -i "error\|warn"

# Логи Registry (хранение образов)
kubectl -n harbor logs deploy/harbor-registry -f --tail=100

# Логи Trivy (сканирование)
kubectl -n harbor logs deploy/harbor-trivy -f --tail=100 | grep -i "scan\|error"

# Логи Jobservice (фоновые задачи: GC, репликация)
kubectl -n harbor logs deploy/harbor-jobservice -f --tail=100
```

### Мониторинг использования хранилища

```bash
# Проверка размера проекта через Harbor API
curl -sk -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  https://harbor.dev.local/api/v2.0/statistics | jq '.total_count, .storage'

# Проверка использования диска на узле
df -h /mnt/data
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       50G   35G   15G  70% /

# Проверка размера хранилища Harbor
du -sh /mnt/data/registry/docker/
# → 25G    /mnt/data/registry/docker/
```

### Мониторинг метрик Harbor

Harbor экспонирует Prometheus-метрики через порт 8001:

```bash
# Метрики Harbor
kubectl -n harbor port-forward svc/harbor-core 8001:8001 &
curl -s http://localhost:8001/metrics | grep -E "harbor_project_total|harbor_artifact_total|harbor_quota"
# → harbor_project_total 3
# → harbor_artifact_total 150
```

---

## Безопасность

### RBAC для доступа к Harbor

```yaml
# Role для CI/CD в namespace harbor
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: harbor-ci-access
  namespace: harbor
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
    resourceNames: ["harbor-core-secret"]
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: harbor-ci-binding
  namespace: harbor
subjects:
  - kind: ServiceAccount
    name: ci-runner
    namespace: gitlab
roleRef:
  kind: Role
  name: harbor-ci-access
  apiGroup: rbac.authorization.k8s.io
```

### Сетевая безопасность (NetworkPolicy)

```yaml
# Ограничение доступа к Harbor только из GitLab и K3s
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: harbor-ingress
  namespace: harbor
spec:
  podSelector:
    matchLabels:
      app: harbor-core
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: gitlab
        - namespaceSelector:
            matchLabels:
              name: kube-system
      ports:
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 80
```

### Настройка Immutability Tags

Неизменяемые теги гарантируют, что артефакт под определенным тегом не будет перезаписан:

```bash
# Настройка через Harbor API
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "tag_selectors": [{"kind": "doublestar", "decoration": "matches", "pattern": "v*.*.*"}],
    "disabled": false
  }' \
  https://harbor.dev.local/api/v2.0/projects/1/immutabletagrules
```

**Рекомендация:** Включите Immutability для production-проектов. В dev-окружении используйте только Retention Policy для контроля версий.

---

## Дополнительная информация

### Команды управления Harbor (kubectl)

```bash
# Перезапуск компонентов
kubectl -n harbor rollout restart deployment harbor-core
kubectl -n harbor rollout restart deployment harbor-registry
kubectl -n harbor rollout restart deployment harbor-trivy

# Проверка статуса деплоя
kubectl -n harbor rollout status deployment harbor-core
# → deployment "harbor-core" successfully rolled out

# Масштабирование (для высоконагруженных сред)
kubectl -n harbor scale deployment harbor-core --replicas=2

# Обновление Harbor через Helm
helm upgrade harbor harbor/harbor \
  --namespace harbor \
  -f harbor-values.yaml \
  --timeout 10m \
  --wait
```

### Структура данных Harbor в K3s

| Путь | Назначение |
| :--- | :--- |
| `/mnt/data/registry/docker/` | Физическое хранение слоев и манифестов |
| `/mnt/data/database/` | PostgreSQL data directory |
| `/mnt/data/redis/` | Valkey/Redis data directory |
| `/mnt/data/ca_download/` | CA-сертификаты для репликации |

### Актуальность компонентов (август 2026)

| Компонент | Версия | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **Harbor** | v2.15.2 | Stable | Valkey вместо Redis, OCI 1.1 Referrers |
| **GitLab** | 19.2 | Stable | GitLab Secrets Manager (GA), нативная интеграция Harbor |
| **Trivy** | v0.52+ | Stable | Встроен в Harbor, EPSS-оценка уязвимостей |
| **Cosign** | v2.4.0 | Stable | Keyless подпись через OIDC |
| **Kaniko** | v1.28.2 | Active | Форк `osscontainertools/kaniko` |

### Предупреждения и риски

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **Valkey Migration** | Ошибки кэширования | Harbor 2.15+ использует Valkey. При обновлении с v2.14 убедитесь в отсутствии кастомных настроек Redis. |
| **OIDC Misconfiguration** | Отказ в доступе пайплайнам | Начинайте с робот-аккаунтов, переходите на OIDC только после валидации `id_tokens` в GitLab. |
| **Masked Variables** | Отображение секрета при ошибке | Всегда активируйте `Masked`. Убедитесь, что значение > 8 символов и не содержит пробелов. |
| **Срок действия CA** | Остановка всех пайплайнов | Мониторьте срок действия сертификата через `cert-manager` (Certificate resource). |
| **Размер образов** | Переполнение диска K3s | Настройте **Retention Policy** в Harbor для удаления старых тегов (например, старше 14 дней). |
| **Garbage Collection** | Временная недоступность при GC | Настройте GC на ночное время, чтобы не влиять на дневные пайплайны. |
| **Квоты проекта** | Блокировка push при превышении лимита | Установите разумные квоты (5-10 ГБ) для dev-проектов. |
| **Trivy DB** | Устаревшие базы уязвимостей | Настройте ежедневное обновление Trivy DB через CronJob. |

### См. также

- **Harbor:** [Обзор Harbor](../../../Docker/Docker_registries/Harbor/overview.md) -- компоненты, архитектура, OCI 1.1
- **GitLab CI:** [Переменные и секреты](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md) -- GitLab Secrets Manager, OIDC, иерархия переменных
- **Dev-окружение:** [Архитектура K3s](./k3s_architecture.md) -- общая архитектура лаборатории

---

## Крайние случаи и ограничения

### Сеть и DNS в K3s

| Случай | Проявление | Решение |
|--------|------------|---------|
| **CoreDNS не резолвит Harbor** | `dial tcp: lookup harbor.dev.local: no such host` | Добавьте `hostAliases` в values.yaml Runner или настройте CoreDNS rewriting |
| **Flannel overlay и Harbor** | Задержки при скачивании больших слоев (>500 МБ) | Используйте `host-gw` mode вместо VXLAN в Flannel |
| **ServiceLB конфликты** | Ingress NGINX и Harbor получают одинаковые NodePort | Явно укажите `nodePort` для Harbor или используйте `ClusterIP` + Ingress |
| **Self-signed CA в K3s** | Пада в статусе `ImagePullBackOff` | Убедитесь, что CA добавлен в секрет `harbor-ca-tls` и смонтирован в Runner |

### Ограничения Harbor в K3s

| Случай | Проявление | Решение |
|--------|------------|---------|
| **Valkey Migration** | Ошибки кэширования при обновлении с v2.14 | Harbor 2.15+ использует Valkey. При обновлении убедитесь в отсутствии кастомных настроек Redis в values.yaml |
| **Ограничение Loki/размера БД** | PostgreSQL заполняет диск | Настройте `persistence.size` для `harbor-database` не менее 10 ГБ |
| **GC во время пайплайна** | Временная недоступность образов | Настройте GC на ночное время (cron), убедитесь что Harbor не удаляет используемые теги |
| **Многопоточный push** | Конфликты при одновременном push одного образа | Используйте `mutex` в пайплайнах или уникальные теги (SHA) |
| **Project Quota exceeded** | `quota exceeded` при push | Увеличьте квоту проекта или настройте Retention Policy для удаления старых образов |

### Ограничения GitLab Runner в K3s

| Случай | Проявление | Решение |
|--------|------------|---------|
| **Pod Security Admission (PSA)** | Пода Runner не может стартовать | Убедитесь, что ServiceAccount имеет разрешения `pods/create`, `secrets/get` |
| **Сетевые политики** | Раннер не может достичь Harbor | Разрешите egress в namespace `harbor` для namespace `gitlab-runner` |
| **Ресурсы ноды** | Пода в статусе `Pending` из-за нехватки ресурсов | Увеличьте `resources.requests/limits` для задач или добавьте worker-узел |
| **containerd insecure registry** | Ошибка `x509: certificate signed by unknown authority` | Добавьте Harbor в `/etc/rancher/k3s/registries.yaml` на всех узлах |

## Дополнительная теоретическая информация

### Harbor Webhooks для интеграции с GitLab

Harbor поддерживает Webhook-уведомления о событиях в реестре, что позволяет реализовать реактивную логику в GitLab CI:

| Событие | Назначение | Пример использования |
|---------|------------|---------------------|
| **PUSH_ARTIFACT** | Новый образ опубликован | Запуск пайплайна тестирования в GitLab |
| **PULL_ARTIFACT** | Образ скачан | Логирование аудита |
| **SCANNING_COMPLETED** | Trivy завершил сканирование | Блокировка деплоя при наличии критических CVE |
| **GARBAGE_COLLECTION** | GC завершен | Уведомление команды о высвобождении диска |

**Пример настройки Webhook через Harbor API:**

```bash
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "event_types": ["PUSH_ARTIFACT", "SCANNING_COMPLETED"],
    "targets": [
      {
        "type": "http",
        "url": "https://gitlab.dev.local/api/v4/hooks/harbor-webhook",
        "skip_cert_verify": true
      }
    ],
    "notify_type": "http"
  }' \
  https://harbor.dev.local/api/v2.0/projects/my-project/webhook/policies
```

### Конфигурация containerd в K3s для работы с Harbor

K3s использует containerd как runtime. Для доступа к Harbor с самоподписанными сертификатами необходимо настроить `registries.yaml`:

```bash
# /etc/rancher/k3s/registries.yaml
mirrors:
  "harbor.dev.local":
    endpoint:
      - "https://harbor.dev.local"
configs:
  "harbor.dev.local":
    tls:
      ca_file: "/etc/rancher/k3s/harbor-ca.crt"

# Применение конфигурации
sudo systemctl restart k3s

# Проверка
sudo k3s crictl info | jq '.config.configPath'
# → "/etc/rancher/k3s/registries.yaml"
```

**Важно:** Файл `registries.yaml` должен быть идентичен на всех узлах кластера (server и agent). При использовании `hostPath` для хранения данных K3s конфиг автоматически реплицируется.

### Шаблоны GitLab CI для Harbor

Для повторного использования создайте GitLab CI Component с интеграцией Harbor:

**Файл `.gitlab-ci/components/harbor-integration.yml`:**

```yaml
spec:
  inputs:
    harbor_project:
      type: string
      default: "my-project"
    harbor_host:
      type: string
      default: "harbor.dev.local"

---
stages:
  - harbor-validate

harbor_connectivity:
  stage: harbor-validate
  image: curlimages/curl:latest
  script:
    - curl -sk -o /dev/null -w "%{http_code}" "https://$[[ inputs.harbor_host ]]/api/v2.0/health"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push"'
```

**Использование в `.gitlab-ci.yml`:**

```yaml
include:
  - component: gitlab.com/my-org/templates/harbor-integration@1.0.0
    inputs:
      harbor_project: production
      harbor_host: harbor.dev.local
```

### Управление квотами проекта

Для предотвращения переполнения хранилища настройте квоты через Harbor API:

```bash
curl -k -u admin:$(kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d) \
  -X PUT \
  -H "Content-Type: application/json" \
  -d '{
    "quota": {
      "count": 100,
      "storage": 10737418240
    }
  }' \
  https://harbor.dev.local/api/v2.0/projects/my-project
```

**Параметры:**
- `count`: максимальное количество артефактов (100)
- `storage`: лимит дискового пространства в байтах (10 ГБ = 10737418240)

### Ротация Robot Accounts

Для повышения безопасности периодически ротируйте пароли робот-аккаунтов:

```bash
# 1. Получение текущего пароля робота
kubectl -n harbor get secret harbor-core-secret -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d

# 2. Генерация нового секрета (в Harbor UI: Administration -> Robot Accounts -> Regenerate Secret)
# Или через API:

curl -k -u admin:<admin_password> \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-pipeline", "duration": -1}' \
  https://harbor.dev.local/api/v2.0/robots/my-project%2Fci-pipeline/secret
```

**Автоматизация через GitLab Schedule:**

```yaml
rotate_harbor_robot:
  stage: rotate
  image: curlimages/curl:latest
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
  script:
    - |
      NEW_SECRET=$(curl -sk -u admin:$HARBOR_ADMIN_PASSWORD \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{"name": "ci-pipeline", "duration": -1}' \
        "https://$HARBOR_HOST/api/v2.0/robots/$HARBOR_PROJECT%2Fci-pipeline/secret" | jq -r '.secret')
    - |
      curl --request PUT \
        --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
        --header "Content-Type: application/json" \
        --data "{\"value\": \"${NEW_SECRET}\", \"masked\": true, \"protected\": true}" \
        "https://gitlab.dev.local/api/v4/projects/${CI_PROJECT_ID}/variables/DEV_REGISTRY_PASSWORD"
  variables:
    HARBOR_ADMIN_PASSWORD:
      vault: harbor/admin-password
```
