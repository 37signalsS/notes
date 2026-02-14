# Podman vs Docker: Ключевые различия

Оба инструмента поддерживают стандарты [Open Container Initiative (OCI)](../Docker/docker_overview.md#open-container-initiative-oci-spec), что обеспечивает совместимость образов и сред выполнения. Однако их архитектура и философия безопасности кардинально различаются.

## Основные концепции: Сравнительный анализ

| Критерий | Docker | Podman |
| :--- | :--- | :--- |
| **Архитектура** | **Клиент-серверная (`daemon`)**: `docker` CLI отправляет команды демону `dockerd`, который управляет контейнерами. | **Без демона (`daemonless`)**: `podman` напрямую взаимодействует со средой выполнения, запуская контейнеры как дочерние процессы. |
| **Безопасность** | Изначально `root-centric`, но поддерживает `rootless` режим. Безопасность зависит от защиты демона. | `Rootless-first` дизайн. Контейнеры по умолчанию запускаются от имени обычного пользователя, используя **[user namespaces](../Docker/Concepts/linux_isolation.md#1-пространства-имён-namespaces)**. |
| **Среда выполнения** | `containerd` + `runc` | `crun` (часто по умолчанию, быстрее) или `runc`. |
| **Интеграция с ОС** | Ограниченная. Для автозапуска контейнеров требуются [собственные systemd-юниты](../Docker/docker_systemd.md). | Глубокая. Команда `podman generate systemd` автоматически создает `unit`-файлы для управления контейнерами. |
| **Группы контейнеров** | `docker-compose` (официальный инструмент) | `podman-compose` (сторонняя утилита) или концепция **Pods** — групп контейнеров с общими ресурсами. |
| **Интеграция с K8s** | Отсутствует встроенная генерация манифестов. | `podman generate kube` / `podman play kube` для прямого взаимодействия с Kubernetes-манифестами. |
| **Сеть** | `libnetwork` | `Netavark` и `Aardvark-dns` (для rootful) или `slirp4netns` (для rootless). |

## Практические сценарии

### 1. Совместимость команд (CLI)

Для большинства базовых операций достаточно заменить `docker` на `podman`. Многие пользователи создают псевдоним `alias docker=podman` для полной прозрачности.

```bash
# Запуск контейнера
docker run -d --name web -p 8080:80 nginx
podman run -d --name web -p 8080:80 nginx

# Сборка образа
docker build -t app:1.0 .
podman build -t app:1.0 .

# Работа с реестром
docker login registry.example.com
podman login registry.example.com
```

### 2. Сценарии выбора

-   **Podman** — идеальный выбор для:
    -   Linux-серверов с фокусом на безопасность и интеграцию с `systemd`.
    -   Многопользовательских сред, где изоляция пользователей критична (`rootless`).
    -   Разработки и тестирования Kubernetes-приложений (`podman play kube`).

-   **Docker** — остается сильным выбором для:
    -   Устоявшихся CI/CD пайплайнов, сильно завязанных на `docker-compose`.
    -   Кросс-платформенной разработки (Windows/macOS), где `Docker Desktop` предоставляет более зрелый UX.
    -   Экосистем с большим количеством плагинов и инструментов, ориентированных на Docker API.

## Дополнительная информация

-   **Архитектура Docker:** [Обзор Docker](../Docker/docker_overview.md)
-   **Архитектура Podman:** [Daemonless архитектура Podman](./podman_daemonless_architecture.md)
-   **Rootless режим:** [Rootless режим в Podman](./podman_rootless.md)
-   **Механизмы изоляции:** [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md)
-   **Альтернативные среды выполнения:** [Сравнение CRI-O, Containerd и других сред](./alternatives_crio_containerd.md)
-   **Запуск `systemd` в контейнере:** [Docker и systemd](../Docker/docker_systemd.md)
