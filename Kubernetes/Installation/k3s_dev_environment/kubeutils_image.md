# Вспомогательный образ Kubeutils

Руководство по созданию универсального образа с утилитами для работы с Kubernetes в пайплайнах CI/CD. Образ используется для сборки, валидации и развертывания приложений в кластере K3s.

Контекст: Часть серии по созданию dev-окружения в K3s. Образ используется в пайплайнах GitLab CI для взаимодействия с Harbor и Kubernetes. См. [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Kubeutils** | Вспомогательный образ с набором утилит CLI: `kubectl`, `helm`, `regctl`, `kubeconform`. Используется в CI/CD для управления жизненным циклом приложений в Kubernetes. |
| **Kaniko** | Инструмент для сборки образов контейнеров внутри контейнера или Kubernetes без зависимости от Docker-демона. Стандарт безопасности для современных CI/CD систем. См. [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md). |
| **Build Args** | Переменные, передаваемые в Dockerfile во время сборки (`--build-arg`). Позволяют изменять версии утилит без правки кода Dockerfile. |
| **SBOM (Software Bill of Materials)** | Полный перечень всех программных компонентов и зависимостей в образе. Необходим для аудита безопасности. |
| **OCI (Open Container Initiative)** | Стандарт для форматов образов и сред выполнения, обеспечивающий совместимость между Docker, Podman и другими инструментами. |

Навигация: [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md) | [Docker Best Practices](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md) | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)

---

## Основные концепции

### Назначение и преимущества образа

Образ `kubeutils` предоставляет единое, воспроизводимое окружение для выполнения задач в пайплайнах:

| Утилита | Назначение в пайплайне |
| :--- | :--- |
| **`kubectl`** | Взаимодействие с API Kubernetes (развертывание, диагностика, управление ресурсами). |
| **`helm`** | Управление Helm-чартами (установка, обновление, откат, шаблонизация). |
| **`regctl`** | Работа с OCI реестрами (тегирование, копирование образов, инспекция манифестов без Docker). |
| **`kubeconform`** | Валидация манифестов Kubernetes против схем API (OpenAPI), замена устаревшего `kubeval`. |

**Преимущества единого образа:**
- **Воспроизводимость:** Одинаковые версии инструментов во всех проектах исключают ошибки "разницы версий".
- **Скорость:** Исключается этап установки инструментов в каждом джобе пайплайна.
- **Безопасность:** Централизованное обновление версий и сканирование единого базового образа на CVE.
- **Масштабируемость:** Легкое расширение набора инструментов для всей компании через обновление одного репозитория.

### Почему Kaniko для сборки?

В средах Kubernetes и GitLab CI доступ к Docker-демону ограничен. Kaniko решает проблемы безопасности и архитектуры.

| Подход | Требования | Безопасность | Особенности |
| :--- | :--- | :--- | :--- |
| **Docker-in-Docker (dind)** | Привилегированный режим | Низкая | Требует `--privileged`, что опасно в мультитеннантных кластерах. |
| **Docker-outside-of-Docker (DooD)** | Монтирование `docker.sock` | Низкая | Контейнер получает полный контроль над хостовым Docker. |
| **Kaniko** | Стандартный контейнер | Высокая | Работает в userspace, не требует демон или привилегии ядра. |

**Особенности Kaniko:**
- Выполняет инструкции Dockerfile внутри файловой системы контейнера без демона.
- Идеально подходит для **Pod Security Standards: Restricted**.
- С июня 2025 года (после архивации проекта Google) стандартом является форк от сообщества — **`osscontainertools/kaniko`**.

### Выбор базового образа (Alpine Linux)

Alpine Linux остается оптимальным выбором для утилит благодаря:
- **Минимальному размеру:** Базовый слой ~5 МБ. Итоговый образ с утилитами остается компактным, что ускоряет `pull` в пайплайнах.
- **Безопасности:** Меньшее количество пакетов снижает поверхность атаки.
- **Совместимости:** Большинство облачных инструментов (Go-бинарники) работают в среде `musl` напрямую или через `gcompat`.

### Безопасность цепочки поставок (Supply Chain)

В 2026 году образ должен соответствовать стандартам безопасности:
1.  **Non-root:** Запуск процессов от пользователя с UID 1000.
2.  **SBOM Generation:** Генерация спецификации состава (например, через Syft в пайплайне) для загрузки в Harbor.
3.  **Image Signing:** Подпись образа через Cosign для гарантии того, что в кластер попадет именно тот артефакт, который прошел CI.

---

## Практические сценарии

### Dockerfile для kubeutils (Версия Август 2026)

Dockerfile поддерживает многоплатформенность (`amd64`/`arm64`) и настройку безопасности.

