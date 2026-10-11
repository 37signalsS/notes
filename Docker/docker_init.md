# Инициализация проекта: docker init

**Актуально для:** Docker Desktop 4.27+, Docker Engine (Linux) с плагином `docker init`

---

## Определения

- **docker init** — интерактивная утилита CLI, входящая в состав Docker, которая автоматизирует создание стартовых конфигурационных файлов для контейнеризации приложений. Анализирует структуру проекта и генерирует `Dockerfile`, `compose.yaml`, `.dockerignore` и `README.Docker.md` по специализированным шаблонам.
- **Шаблон (template)** — набор заготовок файлов, адаптированных под конкретный стек технологий (Node.js, Python, Go и т.д.). Шаблон определяет базовый образ, многоэтапную сборку, команду запуска и параметры безопасности.
- **Манифест проекта** — файл, по которому `docker init` определяет стек: `package.json` (Node.js), `requirements.txt` (Python), `go.mod` (Go), `pom.xml` (Java/Maven) и т.д.
- **docker-init (бинарный файл)** — легковесный инициализатор процессов (PID 1), используемый флагом `--init` в `docker run`. Не путать с командой `docker init`.
- **BuildKit** — современная система сборки образов Docker, используемая `docker init` по умолчанию для кэширования слоёв и оптимизации контекста.

---

## Архитектура и принцип работы

### Как работает docker init

Утилита выполняет четыре последовательных этапа:

1. **Сканирование директории:** Рекурсивно обходит корень проекта и ищет манифестные файлы (`package.json`, `requirements.txt`, `go.mod`, `pom.xml`, `*.csproj` и т.д.). Если найден несколько манифестов (например, в монорепозитории), утилита запрашивает уточнение.
2. **Выбор шаблона:** На основе обнаруженного стека подставляет специализированный шаблон. Если стек не определён автоматически, предлагает список вручную: ASP.NET Core, Go, Java, Node.js, PHP with Apache, Python, Rust, Other.
3. **Интерактивные промпты:** Запрашивает у пользователя:
   - Версию runtime (например, `22.x`, `3.12`, `8.2`)
   - Относительный путь к приложению (например, `./src`, `.`)
   - Команду запуска (например, `npm start`, `python main.py`)
   - Порт (например, `3000`, `8000`)
4. **Генерация файлов:** Создаёт четыре файла с безопасными значениями по умолчанию:
   - `Dockerfile` — многоэтапная сборка, непривилегированный пользователь, pinning версий
   - `.dockerignore` — исключение `node_modules`, `.git`, секретов, артефактов сборки
   - `compose.yaml` — сервис с портом, томами и (опционально) зависимостями
   - `README.Docker.md` — инструкции по запуску и проверке

### Детекция стека

Утилита использует следующие сигнатуры для автоматического определения платформы:

| Стек | Манифестные файлы | Шаблон по умолчанию |
|:---|:---|:---|
| Node.js | `package.json` | Node.js |
| Python | `requirements.txt`, `pyproject.toml`, `Pipfile` | Python |
| Go | `go.mod`, `go.sum` | Go |
| Java | `pom.xml`, `build.gradle` | Java (Maven uber-jar) |
| .NET | `*.csproj`, `*.sln` | ASP.NET Core |
| PHP | `composer.json`, `index.php` | PHP with Apache |
| Rust | `Cargo.toml`, `Cargo.lock` | Rust |
| Не определён | — | Other |

### Механизм перезаписи

Если в директории уже существуют целевые файлы (`Dockerfile`, `compose.yaml`, `docker-compose.yaml`, `.dockerignore`), утилита запрашивает подтверждение:

```
Dockerfile already exists. Overwrite? [y/N]
```

- При выборе `y` файл перезаписывается безвозвратно.
- При выборе `N` файл сохраняется, утилита генерирует только отсутствующие артефакты.
- Если существует `docker-compose.yaml` (старое имя), `docker init` может перезаписать его, сохранив имя `docker-compose.yaml`.

---

## Предварительные требования

### Для Docker Desktop (macOS, Windows)

- **Docker Desktop 4.27+** — `docker init` стал GA (general availability) в версии 4.27 (февраль 2024). В версиях 4.18–4.26 доступен в beta.
- **Docker Engine** — включён по умолчанию.
- **BuildKit** — активирован автоматически в Docker Desktop.

### Для Linux (Docker Engine)

Утилита поставляется как отдельный плагин CLI:

```bash
# Установка плагина (Docker 25+)
dockerd-rootless.sh --install-init-plugin

# Или через пакет docker-ce-cli (включает плагин)
apt-get install -y docker-ce-cli

# Проверка установки
docker init --version
# → docker-init version 0.x.x
```

### Требования к проекту

- Проект должен иметь хотя бы один манифестный файл в корне или в непосредственной поддиректории.
- Для монорепозиториев с несколькими сервисами запускайте `docker init` в директории конкретного сервиса.
- Достаточные права на запись в директории проекта для создания новых файлов.

