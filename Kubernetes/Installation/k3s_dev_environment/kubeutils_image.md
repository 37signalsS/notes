# Вспомогательный образ Kubeutils

Руководство по созданию универсального образа с утилитами для работы с Kubernetes в CI/CD-пайплайнах. Образ используется для сборки, валидации и развертывания приложений в кластере K3s.

> **Контекст:** Часть серии по созданию dev-окружения в K3s. Образ используется в пайплайнах GitLab CI для взаимодействия с Harbor и Kubernetes. См. [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Kubeutils** | Вспомогательный образ с набором CLI-утилит: `kubectl`, `helm`, `regctl`, `kubeconform`. Используется в CI/CD для работы с Kubernetes |
| **Kaniko** | Инструмент сборки Docker-образов без демона Docker. Запускается в контейнере, идеален для Kubernetes. См. [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md) |
| **Build Args** | Переменные, передаваемые в Dockerfile во время сборки. Позволяют кастомизировать версии утилит |

**Навигация:** [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md) | [Docker Best Practices](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md) | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)

---

## Основные концепции

### Назначение образа

Образ `kubeutils` предоставляет единое окружение для выполнения задач в пайплайнах:

| Утилита | Назначение |
|---------|------------|
| **`kubectl`** | Взаимодействие с Kubernetes API (развертывание, диагностика) |
| **`helm`** | Управление Helm-чартами (установка, обновление, откат) |
| **`regctl`** | Работа с OCI-реестрами (тегирование, копирование образов) |
| **`kubeconform`** | Валидация манифестов Kubernetes против схем API |

**Преимущества единого образа:**

- **Воспроизводимость:** Одинаковые версии утилит во всех пайплайнах
- **Скорость:** Не требуется установка утилит в каждом джобе
- **Безопасность:** Централизованное обновление и контроль версий

### Почему Kaniko для сборки?

В CI/CD-средах (GitLab CI, Kubernetes) доступ к Docker-демону ограничен или отсутствует.

| Подход | Требования | Безопасность |
|--------|------------|--------------|
| **Docker-in-Docker (dind)** | Привилегированный режим | ⚠️ Низкая |
| **Docker socket binding** | Доступ к `/var/run/docker.sock` | ⚠️ Низкая |
| **Kaniko** | Непривилегированный контейнер | ✓ Высокая |

**Kaniko:**

- Выполняет команды `Dockerfile` в userspace
- Не требует Docker-демона
- Работает в непривилегированных подах Kubernetes

Подробности в [Kaniko Overview](../../../Docker/Dockerfile/dockerfile_kaniko.md).

### Выбор базового образа

**Alpine Linux** выбран по причинам:

- **Минимальный размер:** ~5MB базовый образ
- **Безопасность:** Меньшая поверхность атаки
- **Совместимость:** Статические бинарники утилит работают без проблем

**Best practices:**

- Использование `--no-install-recommends` для минимизации размера
- Очистка кэша в том же слое `RUN`
- Объединение команд для уменьшения количества слоев

---

## Практические сценарии

### Dockerfile для kubeutils

```dockerfile
# Версии утилит передаются как build-args
ARG KUBE_VERSION=v1.28.6
ARG HELM_VERSION=v3.13.0
ARG REGCLIENT_VERSION=v0.5.6
ARG KUBECONFORM_VERSION=v0.6.4

FROM alpine:3.18

# Установка kubectl
RUN wget -q "https://dl.k8s.io/release/${KUBE_VERSION}/bin/linux/amd64/kubectl" -O /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# Установка Helm
RUN wget -q "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" -O - | tar -xzO linux-amd64/helm > /usr/local/bin/helm && \
    chmod +x /usr/local/bin/helm

# Установка regclient
RUN wget -q "https://github.com/regclient/regclient/releases/download/${REGCLIENT_VERSION}/regctl-linux-amd64" -O /usr/local/bin/regctl && \
    chmod +x /usr/local/bin/regctl

# Установка kubeconform
RUN wget -q "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" -O - | tar -xzO kubeconform > /usr/local/bin/kubeconform && \
    chmod +x /usr/local/bin/kubeconform

# Проверка версий
RUN kubectl version --client && helm version && regctl version && kubeconform -v
```

