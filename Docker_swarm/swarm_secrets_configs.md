# Docker Swarm: Секреты и конфигурации

**Актуально для:** Docker Swarm 29.x

## Определения

**Секреты (Secrets)** — встроенный механизм Docker Swarm для безопасного хранения и доставки чувствительных данных (пароли, токены, ключи SSH, сертификаты TLS).
- **Безопасность:** Шифруются при хранении в Raft-логе на менеджерах.
- **Доставка:** Передаются на узлы по зашифрованному каналу mTLS и монтируются в контейнеры как файлы во временную файловую систему в оперативной памяти (tmpfs). Данные никогда не записываются на диск рабочих узлов (workers).

**Конфигурации (Configs)** — механизм для управления нечувствительными данными (файлы настроек `.conf`, `.yaml`, параметры приложений).
- **Отличие от секретов:** Конфигурации не шифруются при хранении в Raft-логе. По умолчанию монтируются по пути `/<имя-конфига>` внутри контейнера (не в `/run/secrets/`).

## Предварительные требования

- Docker Engine 29.x с включенным Swarm mode (`docker swarm init` или `docker swarm join`)
- Узел-менеджер с доступом к Raft-логу (секреты и конфиги хранятся только на менеджерах)
- Для production: включенный `autolock` для защиты ключей шифрования Raft при перезагрузке менеджеров
- Сетевая связность между менеджерами (порт `2377/TCP`) и между всеми узлами (порт `7946/TCP+UDP`, `4789/UDP`)
- Достаточно свободной оперативной памяти на узлах: каждый секрет/конфиг монтируется в tmpfs и занимает место в RAM

## Базовые концепции

### Хранение и доступ

| Характеристика | Секреты (Secrets) | Конфигурации (Configs) |
| :--- | :--- | :--- |
| **Шифрование (Raft)** | Зашифровано | Не шифровано (Plaintext) |
| **Путь в контейнере** | По умолчанию `/run/secrets/<имя>` | Любой путь (через `target`) |
| **Тип хранилища** | tmpfs (только в памяти) | tmpfs (только в памяти) |
| **Изменяемость** | Неизменяемы (Immutable) | Неизменяемы (Immutable) |
| **Лимит размера** | 500 КБ | 500 КБ |

### Архитектура безопасности

1. **Изоляция:** Секрет доступен только тем узлам, на которых запущены задачи (tasks) конкретного сервиса.
2. **Принцип минимальных привилегий:** Узел-воркер получает только те секреты, которые необходимы его текущим задачам. После остановки задачи секрет размонтируется и удаляется из памяти узла.
3. **Autolock (Автоблокировка):** Механизм защиты ключей шифрования Raft. При включенном `autolock` после перезапуска демона Docker менеджер остается заблокированным до ввода ключа разблокировки (`unlock-key`).

### Неизменяемость и версионность

Объекты в Swarm неизменяемы. Если содержимое файла (например, `nginx.conf`) изменилось, нельзя просто обновить существующий `config`. Стандартный паттерн — **версионирование**:

1. Создается новый объект: `app_config_v2`.
2. Сервис обновляется для использования новой версии.
3. Swarm выполняет **Rolling Update**, постепенно заменяя контейнеры.
4. Старая версия `app_config_v1` удаляется после завершения обновления.

## Практические сценарии

### Управление через CLI

#### Создание и удаление

```bash
# Создание секрета из файла
docker secret create db_password ./password.txt

# Создание из стандартного ввода (безопаснее, не оставляет следов в истории)
echo "my_secret_token" | docker secret create api_token -

# Создание конфигурации с метками
docker config create --label env=prod --label app=nginx nginx_v1 ./nginx.conf

# Удаление (только если объект не используется сервисами)
docker secret rm db_password
```

#### Инспекция и фильтрация

```bash
# Список с фильтрацией по меткам
docker config ls --filter label=env=prod

# Просмотр метаданных (содержимое секрета скрыто)
docker secret inspect db_password

# Просмотр содержимого конфигурации (только для Configs)
docker config inspect --format='{{json .Spec.Data}}' nginx_v1 | jq -r . | base64 -d
```

**Валидация:**
```bash
docker secret ls
# → db_password, api_token в списке

docker config ls --filter label=env=prod
# → nginx_v1 найден по фильтру

docker secret inspect db_password
# → отображаются метаданные, содержимое скрыто
```

### Использование в Swarm-сервисах

#### Расширенная настройка монтирования

При создании сервиса можно переопределить имя файла, владельца и права доступа:

```bash
docker service create --name web \
  --secret source=ssl_cert,target=/etc/nginx/certs/server.crt,uid=101,gid=101,mode=0400 \
  --config source=nginx_conf,target=/etc/nginx/nginx.conf,mode=0444 \
  nginx:alpine
```

