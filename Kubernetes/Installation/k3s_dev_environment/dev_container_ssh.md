# Создание Dev-контейнера с SSH (Secure Shell)

Руководство по созданию изолированного рабочего пространства внутри кластера K3s (Kubernetes K3s). Контейнер предоставляет доступ по протоколу SSH и персистентную домашней директорию, используется для разработки непосредственно в кластере.

> **Контекст:** Часть серии по созданию dev-окружения в K3s. Развертывание через Helm описано в [Развертывание Dev-контейнера с помощью Helm](./dev_container_helm_deployment.md). Предварительно требуется [вспомогательный образ kubeutils](./kubeutils_image.md).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Dev-контейнер** | Изолированное рабочее пространство в кластере Kubernetes с доступом по SSH и персистентной домашней директорией |
| **Init Script** | Скрипт инициализации, выполняемый при старте контейнера (ENTRYPOINT). Создает пользователя, настраивает SSH и доверенные сертификаты |
| **SSO-аутентификация** | В данном контексте — аутентификация Single Sign-On (единый вход) по SSH-ключам без пароля. Подробнее см. [SSH Аутентификация](../../../Linux/Security/ssh/server/ssh_authentication.md) |

**Навигация по SSH:** [Обзор SSH](../../../Linux/Security/ssh/ssh_overview.md) | [Настройка сервера](../../../Linux/Security/ssh/server/ssh_server_security_overview.md) | [Управление сессиями](../../../Linux/Security/ssh/ssh_session_management.md)

---

## Основные концепции

### Архитектура решения

Dev-контейнер представляет собой Ubuntu 24.04 с SSH-сервером и набором базовых утилит:

**Компоненты:**

1. **Базовый образ:** `ubuntu:24.04` — минимальный образ с полной совместимостью
2. **SSH-сервер:** `openssh-server` — доступ по ключам без пароля
3. **Утилиты:** `sudo`, `git`, `curl` — базовый набор разработчика
4. **Init-скрипт:** Динамическое создание пользователя по переменным окружения

**Принцип работы:**

```
┌─────────────────────────────────────────────────────────┐
│                    Pod: dev-container                    │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────┐      ┌──────────────────────────┐  │
│  │ Init Container  │ ──→  │  Main Container          │  │
│  │ (подготовка SSH)│      │  (sshd + рабочая среда)  │  │
│  └─────────────────┘      └──────────────────────────┘  │
│                            │                             │
│                            ↓                             │
│                   ┌─────────────────┐                   │
│                   │ hostPath Volume │ ←── K3s Node      │
│                   │ /home/<user>    │     filesystem    │
│                   └─────────────────┘                   │
└─────────────────────────────────────────────────────────┘
                              │
                              ↓ SSH (NodePort 32022)
                    ┌─────────────────┐
                    │  Developer SSH  │
                    │  Client         │
                    └─────────────────┘
```

### Почему SSH в контейнере?

**Преимущества подхода:**

| Аспект | Традиционный подход | Dev-контейнер в K3s |
|--------|---------------------|---------------------|
| **Изоляция** | Общая среда на всех разработчиков | Полная изоляция на уровне контейнера |
| **Воспроизводимость** | Зависит от ручной настройки | Одинаковый образ для всех |
| **Миграция** | Сложности при переходе на другой хост | Контейнер перезапускается в любом месте кластера |
| **Ресурсы** | Выделенная ВМ (виртуальная машина) на каждого | Общие ресурсы кластера с лимитами |
| **Бэкап** | Резервное копирование всей ВМ | Персистентность только домашней директории |

**Ограничения:**

- **Безопасность:** `hostPath` требует доверия к узлу K3s
- **Сеть:** NodePort открывает доступ к SSH на уровне узла
- **Производительность:** I/O (ввод-вывод) через `hostPath` может быть медленнее локального диска

### Init-скрипт: принцип работы

Скрипт инициализации (`init-container.sh`) выполняет настройку при каждом старте контейнера:

1. **Создание пользователя:** Динамически по переменным `DEV_USER_NAME`, `DEV_USER_ID`
2. **Настройка sudo:** Без пароля для удобства разработки
3. **Доверенные сертификаты:** Копирование CA (Certificate Authority) из смонтированного тома
4. **Запуск sshd:** Демон в foreground-режиме (`-D`)

**Важно:** Скрипт использует `addgroup`/`adduser` из Ubuntu (не `groupadd`/`useradd` из RHEL (Red Hat Enterprise Linux)).

---

## Практические сценарии

### Dockerfile для Dev-контейнера

