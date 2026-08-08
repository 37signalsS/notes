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
| **GitLab Secrets Manager** | Встроенное решение (с v19.0), позволяющее централизованно хранить секреты с привязкой к ролям и аудитом, заменяя обычные CI/CD переменные. |
| **OIDC Federation** | Метод беспарольной аутентификации, при котором GitLab выступает провайдером личности для Harbor через JWT-токены. |
| **Kaniko / Buildah** | Инструменты для сборки OCI-образов внутри Kubernetes без использования привилегированного режима (Docker-in-Docker). |

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
└─────────────────────────────────────────────────────────────┘
```

### Проблема конфликта встроенного и внешнего реестров

При использовании официального Helm-чарта GitLab (`gitlab/gitlab`) критически важно отключить компонент Registry в **двух независимых секциях** конфигурации. 

**Причина:** Параметр `global.registry.enabled: false` отключает отображение реестра в UI и логику Rails, но сам микросервис `registry` может продолжать запускаться и занимать ресурсы, если не указано `registry: { enabled: false }`.

**Симптомы некорректной настройки:**
- Ошибки аутентификации в пайплайнах (Runner пытается обратиться к `registry.gitlab.svc`).
- Конфликты в Ingress-контроллере при совпадении доменов.
- Бесполезное потребление CPU/RAM подом реестра.

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
    externalUrl: https://harbor.example.com

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
```

### 2. Централизованная настройка доступа к Harbor

#### Вариант А: Нативная интеграция (Рекомендуется)

1. В Harbor: создайте **Robot Account** (Project level) с правами `push` и `pull`.
2. В GitLab: **Settings > Integrations > Harbor**.
3. Укажите URL Harbor, имя проекта и данные робот-аккаунта.
4. В пайплайнах автоматически станут доступны переменные: `$HARBOR_HOST`, `$HARBOR_USERNAME`, `$HARBOR_PASSWORD`.

#### Вариант Б: GitLab Secrets Manager (GitLab 19.x+)

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

#### Вариант В: Group-level Variables (Традиционный)

Для обратной совместимости или простых окружений. Настройте в **Group → Settings → CI/CD → Variables**.

| Ключ | Значение | Тип | Опции | Описание |
|------|----------|-----|-------|----------|
| `DEV_REGISTRY` | `harbor.example.com` | `Variable` | — | FQDN адрес Harbor |
| `DEV_REGISTRY_USER` | `robot$ci-pipeline` | `Variable` | `Masked` | Робот-аккаунт Harbor |
| `DEV_REGISTRY_PASSWORD` | `<token>` | `Variable` | `Masked`, `Protected` | Пароль робота |
| `DEV_CA_CERT` | (содержимое `ca.crt`) | `File` | — | Root CA Harbor |

### 3. Безопасная сборка с Kaniko

Использование Kaniko исключает необходимость `privileged: true` для ранеров и корректно работает с Harbor.

```yaml
# .gitlab-ci.yml
image-build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  variables:
    DOCKER_IMAGE: $HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME:$CI_COMMIT_SHORT_SHA
  script:
    # Подготовка конфига для Kaniko (через переменные нативной интеграции)
    - echo "{\"auths\":{\"$HARBOR_HOST\":{\"auth\":\"$(echo -n $HARBOR_USERNAME:$HARBOR_PASSWORD | base64)\"}}}" > /kaniko/.docker/config.json
    # Импорт CA-сертификата (если Harbor самоподписанный)
    - |
      if [ -f "$DEV_CA_CERT" ]; then
        cp "$DEV_CA_CERT" /kaniko/ssl/certs/ca-certificates.crt
      fi
    # Сборка и автоматический пуш
    - /kaniko/executor
      --context "$CI_PROJECT_DIR"
      --dockerfile "$CI_PROJECT_DIR/Dockerfile"
      --destination "$DOCKER_IMAGE"
```

### 4. Извлечение CA-сертификата для GitLab

Если ваш Harbor использует TLS, выданный внутренним `cert-manager` кластера K3s, получите его следующей командой:

```bash
# Для сертификатов, выданных через CA Issuer
kubectl get secret harbor-ca-tls -n harbor \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > harbor-ca.crt
```

Скопируйте содержимое `harbor-ca.crt` в переменную `DEV_CA_CERT` типа `File` или загрузите в Secrets Manager.

---

## Дополнительная информация

### Связанные темы

- **Установка GitLab:** [Helm Installation](../gitlab_kubernetes_helm_installation.md), [Offline Mode](../gitlab_offline_kubernetes_installation.md).
- **Harbor:** [Обзор Harbor](../../../Docker/Docker_registries/Harbor/overview.md), [Сертификаты и TLS](../../../Docker/Docker_registries/Harbor/certificates.md).
- **Безопасность CI/CD:** [Переменные и секреты](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md), [DevSecOps Overview](../../../CI-CD/DevSecOps/devsecops_overview.md).

### Предупреждения и риски

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **Valkey Migration** | Ошибки кэширования | Harbor 2.15+ использует Valkey. При обновлении с v2.14 убедитесь в отсутствии кастомных настроек Redis. |
| **OIDC Misconfiguration** | Отказ в доступе пайплайнам | Начинайте с робот-аккаунтов, переходите на OIDC только после валидации `id_tokens` в GitLab. |
| **Masked Variables** | Отображение секрета при ошибке | Всегда активируйте `Masked`. Убедитесь, что значение > 8 символов и не содержит пробелов. |
| **Срок действия CA** | Остановка всех пайплайнов | Мониторьте срок действия сертификата через `cert-manager` (Certificate resource). |
| **Размер образов** | Переполнение диска K3s | Настройте **Retention Policy** в Harbor для удаления старых тегов (например, старше 14 дней). |

### Сравнение альтернативных подходов

| Подход | Когда использовать | Плюсы | Минусы |
|--------|-------------------|-------|--------|
| **Harbor (OCI)** | Enterprise / Dev-кластер | Максимальная безопасность (Vulnerability Gates), кэш, Helm | Требует отдельного управления |
| **GitLab Registry** | Мини-проекты | Нет доп. сущностей, всё в одном UI | Нет кэша, слабая безопасность, нагрузка на GitLab |
| **Nexus OSS** | Смешанные артефакты (Maven, NPM) | Универсальность | Тяжеловесный, менее удобный для OCI/Cloud-native |
| **Cloud Registry** | Облачный K8s (EKS/GKE) | Нулевое администрирование | Затраты на трафик и хранение, вне вашего контура |