---

## Установка и настройка

### Docker Desktop

Установка через стандартный установщик:

```bash
# macOS (Homebrew Cask)
brew install --cask docker

# Windows (winget)
winget install Docker.DockerDesktop
```

После установки проверьте доступность:

```bash
docker init --version
# → docker-init version 0.x.x
```

### Linux (Docker Engine)

Docker Engine с CLI (включает `docker init`) устанавливается из официального apt-репозитория Docker — пошаговая инструкция: **[docker_install_ubuntu.md](./docker_install_ubuntu.md)**.

```bash
# Проверка
docker init --version
# → docker-init version 0.x.x
```

### Резервное копирование перед генерацией

Перед первым запуском в существующем проекте создайте бэкап:

```bash
# Копирование существующих файлов
cp Dockerfile Dockerfile.bak
cp compose.yaml compose.yaml.bak
cp .dockerignore .dockerignore.bak

# Или через git
git add -A && git commit -m "backup: before docker init"
```

---

## Практические сценарии

### Сценарий 1: Node.js (Express) — интерактивная инициализация

```bash
# В директории проекта с package.json
docker init

# Интерактивные промпты:
# ? What application platform does your project use? Node.js
# ? What version of Node.js do you want to use? 22.x
# ? What's the relative directory (with a leading .) for your app? .
# ? What is the command to run your app? npm start
# ? What port does your app listen on? 3000

# Запуск
docker compose up --build
# → Container started
```

### Сценарий 2: Python (FastAPI) с базой данных

```bash
docker init

# Результат в compose.yaml:
services:
  server:
    build:
      context: .
    ports:
      - 8000:8000
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - db_data:/var/lib/postgresql/data
volumes:
  db_data: {}
```

### Сценарий 3: Go (бинарный сервер)

```bash
docker init

# Генерируется оптимизированный multi-stage Dockerfile:
# - builder stage: компиляция Go
# - runtime stage: минимальный alpine-образ
# - USER nonroot для безопасности
```

### Сценарий 4: Неинтерактивный режим (CI/CD)

В автоматизированных пайплайнах используйте подавление промптов:

```bash
# Вариант 1: пустой ввод (принимаются все дефолты)
echo "" | docker init

# Вариант 2: expect-скрипт для сложных сценариев
#!/usr/bin/expect -f
spawn docker init
expect "What application platform"
send "Python\r"
expect "What version"
send "3.12\r"
expect "What port"
send "8000\r"
expect eof
```

### Сценарий 5: Переинициализация существующего проекта

```bash
# Если файлы уже существуют — утилита запросит подтверждение
docker init

# Dockerfile already exists. Overwrite? [y/N]: y
# compose.yaml already exists. Overwrite? [y/N]: n
# → Перезаписан только Dockerfile
```

---

## Операции и команды

### Основные команды

```bash
# Запуск интерактивного помощника
docker init

# Проверка версии плагина
docker init --version
# → docker-init version 0.x.x
```

### Валидация после генерации

```bash
# Проверка синтаксиса Dockerfile
docker buildx build --check .

# Просмотр слоёв образа (v27+)
docker image ls --tree

# Запуск compose с пересборкой
docker compose up --build

# Проверка что контейнер запущен
docker compose ps
# → NAME                SERVICE             STATUS
# → project-server-1    server              running
```

### Проверка безопасности сгенерированных файлов

```bash
# Проверка что приложение работает от непривилегированного пользователя
docker exec <container> id
# → uid=1000(node) gid=1000(node)

# Проверка HEALTHCHECK
docker inspect --format='{{json .State.Health}}' <container>

# Сканирование уязвимостей
docker scout quickview <image>
```

---

## Типичные ошибки и их решение

### Ошибка 1: `docker init` не найден

**Причина:** Плагин не установлен или Docker Desktop устарел.

```bash
# Проверка установки
docker init --version

# Linux: установка плагина
apt-get install -y docker-ce-cli

# macOS/Windows: обновление Docker Desktop
# Скачайте последнюю версию с https://www.docker.com/products/docker-desktop/
```

### Ошибка 2: Нет манифестных файлов

**Причина:** Проект не содержит распознаваемых файлов (`package.json`, `requirements.txt` и т.д.).

```bash
# Решение 1: выбрать шаблон "Other" вручную
docker init

# Решение 2: создать минимальный манифест
touch requirements.txt  # для Python
# или
touch package.json      # для Node.js
```

### Ошибка 3: Файлы не перезаписываются

**Причина:** При предыдущем запуске выбрано `N` на промпте перезаписи.

```bash
# Решение: удалить или переместить существующие файлы
rm Dockerfile compose.yaml .dockerignore
docker init
```

### Ошибка 4: Контейнер не стартует после генерации

**Причины:**
- Неправильная команда запуска в промпте
- Порт уже занят на хосте

