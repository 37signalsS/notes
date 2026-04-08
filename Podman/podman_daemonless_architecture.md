# Podman: Daemonless-архитектура

## Определения

**Daemonless Architecture** — модель управления контейнерами без центрального привилегированного демона. Каждая команда (`podman run`, `podman ps`) запускает отдельный процесс, который выполняет задачу и завершается. Жизненным циклом запущенных контейнеров управляют легковесные процессы-мониторы `conmon`.

**conmon (Container Monitor)** — легковесный процесс на C, запускаемый индивидуально для каждого контейнера. Мониторит основной процесс, обрабатывает stdin/stdout/stderr, TTY, передаёт exit-code и реагирует на сигналы (`podman kill`).

## Основные концепции

### Сравнение архитектур

Полное сравнение Podman vs Docker: [Podman vs Docker](./podman_vs_docker.md).

Ключевые аспекты:

### Жизненный цикл `podman run`

```
[user@host]$ podman run -d nginx
    |
    +--> 1. Запускается процесс `podman`
    |
    +--> 2. `podman` порождает `conmon`
    |
    +--> 3. `conmon` вызывает `crun/runc` для создания контейнера (namespaces/cgroups)
    |
    +--> 4. `runc` запускает `nginx` внутри контейнера
    |
    +--> 5. Процесс `podman` завершается. Остаются:
           - conmon (мониторит nginx)
           - nginx (работает в контейнере)
```

Проверка: `ps -ef --forest | grep -E 'podman|conmon|nginx'` — процесса `podman` в списке не будет.

### Компоненты экосистемы

Архитектура Podman следует UNIX-философии — каждая утилита решает одну задачу:

| Компонент | Назначение |
| :--- | :--- |
| **Podman** | Управление контейнерами и подами |
| **conmon** | Монитор контейнера (легковесный процесс на C) |
| **crun** | OCI runtime (на C, быстрее runc, по умолчанию в rootless) |
| **runc** | OCI runtime (эталонная реализация на Go) |
| **Netavark** | Сетевой драйвер (заменяет CNI в Podman 4+) |
| **Aardvark-dns** | DNS для контейнеров (заменяет dnsmasq) |

Дополнительные инструменты экосистемы: [Альтернативные среды выполнения](../Docker/alternative_runtimes_and_tools.md) (Buildah, Skopeo, CRI-O).

### Интеграция с systemd

Поскольку контейнеры (через `conmon`) — обычные дочерние процессы пользовательской сессии, они нативно вписываются в модель управления `systemd`.

**Ключевые возможности:**

- Автоматическая генерация unit-файлов: `podman generate systemd`
- Управление контейнерами как системными службами (автозапуск, зависимости, перезапуск при сбое)
- Логи контейнеров по умолчанию отправляются в `journald`
- Встроенные функции [автообновления и отката](./podman_auto_update.md) через `podman auto-update`

**Процесс настройки автозапуска:**

```bash
# 1. Создание контейнера
podman run -d --name my_app -p 8080:80 nginx

# 2. Генерация systemd-юнита
podman generate systemd --name my_app --files --new

# 3. Копирование в директорию systemd
cp -p my_app.service ~/.config/systemd/user/

# 4. Включение сервиса
systemctl --user enable --now my_app.service

# 5. Включение lingering (для запуска после перезагрузки без логина)
loginctl enable-linger $(whoami)
```

> **Примечание о портах:** В rootless-режиме контейнеры не могут слушать порты ниже 1024. Используйте порты > 1024 или reverse proxy. Подробнее: [Rootless режим](./podman_rootless.md).

## Практические сценарии

### 1. Проверка изоляции процессов

```bash
# Запуск контейнера
podman run -d --name demo nginx

# Подтверждение отсутствия процесса podman
ps -ef --forest | grep -E 'podman|conmon|demo'

# Вывод: conmon и nginx присутствуют, podman — нет
```

### 2. Эмуляция Docker API

Для совместимости с инструментами, ожидающими Docker API (например, `docker-compose`), Podman предоставляет сокет-сервис:

```bash
# Включить сокет
systemctl --user enable --now podman.socket

# Установить переменную окружения
export DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock

# Инструменты Docker API работают с Podman
docker-compose up -d
```

### 3. Управление логами через journald

```bash
# Логи контейнера через podman
podman logs my_app

# Те же логи через journald
journalctl --user -u my_app.service

# Мониторинг в реальном времени
journalctl --user -u my_app.service -f
```

### 4. Диагностика дерева процессов

```bash
# Показать дерево процессов контейнера
ps -eo pid,ppid,user,cmd --forest | grep -A5 conmon

# Проверить, сколько conmon запущено (должно совпадать с числом контейнеров)
pgrep -c conmon
podman ps -q | wc -l
```

## Дополнительная информация

### Преимущества и недостатки

| Преимущества | Недостатки |
| :--- | :--- |
| Нет единой точки отказа | Нет централизованного управления |
| Экономия памяти (0 МБ idle) | Некоторые инструменты требуют Docker API |
| Лучшая изоляция процессов | Сложнее отладка распределённых процессов |
| Нативная интеграция с systemd и journald | Меньшая зрелость экосистемы |
| Rootless по умолчанию (подробнее: [Rootless режим](./podman_rootless.md)) | |

### Механизмы изоляции

Каждый контейнер изолирован через namespaces и cgroups, управляемые `systemd`. Контейнеры видны как обычные процессы в дереве systemd и управляются стандартными утилитами (`systemctl`, `journalctl`, `systemd-cgtop`).

Подробнее об механизмах ядра: [Изоляция в Linux: Namespaces и Cgroups](../Docker/Concepts/linux_isolation.md), Podman-специфичные особенности: [Изоляция в Podman](./linux_isolation.md).