```dockerfile
# Аргументы для управления версиями
ARG ALPINE_VERSION=3.24.1
ARG KUBE_VERSION=v1.36.3
ARG HELM_VERSION=v4.2.3
ARG REGCLIENT_VERSION=v0.11.5
ARG KUBECONFORM_VERSION=v0.8.0

FROM alpine:${ALPINE_VERSION}

# Установка системных зависимостей (только необходимые)
RUN apk add --no-cache ca-certificates curl git bash tar gzip

# Создание непривилегированного системного пользователя
RUN addgroup -S kube && adduser -S kube -G kube

# Установка бинарных файлов утилит
RUN set -x && \
    ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    # 1. Kubectl (August 2026 release)
    curl -LO "https://dl.k8s.io/release/${KUBE_VERSION}/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    # 2. Helm v4
    curl -L "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz" | tar -xzO linux-${ARCH}/helm > /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && \
    # 3. regclient (regctl)
    curl -L "https://github.com/regclient/regclient/releases/download/${REGCLIENT_VERSION}/regctl-linux-${ARCH}" -o /usr/local/bin/regctl && \
    chmod +x /usr/local/bin/regctl && \
    # 4. kubeconform
    curl -L "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-${ARCH}.tar.gz" | tar -xzO kubeconform > /usr/local/bin/kubeconform && \
    chmod +x /usr/local/bin/kubeconform

# Настройка рабочего окружения
USER kube
WORKDIR /home/kube

# Валидация установки
RUN kubectl version --client && \
    helm version && \
    regctl version && \
    kubeconform -v
```

### GitLab CI пайплайн для сборки (Kaniko + Multi-tag)

Пример сборки с использованием актуального форка Kaniko и поддержкой Registry Harbor.

```yaml
build-kubeutils:
  stage: build
  image:
    name: osscontainertools/kaniko:v1.28.2-debug
    entrypoint: [""]
  tags:
    - global
  variables:
    KUBE_VERSION: "v1.36.3"
    HELM_VERSION: "v4.2.3"
  script:
    # 1. Настройка аутентификации в Harbor
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$INTERNAL_REGISTRY\":{\"username\":\"$REGISTRY_USER\",\"password\":\"$REGISTRY_PASS\"}}}" > /kaniko/.docker/config.json
    
    # 2. Сборка и отправка
    - /kaniko/executor \
        --context "dir://$CI_PROJECT_DIR" \
        --dockerfile "$CI_PROJECT_DIR/Dockerfile" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:latest" \
        --destination "$INTERNAL_REGISTRY/library/kubeutils:$KUBE_VERSION" \
        --build-arg KUBE_VERSION=$KUBE_VERSION \
        --build-arg HELM_VERSION=$HELM_VERSION \
        --registry-mirror "proxy.registry.local" \
        --registry-certificate /path/to/internal-ca.crt # Если используется свой CA
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

### Использование в пайплайнах (Валидация и Деплой)

Пример использования образа для проверки манифестов и развертывания через Helm.

```yaml
deploy-app:
  stage: deploy
  image: $INTERNAL_REGISTRY/library/kubeutils:v1.36.3
  script:
    # Валидация манифестов (строгий режим)
    - kubeconform -strict -ignore-missing-schemas manifests/
    
    # Деплой с ожиданием готовности
    - helm upgrade --install my-app ./chart \
        --namespace production \
        --atomic \
        --wait \
        --timeout 300s
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## Дополнительная информация

### Актуальность компонентов (август 2026)

| Компонент | Версия | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Alpine Linux** | 3.24.1 | Stable | Релиз от июня 2026. Актуальная ветка 3.24. |
| **Kubernetes (kubectl)** | v1.36.3 | Stable | Выпуск от 6 августа 2026. Полная поддержка API 1.36. |
| **Helm** | v4.2.3 | Stable | Мажорная версия v4 (прекращена поддержка v2/v3 в новых инсталляциях). |
| **regclient (regctl)** | v0.11.5 | Stable | Легковесная альтернатива Docker CLI для CI. |
| **kubeconform** | v0.8.0 | Stable | Стандарт де-факто для валидации схем OpenAPI. |
| **Kaniko (fork)** | v1.28.2 | Active | Используйте `osscontainertools/kaniko`. |

### См. также

- **Kaniko:** [Обзор Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md), [Оптимизация сборки](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md).
- **Безопасность:** [Безопасность Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md), [Supply Chain Security](../../../Security/supply_chain_security.md).
- **GitLab CI:** [Основы GitLab CI](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md), [Интеграция с Kubernetes](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md).
- **Dev-окружение:** [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **Устаревшие версии** | Уязвимости (CVE) в утилитах. | Настройте ежемесячное обновление образа через CI Scheduler. |
| **glibc зависимость** | Несовместимость некоторых бинарников с Alpine. | Используйте только статические бинарники или устанавливайте `gcompat`. |
| **Права доступа** | Ошибки записи в CI (например, Helm cache). | Helm в образе настроен на работу от `kube`, убедитесь в наличии прав на `/home/kube`. |
| **TLS/SSL** | Ошибки сертификатов Harbor. | Всегда передавайте `--registry-certificate` или монтируйте CA в `/kaniko/ssl/certs/`. |
| **Лимиты ресурсов** | `OOMKilled` при валидации больших чартов. | Выделяйте не менее 512Mi RAM для джобов с `kubeconform`. |
