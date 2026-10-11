# Docker Swarm: Развертывание стеков (Stack Deployment)

**Актуально для:** Docker Swarm 29.x

## Определения

**Стек (Stack)** — группа взаимосвязанных сервисов, которые совместно образуют приложение в среде Docker Swarm. Стек описывается декларативно в YAML-файле и управляется как единая сущность через команду `docker stack deploy`.

**Docker Stack** — нативный инструмент оркестрации Docker для управления жизненным циклом многоконтейнерных приложений в кластере. Он транслирует инструкции из файла спецификации (обычно `docker-compose.yml`) в объекты Swarm: сервисы, сети, секреты и конфигурации.

**Rolling Update (Поэтапное обновление)** — стратегия плавной замены старых версий контейнеров новыми с целью минимизации простоя.

**Rollback (Откат)** — процесс возврата к предыдущей стабильной версии конфигурации или образа при обнаружении сбоев в новой версии.

**Immutable Infrastructure (Неизменяемая инфраструктура)** — принцип, согласно которому объекты Swarm (секреты, конфиги, задачи) не изменяются после создания. Для обновления требуется создание нового объекта с новым именем.

## Предварительные требования

- **Docker Engine 29.x** на всех узлах кластера. Swarm mode ships внутри Docker Engine, отдельная установка не требуется.
- **Swarm mode инициализирован** на менеджере: `docker swarm init`. Кластер должен иметь quorum (≥3 менеджера для продакшена).
- **Docker Registry** с предварительно загруженными образами. Секция `build` в Compose-файле игнорируется; образы должны быть собраны и опубликованы до деплоя.
- **Порты открыты** на всех узлах: `2377/tcp` (менеджерный интерфейс), `7946/tcp+udp` (discovery), `4789/udp` (overlay VXLAN).
- **Права доступа**: пользователь, под которым запускается `docker stack deploy`, должен иметь доступ к Docker socket и права на чтение compose-файлов.
- **Приватный Registry**: для образов из приватных реестров требуется локальный `docker login` и флаг `--with-registry-auth` при деплое.
- **Секреты и конфиги**: перед деплоем убедитесь, что все секреты (`docker secret create`) и конфиги (`docker config create`) существуют в кластере, если они объявлены как `external: true`.

## Базовые концепции

### Отличия от Docker Compose

Несмотря на использование идентичного формата файлов, механизмы работы инструментов принципиально различаются:

| Параметр | Docker Compose | Docker Stack |
|---|---|---|
| **Команда** | `docker compose up` | `docker stack deploy` |
| **Масштаб** | Одиночный хост | Весь Swarm-кластер |
| **Секция `deploy`** | Игнорировалась в v1, частично в v2 | Первостепенная значимость |
| **Имена контейнеров** | Задаются через `container_name` | Генерируются автоматически |
| **Порядок запуска** | Строгий через `depends_on` | Декларативный (через Healthchecks) |
| **Сборка образов** | Инструкция `build` | Не поддерживается (нужен Registry) |

### Параметры, игнорируемые в режиме Swarm

Оркестратор Swarm берет на себя управление жизненным циклом процессов, поэтому следующие инструкции из YAML-файла игнорируются:

- `container_name`: Swarm самостоятельно формирует имена вида `<stack>_<service>.<index>.<id>`.
- `restart`: Вместо этого используется `deploy.restart_policy`.
- `depends_on`: В версиях Compose до 3.x Swarm полностью игнорирует эту инструкцию. Сервисы запускаются параллельно.
- `build`: Все образы должны быть предварительно собраны и загружены в Docker Registry.
- `links` и `network_mode`: Используются только оверлейные сети (`overlay`).

### Использование переменных окружения

Docker Stack поддерживает подстановку переменных окружения из оболочки, в которой запущена команда `deploy`. Это позволяет параметризовать файлы для разных окружений (dev/prod).

```yaml
services:
  app:
    image: my-repo/app:${APP_VERSION:-latest}
    networks:
      - app_net
```

**Важно:** Переменные подставляются **в момент запуска** команды на менеджере. Если переменная изменится позже, Swarm не узнает об этом до следующего `deploy`.

## Практические сценарии

### Управление жизненным циклом стека

Команда `deploy` идемпотентна: она создает стек, если он не существует, или обновляет его конфигурацию до состояния, описанного в файле.

#### Развертывание и обновление

```bash
# Развертывание из одного или нескольких файлов
docker stack deploy -c base.yml -c prod.yml myapp
# → Creating network myapp_default
# → Creating service myapp_web

# Удаление сервисов, которых больше нет в YAML-файле
docker stack deploy --prune -c docker-compose.yml myapp
# → Removing service myapp_old_worker

# Деплой с авторизацией в приватном Registry (обязательно для воркеров)
docker stack deploy --with-registry-auth -c docker-compose.yml myapp
# → Updating service myapp_web (id: ...)
```

