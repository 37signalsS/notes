# Podman Compose

## Определения

**Podman Compose** — инструмент для запуска многоконтейнерных приложений и управления ими с помощью файлов конфигурации, аналогичных Docker Compose. Он позволяет описывать сервисы, сети и тома в одном файле (обычно `compose.yaml` или `docker-compose.yml`).

В современной экосистеме выделяют следующие стандарты и инструменты:

- **Docker Compose (v2)** — основной и современный стандарт Docker, реализованный как плагин.
- **docker-compose** — устаревший (legacy) способ запуска через отдельную Python-утилиту.
- **Podman Compose** — официальный механизм в Podman для работы с Compose-спецификацией.
- **podman-compose** — сторонний инструмент (Python-утилита) с открытым исходным кодом, реализующий поддержку Compose без зависимостей от Docker.

Существует два основных способа запуска Compose-файлов в Podman:

1. **Podman Compose (подкоманда `podman compose`)** — встроенный механизм (начиная с версии 4.1), который выступает прокси-слоем. По умолчанию он ищет установленный в системе `docker-compose` (v2) и проксирует команды через него на сокет Podman.
2. **podman-compose (отдельная утилита)** — нативная реализация спецификации Compose для Podman, написанная на Python. Она напрямую взаимодействует с API Podman и не требует Docker-компонентов. Это "чистый" путь для Podman, избавленный от Docker-прокладок.


**Основные задачи:**
- Определение и запуск связанных сервисов из одного файла.
- Автоматическое создание сетей и томов.
- Поддержка синтаксиса и опций Docker Compose.
- Обеспечение безопасности через архитектуру без демона и rootless-режим.

## Основные концепции

### Различия подходов

| Характеристика | Podman Compose (подкоманда) | podman-compose (Python-утилита) |
| :--- | :--- | :--- |
| **Тип** | Встроенная прослойка (wrapper) | Сторонний инструмент |
| **Зависимости** | Требует `docker-compose` | Требует Python и пакет `podman-compose` |
| **Совместимость** | Максимальная (через Docker-провайдер) | Средняя (нативная реализация) |
| **Архитектура** | Проксирует команды в Docker Compose | Нативно вызывает API Podman |
| **Работа с Pods** | Создает отдельные контейнеры | Автоматически объединяет сервисы в **Pod** |

Выбор зависит от целей: для максимальной совместимости с Docker-воркфлоу — `podman compose`, для "чистого" Podman без Docker-прокладок — `podman-compose`.

## Практические сценарии

### 1. Установка

#### Пакетные менеджеры (Linux)
```bash
# Debian/Ubuntu
apt install podman-compose

# RHEL/CentOS/Fedora
yum install podman-compose
```

#### Универсальный способ (pip)
```bash
pip3 install podman-compose
podman-compose --version
```

#### Windows и macOS
- **Windows**: Рекомендуется **Podman Desktop**, который включает Podman Machine (ВМ для запуска контейнеров). После установки команды доступны в PowerShell или Windows Terminal.
- **macOS**:
  ```bash
  brew install podman
  podman machine init
  podman machine start
  pip3 install podman-compose
  ```

#### Ручная установка из исходного кода
Если `pip` недоступен или нужна версия из репозитория:
```bash
git clone https://github.com/containers/podman-compose.git
cd podman-compose
python3 setup.py install
```

### 2. Управление приложением

Podman Compose автоматически подтягивает конфигурационные файлы в текущей директории, если они названы:
- `compose.yaml`
- `docker-compose.yml`
- `container-compose.yml`

При использовании Podman важно помнить, что он требует явного указания реестра (например, `docker.io/library/nginx`), так как по умолчанию не всегда выполняет поиск в Docker Hub.

**Пример `compose.yaml` (PostgreSQL + Nginx):**
```yaml
services:
  db:
    image: docker.io/postgres:16
    environment:
      POSTGRES_PASSWORD: example
    volumes:
      - db_data:/var/lib/postgresql/data

  app:
    image: docker.io/nginx:alpine
    ports:
      - "8080:80"
    depends_on:
      - db

volumes:
  db_data:
```

**Основные команды:**
- `podman-compose up -d` — запуск всех сервисов в фоновом режиме.
- `podman-compose ps` — список запущенных сервисов и их статусы.
- `podman-compose logs -f` — просмотр логов всех сервисов в реальном времени.
- `podman-compose stop <service>` — остановка конкретного сервиса.
- `podman-compose down` — полное удаление контейнеров, сетей и томов.

### 3. Работа с переменными окружения (.env)

Файл `.env` позволяет отделить настройки и секреты от основного YAML-файла. Podman Compose автоматически считывает `.env` в той же директории.

