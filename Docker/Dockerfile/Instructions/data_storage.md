# Инструкция Dockerfile: VOLUME

## Предварительные требования

Для работы с инструкцией `VOLUME` необходимо:

1. **Docker Engine:** Версия 17.06 или новее (для поддержки JSON-формата). Рекомендуется последняя стабильная версия Docker Engine или Docker Desktop.
2. **BuildKit:** Для предсказуемого поведения во время сборки рекомендуется использование BuildKit (включен по умолчанию в Docker 23.0+). Проверить статус: `docker buildx ls`.
3. **Знания:** Понимание базовых концепций Docker: образы, контейнеры, слои (layers), записываемый слой (writable layer). Рекомендуется предварительное чтение раздела **[Docker Volumes](../../Docker_fs/docker_volumes.md)** для понимания типов томов и их архитектуры.
4. **Рабочее окружение:** Доступ к терминалу с установленным Docker. Для монтирования bind mounts может потребоваться доступ к файловой системе хоста.

## Определения

**Инструкция `VOLUME`** — директива в Dockerfile, которая создает точку монтирования с указанным именем и помечает ее как содержащую внешне монтируемые тома (volumes). Она фиксирует "контракт" образа, указывая, какие пути предназначены для постоянного хранения данных.

Основные функции:
1. **Метаданные:** Добавляет в манифест образа (`Config.Volumes`) информацию о путях, которые Docker должен обрабатывать как тома.
2. **Автоматизация:** При запуске контейнера Docker автоматически создает **анонимный том** для этой точки, если пользователь не указал явное монтирование (через `-v`, `--mount` или в Compose).
3. **Безопасность данных:** Гарантирует, что данные будут вынесены за пределы эфемерного записываемого слоя контейнера, предотвращая их потерю при удалении контейнера.

Для понимания общей концепции томов, их типов и преимуществ см. **[Docker Volumes](../../Docker_fs/docker_volumes.md)**.

## Основные концепции

### Синтаксис

Инструкция поддерживает два формата: JSON-массив (рекомендуется) и строковый формат.

```dockerfile
# JSON-массив (рекомендуется, исключает ошибки парсинга оболочки)
VOLUME ["/var/log/"]

# Строковый формат с несколькими путями (разделение пробелами)
VOLUME /var/log /var/db

# Несколько путей в JSON-формате
VOLUME ["/app/data", "/app/cache"]
```

### Механизм инициализации (Copy-up)

Одной из важнейших особенностей `VOLUME` является автоматическое наполнение тома данными из образа при его создании.

*   **Как это работает:** Если при старте контейнера монтируется **новый (пустой)** именованный или анонимный том в директорию, где в образе уже есть файлы, Docker **копирует** эти файлы в том.
*   **Сохранение прав:** При копировании сохраняются UID/GID и права доступа (permissions), установленные в Dockerfile.
*   **Исключение (Bind Mounts):** Этот механизм **не работает** для bind mounts (монтирование папок с хоста). Папка с хоста всегда "перекрывает" содержимое контейнера, даже если она пуста.

### BuildKit vs Legacy Builder

Поведение `VOLUME` во время сборки (инструкции `RUN`, `COPY`, `ADD` после объявления тома) радикально различается.

| Характеристика | Legacy Builder (Старый) | BuildKit (Современный) |
| :--- | :--- | :--- |
| **Логика работы** | Создает реальный временный том для каждого шага `RUN`. | Воспринимает `VOLUME` только как метаданные для рантайма. |
| **Изменения после `VOLUME`** | **Отбрасываются.** Изменения в этой папке не попадут в итоговый образ. | **Сохраняются.** Изменения записываются в слои образа. |
| **Применение `chown`** | Не сработает для папки тома в последующих слоях. | Работает корректно. |

**Пример (BuildKit):**
```dockerfile
FROM alpine
VOLUME /data
RUN touch /data/test.txt # В BuildKit этот файл сохранится в образе
```

### VOLUME против BuildKit Cache Mounts

В современном Docker (2025+) для ускорения сборки вместо `VOLUME` следует использовать специфичные кэш-маунты.

