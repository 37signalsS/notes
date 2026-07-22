# Миграция с Docker на Podman

## Определения

**Миграция на Podman** — процесс перевода контейнеризированных приложений с Docker на Podman. Основная цель — переход от централизованного привилегированного демона (`dockerd`) к бездемонной (**daemonless**) архитектуре и безрутовому (**rootless**) режиму работы.

### Мотивация миграции

1.  **Устранение единой точки отказа**: В Docker перезапуск демона останавливает все контейнеры. В Podman каждый контейнер — независимый процесс.
2.  **Безопасность (Rootless)**: Работа под обычным пользователем минимизирует риски при компрометации контейнера (злоумышленник не получает root-права на хосте).
3.  **Нативная интеграция с ОС**: Использование **systemd** для управления жизненным циклом, логирования (**journald**) и зависимостей.
4.  **Экономия ресурсов**: Отсутствие постоянно запущенного демона снижает потребление RAM/CPU в простое.

## Практические сценарии

### 1. Подготовка системы для rootless-режима

Для полноценной работы без прав root необходимо выполнить несколько настроек.

#### Разрешение низких портов

По умолчанию порты < 1024 зарезервированы за root. В rootless-режиме попытка открыть, например, порт 80 вызовет ошибку `permission denied`. Чтобы разрешить пользователям открывать порты начиная с 80:

```bash
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/90-unprivileged-ports.conf
sudo sysctl -p /etc/sysctl.d/90-unprivileged-ports.conf
# → net.ipv4.ip_unprivileged_port_start = 80
```

#### Включение Linger

Гарантирует, что процессы пользователя (контейнеры) не будут завершены после закрытия сессии (например, при выходе из SSH) и будут автоматически запускаться при старте системы:

```bash
sudo loginctl enable-linger $USER
# → Проверка: ls /var/lib/systemd/linger/$USER
```

### 2. Установка и режимы работы

```bash
# Установка (Debian/Ubuntu)
sudo apt install podman
```

**Режимы работы:**
- **CLI (Основной)**: Прямой запуск контейнеров без демона (`podman run`). Рекомендуется для всех новых задач.
- **API (Совместимость)**: Работа через сокет для инструментов, ожидающих Docker API (CI/CD, сторонние клиенты).
  ```bash
  systemctl --user enable --now podman.socket
  # Сокет: /run/user/$(id -u)/podman/podman.sock
  ```

### 3. Конвертация Docker Compose в Quadlet

Хотя `podman-compose` позволяет запускать файлы YAML "как есть", рекомендуемый путь для продакшена — конвертация в юниты Quadlet.

#### Использование утилиты podlet

**podlet** — инструмент для автоматической генерации Quadlet-файлов из Compose или команд `podman run`.

**Установка:**
```bash
# Скачивание бинарного файла (пример для x86_64)
curl -L https://github.com/containers/podlet/releases/download/v0.3.1/podlet-x86_64-unknown-linux-gnu.tar.xz -o podlet.tar.xz
tar -xf podlet.tar.xz
sudo mv podlet-x86_64-unknown-linux-gnu/podlet /usr/local/bin/
sudo chmod +x /usr/local/bin/podlet
```

**Конвертация:**
```bash
podlet -i -a compose docker-compose.yaml
# → Генерирует содержимое .container и .network файлов
```

#### Нюансы сетевой миграции

Автоматическая конвертация внешних сетей (`external: true`) в `podlet` может завершаться ошибкой. В таких случаях сеть описывается вручную.

**Пример `caddy.network`:**
```ini
[Unit]
Description=Caddy network

[Network]
Driver=bridge

[Install]
WantedBy=default.target
```

**Привязка в `caddy.container`:**
```ini
[Container]
Image=docker.io/library/caddy:latest
Network=caddy.network
```

### 4. Управление зависимостями

В Podman (и Quadlet) нет прямого аналога `depends_on`. Зависимости реализуются через механизмы **systemd**:
- `Requires=db.service`
- `After=db.service`
- **Healthchecks** + `Notify=healthy`.

Подробнее: **[Управление зависимостями и готовностью](./podman-dependencies.md)**.

## Особенности и ограничения

- **Отсутствие systemd**: На дистрибутивах без systemd (Alpine с OpenRC) Quadlet не работает, миграция потребует ручного написания скриптов запуска.
- **Docker Socket**: Приложения, жестко привязанные к `/var/run/docker.sock` (например, Portainer), требуют перенаправления на сокет Podman или использования переменной `DOCKER_HOST`. При этом Portainer в rootless-режиме может иметь ограниченный функционал.
- **Безопасность**: При миграции критически важно сменить все дефолтные пароли и ограничивать биндинг портов (например, `-p 127.0.0.1:5432:5432`), чтобы сервисы не торчали наружу.

## Дополнительная информация

### См. также

- **[Rootless режим](./podman_rootless.md)** — механизмы изоляции и настройки.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — принципы работы без демона.
- **[Podman vs Docker](./podman_vs_docker.md)** — детальное сравнение.
- **[Podman Compose](./podman-compose.md)** — работа с Compose-файлами.
