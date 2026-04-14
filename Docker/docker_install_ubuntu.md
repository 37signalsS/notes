# Установка Docker на Ubuntu

## Определения

**Docker Engine** — контейнерный движок, устанавливаемый на хостовую систему. Включает демон `dockerd`, REST API и CLI.

## Основные концепции

### Способ установки

Рекомендуемый способ — установка из официального репозитория Docker (не из стандартных репозиториев дистрибутива), что гарантирует актуальные версии и поддержку:

```bash
# 1. Обновление репозиториев
sudo apt-get update

# 2. Установка зависимостей
sudo apt-get install -y ca-certificates curl gnupg

# 3. Добавление GPG-ключа Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. Добавление репозитория Docker
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. Обновление репозиториев и установка последней версии
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Проверка установки

```bash
# Запуск тестового контейнера
sudo docker run hello-world
```

Команда загружает образ `hello-world` из Docker Hub (если отсутствует локально) и запускает контейнер, который выводит приветственное сообщение.

### Управление сервисом

```bash
# Docker запускается автоматически как systemd-юнит
sudo systemctl status docker

# Включение автозапуска
sudo systemctl enable docker

# Запуск/остановка/перезапуск
sudo systemctl start docker
sudo systemctl stop docker
sudo systemctl restart docker
```

> **Примечание:** на production-серверах рекомендуется настраивать Docker через daemon.json, а не через флаги запуска systemd-юнита. Подробнее: [Конфигурация Docker через systemd](../docker_systemd.md).

## Практические сценарии

### Запуск без sudo

По умолчанию Docker требует root-privileges. Для удобства работы можно добавить пользователя в группу `docker`:

```bash
sudo usermod -aG docker $USER
# Перезайдите в сессию для применения
```

> **Важно:** членство в группе `docker` эквивалентно root-доступу. В production-средах используйте [Rootless-режим](../docker-in-docker.md#rootless-docker).

### Установка конкретной версии

```bash
# Список доступных версий
apt-cache madison docker-ce | head -10

# Установка конкретной версии
sudo apt-get install -y docker-ce=<VERSION> docker-ce-cli=<VERSION> containerd.io docker-buildx-plugin docker-compose-plugin
```

### Блокировка версии (hold)

```bash
sudo apt-mark hold docker-ce docker-ce-cli containerd.io
```

## Дополнительная информация

**Связанные темы:**

- [Команды Docker CLI](./docker_commands.md)
- [Архитектура Docker](./docker_overview.md)
- [Конфигурация через systemd](./docker_systemd.md)
- [Docker Compose плагин](./Docker_compose/docker_compose_cli_commands.md)