**Валидация:**
```bash
docker stack ls
# → myapp должен присутствовать в списке
docker stack services myapp
# → все сервисы имеют желаемое количество реплик (DESIRED == RUNNING)
docker service inspect --format='{{.UpdateStatus.State}}' <service>
# → should be "updating" during deploy, then "completed"
```

#### Мониторинг и диагностика

```bash
# Список всех запущенных стеков
docker stack ls
# → NAME      SERVICES   ORCHESTRATOR
# → myapp     2          Swarm

# Просмотр задач (контейнеров) и причин их падения
docker stack ps myapp --no-trunc
# → ID            NAME          IMAGE          NODE      DESIRED STATE  CURRENT STATE            ERROR
# → 123abc456def  myapp_web.1   nginx:1.26.3   node-2    Running        Running 2 hours ago

# Список сервисов в стеке с указанием реплик
docker stack services myapp
# → ID            NAME          MODE          REPLICAS  IMAGE          PORTS
# → xyz789012345  myapp_web     replicated    3/3       nginx:1.26.3   *:80->80/tcp
```

**Валидация:**
```bash
docker stack ls --format '{{.Name}} {{.Services}}'
# → myapp 2
docker stack services myapp --format '{{.Name}} {{.Replicas}}'
# → myapp_web 3/3
docker stack ps myapp --filter "desired-state=running" --format '{{.Name}} {{.CurrentState}}'
# → только запущенные задачи
```

### Настройка Rolling Update и Rollback

Блоки `update_config` и `rollback_config` определяют поведение Swarm при изменениях.

```yaml
deploy:
  replicas: 5
  update_config:
    parallelism: 2
    delay: 10s
    order: start-first
    failure_action: rollback  # Автоматический откат при неудаче
  rollback_config:
    parallelism: 0            # 0 означает обновление всех реплик сразу
    order: stop-first
```

| Параметр | Описание |
|---|---|
| `parallelism` | Количество реплик, обновляемых одновременно. `0` означает обновление всех реплик сразу. |
| `delay` | Задержка между обновлением групп реплик. |
| `failure_action` | `pause` (остановить деплой), `continue` (игнорировать), `rollback` (вернуть старую версию). |
| `order` | `start-first` (сначала новые), `stop-first` (сначала остановить старые). По умолчанию `stop-first`. |
| `monitor` | Время наблюдения за стабильностью контейнера после запуска. По умолчанию `5s`. |
| `max_failure_ratio` | Допустимая доля ошибок (0..1). По умолчанию `0`. |

**Валидация:**
```bash
docker service inspect --format='{{.Spec.UpdateConfig}}' <service>
# → parallelism:2 delay:10s order:start-first failure_action:rollback
docker service inspect --format='{{.Spec.RollbackConfig}}' <service>
# → parallelism:0 delay:0s order:stop-first
docker service ps <service> --no-trunc
# →观察Update status字段
```

### Размещение и ограничения (Placement)

Для управления распределением задач используются метки узлов.

```bash
# Добавление метки на узел
docker node update --label-add zone=dmz node-1
# → node-1
```

```yaml
deploy:
  placement:
    constraints:
      - node.role == worker
      - node.labels.zone == dmz
    preferences:
      - spread: node.labels.datacenter  # Равномерное распределение по дата-центрам
```

**Валидация:**
```bash
docker service ps <service> --format '{{.Node}} {{.Name}}'
# → убедитесь, что задачи распределены только по worker-узлам
docker node ls --filter "label=zone=dmz"
# → список узлов, удовлетворяющих constraint
```

### Ограничение ресурсов

Всегда указывайте лимиты, чтобы один сервис не "задушил" весь узел.

```yaml
deploy:
  resources:
    reservations:
      cpus: '0.25'
      memory: 256M
    limits:
      cpus: '0.50'
      memory: 512M
```

**Валидация:**
```bash
docker service inspect --format='{{.Spec.TaskTemplate.Resources}}' <service>
# → reservations.cpus:0.25 reservations.memory:268435456 limits.cpus:0.50 limits.memory:536870912
docker node ls
# → убедитесь, что узлы не перегружены (AVAILABILITY == Active)
docker stats --no-stream
# → проверка фактического потребления ресурсов контейнерами
```

## Операции и команды