| Характеристика | `VOLUME` | `RUN --mount=type=cache` |
| :--- | :--- | :--- |
| **Назначение** | Персистентность данных в рантайме. | Ускорение сборки (кэш зависимостей). |
| **Жизненный цикл** | Привязан к контейнеру/тому. | Сохраняется между сборками разных образов. |
| **Влияние на образ** | Создает точку монтирования в манифесте. | Не оставляет следов в итоговом образе. |

## Особенности и ограничения

1. **Необратимость:** Если в базовом образе (`FROM`) объявлен `VOLUME`, дочерние образы не могут его "удалить". Директория навсегда останется томом. Единственный способ обойти это — пересобрать базовый образ без `VOLUME`.

2. **Портативность:** В Dockerfile **нельзя** указать путь на хосте (bind mount), так как это нарушит переносимость образа. Путь всегда указывается относительно файловой системы контейнера.

3. **Взаимодействие с USER:** Права на папку тома фиксируются в момент выполнения инструкции `VOLUME`. Если после `VOLUME` выполнить `USER` с другим UID/GID, записи в томе будут принадлежать пользователю из `VOLUME`-слоя.
   *   *Рекомендация:* Сначала создайте папку, установите `chown` и `USER`, и только потом объявляйте `VOLUME`.

4. **Утечка места:** Анонимные тома, созданные автоматически, не удаляются вместе с контейнером (если не указан флаг `--rm`). Это приводит к накоплению "мусора" (`docker volume prune`). Периодически проверяйте:
   ```bash
   docker volume ls -f dangling=true
   ```

5. **Безопасность:** Использование `VOLUME` для чувствительных данных (секретов) не рекомендуется, так как данные сохраняются на диске хоста. Используйте `tmpfs` или Docker Secrets.

6. **Ограничение пути в Windows-контейнерах:** На Windows-хосте тома создаются в `\\?\pipe\docker-engine` или в `C:\ProgramData\docker\volumes`. Пути должны быть в формате Windows (обратные слэши) при монтировании.

7. **Множественные инструкции VOLUME:** Если объявить несколько `VOLUME` для одного пути — они не конфликтуют, но имеют эффект "последнего победителя". Рекомендуется объявлять тома в одной инструкции:
   ```dockerfile
   # Лучше так
   VOLUME ["/data", "/logs"]
   # А не так
   VOLUME /data
   VOLUME /logs
   ```

8. **Взаимодействие с .dockerignore:** Инструкция `VOLUME` не влияет на файлы, исключенные через `.dockerignore`. Однако, если исключенный путь объявлен как `VOLUME`, он всё равно будет создан как пустая директория.

9. **Поведение при `docker commit`:** При сохранении контейнера в образ через `docker commit`, тома **не включаются** в создаваемый образ. Это защищает данные от случайного включения в новый образ.

10. **Ограничение производительности:** На macOS/Windows через Docker Desktop тома с bind mounts работают через виртуальную машину, что может снижать производительность операций с большим количеством мелких файлов. Для таких сценариев предпочтительнее именованные тома.

## Практические сценарии

### Сценарий 1: Гарантированная персистентность (Базы данных)

Для баз данных `VOLUME` является обязательным "контрактом", гарантирующим, что данные не будут потеряны при случайном перезапуске без флагов монтирования.

```dockerfile
FROM postgres:16-alpine
# Данные БД всегда будут вынесены в том
VOLUME /var/lib/postgresql/data
```

### Сценарий 2: Защита зависимостей от Bind Mount (Node.js)

При использовании bind-mount для разработки (`-v .:/app`) папка `node_modules` на хосте (если она пуста или для другой ОС) может перекрыть установленные в контейнере пакеты. Анонимный том решает эту проблему.

```dockerfile
FROM node:20
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# Анонимный том для node_modules будет иметь приоритет над bind-mount корня
VOLUME ["/app/node_modules"]
```

### Сценарий 3: Передача данных между стадиями (Multi-stage)

Метаданные `VOLUME` не наследуются при `COPY --from`. Их нужно объявлять заново в финальном образе.