**Пример `.env`:**
```text
WEB_PORT=8080
DB_USER=admin
POSTGRES_PASSWORD=supersecret
```

**Использование в `docker-compose.yml`:**
```yaml
services:
  web:
    image: docker.io/nginx:alpine
    ports:
      - "${WEB_PORT:-80}:80"
  db:
    image: docker.io/postgres:16
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
```

*Совет: Чтобы проверить финальный YAML с подставленными значениями, выполните `podman-compose config`.*

### 4. Управление сетями

Podman Compose автоматически создает изолированную сеть, но можно управлять сетями вручную:
- `podman network create <name>` — создание новой сети.
- `podman network ls` — список всех сетей Podman.

В rootless-режиме сети настраиваются через `slirp4netns` или `pasta`.

### 5. Особенности сетевого взаимодействия (Networking)

В `podman-compose` контейнеры по умолчанию объединяются в один **Pod**. Это дает им общее пространство имен, но есть нюанс в сетевом стеке:

- **Обращение по именам сервисов**: Контейнеры видят друг друга по именам, описанным в `compose.yaml` (например, `curl db:5432`). Это рекомендуемый способ.
- **Проблема localhost**: При запуске через `podman-compose`, контейнеры могут не видеть друг друга через `127.0.0.1` (localhost), даже находясь в одном поде. Это связано с тем, что `podman-compose` создает bridge-сеть "сверху", и сетевая модель остается близкой к Docker.
- **Различие с нативным Podman**: Если создать под вручную (`podman pod create`), Podman создает `infra container` с единым network namespace, где `localhost` работает для всех контейнеров. `podman-compose` работает иначе ради совместимости со спецификацией Docker Compose.

**Рекомендация:** Всегда используйте имена сервисов (`db`, `redis`, `app`) вместо `localhost` для межсервисного взаимодействия.

### 6. Мониторинг и отладка

Для анализа работы сервисов в Podman Compose используйте нативные команды Podman для подов:

- `podman pod ps` — просмотр созданных подов.
- `podman ps --pod` — список контейнеров с привязкой к их подам.
- `podman pod logs <POD_ID>` — просмотр агрегированных логов всех контейнеров в поде.
- `podman exec -it <container_name> sh` — вход в контейнер для отладки (например, проверки связи через `curl db:5432`).

## Миграция из Docker Compose

1. **Проверка манифеста**: Большинство файлов версии 3.x работают "как есть".
2. **Явные реестры**: Проверьте, что во всех `image` указаны полные пути (`docker.io/...`).
3. **Права на тома**: В rootless-режиме может потребоваться настройка прав доступа к папкам на хосте (см. `podman unshare chown`).
4. **Сетевые нюансы**: Используйте имена сервисов вместо `localhost` (§5).
5. **Запуск**: Замените вызов `docker-compose` на `podman-compose`.

### Использование Docker Compose v2 как провайдера
Для максимальной совместимости с оригинальным Docker Compose можно использовать подкоманду `podman compose`:
1. Включите сокет Podman: `systemctl --user enable --now podman.socket`.
2. Настройте переменную: `export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"`.
3. Запускайте через `podman compose up` (без дефиса). Podman будет проксировать команды в установленный плагин `docker-compose`.

## Дополнительная информация

### Генерация Kubernetes-манифестов
Podman позволяет экспортировать запущенный под (включая созданный через compose) в YAML для Kubernetes:

```bash
# Узнать ID созданного пода
podman pod ps

# Сгенерировать YAML (Podman 4.x+)
podman kube generate <POD_ID> > deployment.yaml

# Устаревший синтаксис (может встречаться в старых версиях)
podman generate kube <POD_ID>
```

Это отличное решение для быстрой миграции из локальной разработки в кластер, хотя полученный YAML обычно требует доработки (например, добавления Deployment или Service).

### Альтернатива: Quadlet

Для продакшн-сред на Linux рекомендуется переходить с Compose на **Quadlet**. Это нативный способ описания контейнеров Podman в виде юнитов systemd.

**Преимущества Quadlet:**
- Декларативность и интеграция с `systemctl`.
- Автоматический перезапуск при сбоях или после перезагрузки хоста.
- Отсутствие зависимости от Python или сторонних утилит типа `podman-compose`.
- Гибкость настройки через юниты.

Подробнее: **[Миграция с Docker (Compose → Quadlet)](./migration-from-docker.md)**.

### См. также
- **[Podman vs Docker](./podman_vs_docker.md)** — архитектурные различия.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — как Podman работает без демона.
- **[Rootless режим](./podman_rootless.md)** — особенности запуска без root.
- **[Поды в Podman](./podman_pods.md)** — концепция групп контейнеров.