```dockerfile
FROM ubuntu:24.04

# Установка SSH-сервера и базовых утилит
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем и настраиваем скрипт инициализации
COPY init-container.sh /init-container.sh
RUN chmod +x /init-container.sh

# Открываем порт для SSH
EXPOSE 22

# Скрипт инициализации будет запущен при старте контейнера
ENTRYPOINT ["/init-container.sh"]
```

**Best practices (лучшие практики) Dockerfile:**

- `--no-install-recommends` — уменьшает размер образа
- `rm -rf /var/lib/apt/lists/*` — очистка кэша в том же слое
- Явный `chmod +x` — гарантия исполняемости
- `EXPOSE 22` — документирование порта (не влияет на сеть)

### Init-скрипт (`init-container.sh`)

```bash
#!/bin/sh
set -e

# Переменные окружения, передаваемые при запуске пода
USER_NAME=${DEV_USER_NAME:-user}
GROUP_NAME=${DEV_GROUP_NAME:-user}
USER_ID=${DEV_USER_ID:-1000}
GROUP_ID=${DEV_GROUP_ID:-1000}

# Создание группы и пользователя
addgroup -g ${GROUP_ID} ${GROUP_NAME}
adduser -u ${USER_ID} -G ${GROUP_NAME} -s /bin/bash -D ${USER_NAME}
echo "${USER_NAME} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Добавление CA в доверенные, если он был смонтирован в контейнер
CA_CERT_PATH="/etc/ssl/certs/dfca.crt"
if [ -f "$CA_CERT_PATH" ]; then
    cp "$CA_CERT_PATH" /usr/local/share/ca-certificates/
    update-ca-certificates
fi

# Запуск SSH-демона
/usr/sbin/sshd -D
```

**Ключевые моменты:**

| Параметр | Значение по умолчанию | Описание |
|----------|----------------------|----------|
| `DEV_USER_NAME` | `user` | Имя пользователя в контейнере |
| `DEV_USER_ID` | `1000` | UID (User ID) пользователя (должен совпадать с владельцем hostPath) |
| `DEV_GROUP_NAME` | `user` | Имя группы |
| `DEV_GROUP_ID` | `1000` | GID (Group ID) группы |

**Важно:** UID/GID должны совпадать с владельцем `hostPath` тома на узле K3s для корректного доступа к файлам.

### Сборка образа

```bash
# Сборка образа
docker build -t <registry>/dev-container:1.0.0 ./dev-container

# Тестирование локально
docker run -d \
  -p 2222:22 \
  -e DEV_USER_NAME=developer \
  -e DEV_USER_ID=1001 \
  -v ~/dev-home:/home/developer \
  --name dev-test \
  <registry>/dev-container:1.0.0

# Проверка логов
docker logs -f dev-test

# Подключение для теста
ssh -p 2222 developer@localhost
```

### Развертывание в K3s

Полное развертывание описано в [Развертывание Dev-контейнера с помощью Helm](./dev_container_helm_deployment.md).

**Кратко:**

1. Сборка и push образа в Harbor
2. Создание Helm-чарта с `values.yaml`
3. Публикация чарта в OCI (Open Container Initiative) реестр
4. Развертывание через ArgoCD или `helm install`

---

## Дополнительная информация

### Связанные темы

- **Развертывание:** [Helm-чарт для Dev-контейнера](./dev_container_helm_deployment.md)
- **Инфраструктура:** [Архитектура K3s](./k3s_architecture.md)
- **CI/CD:** [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md)
- **SSH:** [Обзор SSH](../../../Linux/Security/ssh/ssh_overview.md), [Аутентификация](../../../Linux/Security/ssh/server/ssh_authentication.md)
- **Docker:** [Оптимизация сборки](../../../Docker/Dockerfile/Docker_best_practices/build_optimization.md), [Безопасность](../../../Docker/Dockerfile/Docker_best_practices/security.md)

### Предупреждения

| Аспект | Риск | Рекомендация |
|--------|------|--------------|
| **SSH в контейнере** | Не рекомендуется для промышленной эксплуатации (production) | Только для dev-окружений |
| **hostPath Volume** | Доступ к файловой системе узла | Ограничьте права на уровне OS (Operating System) |
| **NodePort для SSH** | Открытый порт на узле | Используйте firewall (межсетевой экран) или VPN (Virtual Private Network) |
| **sudo без пароля** | Повышенные привилегии | Допустимо в изолированном контейнере |

### Альтернативы

| Решение | Описание | Когда использовать |
|---------|----------|-------------------|
| **VS Code Remote** | Подключение к контейнеру через IDE (Integrated Development Environment) (например, Visual Studio Code) | Локальная разработка |
| **Jupyter Hub** | Веб-интерфейс для разработки | Data Science сценарии |
| **Gitpod/CodeSpaces** | Облачные dev-окружения | Командная разработка |
| **Teleport** | SSH с аудитом и сессиями | Production доступ |