```dockerfile
# Стадия сборки
FROM node:20 AS builder
WORKDIR /app
COPY . .
RUN npm run build

# Финальный образ
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# Объявляем тома только здесь
VOLUME ["/var/cache/nginx", "/var/log/nginx"]
```

### Сценарий 4: Централизованное логирование (ELK/EFK)

Для сбора логов из контейнеров в сторонние системы (Filebeat, Fluentd) необходимо выносить директории логов в тома, чтобы агенты сбора имели к ним доступ.

```dockerfile
FROM nginx:alpine
# Логи nginx по умолчанию
RUN mkdir -p /var/log/nginx
VOLUME ["/var/log/nginx"]
# Приложение пишет логи в общую директорию
VOLUME ["/var/log/app"]
```

Запуск с привязкой к локальной директории для агента сбора:

```bash
docker run -d \
  -v /var/log/nginx:/var/log/nginx \
  -v /var/log/app:/var/log/app \
  --name webapp my-webapp
```

### Сценарий 5: Временные данные и кэши (tmpfs vs VOLUME)

Для данных, которые не должны сохраняться на диске хоста (временные кэши, промежуточные результаты вычислений), `VOLUME` не подходит — используйте `tmpfs`-маунты при запуске.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
# Временная директория для кэша (не сохраняется в образе)
RUN mkdir -p /tmp/cache
# Объявляем как том для возможности tmpfs-монтирования
VOLUME ["/tmp/cache"]
```

Запуск с `tmpfs` (данные хранятся только в RAM):

```bash
docker run -d --tmpfs /tmp/cache:rw,noexec,nosuid,size=100m my-app
```

### Сценарий 6: Секреты и конфиденциальные данные

**Не используйте `VOLUME` для хранения секретов** — данные записываются на диск хоста в открытом виде. Вместо этого:

1. **Docker Secrets** (рекомендуется для Swarm):
   ```bash
   echo "my_secret_password" | docker secret create db_password -
   ```

2. **tmpfs-маунты** (для non-Swarm окружений):
   ```bash
   docker run -d --tmpfs /run/secrets:rw,noexec,nosuid my-app
   ```

3. **Внешние менеджеры секретов** (HashiCorp Vault, AWS Secrets Manager).

Если всё же необходимо передать секрет через том, используйте **read-only** режим и минимизируйте времени жизни контейнера:

```bash
docker run -d \
  -v /path/to/secrets:/run/secrets:ro \
  --read-only \
  my-app
```

### Сценарий 7: Разработка vs Продакшн (переопределение VOLUME)

В разработке используйте bind mounts для hot-reload, в продакшн — именованные тома для персистентности. Инструкция `VOLUME` в Dockerfile задает "контракт", но не ограничивает способ монтирования.

**Dockerfile (общий):**

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --production
COPY . .
VOLUME ["/app/data", "/app/logs"]
CMD ["node", "server.js"]
```

**Разработка (bind mount):**

```bash
docker run -d \
  -v $(pwd)/src:/app/src \
  -v $(pwd)/data:/app/data \
  --name dev-app my-app
```

**Продакшн (именованные тома):**

```bash
docker run -d \
  -v app-data:/app/data \
  -v app-logs:/app/logs \
  --name prod-app my-app
```

## Дополнительная информация

### Инспекция образа

Проверить, какие тома объявлены в образе, можно с помощью команды `inspect`:

```bash
docker image inspect --format '{{.Config.Volumes}}' <image_name>
# → map[/var/lib/postgresql/data:{}]
```

### Сравнение типов хранилищ (Резюме)

| Тип | Где хранятся данные | Механизм Copy-up | Лучшее применение |
| :--- | :--- | :--- | :--- |
| **Named Volume** | /var/lib/docker/volumes | **Да** | Продакшн данные, БД |
| **Bind Mount** | Любая папка хоста | **Нет** | Исходный код (Hot-reload) |
| **tmpfs** | В оперативной памяти | **Нет** | Секреты, временные кэши |