```bash
# Диагностика
docker compose logs server
# → Error: Cannot find module

# Решение: исправить команду запуска в compose.yaml или Dockerfile

# Проверка портов
ss -tlnp | grep 3000
# → Если занят — изменить порт в compose.yaml
```

### Ошибка 5: Проблемы с `USER` в Alpine

**Причина:** Некоторые базовые образы Alpine не содержат созданного пользователя.

```bash
# Диагностика
docker exec <container> id
# → uid=0(root) gid=0(root)

# Решение: добавить создание пользователя в Dockerfile
RUN addgroup -S app && adduser -S app -G app
USER app
```

---

## Лучшие практики

### Обязательная проверка после генерации

`snippet` `docker init` создаёт стартовые заготовки, а не production-ready конфигурации. Всегда проверяйте:

- **Пinning версий:** Базовые образы должны быть зафиксированы по конкретному тегу или SHA256.
- **HEALTHCHECK:** Наличие и корректность проверки здоровья.
- **Политика перезапуска:** В `compose.yaml` добавьте `restart: unless-stopped` для продакшн.
- **Лимиты ресурсов:** Установите `mem_limit` и `cpus` в `compose.yaml` или через `deploy` в Swarm/K8s.
- **Секреты:** Никогда не хардкодьте пароли в сгенерированных файлах — используйте переменные окружения или Docker secrets.

### Адаптация под проект

```bash
# 1. Сгенерировать файлы
docker init

# 2. Просмотреть и отредактировать
vim Dockerfile compose.yaml .dockerignore

# 3. Проверить что .dockerignore исключает нужные файлы
docker build --no-cache --progress=plain . 2>&1 | grep "Sending build context"

# 4. Собрать и запустить
docker compose up --build

# 5. Проверить работоспособность
curl http://localhost:3000/health
```

### Интеграция в CI/CD

```yaml
# .gitlab-ci.yml / .github/workflows/docker.yml
- name: Generate Docker files
  run: echo "" | docker init

- name: Build and test
  run: docker compose up --build -d

- name: Run tests
  run: docker compose exec server npm test
```

### Версионирование сгенерированных файлов

```bash
# Добавьте в git сразу после генерации
git add Dockerfile compose.yaml .dockerignore README.Docker.md
git commit -m "chore: add docker init files"
```

---

## Дополнительная информация

### Поддерживаемые платформы (2025–2026)

| Шаблон | Базовый образ | Особенности |
|:---|:---|:---|
| Node.js | `node:<version>-slim` | Multi-stage, tini, npm ci |
| Python | `python:<version>-slim` | venv, pip install, USER |
| Go | `golang:<version>-alpine` | Кросс-компиляция, минимальный образ |
| Java | `eclipse-temurin:<version>` | Maven, uber-jar |
| .NET | `mcr.microsoft.com/dotnet/aspnet:<version>` | Multi-stage, AOT |
| PHP with Apache | `php:<version>-apache` | mod_php, composer |
| Rust | `rust:<version>-slim` | cargo build, Alpine |
| Other | `alpine:latest` | Универсальный шаблон |

### Важное различие: docker init vs --init

| Компонент | Назначение | Пример использования |
|:---|:---|:---|
| `docker init` | Генерация файлов проекта | `docker init` |
| `--init` (флаг) | Запуск tini как PID 1 | `docker run --init myapp` |
| `init: true` (Compose) | Аналогично `--init` в Compose | `services: server: init: true` |

**Рекомендация:** Используйте `docker init` для создания структуры проекта, а `--init` в рантайме, если приложение не умеет корректно работать как PID 1 (обработка сигналов, очистка зомби-процессов).

### Ограничения

- **Сложные монолиты:** Проекты с специфическими системными библиотеками (обработка изображений, GPU) потребуют ручной правки `RUN apt-get install...`.
- **Монорепозитории:** Для Turborepo/Nx используйте `turbo prune` перед `docker init` для генерации файлов только для конкретного сервиса.
- **Кастомные базовые образы:** Генерация всегда использует официальные образы Docker Hub. Для корпоративных зеркал редактируйте `Dockerfile` вручную.
- **Docker Engine на Linux:** Если команда не найдена, убедитесь что установлен `docker-ce-cli` актуальной версии.

---

## См. также

- **[Команды Docker CLI](./docker_commands.md)** — справочник команд.
- **[Лучшие практики Dockerfile](./Dockerfile/Docker_best_practices/build_optimization.md)** — для ручной доработки.
- **[Docker Compose: Руководство](./Docker_compose/docker_compose_file_example.md)** — детали работы с `compose.yaml`.
- **[Решение проблемы PID 1](./Dockerfile/Instructions/runtime_execution.md)** — подробнее о флаге `--init` и `tini`.
- **[Безопасность в Dockerfile](./Dockerfile/Docker_best_practices/security.md)** — работа с пользователями и SBOM.
