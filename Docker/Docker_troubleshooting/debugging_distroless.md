# Debugging Distroless Containers

## Определения

**Distroless-образы** — минималистичные базовые образы, содержащие только приложение и runtime-зависимости. Отсутствуют shell, менеджеры пакетов, отладочные утилиты. Стандартный `docker exec -it <container> /bin/sh` не работает.

Типичные представители: `gcr.io/distroless/*`, `FROM scratch`.

## Основные концепции

### Почему distroless усложняют отладку

| Характеристика | Обычный образ | Distroless |
| :--- | :--- | :--- |
| **Shell** | `/bin/sh`, `/bin/bash` | Отсутствует |
| **Утилиты** | `ls`, `ps`, `curl`, `netstat` | Отсутствуют |
| **Доступ exec** | Работает | Недоступен |
| **Поверхность атаки** | Большая | Минимальная |

### Стратегии отладки

1. **Внешние инструменты** — запуск утилит из другого контейнера через общие namespaces
2. **Копирование данных** — извлечение файлов для анализа на хосте
3. **Специализированные команды** — `docker debug` (требует поддержки)

Подробно о пространствах имён: **[Namespaces](../../Linux/Core/namespaces.md)**.

## Практические сценарии

### Сценарий 1: Эфемерные отладочные контейнеры (рекомендуемый)

Запуск временного контейнера с утилитами, подключённого к namespaces целевого контейнера.

**Анализ сети:**

```bash
# nicolaka/netshoot — набор сетевых утилит (tcpdump, ss, dig, curl)
docker run --rm -it --network=container:<target_container> nicolaka/netshoot
```

**Анализ процессов:**

```bash
# Видны процессы целевого контейнера (ps, top, strace)
docker run --rm -it --pid=container:<target_container> alpine
```

**Анализ файловой системы:**

```bash
# Монтирование ФС целевого контейнера
docker run --rm -it --pid=container:<target_container> --volume=/proc/$(docker inspect -f '{{.State.Pid}}' <target_container>)/root:/hostfs alpine
```

### Сценарий 2: Отладка через `nsenter`

Прямой вход в namespaces работающего контейнера через привилегированный отладочный контейнер.

```bash
# Получить PID целевого контейнера
PID=$(docker inspect -f '{{.State.Pid}}' <container>)

# Войти во все namespaces через отладочный образ
docker run --rm -it --pid=host --net=host --privileged ubuntu bash -lc \
  "nsenter -t $PID -m -u -i -n -p -U bash"
```

**Параметры nsenter:**
- `-m` — mount namespace (ФС)
- `-u` — UTS namespace (hostname)
- `-i` — IPC namespace
- `-n` — network namespace
- `-p` — PID namespace
- `-U` — user namespace

Результат: оболочка внутри окружения целевого контейнера с утилитами из `ubuntu`.

### Сценарий 3: Копирование файлов для анализа

Извлечение логов, конфигов, артефактов на хост:

```bash
# Копирование файла из контейнера
docker cp <container>:/path/to/file /local/path/

# Копирование директории
docker cp <container>:/var/log ./logs/

# Анализ на хосте
cat /local/path/file.log
```

### Сценарий 4: `docker debug` (экспериментально)

Команда создаёт эфемерную копию контейнера с отладочными инструментами.

```bash
docker debug <container_name>
```

**Ограничения:**
- Требует Docker CLI с поддержкой плагина
- Может не работать с `scratch` и минимальными distroless-образами
- Изменения не сохраняются после перезапуска

Подробно: **[Docker Debug](./docker_debug.md)**.

## Дополнительная информация

### Сравнение методов

| Метод | Требования | Применимость | Сохранение изменений |
| :--- | :--- | :--- | :--- |
| **Эфемерные контейнеры** | Стандартный Docker | Все distroless | Нет |
| **nsenter** | `--privileged` | Все контейнеры | Нет |
| **docker cp** | Стандартный Docker | Все контейнеры | На хост |
| **docker debug** | Плагин Docker | Ограниченная | Нет |

### Профилактика проблем

Для упрощения будущей отладки:

1. **Централизованное логирование** — отправляйте логи во внешнюю систему (ELK, Loki)
2. **Health checks** — настройте `[HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)` для мониторинга
3. **Debug-образы** — создавайте отдельные образы с отладочными инструментами для staging
4. **Remote debugging** — используйте отладчики языка (Delve для Go, pdb для Python)
