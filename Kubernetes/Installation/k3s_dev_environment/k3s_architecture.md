# Архитектура Dev-окружения на K3s

Обзор архитектуры самодостаточной лаборатории для изучения практик DevOps (Development and Operations) на базе легковесного дистрибутива Kubernetes K3s. Все вспомогательные сервисы (CI/CD (Continuous Integration / Continuous Deployment), реестр, GitOps) запускаются внутри кластера.

> **Контекст:** Этот файл описывает общую архитектуру. Детали реализации см. в [Создание Dev-контейнера с SSH](./dev_container_ssh.md), [Развертывание через Helm](./dev_container_helm_deployment.md), [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **K3s Dev Environment** | Самодостаточная лаборатория для изучения DevOps-практик на базе одного сервера с K3s. Все сервисы (GitLab, Harbor, ArgoCD) запускаются внутри кластера |
| **Dev-контейнер** | Изолированное рабочее пространство в кластере с доступом по протоколу SSH (Secure Shell) и персистентной домашней директорией через `hostPath`. См. [Создание Dev-контейнера](./dev_container_ssh.md) |
| **Local Path Provisioner** | Встроенный в K3s provisioner для динамического выделения хранилища. Поддерживает только режим доступа RWO (ReadWriteOnce) |

**Навигация по K3s:** [Kubernetes Overview](../../kubernetes_overview.md) | [Local Path Provisioner](../../Storage/local-path-provisioner.md)

---

## Основные концепции

### Архитектура решения

В основе — один сервер (физический или виртуальный) с **K3s**. Вспомогательные сервисы запускаются внутри кластера.

**Ключевые компоненты:**

| Компонент | Назначение | Ссылка |
|-----------|------------|--------|
| **Платформа** | K3s вместо "ванильного" Kubernetes для простоты на одном узле | [Kubernetes Overview](../../kubernetes_overview.md) |
| **Ingress Controller** | NGINX вместо стандартного Traefik | [Ingress Overview](../../Networking/Ingress/overview.md) |
| **Хранилище** | Local Path Provisioner (только RWO) | [Local Path Provisioner](../../Storage/local-path-provisioner.md) |
| **CI/CD** | GitLab для хранения кода (SCM — Source Code Management) и автоматизации пайплайнов | [GitLab CI Basics](../../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md) |
| **GitOps** | ArgoCD для декларативного развёртывания | [ArgoCD Overview](../../../GitOps/ArgoCD/argocd_overview.md) |
| **Реестр** | Harbor для Docker-образов и Helm-чартов | [Harbor Overview](../../../Docker/Docker_registries/Harbor/overview.md) |
| **S3** | Minio для объектного хранения артефактов (S3 — Simple Storage Service) | — |
| **БД** | PostgreSQL как основная реляционная СУБД (Система Управления Базами Данных) | [PostgreSQL Overview](../../../Databases/PostgreSQL/overview.md) |

### Почему K3s для dev-окружения?

**Преимущества K3s:**

- **Легковесность:** ~70MB бинарный файл, минимальные требования к ресурсам
- **Простота установки:** Один бинарник, автоматическая настройка
- **Встроенные компоненты:** Local Path Provisioner, ServiceLB, Helm Controller
- **Production-совместимость:** Полная совместимость с Kubernetes API (Application Programming Interface)

**Ограничения:**

- **Один узел:** Для multi-node требуется дополнительная настройка etcd
- **Local Path Provisioner:** Только RWO, нет контроля ёмкости

### Сравнение: K3s vs MicroK8s

Оба дистрибутива сертифицированы CNCF и подходят для home lab, edge-вычислений и слабых виртуалок.

| Характеристика | K3s | MicroK8s |
|:---------------|:----|:---------|
| **Упаковка** | Один бинарник <100 МБ | Snap-пакет (изолированные компоненты) |
| **Хранилище состояния** | SQLite (Kine) по умолчанию | DQLite (распределённая БД) |
| **Архитектура** | Все компоненты в одном процессе | Раздельные systemd-процессы |
| **RAM (idle)** | ~512 МБ | 2–4 ГБ |
| **CPU (min)** | 1 ядро | 2 ядра |
| **Аддоны** | Только base: flannel, ServiceLB, Ingress | Встроенная система addon'ов (Ingress, Storage, Monitoring) |
| **Авторазвёртывание** | Директория авторазвёртывания (`/var/lib/rancher/k3s/server/manifests/`) | — |

**Вывод:** K3s — абсолютный чемпион по экономии ресурсов. MicroK8s ближе к классическому K8s архитектурно, но требует больше ресурсов. Для Raspberry Pi и виртуалок с 1–2 ГБ RAM предпочтителен K3s.

### Рабочий процесс "Dev-контейнер"

**Принцип:** Отказ от установки инструментов разработки на хост или локальные машины.

**Процесс:**

1. **Создание образа** — Docker-образ на базе Ubuntu с SSH-сервером и инструментами (Go, Python, Java, SDK (Software Development Kit)). Детали в [Создание Dev-контейнера с SSH](./dev_container_ssh.md).
2. **Развёртывание в K3s** — запуск как `Deployment` с `hostPath` Volume. Инструкция в [Развертывание через Helm](./dev_container_helm_deployment.md).
3. **Персистентность** — домашняя директория (`/home/user`) монтируется с хоста, данные переживают перезапуски.
4. **Удалённая разработка** — подключение через расширение **VS Code (Visual Studio Code) Remote - SSH** (локальная машина как "тонкий клиент").

**Преимущества:**

- Унифицированная среда независимо от ОС (Operating System) разработчика
- Изоляция инструментов от хоста
- Воспроизводимость окружения

---

## Практические сценарии

### Типовая последовательность развёртывания

1. **Установка K3s** на сервер
2. **Замена Traefik на NGINX Ingress Controller**
3. **Развёртывание Harbor и GitLab** через Helm
4. **Настройка интеграции GitLab ↔ Harbor** — см. [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md)
5. **Создание образа `kubeutils`** для пайплайнов — см. [Kubeutils Image](./kubeutils_image.md)
6. **Создание и развёртывание `dev-container`**
7. **Подключение через SSH** и начало работы

---

## Дополнительная информация

### Актуальность версий

> **Внимание:** В файлах серии K3s Dev Environment указаны версии компонентов 2024 года. Перед развёртыванием проверьте актуальные стабильные версии:

| Компонент | Указанная версия | Статус | Рекомендация |
|-----------|------------------|--------|--------------|
| **Kubernetes** | v1.28.6 | Устарел | Рекомендуется v1.31+ |
| **Helm** | v3.13.0 | Проверить | [GitHub Releases](https://github.com/helm/helm/releases) |
| **regclient** | v0.5.6 | Проверить | [GitHub Releases](https://github.com/regclient/regclient/releases) |
| **kubeconform** | v0.6.4 | Проверить | [GitHub Releases](https://github.com/yannh/kubeconform/releases) |

**Проверка версий:**

- K3s: [release.k3s.io](https://github.com/k3s-io/k3s/releases)
- Kubernetes: [kubernetes.io/releases/](https://kubernetes.io/releases/)

### Ограничения Local Path Provisioner

- **Не поддерживает режим RWX (ReadWriteMany)** — только для однонодовых кластеров или StatefulSet с одним репликом на узел
- **Данные привязаны к узлу** — при перемещении пода доступ к данным теряется
- **Нет контроля ёмкости** — приложение использует всё доступное пространство

Подробности: [Local Path Provisioner](../../Storage/local-path-provisioner.md)

### Безопасность hostPath

> **Внимание:** Использование `hostPath` небезопасно в промышленной эксплуатации (production). Допустимо только для локальных dev-сред. См. [Тома в Kubernetes](../../Base/Pod/volume_types/volume_types.md).

**Риски:**

- Доступ к файловой системе узла из контейнера
- Возможность эскалации привилегий при неправильной настройке
- Отсутствие изоляции между подами на одном узле

**Рекомендации:**

- Ограничьте права доступа на уровне OS
- Используйте отдельные директории для каждого пода
- Применяйте `securityContext` с минимальными привилегиями, включая настройки UID/GID (User ID / Group ID)