| Область | Команды | Назначение |
|---|---|---|
| **Развертывание** | `docker stack deploy -c <file> <name>` | Деплой стека из Compose-файла |
| | `docker stack deploy --prune -c <file> <name>` | Деплой с удалением устаревших сервисов |
| | `docker stack deploy --with-registry-auth -c <file> <name>` | Передача registry-авторизации воркерам |
| | `docker stack deploy --detach=false -c <file> <name>` | Ожидание convergence вместо немедленного выхода |
| **Инспекция** | `docker stack ls` | Список всех стеков |
| | `docker stack services <name>` | Сервисы в стеке |
| | `docker stack ps <name> --no-trunc` | Задачи в стеке с деталями |
| | `docker stack config <name>` | Финальный скомпилированный Compose-файл |
| **Обновление** | `docker service update --image <new> <svc>` | Принудительное обновление образа (инициирует Rolling Update) |
| | `docker service update --rollback <svc>` | Ручной откат к предыдущей версии |
| | `docker service update --update-parallelism <n> <svc>` | Изменение parallelism без полного передеплоя |
| **Удаление** | `docker stack rm <name>` | Полное удаление стека и всех его сервисов |

### Ошибка "depends_on" и порядок запуска

Так как Swarm игнорирует `depends_on`, приложения должны быть устойчивы к отсутствию зависимостей (БД, очередь) в момент старта.

**Решение:**
1.  Использование **Healthchecks** в Docker-файле или Compose.
2.  Использование скриптов ожидания (`wait-for-it.sh`, `dockerize -wait`) в `entrypoint`.
3.  Настройка циклов переподключения в коде приложения.

**Диагностика:**
```bash
docker service ps <service> --filter "desired-state=running" --format '{{.Name}} {{.CurrentState}}'
# → проверка, что все реплики перешли в Running
docker logs <task-id>
# → поиск ошибок подключения к зависимостям
```

### Проблемы с обновлением секретов и конфигов

В Docker Swarm **Config** и **Secret** неизменяемы (immutable). Чтобы обновить их содержимое, нужно создать новый объект с новым именем (например, `config-v2`) и обновить ссылку в YAML-файле. Это инициирует Rolling Update сервиса.

**Диагностика:**
```bash
docker secret ls
# → проверка версий секретов
docker config ls
# → проверка версий конфигов
docker service inspect --format='{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}' <service>
# → список смонтированных секретов
```

### `update_config` не применяется

Swarm игнорирует изменения только в секции `labels` и `annotations` без изменения образа или аргументов. Для применения `update_config` требуется изменение конфигурации, затрагивающей задачи.

**Решение:**
1.  Убедитесь, что изменяется поле, влияющее на задачи (`image`, `args`, `env`, `secrets`, `configs`).
2.  Проверьте, что `parallelism` > 0 и `delay` задан в правильном формате (`10s`, `1m`).
3.  Для принудительного перезапуска без изменений конфигурации используйте `--force`:
    ```bash
    docker service update --force <service>
    ```

**Диагностика:**
```bash
docker service inspect --format='{{.UpdateStatus.State}}' <service>
# → "paused" при ошибке, "updating" в процессе, "completed" после успеха
docker service inspect --format='{{.UpdateStatus.Message}}' <service>
# → причина паузы или ошибки
docker events --filter 'service=<service>' --filter 'event=update'
# → live-события обновления
```

### Workers не могут скачать образ из приватного Registry

При деплое без флага `--with-registry-auth` воркеры не получают credentials и не могут скачать образ.

**Решение:**
```bash
docker login registry.example.com
docker stack deploy --with-registry-auth -c docker-compose.yml myapp
```

**Диагностика:**
```bash
docker service ps <service> --filter "desired-state=running" --format '{{.Node}} {{.CurrentState}}'
# → найдите узлы с ошибками
docker node ls
# → проверка доступности узлов
```

### Стек не удаляется полностью

Внешние ресурсы (`external: true` в сетях/volumes) не удаляются вместе со стеком.

**Решение:**
```bash
docker stack rm myapp
docker network ls --filter "label=com.docker.stack.namespace=myapp"
# → удалите оставшиеся сети вручную, если они external
docker volume ls --filter "label=com.docker.stack.namespace=myapp"
# → аналогично для volumes
```

### Проблемы с Healthcheck и Rolling Update

Если `monitor` меньше времени прогрева приложения, Swarm считает задачу упавшей и инициирует rollback.

**Решение:**
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
  start_period: 30s  # Для JIT-компилируемых языков (Java, .NET)
  interval: 10s
  timeout: 5s
  retries: 3
deploy:
  update_config:
    monitor: 60s  # Должен превышать start_period
