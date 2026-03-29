# Обзор Docker

## Определения

**Docker** — платформа для разработки, доставки и запуска приложений в контейнерах. Использует механизмы изоляции ядра Linux для создания легковесных, переносимых окружений.

**Ключевые компоненты:**

| Компонент | Описание |
| :--- | :--- |
| **Контейнер** | Изолированный процесс с собственным окружением (namespaces + cgroups) |
| **Образ (Image)** | Неизменяемый шаблон с кодом, библиотеками, зависимостями |
| **Реестр (Registry)** | Хранилище образов (Docker Hub, Harbor, GitLab Registry) |
| **Docker Daemon (`dockerd`)** | Демон, управляющий контейнерами, образами, сетями, томами |
| **`containerd`** | Демон жизненного цикла контейнеров (проект CNCF) |
| **`runc`** | OCI-совместимый runtime для запуска контейнеров |
| **OCI spec** | Стандарт формата образа и среды выполнения |
| **CRI** | API Kubernetes для взаимодействия с runtime (`containerd`, `CRI-O`) |

## Основные концепции

### Образ и контейнер

- **Образ** — неизменяемый шаблон (read-only)
- **Контейнер** — запущенный экземпляр образа с записываемым слоем (writable layer)

**Жизненный цикл writable layer:**
- При остановке (`docker stop`) — данные сохраняются
- При перезапуске (`docker start`) — данные доступны
- При удалении (`docker rm`) — данные теряются (если не вынесены в volumes)

Подробнее: [Тома и хранение данных](./Docker_fs/docker_volumes.md)

### Контейнеры vs Виртуальные машины

| Критерий | Контейнеры | Виртуальные машины |
| :--- | :--- | :--- |
| **Изоляция** | Процессная (namespaces, cgroups) | Аппаратная (гипервизор) |
| **Ядро** | Общее с хостом | Собственное в каждой ВМ |
| **Старт** | Секунды | Десятки секунд |
| **Плотность** | Высокая | Ниже |
| **Безопасность** | Зависит от ядра хоста | Граница гипервизора |

**Когда выбирать:**
- **Контейнеры:** микросервисы, CI/CD, масштабирование, высокая плотность
- **ВМ:** смешанные ОС, монолиты, строгие границы безопасности
- **Гибрид:** контейнеры внутри ВМ (многоарендность)

Подробнее: [Виртуализация в Linux](../Linux/Virtualization/virtualization_overview.md#сравнение-контейнеры-vs-вм)

### Слоеная файловая система

Docker использует драйверы хранения (OverlayFS) для эффективной работы с образами:

- **lowerdir** — слои образа (read-only)
- **upperdir** — записываемый слой контейнера
- **merged** — объединенное представление

Общие слои переиспользуются между образами, что экономит место.

Подробнее: [OverlayFS в Docker](./Docker_fs/docker_overlayfs.md)

### Структура образа (OCI Format)

При сохранении образа (`docker save -o image.tar`) архив содержит:

- **`manifest.json`** — манифест образа со слоями
- **`config.json`** — метаданные (ENV, WORKDIR, CMD, ENTRYPOINT)
- **Слои (`sha256:.../layer.tar`)** — файловая система по слоям

**Инструкции Dockerfile:**
- Создают слои: `RUN`, `COPY`, `ADD`
- Изменяют метаданные: `ENV`, `WORKDIR`, `CMD`, `EXPOSE`

Подробнее: [Анализ слоев (dive)](./Dockerfile/dockerfile_optimization_tools.md)

### Технологии изоляции

**Namespaces** — изоляция видимости ресурсов:
- PID, Mount, Network, UTS, IPC, User, Cgroup, Time

**Cgroups** — ограничение потребления ресурсов:
- CPU, память, I/O, количество процессов

> **Важно:** Namespaces и cgroups не являются полноценной границей безопасности. Используйте совместно с capabilities, seccomp, AppArmor/SELinux.

Подробнее: [Изоляция в Linux: Namespaces и Cgroups](./Concepts/linux_isolation.md)

### Архитектура Docker

```
docker CLI ←[REST API]→ dockerd ←[gRPC]→ containerd → runc → контейнер
```

| Компонент | Протокол | Описание |
| :--- | :--- | :--- |
| **CLI ↔ Daemon** | REST API (Unix-сокет `/var/run/docker.sock`) | Клиент отправляет команды |
| **Daemon ↔ containerd** | gRPC (Unix-сокет `/run/containerd/containerd.sock`) | Управление жизненным циклом |
| **containerd ↔ runc** | OCI runtime spec | Запуск контейнера |

**Преимущество разделения:** перезапуск `dockerd` не останавливает запущенные контейнеры.

## Практические сценарии

### Процесс запуска `docker run`

1. CLI отправляет `POST /containers/create` и `/start` на REST API `dockerd`
2. `dockerd` делает gRPC-вызов к `containerd`
3. `containerd` вызывает `runc` для создания namespaces и cgroups
4. `runc` запускает процесс контейнера

**Зачем это знать:**
- **Отладка:** локализация проблем (dockerd, containerd, runc)
- **Мониторинг:** метрики с `dockerd` и `containerd`
- **Безопасность:** настройка isolation на уровне runc

### Работа в Kubernetes

```
kubelet ←[CRI API/gRPC]→ containerd/CRI-O ←[OCI]→ runc/crun → контейнер
```

`kubelet` взаимодействует с runtime через CRI API, runtime вызывает OCI-совместимый runtime для создания контейнера.

Подробнее: [Альтернативные среды выполнения](./alternative_runtimes_and_tools.md)

## Дополнительная информация

**Реестры:**
- [Docker Hub](./docker_registries.md) — публичный реестр по умолчанию
- Частные: Harbor, GitLab Container Registry, Nexus

**Историческая справка:**
- **`chroot`** (1979) — изоляция ФС, без изоляции процессов/сети
- **Docker** (2013) — полноценная изоляция с namespaces + cgroups

**Связанные темы:**
- [Команды Docker CLI](./docker_commands.md)
- [Оптимизация Dockerfile](./Dockerfile/dockerfile_optimization_tools.md)
- [Сети в Docker](./Docker_network/docker_network.md)
- [Безопасность контейнеров](./Docker_security/container_hardening.md)
