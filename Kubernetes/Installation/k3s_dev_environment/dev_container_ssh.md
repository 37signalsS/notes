# Создание Dev-контейнера с SSH

Руководство по созданию изолированного рабочего пространства внутри кластера K3s. Контейнер предоставляет доступ по протоколу SSH и персистентную домашнюю директорию, используется для удаленной разработки непосредственно в кластере.

Контекст: Часть серии по созданию dev-окружения в K3s. Развертывание через Helm описано в [Развертывание Dev-контейнера с помощью Helm](./dev_container_helm_deployment.md). Предварительно требуется [вспомогательный образ kubeutils](./kubeutils_image.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Dev-контейнер** | Изолированное рабочее пространство в кластере Kubernetes с настроенным SSH-сервером, оптимизированное для работы с удаленными IDE (VS Code, JetBrains Gateway). |
| **Init Script** | Скрипт инициализации (`ENTRYPOINT`), выполняющий финальную настройку среды при старте: создание пользователя, синхронизацию UID/GID и запуск демона `sshd`. |
| **SSH Certificate Authority (CA)** | Метод аутентификации, при котором сервер доверяет ключам, подписанным доверенным центром сертификации. Это исключает необходимость управления файлами `authorized_keys` на каждом узле. |
| **Pod Security Standards (PSS)** | Политики безопасности Kubernetes (Privileged, Baseline, Restricted). SSH-контейнеры обычно требуют режима `Baseline` или специальных исключений для запуска демона. |

Навигация по SSH: [Обзор SSH](../../../Linux/Security/ssh/ssh_overview.md) | [Настройка сервера](../../../Linux/Security/ssh/server/ssh_server_security_overview.md) | [Управление сессиями](../../../Linux/Security/ssh/ssh_session_management.md)

---

## Основные концепции

### Архитектура решения

Dev-контейнер представляет собой образ на базе Ubuntu 24.04 LTS с SSH-сервером и набором базовых утилит.

Компоненты:
1.  **Базовый образ:** `ubuntu:24.04` — LTS-версия (Noble Numbat), обеспечивающая долгосрочную поддержку и актуальность системных библиотек.
2.  **SSH-сервер:** OpenSSH 9.6p1+ — настроен на работу по протоколу v2 с отключением парольной аутентификации.
3.  **Персистентность:** Домашняя директория разработчика монтируется через `hostPath` или `Local PV`, сохраняя настройки IDE, кэши инструментов и историю команд.
4.  **Скрипт инициализации:** Связывает жизненный цикл пода с UID/GID хостовой системы для бесшовной работы с томами.

Принцип работы:
```text
┌─────────────────────────────────────────────────────────┐
│                    Pod: dev-container                   │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────┐      ┌──────────────────────────┐  │
│  │ init-container.sh ──→  │ sshd (foreground)        │  │
│  │ (синхронизация) │      │ рабочая среда bash       │  │
│  └─────────────────┘      └──────────────────────────┘  │
│                            │                            │
│                            ↓                            │
│                   ┌─────────────────┐                   │
│                   │ hostPath Volume │ ←── K3s Node      │
│                   │ /home/<user>    │     filesystem    │
│                   └─────────────────┘                   │
└─────────────────────────────────────────────────────────┘
                              │
                              ↓ SSH (NodePort / Ingress TCP)
                    ┌─────────────────┐
                    │  Developer IDE  │
                    │  (VS Code SSH)  │
                    └─────────────────┘
```

### Сравнение подходов к среде разработки

| Аспект | Традиционная ВМ | Dev-контейнер в K3s |
| :--- | :--- | :--- |
| **Изоляция** | Общая среда на команду, риск конфликтов. | Строгая контейнерная изоляция на уровне Pod. |
| **Воспроизводимость** | Зависит от состояния ВМ (Configuration Drift). | Гарантируется иммутабельным Docker-образом. |
| **Масштабирование** | Трудоемкое изменение ресурсов (RAM/CPU). | Мгновенное управление квотами через K8s. |
| **Безопасность** | Компрометация ВМ дает доступ ко всей системе. | Ограничена namespace'ом и ServiceAccount. |
| **Скорость запуска** | Минуты (загрузка ОС). | Секунды (старт контейнера). |

### Механика Init-скрипта

Скрипт решает критическую проблему монтирования томов в Kubernetes: несовпадение прав. Если `hostPath` на узле принадлежит UID 1000, а пользователь в образе имеет UID 1001, возникнет ошибка `Permission denied`.

Логика `init-container.sh`:
1.  **Чтение параметров:** Получение желаемых UID/GID из переменных среды (`DEV_USER_ID`, `DEV_GROUP_ID`).
2.  **Создание пользователя:** Динамическое создание системной группы и пользователя с точным совпадением ID.
3.  **Настройка sudo:** Выдача пользователю прав `sudo` без пароля (критично для установки инструментов "на лету").
4.  **Корректировка прав:** Идемпотентное выполнение `chown` для домашней директории, если она была смонтирована с другими правами.
5.  **Запуск демона:** Запуск `sshd` в режиме PID 1 с выводом логов в `stderr` для диагностики через `kubectl logs`.

---

## Практические сценарии

### Dockerfile для Dev-контейнера (Ubuntu 24.04)

Файл оптимизирован для безопасности и включает исправления для OpenSSH в Ubuntu.

```dockerfile
FROM ubuntu:24.04

# Отключение интерактивных запросов apt
ENV DEBIAN_FRONTEND=noninteractive

# Установка SSH-сервера и базовых утилит
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    sudo \
    git \
    curl \
    ca-certificates \
    vim \
    bash-completion \
    && rm -rf /var/lib/apt/lists/*

# Директория для privilege separation (критично для Ubuntu/Debian)
RUN mkdir -p /run/sshd && chmod 0755 /run/sshd

# Усиление безопасности конфигурации sshd
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config && \
    # Ограничение времени на логин для защиты от regreSSHion
    echo "LoginGraceTime 30" >> /etc/ssh/sshd_config

# Копирование и настройка скрипта инициализации
COPY init-container.sh /usr/local/bin/init-container.sh
RUN chmod +x /usr/local/bin/init-container.sh

EXPOSE 22

ENTRYPOINT ["/usr/local/bin/init-container.sh"]
```

### Скрипт инициализации (`init-container.sh`)

Обеспечивает корректную работу с UID/GID и системными сертификатами.

```bash
#!/bin/bash
set -e

# Переменные окружения с дефолтными значениями
USER_NAME=${DEV_USER_NAME:-developer}
GROUP_NAME=${DEV_GROUP_NAME:-developer}
USER_ID=${DEV_USER_ID:-1000}
GROUP_ID=${DEV_GROUP_ID:-1000}

# Создание группы (если она еще не существует)
if ! getent group "${GROUP_NAME}" > /dev/null 2>&1; then
    groupadd -g "${GROUP_ID}" "${GROUP_NAME}"
fi

# Создание пользователя
if ! id -u "${USER_NAME}" > /dev/null 2>&1; then
    useradd -u "${USER_ID}" -g "${GROUP_ID}" -s /bin/bash -m "${USER_NAME}"
    passwd -d "${USER_NAME}" # Отключение пароля
fi

# Настройка sudo без пароля
echo "${USER_NAME} ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/${USER_NAME}"
chmod 0440 "/etc/sudoers.d/${USER_NAME}"

# Идемпотентная смена владельца домашней директории
chown "${USER_ID}:${GROUP_ID}" "/home/${USER_NAME}"

# Импорт дополнительных CA-сертификатов (например, корпоративный Harbor)
CA_CERT_PATH="/etc/ssl/certs/custom-ca.crt"
if [ -f "$CA_CERT_PATH" ]; then
    cp "$CA_CERT_PATH" /usr/local/share/ca-certificates/
    update-ca-certificates > /dev/null 2>&1
fi

# Запуск SSH-демона
# -D: не отсоединяться (foreground)
# -e: вывод логов в stderr (доступно через kubectl logs)
echo "Starting sshd for ${USER_NAME} (UID: ${USER_ID})..."
exec /usr/sbin/sshd -D -e
```

### Локальное тестирование образа

Проверка работоспособности перед развертыванием в K3s.

```bash
# 1. Сборка
docker build -t dev-container:2026 .

# 2. Подготовка локального тома
mkdir -p ~/dev-home/.ssh
cp ~/.ssh/id_ed25519.pub ~/dev-home/.ssh/authorized_keys
chmod 700 ~/dev-home/.ssh && chmod 600 ~/dev-home/.ssh/authorized_keys

# 3. Запуск контейнера
docker run -d \
  -p 2222:22 \
  -e DEV_USER_NAME=$USER \
  -e DEV_USER_ID=$(id -u) \
  -e DEV_GROUP_ID=$(id -g) \
  -v ~/dev-home:/home/$USER \
  --name dev-debug \
  dev-container:2026

# 4. Проверка подключения
ssh -p 2222 $USER@localhost
```

---

## Дополнительная информация

### Сравнение методов аутентификации в 2026 году

| Метод | Плюсы | Минусы | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Статические ключи** | Простота, не требует доп. сервисов. | Сложность ротации, риск утечки. | Только для персональных песочниц. |
| **SSH CA (Certificates)** | Централизованное управление, TTL. | Требует настройки CA (Vault/Teleport). | Стандарт для командной разработки. |
| **FIDO2 (ed25519-sk)** | Аппаратная защита ключей. | Требует физический токен. | Для доступа к критической инфраструктуре. |

### Безопасность и риски

| Аспект | Риск | Решение |
| :--- | :--- | :--- |
| **SSH от Root** | Взлом `sshd` дает права root в контейнере. | Регулярно обновляйте образ; используйте AppArmor. |
| **hostPath** | Побег на узел через монтирование. | Ограничивайте монтирование только папкой проекта. |
| **sudo NOPASSWD** | Неограниченные права в контейнере. | Используйте квоты ресурсов (Resource Quotas) в K8s. |
| **regreSSHion** | CVE-2024-6387 (RCE до аутентификации). | `LoginGraceTime 30` и актуальный OpenSSH 9.8+. |

### Современные альтернативы

Если SSH кажется избыточным или небезопасным, рассмотрите следующие инструменты:
1.  **DevSpace / Skaffold:** Синхронизация кода в реальном времени через API Kubernetes.
2.  **GitLab Workspaces:** Встроенное в GitLab 19+ решение для оркестрации облачных сред разработки.
3.  **Teleport:** Современный доступ к инфраструктуре с нативной поддержкой SSH CA и аудитом сессий.

### Связанные темы

- **Развертывание в кластере:** [Helm-чарт для Dev-контейнера](./dev_container_helm_deployment.md)
- **Инфраструктура:** [Архитектура K3s](./k3s_architecture.md)
- **Сетевая интеграция:** [Интеграция GitLab с Harbor](./gitlab_harbor_integration.md)
- **Основы SSH:** [Обзор SSH](../../../Linux/Security/ssh/ssh_overview.md), [Аутентификация](../../../Linux/Security/ssh/server/ssh_authentication.md)