**Валидация:**
```bash
docker service inspect web --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'
# → ssl_cert с target=/etc/nginx/certs/server.crt, mode=0400

docker service inspect web --format '{{json .Spec.TaskTemplate.ContainerSpec.Configs}}'
# → nginx_conf с target=/etc/nginx/nginx.conf, mode=0444

docker exec $(docker ps --filter name=web -q) ls -l /etc/nginx/certs/server.crt
# → -r-------- 101 101 ... server.crt

docker exec $(docker ps --filter name=web -q) ls -l /etc/nginx/nginx.conf
# → -r--r--r-- ... nginx.conf
```

### Развертывание через Stack (Docker Compose)

В файлах стека поддерживаются два способа определения ресурсов:

#### 1. Внешние ресурсы (External) — Рекомендуется для Prod
Секреты создаются заранее вручную или через CI/CD, что исключает наличие чувствительных данных в репозитории.

```yaml
version: '3.8'
services:
  app:
    image: my-app:latest
    secrets:
      - db_password
secrets:
  db_password:
    external: true
```

#### 2. Файловые ресурсы (File) — Для разработки
Docker создаст секрет автоматически при первом деплое. **Внимание:** при изменении файла на диске Swarm не обновит секрет автоматически, так как он неизменяем.

```yaml
secrets:
  db_password:
    file: ./prod_password.txt
```

**Валидация:**
```bash
docker stack deploy -c docker-compose.yml myapp
# → secret db_password создан автоматически

docker secret ls
# → myapp_db_password в списке (имя преобразовано в <stack>_<secret>)

docker service inspect myapp_app --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'
# → db_password с target=/run/secrets/db_password
```

### Ротация секретов без простоя

Для обновления секрета без остановки сервиса:

1. Создайте новую версию: `docker secret create db_pass_v2 ./new_pass.txt`.
2. Обновите сервис атомарно:
   ```bash
   docker service update \
     --secret-rm db_pass_v1 \
     --secret-add source=db_pass_v2,target=db_password \
     my-service
   ```
   *Здесь `target=db_password` позволяет приложению продолжать читать файл по старому пути, хотя источник изменился.*

**Валидация:**
```bash
docker service ps my-service --no-trunc
# → задачи обновлены, новый секрет db_pass_v2 активен

docker service inspect my-service --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'
# → db_pass_v2 с target=db_password

docker secret ls
# → db_pass_v2 (актуальный), db_pass_v1 (старый, можно удалить)

# Проверка содержимого внутри контейнера
docker exec $(docker ps --filter name=my-service -q) cat /run/secrets/db_password
# → новое значение из db_pass_v2
```

## Безопасность и Best Practices

1. **Включите Autolock:** Это защитит секреты при краже диска менеджера или несанкционированном доступе к ФС.
   ```bash
   docker swarm update --autolock=true
   ```
2. **Ротируйте Unlock-key:** Регулярно меняйте ключ разблокировки.
   ```bash
   docker swarm unlock-key --rotate
   ```
3. **Избегайте Environment Variables для секретов:** Переменные окружения часто логируются и видны через `docker inspect`. Используйте монтирование файлов в `/run/secrets/`.
 4. **Паттерн `_FILE`:** Многие официальные образы (Postgres, MySQL) поддерживают суффикс `_FILE` в переменных окружения (например, `POSTGRES_PASSWORD_FILE=/run/secrets/db_pass`), что позволяет безопасно считывать пароль из файла.
 5. **Версионирование имен:** При ротации используйте суффиксы `_v2`, `_v3` или даты (`_20260101`), чтобы Swarm корректно выполнял Rolling Update.
 6. **Ограничение размера:** Секреты и конфиги имеют лимит 500 КБ. Для больших файлов используйте тома (NFS, GlusterFS) или внешние хранилища (S3/Vault).
 7. **Минимальные права:** При монтировании указывайте `mode` как можно более restrictive (например, `0400` для секретов, `0444` для конфигов).
 8. **Cleanup:** После Rolling Update удаляйте старые версии секретов/конфигов (`docker secret rm <old>`) чтобы избежать накопления "сиротских" объектов.
 9. **External registry:** Для production создавайте секреты вне стека (`external: true`) и предоставляйте им через CI/CD, а не через `file:` в Compose.
 10. **Configs vs Secrets:** Используйте Secrets только для чувствительных данных. Configs не шифруются и подходят для настроек, которые могут быть доступны при инспекции.

## Операции и команды