```

### Global services и `update_config`

Режим `mode: global` запускает одну задачу на каждом узле. Swarm игнорирует `replicas` и обновляет все узлы при изменении образа. `update_config` применяется, но parallelism ограничен количеством узлов.

**Решение:**
```bash
docker service ls --filter "mode=global"
# → проверка количества задач = количеству узлов
docker service update --image nginx:1.28-alpine <global-service>
# → обновление на всех узлах
```

## Дополнительная информация

### Лучшие практики

- **Фиксация версий**: Всегда указывайте конкретный тег образа вместо `latest`.
- **Registry Auth**: Всегда используйте флаг `--with-registry-auth` в CI/CD пайплайнах.
- **Очистка**: Для полного удаления стека используйте `docker stack rm <name>`. Это удалит все связанные сервисы и сети, кроме внешних (`external: true`).
- **Секреты**: Никогда не храните пароли в переменных окружения в YAML, используйте `secrets`.
- **Idempotency**: `docker stack deploy` идемпотентен. Можно безопасно запускать деплой многократно — Swarm применит только дельту изменений.
- **Prune в CI/CD**: Добавляйте `--prune` в пайплайны для автоматической очистки устаревших сервисов, которых больше нет в YAML.
- **Healthchecks**: Всегда добавляйте `healthcheck` в сервисы. Это позволяет Swarm корректно отслеживать готовность и избегать трафика на неготовые контейнеры.
- **Resource Limits**: Всегда задавайте `reservations` и `limits` для CPU и памяти. Без лимитов один "зависший" сервис может загрузить весь узел.
- **Rollback Config vs Update Config**: Настраивайте их независимо. Rollback должен быть быстрее и агрессивнее обычного обновления:
  ```yaml
  deploy:
    update_config:
      parallelism: 1
      delay: 15s
    rollback_config:
      parallelism: 0  # Откатить все сразу
      order: stop-first
  ```
- **Monitor превышает время прогрева**: Указывайте `monitor` не менее времени, необходимого приложению для старта (включая JIT-компиляцию, загрузку кэша). Добавьте `start_period` в healthcheck для тяжелых приложений.
- **Detach=false для CI/CD**: В пайплайнах используйте `--detach=false`, чтобы команда ждала завершения convergence и возвращала понятную ошибку при неудаче.
- **Global Services**: Помните, что `mode: global` игнорирует `replicas` и обновляет все узлы. Для таких сервисов планируйте окна обслуживания.
- **Placement Constraints вProduction**: Избегайте жестких `constraints` без резерва. Используйте `preferences` для мягкого распределения и `constraints` только для обязательных требований (например, `node.role == manager` для БД).

## Особые случаи и ограничения

- **Compose file v3 только**: `docker stack deploy` поддерживает только формат Compose file version 3.x. Новый Compose Specification (v2+) несовместим. Для проверки скомпилированного файла используйте `docker stack config`.
- **Ignored keys**: Следующие инструкции игнорируются Swarm и не вызывают ошибок: `build`, `container_name`, `depends_on`, `links`, `network_mode`, `restart`, `cgroup_parent`, `devices`, `default_flow_ops` (Windows). Их использование в stack-файлах ведет к неожиданному поведению.
- **External resources**: Сети и тома, объявленные как `external: true`, не удаляются при `docker stack rm`. Необходимо удалять их вручную. То же касается секретов и конфигов, если они используются несколькими стеками.
- **Global services и update_config**: В режиме `mode: global` Swarm игнорирует `replicas` и обновляет все узлы при изменении образа. `parallelism` ограничен количеством узлов, а `delay` применяется между группами узлов.
- **Immutable objects**: Секреты и конфиги неизменяемы. Для обновления требуется создание нового объекта с новым именем и версионирование (например, `app-config-v2`). Старые версии нужно удалять вручную.
- **--detach=true по умолчанию**: `docker stack deploy` возвращает управление немедленно. Для скриптов, требующих ожидания convergence, используйте `--detach=false` или проверяйте статус отдельной командой.
- **API version compatibility**: `--prune` требует API 1.27+, `--with-registry-auth` требует API 1.29+. Убедитесь, что версия Docker Engine на менеджере соответствует минимальным требованиям используемых флагов.
- **Image pull policy**: Swarm всегда проверяет актуальность образа в Registry перед обновлением. Для ускорения деплоя в изолированных сетях используйте `--resolve-image=never`, но только если уверены, что образ на узлах актуален.
- **Service mesh**: Публикуемые порты сервисов проходят через Routing Mesh (VIP). Для режима `host` (без VIP) используйте `mode: host` и `endpoint_mode: host`, но тогда порт должен быть свободен на каждом узле.

### Смотрите также

- **[Продвинутые стратегии развертывания](./swarm_stack_advanced.md)** — Canary, Blue-Green, Spread.
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)** — управление конфигами.
- **[Справочник CLI для Swarm](./swarm_management_cli.md)** — диагностика и управление.
- **[Стратегии Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md)** — общие принципы.
- **[Управление томами](./swarm_volumes.md)** — использование томов в Compose-файлах.