**Оптимизации:**

- Загрузка напрямую в `/usr/local/bin` — без промежуточных копий
- Объединение `wget` и `chmod` в один слой
- Использование `-q` для уменьшения размера логов сборки

### GitLab CI пайплайн для сборки

Сборка осуществляется с помощью Kaniko. Пайплайн запускается вручную.

```yaml
build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:v1.9.0-debug
    entrypoint: [""]
  tags:
    - global # Тег вашего GitLab Runner
  script:
    # 1. Подготовка аутентификации для Kaniko
    - echo "{\"auths\":{\"$dev.registry\":{\"username\":\"$dev.registry-user\",\"password\":\"$dev.registry-password\"}}}" > /kaniko/.docker/config.json
    # 2. Сборка и push образа
    - /kaniko/executor \
        --context $CI_PROJECT_DIR \
        --dockerfile $CI_PROJECT_DIR/Dockerfile \
        --destination "$dev.registry/library/kube-utils:${CI_COMMIT_TAG:-$KUBE_VERSION}" \
        --build-arg KUBE_VERSION=${KUBE_VERSION} \
        --build-arg HELM_VERSION=${HELM_VERSION} \
        --registry-certificate $dev.se
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
  variables:
    KUBE_VERSION: "v1.28.6"
    HELM_VERSION: "v3.13.0"
```

**Ключевые моменты:**

| Параметр | Описание |
|----------|----------|
| `entrypoint: [""]` | Отменяет точку входа Kaniko для выполнения script |
| `--destination` | Целевой реестр и тег образа |
| `--registry-certificate` | CA-сертификат для доверия к Harbor (переменная `dev.se`) |
| `${CI_COMMIT_TAG:-$KUBE_VERSION}` | Тег по коммиту или версии kubectl |

### Использование в пайплайнах

Пример джоба для развертывания в Kubernetes:

```yaml
deploy:
  stage: deploy
  image: $dev.registry/library/kube-utils:v1.28.6
  script:
    # Валидация манифестов
    - kubeconform -strict manifests/
    # Развертывание через Helm
    - helm upgrade --install myapp ./chart \
        --namespace production \
        --atomic \
        --wait
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

---

## Дополнительная информация

### Актуальность версий

> **Внимание:** Указанные версии компонентов относятся к 2024 году. Перед использованием проверьте актуальные стабильные версии:

| Компонент | Указанная версия | Статус | Рекомендация |
|-----------|------------------|--------|--------------|
| **Kubernetes (kubectl)** | v1.28.6 | ⚠️ Устарел | Рекомендуется v1.31+ |
| **Helm** | v3.13.0 | ⚠️ Проверить | [GitHub Releases](https://github.com/helm/helm/releases) |
| **regclient** | v0.5.6 | ⚠️ Проверить | [GitHub Releases](https://github.com/regclient/regclient/releases) |
| **kubeconform** | v0.6.4 | ⚠️ Проверить | [GitHub Releases](https://github.com/yannh/kubeconform/releases) |
| **Alpine** | 3.18 | ⚠️ Проверить | [Alpine Releases](https://alpinelinux.org/releases/) |

**Проверка версий:**

- K3s: [release.k3s.io](https://github.com/k3s-io/k3s/releases)
- Kubernetes: [kubernetes.io/releases/](https://kubernetes.io/releases/)

### Связанные темы

- **Kaniko:** [Обзор Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md), [Best Practices](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md)
- **Безопасность:** [Dockerfile Security](../../../Docker/Dockerfile/Docker_best_practices/security.md)
- **GitLab CI:** [Основы GitLab CI](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md), [Kubernetes Integration](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
- **Dev-окружение:** [Архитектура K3s](./k3s_architecture.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md)

### Предупреждения

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **Устаревшие версии** | CVE в утилитах | Регулярно обновляйте версии |
| **Alpine base** | Проблемы с glibc | Используйте статические бинарники |
| **Hardcoded версии** | Рассинхронизация | Выносите версии в variables пайплайна |