| Область | Команды | Назначение |
|:---|:---|:---|
| **Создание** | `docker secret create <name> <file>` | Создание секрета из файла |
| | `echo "token" \| docker secret create <name> -` | Создание секрета из stdin (не оставляет следов в истории) |
| | `docker config create [--label key=val] <name> <file>` | Создание конфигурации с опциональными метками |
| **Инспекция** | `docker secret ls [--filter label=...]` | Список секретов с фильтрацией |
| | `docker config ls [--filter label=...]` | Список конфигураций с фильтрацией |
| | `docker secret inspect <name>` | Метаданные секрета (содержимое скрыто) |
| | `docker config inspect --format '{{json .Spec.Data}}' <name> \| base64 -d` | Просмотр содержимого конфигурации |
| **Обновление** | `docker service update --secret-rm <old> --secret-add source=<new>,target=<path> <svc>` | Ротация секрета без остановки |
| | `docker service update --config-rm <old> --config-add source=<new>,target=<path> <svc>` | Ротация конфигурации без остановки |
| | `docker stack deploy -c <file> <stack>` | Деплой стека с новыми секретами/конфигами |
| **Удаление** | `docker secret rm <name>` | Удаление неиспользуемого секрета |
| | `docker config rm <name>` | Удаление неиспользуемой конфигурации |

## Устранение неполадок

### Диагностика

```bash
# Статус секретов сервиса
docker service inspect <SERVICE> --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'

# Статус конфигураций сервиса
docker service inspect <SERVICE> --format '{{json .Spec.TaskTemplate.ContainerSpec.Configs}}'

# Проверка прав на файлы секретов внутри контейнера
docker exec $(docker ps --filter name=<service> -q) ls -l /run/secrets/
```

### Типовые проблемы

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Secret not found** | В YAML указано `external: true`, но секрет не создан | `docker secret create <name> <file>` |
| **Секрет не обновляется** | Секрет смонтирован в `tmpfs` при старте контейнера | Версионирование имен или `docker service update --force` |
| **Лимит 500 КБ превышен** | Файл секрета/конфига больше 500 КБ | Использовать тома (NFS, GlusterFS) или внешнее хранилище |
| **Permission denied** | Указан `uid/gid` не существующие в образе | Проверить `id` в контейнере (`docker exec <ctr> id`) |
| **Config не найден по пути** | У Configs default target `/<config-name>`, а не `/run/secrets/` | Указать `target=/run/secrets/<name>` явно или использовать правильный путь |
| **Secret виден в inspect** | Секрет передан через переменную окружения, а не через `--secret` | Использовать монтирование файлов, паттерн `_FILE` |
| **Autolock заблокировал менеджер** | После перезапуска Docker менеджер требует unlock-key | `docker swarm unlock` |
| **Stale secret после удаления** | Секрет удален, но задачи всё еще используют старую ревизию | `docker service update --force <svc>` для пересоздания задач |

## Особые случаи и ограничения

- **Размер 500 КБ:** Жесткий лимит для секретов и конфигов. При превышении возвращается ошибка `ResourceExhausted`. Для TLS-сертификатов с цепочкой или больших конфигов используйте Configs с внешним хранилищем или bind-mount тома.
- **Нулевой размер:** Пустые файлы (`0` байт) не допускаются при создании секрета или конфига — `InvalidArgument: data must be larger than 0`.
- **Windows containers:** Секреты монтируются в `C:\ProgramData\Docker\secrets`, конфиги — в `C:\ProgramData\Docker\internal\configs` с символическими ссылками на целевой путь.
- **Глобальные сервисы (`mode: global`):** Секреты и конфиги монтируются на все узлы кластера, что увеличивает нагрузку на память менеджеров при большом числе секретов.
- **Rollback:** При откате сервиса (`docker service rollback`) старые секреты/конфиги не восстанавливаются автоматически — необходимо явно обновить сервис через `--secret-add`/`--config-add`.
- **Autolock и потеря ключа:** При утере unlock-key при включенном `autolock` доступ к секретам невозможен без переинициализации кластера — резервное копирование ключа обязательно.
- **Configs и кэширование:** Некоторые приложения кэшируют конфиги при старте и не перечитывают их при обновлении Configs — требуется `docker service update --force` или сигнал перезагрузки (SIGHUP).

## Дополнительная информация

### Сравнение методов передачи данных

| Метод | Безопасность | Портируемость | Применение |
|:---|:---|:---|:---|
| **Swarm Secrets** | **Высокая** | Полная | Пароли, ключи, сертификаты |
| **Swarm Configs** | **Средняя** | Полная | Конфиги (nginx, prometheus) |
| **Volumes (bind)** | **Низкая** | Нет | Большие данные, Legacy |
| **Env Vars** | **Низкая** | Полная | Нечувствительные флаги |

### Смотрите также

- **[Управление секретами в Docker](../../Docker/Docker_security/secrets_management.md)** — общие принципы и методы (Compose, BuildKit).
- **[Продвинутые стратегии Stack](../../Docker_swarm/swarm_stack_advanced.md)** — Canary, Blue-Green и ротация через Compose.
- **[Безопасность Docker Swarm](../../Docker_swarm/CI_CD/best_practices.md)** — рекомендации по защите кластера и секретов.
- **[Справочник CLI для Swarm](../../Docker_swarm/swarm_management_cli.md)** — полный перечень команд управления.
