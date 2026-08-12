# Установка Docker на Ubuntu

## Определения

- **Docker Engine:** Основной контейнерный движок, устанавливаемый на хостовую систему. Включает демон `dockerd`, REST API и CLI.
- **Rootless Docker:** Режим запуска Docker-демона и контейнеров от имени обычного пользователя (не root), что значительно повышает безопасность системы.
- **NVIDIA Container Toolkit:** Набор инструментов для обеспечения доступа контейнеров к графическим процессорам (GPU) хоста.

## Базовые концепции

### 1. Удаление старых версий

Перед установкой официальной версии необходимо удалить конфликтующие пакеты (неофициальные сборки и старые версии):

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove $pkg
done
```

### 2. Способы установки

#### Вариант А: Официальный репозиторий (Рекомендуемый)

Рекомендуемый способ — установка из официального репозитория Docker, что гарантирует получение актуальных обновлений безопасности и поддержку плагинов.

1.  **Обновление индекса пакетов и установка зависимостей:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
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

4.  **Установка Docker:**
    Установка движка, CLI и современных плагинов (Buildx и Compose V2):
    ```bash
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ```

#### Вариант Б: Удобный скрипт (Для быстрой настройки / Dev)

Docker предоставляет скрипт для автоматической установки всех необходимых компонентов. Подходит для чистых систем.

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

### 3. Шаги после установки (Post-installation)

Чтобы не прописывать `sudo` перед каждой командой Docker, добавьте текущего пользователя в группу `docker`.

```bash
# Создание группы (обычно уже создана)
sudo groupadd docker
# Добавление пользователя
sudo usermod -aG docker $USER
# Применение изменений для текущей сессии (или перезагрузите терминал)
newgrp docker
```

### 4. Проверка и управление сервисом

```bash
# Проверка запуска
docker run hello-world

# Управление через systemd
sudo systemctl status docker
sudo systemctl enable --now docker
```

---

## Практические сценарии

### Настройка Proxy в корпоративной среде

В изолированных сетях требуется настройка прокси для скачивания образов (демон) и для работы внутри контейнеров (клиент).

#### А. Настройка для Docker Daemon (Systemd)
Создайте drop-in файл конфигурации:
```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf <<EOF
[Service]
Environment="HTTP_PROXY=http://proxy.example.com:8080"
Environment="HTTPS_PROXY=http://proxy.example.com:8080"
Environment="NO_PROXY=localhost,127.0.0.1,docker-registry.local"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker
```

#### Б. Настройка для клиента (контейнеров)
Создайте или отредактируйте `~/.docker/config.json`:
```json
{
 "proxies": {
   "default": {
     "httpProxy": "http://proxy.example.com:8080",
     "httpsProxy": "http://proxy.example.com:8080",
     "noProxy": "localhost,127.0.0.1"
   }
 }
}
```

### Установка NVIDIA Container Toolkit (GPU)

Для AI/ML задач и работы с GPU на Ubuntu 24.04+:

```bash
# Добавление репозитория NVIDIA
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# Настройка рантайма и перезапуск
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Настройка Rootless-режима (Безопасность)

Режим Rootless предотвращает получение злоумышленником прав root на хосте даже при побеге из контейнера.

1.  **Подготовка (Ubuntu 24.04+):**
    ```bash
    # Разрешение unprivileged user namespaces
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    sudo apt-get install -y uidmap dbus-user-session
    ```

2.  **Установка:**
    ```bash
    dockerd-rootless-setuptool.sh install
    ```

3.  **Переменные окружения (~/.bashrc):**
    ```bash
    export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
    ```

### Тюнинг и фиксация версий

#### Фиксация версии (Hold)
```bash
# Установка конкретной версии (пример)
sudo apt-get install -y docker-ce=5:27.2.1-1~ubuntu.24.04~noble
# Фиксация
sudo apt-mark hold docker-ce docker-ce-cli containerd.io
```

#### Настройка логирования (daemon.json)
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  },
  "dns": ["8.8.8.8", "1.1.1.1"]
}
```

---

## Устранение неполадок

### Ошибки DNS и Сети
Если контейнеры не резолвят домены, проверьте настройки `systemd-resolved`. Часто помогает явное указание DNS в `daemon.json` (см. выше) или проброс `/etc/resolv.conf`.

### Конфликты с Firewall (UFW)
Docker обходит правила UFW, манипулируя цепочками `iptables` напрямую. 
- **Проблема:** Опубликованный порт (`-p 80:80`) становится доступен извне, даже если UFW включен.
- **Решение:** Привязывайте порт к localhost (`-p 127.0.0.1:80:80`) или используйте специализированные правила для цепочки `DOCKER-USER`.

---

## Дополнительная информация

### Связанные темы
- **[Команды Docker CLI](./docker_commands.md)** — Справочник по управлению.
- **[Безопасность Docker: Rootless и Hardening](./Docker_security/host_daemon_hardening.md)** — Глубокое погружение в защиту.
- **[Архитектура Docker: Демон и Среда выполнения](./docker_overview.md)**.
