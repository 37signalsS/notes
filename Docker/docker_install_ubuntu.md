# Установка Docker на Ubuntu

## Определения

**Docker Engine** — контейнерный движок, устанавливаемый на хостовую систему. Включает демон `dockerd`, REST API и CLI.

## Базовые концепции

### 1. Удаление старых версий

Перед установкой официальной версии необходимо удалить конфликтующие пакеты (неофициальные сборки и старые версии):

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove $pkg
done
```

### 2. Настройка репозитория

Рекомендуемый способ — установка из официального репозитория Docker, что гарантирует получение актуальных обновлений безопасности и поддержку плагинов.

1.  **Обновление индекса пакетов и установка зависимостей:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    ```

2.  **Добавление GPG-ключа Docker:**
    ```bash
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    ```

3.  **Добавление репозитория в список источников (sources.list):**
    ```bash
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    ```

### 3. Установка Docker

Установка движка, CLI и современных плагинов (Buildx и Compose V2):

```bash
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 4. Проверка и управление сервисом

```bash
# Проверка запуска
sudo docker run hello-world

# Управление через systemd
sudo systemctl status docker
sudo systemctl enable docker
sudo systemctl restart docker
```

## Практические сценарии

### Запуск без sudo

Для работы без прав root добавьте пользователя в группу `docker`:

```bash
sudo usermod -aG docker $USER
# Для применения изменений без перезагрузки:
newgrp docker
```

> **Важно:** членство в группе `docker` предоставляет права, эквивалентные root. Для повышения безопасности используйте [Rootless-режим](./Docker_security/host_daemon_hardening.md#3-установка-и-запуск-rootless-docker).

### Фиксация версии (Hold)

Для предотвращения случайного обновления Docker в production-средах:

```bash
# Список версий
apt-cache madison docker-ce | head -5

# Установка конкретной версии
sudo apt-get install -y docker-ce=<VERSION> docker-ce-cli=<VERSION>

# Блокировка обновлений
sudo apt-mark hold docker-ce docker-ce-cli containerd.io
```

### Настройка логирования (daemon.json)

По умолчанию Docker не ограничивает размер логов контейнеров, что может привести к переполнению диска. Рекомендуется настроить ротацию в `/etc/docker/daemon.json`:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```
После изменения файла выполните `sudo systemctl restart docker`.

### Устранение неполадок (Firewall и AppArmor)

1.  **UFW (Firewall):** Docker обходит правила UFW по умолчанию. Если вы публикуете порт (`-p 80:80`), он будет открыт для всего мира. Рекомендуется использовать пакет `ufw-docker` или привязывать порты к локальному адресу (`-p 127.0.0.1:80:80`).
2.  **AppArmor (Ubuntu 24.04+):** Если Rootless Docker выдает ошибку `operation not permitted` при создании namespaces, проверьте настройки AppArmor:
    ```bash
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    ```

## Дополнительная информация

**Связанные темы:**

- [Команды Docker CLI](./docker_commands.md)
- [Архитектура Docker](./docker_overview.md)
- [Безопасность хоста и демона](./Docker_security/host_daemon_hardening.md)
