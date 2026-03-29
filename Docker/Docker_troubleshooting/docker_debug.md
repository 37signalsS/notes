# Docker Debug

## Определения

**`docker debug`** — CLI-команда для интерактивной отладки контейнеров и образов. Создаёт эфемерный отладочный контейнер с набором инструментов (vim, curl, htop), не требуя модификации основного образа.

**Ключевое преимущество:** Работа с минималистичными образами (slim, distroless), где отсутствует shell.

## Основные концепции

### Принцип работы

`docker debug` создаёт временный контейнер, который:
- Использует файловую систему целевого контейнера/образа
- Предоставляет toolbox с предустановленными утилитами
- Не модифицирует исходный образ
- Для запущенных контейнеров — изменения ФС видны приложению
- Все изменения отбрасываются при выходе (кроме активных контейнеров)

### Toolbox

**Предустановленные инструменты:** `vim`, `nano`, `htop`, `curl`

**Команды toolbox:**

| Команда | Описание |
| :--- | :--- |
| `install <pkg>` | Установить пакет из Nix (https://search.nixos.org/packages) |
| `uninstall <pkg>` | Удалить пакет |
| `entrypoint --print` | Показать entrypoint контейнера |
| `entrypoint --run` | Запустить entrypoint без старта контейнера |
| `builtins` | Список встроенных инструментов |

### Требования

- Docker CLI с поддержкой `debug` (Docker Desktop 4.27+)
- Доступ к Docker daemon
- Для установки пакетов — доступ к Nix registry

## Практические сценарии

### Сценарий 1: Отладка slim-контейнера

**Задача:** Войти в контейнер без shell.

```bash
# Запуск контейнера
docker run -d --name web-app -p 8080:80 nginx

# Подключение к отладке
docker debug web-app
```

**Результат:** Интерактивная оболочка с доступом к ФС контейнера.

### Сценарий 2: Редактирование файлов в реальном времени

**Задача:** Исправить конфиг без пересборки образа.

```bash
# Отладка запущенного контейнера
docker debug web-app

# Редактирование
docker > vim /etc/nginx/nginx.conf

# Проверка синтаксиса
docker > nginx -t

# Перезагрузка (если доступен nginx)
docker > nginx -s reload
```

**Важно:** Изменения сохраняются только в _running_ контейнере. После перезапуска — будут утеряны.

### Сценарий 3: Установка дополнительных инструментов

**Задача:** Добавить утилиты для диагностики.

```bash
docker debug web-app

# Установка nmap
docker > install nmap
docker > nmap --version

# Установка tcpdump
docker > install tcpdump
docker > tcpdump -i any -n port 80
```

### Сценарий 4: Отладка образа без запуска контейнера

**Задача:** Исследовать образ без создания контейнера.

```bash
docker debug nginx:latest

# Просмотр ФС
docker > ls -la /usr/share/nginx/html/

# Проверка entrypoint
docker > entrypoint --print
```

### Сценарий 5: Выполнение команд для скриптов

**Задача:** Автоматизация проверки через CI/CD.

```bash
# Выполнение команды без интерактивной сессии
docker debug --command "cat /etc/os-release" nginx

# Проверка файла
docker debug --command "test -f /app/config.yaml && echo 'exists'" myapp
```

### Сценарий 6: Удалённая отладка

**Задача:** Отладка контейнера на удалённом хосте.

```bash
# Через SSH
docker debug --host ssh://root@remote-host my-container

# Через unix-socket
docker debug --host unix:///var/run/docker.sock my-container
```

### Сценарий 7: Выбор оболочки

**Задача:** Использовать конкретную shell.

```bash
# Bash (по умолчанию auto)
docker debug --shell bash my-container

# Fish
docker debug --shell fish my-container

# Zsh
docker debug --shell zsh my-container
```

## Дополнительная информация

### Сохранение изменений

| Состояние | Сохранение |
| :--- | :--- |
| **Запущенный контейнер** | Изменения видны приложению, но не сохраняются в образ |
| **Остановленный контейнер** | Изменения теряются при выходе |
| **Образ** | Изменения не сохраняются |

**Для перманентных изменений:**

```bash
# 1. Внести изменения через docker debug
docker debug my-container

# 2. Закоммитить в новый образ
docker commit my-container my-container:edited

# 3. (Рекомендуется) Перенести в Dockerfile
# COPY config.yaml /app/config.yaml
```

### Ограничения

- **Distroless/scratch:** Может требовать дополнительных инструментов через `install`
- **Изменения эфемерны:** Не сохраняются в образ автоматически
- **Доступность:** Требуется Docker CLI с поддержкой команды
- **Nix registry:** Для установки пакетов нужен доступ к https://search.nixos.org/packages

### Флаги команды

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `--shell <shell>` | Выбор оболочки | `--shell bash` |
| `--command <cmd>` | Выполнить команду | `--command "ls -la"` |
| `--host <host>` | Docker socket | `--host ssh://user@host` |

### Связанные темы

- **[Debugging Distroless](./debugging_distroless.md)** — отладка минималистичных образов
- **[Health Signals](../Dockerfile/Instructions/health_signals.md)** — проверки здоровья

### Примечания

- Команда работает в бета-режиме (может меняться синтаксис)
- Для production рекомендуется использовать стабильные методы (`docker exec`, `kubectl debug`)
- Toolbox использует Nix для управления пакетами
