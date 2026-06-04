# Podman Compose

## Определения

**Podman Compose** — общее название для способов запуска многоконтейнерных приложений с использованием спецификации Docker Compose в среде Podman. Существует два основных подхода:

1. **Podman Compose (подкоманда)** — встроенный механизм Podman (начиная с версии 4.1), который выступает прокси-слоем. В качестве исполнителя (провайдера) он использует внешнюю утилиту `docker-compose` или Docker Compose v2, перенаправляя её запросы на сокет Podman.
2. **podman-compose** — сторонняя утилита, написанная на Python. Она является нативной реализацией спецификации Compose для Podman, не требует наличия Docker-компонентов и напрямую взаимодействует с API Podman.

**Compose Spec** — открытый стандарт описания многоконтейнерных приложений (файлы `compose.yaml` или `docker-compose.yml`).

## Основные концепции

### Различия подходов

| Характеристика | Podman Compose (подкоманда) | podman-compose (Python-утилита) |
| :--- | :--- | :--- |
| **Тип** | Встроенная прослойка (wrapper) | Сторонний инструмент |
| **Зависимости** | Требует установленный `docker-compose` | Требует Python и пакет `podman-compose` |
| **Совместимость** | Высокая (использует оригинальный движок) | Средняя (реализация спецификации на Python) |
| **Архитектура** | Проксирует команды в Docker Compose | Нативно вызывает команды Podman через API |
| **Работа с Pods** | Обычно создает отдельные контейнеры в сети | По умолчанию может объединять сервисы в один **Pod** (группу контейнеров) |

### Почему Podman вместо Docker Compose

- **Rootless**: Запуск всей связки контейнеров от обычного пользователя без привилегий root.
- **Daemonless**: Отсутствие постоянно запущенного фонового процесса (демона).
- **Интеграция с systemd**: Возможность конвертации в юниты Quadlet для надежного автозапуска.
- **Безопасность**: Изоляция через User Namespaces и отсутствие единой точки отказа.

## Практические сценарии

### 1. Установка podman-compose

Если вы предпочитаете нативный Python-инструмент без Docker-прокладок:

```bash
# Ubuntu/Debian
sudo apt install podman-compose

# Fedora/CentOS/RHEL
sudo dnf install podman-compose

# Через pip (универсальный способ)
pip install podman-compose

# Проверка версии
podman-compose version
# → podman-compose version 1.0.6
```

### 2. Запуск приложения

Podman автоматически ищет файлы в следующем порядке: `compose.yaml`, `docker-compose.yml`, `container-compose.yml`.

**Пример `compose.yaml`:**

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: example
    volumes:
      - db_data:/var/lib/postgresql/data
  app:
    image: nginx:alpine
    ports:
      - "8080:80"
    depends_on:
      - db
volumes:
  db_data:
```

**Команды управления:**

```bash
# Запуск в фоновом режиме
podman-compose up -d
# → podman-compose version 1.0.6, podman version 4.9.4
# → podman pod create --name example_default ...
# → podman run -d --pod example_default ...

# Просмотр статуса
podman-compose ps
# → CONTAINER ID  IMAGE                           COMMAND               CREATED         STATUS             PORTS                 NAMES
# → 8f2a1b3c4d5e  docker.io/library/postgres:16   postgres              1 minute ago    Up 1 minute ago                          example_db_1
# → 1a2b3c4d5e6f  docker.io/library/nginx:alpine  nginx -g daemon o...  1 minute ago    Up 1 minute ago    0.0.0.0:8080->80/tcp  example_app_1

# Остановка и удаление ресурсов
podman-compose down
# → podman stop -t 10 example_app_1 example_db_1
# → podman rm -f example_app_1 example_db_1
# → podman pod rm example_default
```

### 3. Нюансы сетевого взаимодействия

В `podman-compose` есть критическое отличие в работе сети по сравнению с нативными подами Podman:

- **В нативном поде** (`podman pod create`): Контейнеры делят один network namespace и loopback. Обращение между ними доступно через `localhost`. Подробнее: **[Поды в Podman](./podman_pods.md)**.
- **В podman-compose**: Создается bridge-сеть (аналогично Docker). Контейнеры объединяются в логический Pod, но имеют разные сетевые пространства.
- **Правило**: Всегда используйте **имена сервисов** (`db`, `redis`) вместо `localhost` для связи между контейнерами внутри одного compose-файла.

### 4. Использование Docker Compose v2 как провайдера

Если вам нужна максимальная совместимость с плагинами Docker Compose:

1. Установите `docker-compose-plugin`.
2. Включите сокет Podman для пользователя:

   ```bash
   systemctl --user enable --now podman.socket
   ```

3. Укажите путь к сокету в переменной окружения:

   ```bash
   export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
   ```

4. Теперь команда `podman compose up` будет использовать оригинальный движок Docker для управления контейнерами Podman.

## Дополнительная информация

### Генерация Kubernetes-манифестов

Одной из сильнейших сторон Podman является возможность миграции с Compose на Kubernetes. Если приложение запущено через `podman-compose`, оно создает группу контейнеров (Pod), которую можно экспортировать.

```bash
# Узнать ID созданного пода
podman pod ps

# Сгенерировать YAML для Kubernetes (Podman 4.3+)
podman kube generate <POD_ID> > deployment.yaml

# Запуск из YAML
podman kube play deployment.yaml
```

Подробнее об интеграции: **[Поды в Podman: Интеграция с Kubernetes](./podman_pods.md#3-интеграция-с-kubernetes)**.

*Примечание: сгенерированный файл содержит описания Pod и Service, но может потребовать ручной правки для добавления Deployment или StatefulSet.*

### Альтернатива: Quadlet

Для продакшн-сред на Linux рекомендуется переходить с Compose на **Quadlet**. Это нативный способ описания контейнеров Podman в виде юнитов systemd, что обеспечивает:

- Декларативность.
- Нативное управление через `systemctl`.
- Отсутствие зависимости от Python или внешних скриптов.

Подробнее: **[Миграция с Docker (Compose → Quadlet)](./migration-from-docker.md)**.

### См. также

- **[Podman vs Docker](./podman_vs_docker.md)** — архитектурные различия.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — как Podman работает без демона.
- **[Rootless режим](./podman_rootless.md)** — особенности запуска без root.
сти запуска без root.