### Смотрите также
- **[Docker Volumes](../../Docker_fs/docker_volumes.md)** — архитектура и типы томов.
- **[Инструкция USER](./runtime_execution.md#инструкция-user-и-права-доступа)** — настройка прав перед `VOLUME`.
- **[BuildKit в Dockerfile](../dockerfile_buildkit.md)** — подробнее о возможностях современного сборщика.
- **[Оптимизация сборки](../Docker_best_practices/build_optimization.md)** — использование кэш-маунтов.
- **[Docker Compose](../../Docker_compose/docker_compose_file_example.md)** — декларативное управление томами.

## Поиск и устранение неисправностей

### Типичные ошибки и их решения

#### Ошибка 1: "cannot mount volume over existing volume"

**Причина:** Попытка смонтировать том или bind mount на путь, который уже объявлен как `VOLUME` в родительском образе и был ранее смонтирован.

**Решение:**
- Используйте другой путь для монтирования.
- Если необходимо переопределить том, убедитесь, что контейнер запускается с флагом `-v` или `--mount`, который указывает на новый том/путь.

#### Ошибка 2: "error while creating mount source path" / "device or resource busy"

**Причина:** Docker не может создать путь для монтирования на хосте из-за блокировки другим процессом или отсутствия прав.

**Решение:**
```bash
# Проверьте, не занят ли путь другим контейнером
docker ps | grep <path>

# Остановите все контейнеры, использующие этот путь
docker stop $(docker ps -q --filter volume=<volume_name>)

# Убедитесь в правах доступа (Linux)
sudo chown -R $(whoami) /var/lib/docker/volumes/<volume_name>
```

#### Ошибка 3: Данные не сохраняются после перезапуска контейнера

**Причина:** Используется анонимный том вместо именованного, или контейнер был запущен без явного монтирования.

**Решение:**
```bash
# Проверьте тип тома
docker inspect <container_name> | grep -A 10 "Mounts"

# Переименуйте анонимный том или создайте именованный
docker run -d -v mydata:/var/lib/app --name app myimage
```

#### Ошибка 4: "read-only file system" при попытке записи в том

**Причина:** Том смонтирован в режиме read-only (`:ro`) или контейнер запущен с `--read-only`.

**Решение:**
```bash
# Проверьте флаги монтирования
docker inspect <container_name> | grep -A 5 "Mounts"

# Переопределите на read-write
docker run -d -v mydata:/var/lib/app:rw --name app myimage
```

#### Ошибка 5: Не срабатывают права доступа (UID/GID) на томе

**Причина:** Права на папку тома фиксируются в момент выполнения инструкции `VOLUME`. Если пользователь меняется после `VOLUME`, права могут не совпадать.

**Решение:**
```dockerfile
# Правильный порядок: сначала chown, потом VOLUME
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data
USER appuser
VOLUME ["/app/data"]
```

### Диагностические команды

```bash
# Просмотр томов, привязанных к контейнеру
docker inspect --format '{{json .Mounts}}' <container_name> | jq

# Просмотр объявленных томов в образе
docker image inspect --format '{{json .Config.Volumes}}' <image_name> | jq

# Проверка размера тома
docker system df -v | grep -A 5 <volume_name>

# Просмотр содержимого тома (через временный контейнер)
docker run --rm -v <volume_name>:/data alpine ls -la /data
```

## Рекомендации по использованию

### Do's (Рекомендуется)

1. **Всегда используйте именованные тома в продакшн:**
   ```bash
   docker run -v postgres-data:/var/lib/postgresql/data postgres:16
   ```

2. **Объявляйте `VOLUME` для критичных данных** — это гарантирует, что данные не потеряются даже при случайном запуске без флагов монтирования.

3. **Порядок инструкций важен** — создавайте директорию, устанавливайте права, меняйте пользователя и только потом объявляйте `VOLUME`:
   ```dockerfile
   RUN mkdir -p /data && chown appuser:appuser /data
   USER appuser
   VOLUME ["/data"]
   ```

4. **Используйте JSON-формат** для явного указания путей:
   ```dockerfile
   VOLUME ["/var/log", "/var/db"]  # Рекомендуется
   ```

5. **Документируйте тома** в README или Dockerfile с помощью комментариев:
   ```dockerfile
   # Том для базы данных PostgreSQL (персистентные данные)
   VOLUME /var/lib/postgresql/data
   # Том для логов (может быть смонтирован наружу)
   VOLUME /var/log/postgresql
   ```

### Don't (Не рекомендуется)

1. **Не используйте `VOLUME` для исходного кода** — это перекрывает файлы из образа и предотвращает обновления:
   ```dockerfile
   # НЕПРАВИЛЬНО
   COPY . /app
   VOLUME /app
   ```

2. **Не используйте `VOLUME` для конфигурационных файлов** — изменения в образе не будут применяться:
   ```dockerfile
   # НЕПРАВИЛЬНО
   COPY config.yaml /etc/app/
   VOLUME /etc/app
   ```

3. **Не храните секреты в томах** — данные записываются на диск хоста в открытом виде.

4. **Не забывайте про утечку анонимных томов** — регулярно выполняйте очистку:
   ```bash
   docker volume prune
   ```

5. **Не игнорируйте разницу между BuildKit и Legacy Builder** — проверьте, какой сборщик используется:
   ```bash
   docker buildx ls
   ```

## Валидация и проверка

### Шаг 1: Проверка объявленных томов в образе

После сборки образа убедитесь, что тома объявлены корректно:

```bash
# Просмотр конфигурации томов
docker image inspect --format '{{.Config.Volumes}}' myimage
# → map[/var/lib/postgresql/data:{} /var/log/postgresql:{}]

# Просмотр полного манифеста
docker image inspect myimage | jq '.[0].Config.Volumes'
```

### Шаг 2: Запуск контейнера и проверка монтирования

```bash
# Запуск с явным именованным томом
docker run -d \
  -v test-data:/var/lib/postgresql/data \
  --name test-db \
  postgres:16-alpine

# Проверка, что том создан и смонтирован
docker inspect test-db | jq '.[0].Mounts'
```

Ожидаемый результат:
```json
[
  {
    "Type": "volume",
    "Name": "test-data",
    "Source": "/var/lib/docker/volumes/test-data/_data",
    "Destination": "/var/lib/postgresql/data",
    "Mode": "rw",
    "RW": true,
    "Propagation": ""
  }
]
```

### Шаг 3: Проверка персистентности данных

```bash
# Создайте данные в контейнере
docker exec test-db psql -U postgres -c "CREATE TABLE test(id INT); INSERT INTO test VALUES(1);"

# Остановите и удалите контейнер
docker stop test-db && docker rm test-db

# Запустите новый контейнер с тем же томом
docker run -d \
  -v test-data:/var/lib/postgresql/data \
  --name test-db-new \
  postgres:16-alpine

# Проверьте, что данные сохранились
docker exec test-db-new psql -U postgres -c "SELECT * FROM test;"
# →  id
#  ---
#   1
```

### Шаг 4: Проверка поведения Copy-up

```bash
# Создайте Dockerfile с файлами до VOLUME
cat > Dockerfile.test <<EOF
FROM alpine
RUN mkdir -p /data && echo "initial" > /data/file.txt
VOLUME /data
RUN echo "after-volume" > /data/after.txt
EOF

# Соберите образ (BuildKit)
DOCKER_BUILDKIT=1 docker build -t test-copyup -f Dockerfile.test .

# Запустите контейнер и проверьте содержимое
docker run --rm test-copyup ls -la /data/
# → file.txt (должен быть)
# → after.txt (только в BuildKit)
```

### Шаг 5: Проверка прав доступа

```bash
# Создайте Dockerfile с пользователем
cat > Dockerfile.perms <<EOF
FROM alpine
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
RUN mkdir -p /app/data && chown -R appuser:appgroup /app/data
USER appuser
VOLUME ["/app/data"]
EOF

# Соберите и запустите
DOCKER_BUILDKIT=1 docker build -t test-perms -f Dockerfile.perms .
docker run --rm test-perms ls -la /app/
# → drwxr-xr-x ... appuser appgroup ... data
```

### Шаг 6: Проверка на утечку анонимных томов

```bash
# Проверьте количество анонимных томов
docker volume ls -f dangling=true | wc -l

# Очистите неиспользуемые тома
docker volume prune -f

# Проверьте после очистки
docker volume ls -f dangling=true | wc -l
# → 0
```
