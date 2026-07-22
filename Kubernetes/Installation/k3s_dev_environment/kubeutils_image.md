# Вспомогательный образ Kubeutils

Руководство по созданию универсального образа с утилитами для работы с Kubernetes в пайплайнах CI/CD. Образ используется для сборки, валидации и развертывания приложений в кластере K3s.

Контекст: Часть серии по созданию dev-окружения в K3s. Образ используется в пайплайнах GitLab CI для взаимодействия с Harbor и Kubernetes. См. [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Kubeutils** | Вспомогательный образ с набором утилит CLI: `kubectl`, `helm`, `regctl`, `kubeconform`. Используется в CI/CD для работы с Kubernetes |
| **Kaniko** | Инструмент сборки Docker-образов без демона Docker. Запускается в контейнере, идеален для Kubernetes. См. [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md) |
| **Build Args** | Переменные, передаваемые в Dockerfile во время сборки. Позволяют кастомизировать версии утилит |
| **OCI** | Open Container Initiative — стандарт для форматов образов и сред выполнения контейнеров |

Навигация: [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md) | [Docker Best Practices](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md) | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)

---

## Основные концепции

### Назначение образа

Образ `kubeutils` предоставляет единое окружение для выполнения задач в пайплайнах:

| Утилита | Назначение |
|---------|------------|
| **`kubectl`** | Взаимодействие с Kubernetes API (развертывание, диагностика) |
| **`helm`** | Управление Helm-чартами (установка, обновление, откат) |
| **`regctl`** | Работа с OCI реестрами (тегирование, копирование образов) |
| **`kubeconform`** | Валидация манифестов Kubernetes против схем API |

Преимущества единого образа:

- **Воспроизводимость:** Одинаковые версии утилит во всех пайплайнах, что исключает ошибки из-за разницы версий в разных окружениях.
- **Скорость:** Не требуется установка утилит в каждом джобе, образ содержит все необходимое и готов к выполнению команд сразу.
- **Безопасность:** Централизованное обновление версий, контроль состава инструментов и возможность сканирования единого базового образа на уязвимости.
- **Масштабируемость:** Легкое расширение набора инструментов для всех проектных команд путем обновления одного Dockerfile.

### Почему Kaniko для сборки?

В средах CI/CD (GitLab CI, Kubernetes) доступ к Docker-демону часто ограничен по соображениям безопасности или из-за особенностей инфраструктуры.

| Подход | Требования | Безопасность | Особенности |
|--------|------------|--------------|-------------|
| **Docker-in-Docker (dind)** | Привилегированный режим | Низкая | Требует `--privileged`, что открывает доступ к хост-системе |
| **Docker-outside-of-Docker (DooD)** | Доступ к `/var/run/docker.sock` | Низкая | Контейнер может управлять всеми образами и контейнерами хоста |
| **Kaniko** | Непривилегированный контейнер | Высокая | Работает в userspace, не требует демон или привилегии |

Kaniko:
- Выполняет команды Dockerfile внутри файловой системы контейнера.
- Не зависит от Docker-демона.
- Работает в стандартных (непривилегированных) подах Kubernetes.
- С 2025 года рекомендуется использовать форк `osscontainertools/kaniko`, так как оригинальный проект архивирован.

### Выбор базового образа

Alpine Linux является стандартом де-факто для подобных утилит благодаря:

- **Минимальному размеру:** Базовый образ ~5 МБ, итоговый образ с утилитами остается компактным.
- **Безопасности:** Меньшее количество установленных пакетов снижает риск наличия известных уязвимостей.
- **Совместимости:** Статические бинарники (Go) большинства облачных утилит отлично работают в среде musl.

Best practices:
- Использование `--no-cache` для менеджера пакетов `apk`.
- Объединение команд установки в один слой `RUN` для уменьшения метаданных образа.
- **Принцип наименьших привилегий:** Запуск всех процессов от не-root пользователя.

---

## Практические сценарии

### Dockerfile для kubeutils

Dockerfile обновлен до актуальных версий (июль 2026) и включает настройку безопасности.

