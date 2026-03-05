# K3s Dev Environment: Архитектура и Обзор

> **Последнее обновление:** 2026-03-04
> **Версии компонентов:** Требуют проверки (см. [Актуальность версий](#актуальность-версий))

## Определения

**K3s Dev Environment** — самодостаточная лаборатория для изучения DevOps-практик на базе одного сервера с легковесным дистрибутивом Kubernetes **K3s**. Все вспомогательные сервисы (CI/CD, реестр, GitOps) запускаются внутри кластера.

**Dev-контейнер** — изолированное рабочее пространство в кластере: Docker-образ с SSH-сервером и инструментами разработки, развёрнутый как `Deployment` с персистентной домашней директорией через `hostPath`.

## Основные концепции

### Архитектура решения

В основе — один сервер (физический или виртуальный) с **K3s**. Вспомогательные сервисы запускаются внутри кластера.

**Ключевые компоненты:**

| Компонент | Назначение |
|-----------|------------|
| **Платформа** | K3s вместо "ванильного" Kubernetes для простоты на одном узле | [Kubernetes Overview](../../kubernetes_overview.md) |
| **Ingress Controller** | NGINX вместо стандартного Traefik | [Ingress Overview](../../Networking/Ingress/overview.md) |
| **Хранилище** | Local Path Provisioner (только `ReadWriteOnce`, для однонодовых кластеров) | [Local Path Provisioner](../../Storage/local-path-provisioner.md) |
| **CI/CD** | GitLab для хранения кода и автоматизации пайплайнов | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) |
| **GitOps** | ArgoCD для декларативного развёртывания | [ArgoCD Overview](../../../GitOps/ArgoCD/argocd_overview.md) |
| **Реестр** | Harbor для Docker-образов и Helm-чартов (вместо встроенного реестра GitLab) | [Harbor Overview](../../../Docker/Docker_registries/Harbor/overview.md) |
| **S3** | Minio для объектного хранения артефактов | — |
| **БД** | PostgreSQL как основная реляционная СУБД | [PostgreSQL Overview](../../../Databases/PostgreSQL/postgresql_overview.md) |

### Рабочий процесс "Dev-контейнер"

**Принцип:** Отказ от установки инструментов разработки на хост или локальные машины.

**Процесс:**

1. **Создание образа** — Docker-образ на базе Ubuntu с SSH-сервером и инструментами (Go, Python, Java, SDK).
2. **Развёртывание в K3s** — запуск как `Deployment` с `hostPath` Volume.
3. **Персистентность** — домашняя директория (`/home/user`) монтируется с хоста, данные переживают перезапуски.
4. **Удалённая разработка** — подключение через **VS Code Remote - SSH** (локальная машина как "тонкий клиент").

**Преимущества:**
- Унифицированная среда независимо от ОС разработчика
- Изоляция инструментов от хоста
- Воспроизводимость окружения

### Связанные документы

| Файл | Описание |
|------|----------|
| [`dev_container_ssh.md`](./dev_container_ssh.md) | Создание Docker-образа с SSH |
| [`dev_container_helm_deployment.md`](./dev_container_helm_deployment.md) | Развёртывание через Helm и ArgoCD |
| [`kubeutils_image.md`](./kubeutils_image.md) | Вспомогательный образ с kubectl/helm/regclient |
| [`gitlab_harbor_integration.md`](./gitlab_harbor_integration.md) | Настройка GitLab и интеграция с Harbor |

## Практические сценарии

### Типовая последовательность развёртывания

1. Установка K3s на сервер
2. Замена Traefik на NGINX Ingress Controller
3. Развёртывание Harbor и GitLab
4. Настройка интеграции GitLab ↔ Harbor
5. Создание образа `kubeutils` для пайплайнов
6. Создание и развёртывание `dev-container`
7. Подключение через SSH и начало работы

## Дополнительная информация

### Актуальность версий

> **Требует проверки:** В файлах указаны версии 2024 года. Перед развёртыванием проверьте актуальные стабильные версии:
> - K3s: проверить на [release.k3s.io](https://github.com/k3s-io/k3s/releases)
> - Kubernetes: [v1.28.6](https://kubernetes.io/releases/) (указан в `kubeutils_image.md`) — устарел, рекомендуется v1.31+
> - Helm: [v3.13.0](https://github.com/helm/helm/releases) — проверить актуальность
> - regclient: [v0.5.6](https://github.com/regclient/regclient/releases) — проверить актуальность
> - kubeconform: [v0.6.4](https://github.com/yannh/kubeconform/releases) — проверить актуальность

### Ограничения Local Path Provisioner

- **Не поддерживает `ReadWriteMany`** — только для однонодовых кластеров или StatefulSet с одним репликом на узел
- **Данные привязаны к узлу** — при перемещении пода доступ к данным теряется
- **Нет контроля ёмкости** — приложение использует всё доступное пространство

Подробности: [Local Path Provisioner](../../Storage/local-path-provisioner.md)

### Безопасность hostPath

> **Внимание:** Использование `hostPath` небезопасно в production. Допустимо только для локальных dev-сред. См. [Pod Volumes](../../Base/Pod/pod_volumes.md).