```dockerfile
# Аргументы для управления версиями
ARG ALPINE_VERSION=3.24.1
ARG KUBE_VERSION=v1.36.2
ARG HELM_VERSION=v4.2.3
ARG REGCLIENT_VERSION=v0.11.5
ARG KUBECONFORM_VERSION=v0.8.0

FROM alpine:${ALPINE_VERSION}

# Установка системных зависимостей
RUN apk add --no-cache ca-certificates curl git bash tar

# Создание непривилегированного пользователя
RUN addgroup -S kubeuser && adduser -S kubeuser -G kubeuser

# Установка бинарных файлов утилит
RUN set -x && \
    ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    # kubectl
    curl -LO "https://dl.k8s.io/release/${KUBE_VERSION}/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/ && \
    # Helm
    curl -L "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz" | tar -xzO linux-${ARCH}/helm > /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm && \
    # regclient (regctl)
    curl -L "https://github.com/regclient/regclient/releases/download/${REGCLIENT_VERSION}/regctl-linux-${ARCH}" -o /usr/local/bin/regctl && \
    chmod +x /usr/local/bin/regctl && \
    # kubeconform
    curl -L "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-${ARCH}.tar.gz" | tar -xzO kubeconform > /usr/local/bin/kubeconform && \
    chmod +x /usr/local/bin/kubeconform

# Настройка рабочего окружения
USER kubeuser
WORKDIR /home/kubeuser

# Валидация установки
RUN kubectl version --client && helm version && regctl version && kubeconform -v
```

### GitLab CI пайплайн для сборки

Пример сборки образа с использованием Kaniko (форк `osscontainertools`).

```yaml
build:
  stage: build
  image:
    name: osscontainertools/kaniko:v1.28.0-debug
    entrypoint: [""]
  tags:
    - global
  variables:
    KUBE_VERSION: "v1.36.2"
    HELM_VERSION: "v4.2.3"
  script:
    # 1. Настройка аутентификации в реестре Harbor
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$dev.registry\":{\"username\":\"$dev.registry-user\",\"password\":\"$dev.registry-password\"}}}" > /kaniko/.docker/config.json
    # 2. Сборка и отправка образа с несколькими тегами
    - /kaniko/executor \
        --context "dir://$CI_PROJECT_DIR" \
        --dockerfile $CI_PROJECT_DIR/Dockerfile \
        --destination "$dev.registry/library/kube-utils:latest" \
        --destination "$dev.registry/library/kube-utils:${CI_COMMIT_TAG:-$KUBE_VERSION}" \
        --build-arg KUBE_VERSION=${KUBE_VERSION} \
        --build-arg HELM_VERSION=${HELM_VERSION} \
        --registry-certificate $dev.se
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
```

### Использование в пайплайнах

Пример джоба для развертывания в Kubernetes с использованием образа `kubeutils`.

```yaml
deploy:
  stage: deploy
  image: $dev.registry/library/kube-utils:v1.36.2
  script:
    # Валидация манифестов перед применением
    - kubeconform -strict -ignore-missing-schemas manifests/
    # Развертывание или обновление приложения
    - helm upgrade --install myapp ./chart \
        --namespace production \
        --atomic \
        --wait \
        --timeout 300s
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## Дополнительная информация

### Актуальность компонентов (июль 2026)

Версии ниже являются стабильными и рекомендуемыми для использования в продакшен-пайплайнах.

| Компонент | Текущая версия | Статус | Рекомендация |
|-----------|----------------|--------|--------------|
| **Alpine Linux** | 3.24.1 | Stable | Релиз от июня 2026 |
| **Kubernetes (kubectl)** | v1.36.2 | Stable | [Kubernetes Releases](https://kubernetes.io/releases/) |
| **Helm** | v4.2.3 | Stable | [Helm Releases](https://github.com/helm/helm/releases) |
| **regclient (regctl)** | v0.11.5 | Stable | [regclient Releases](https://github.com/regclient/regclient/releases) |
| **kubeconform** | v0.8.0 | Stable | [kubeconform Releases](https://github.com/yannh/kubeconform/releases) |
| **Kaniko (fork)** | v1.28.0 | Active | Используйте `osscontainertools/kaniko` |

### Связанные темы

- **Kaniko:** [Обзор Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md), [Оптимизация сборки](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md)
- **Безопасность:** [Безопасность Dockerfile](../../../Docker/Dockerfile/Docker_best_practices/security.md)
- **GitLab CI:** [Основы GitLab CI](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md), [Интеграция с Kubernetes](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
- **Dev-окружение:** [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md)

### Предупреждения

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **Устаревшие версии** | Наличие CVE в утилитах и базовом образе | Настройте регулярное (ежемесячное) сканирование и обновление |
| **Alpine base** | Проблемы с glibc-зависимыми бинарниками | Используйте только статические бинарники или добавляйте `gcompat` |
| **Права доступа** | Ошибки при записи в `/home/kubeuser` в CI | Убедитесь, что пайплайн не требует записи в системные папки под `kubeuser` |
| **TLS/SSL** | Ошибки сертификатов при работе с Harbor | Всегда передавайте `--registry-certificate` в Kaniko для внутренних CA |
