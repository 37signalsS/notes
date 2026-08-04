# Docker Swarm: Развертывание стеков (Stack Deployment)

## Определения

**Стек (Stack)** — группа взаимосвязанных сервисов, которые совместно образуют приложение в среде Docker Swarm. Стек описывается декларативно в YAML-файле и управляется как единая сущность через команду `docker stack deploy`.

**Docker Stack** — нативный инструмент оркестрации Docker для управления жизненным циклом многоконтейнерных приложений в кластере. Он транслирует инструкции из файла спецификации (обычно `docker-compose.yml`) в объекты Swarm: сервисы, сети, секреты и конфигурации.

**Rolling Update (Поэтапное обновление)** — стратегия плавной замены старых версий контейнеров новыми с целью минимизации простоя.

**Rollback (Откат)** — процесс возврата к предыдущей стабильной версии конфигурации или образа при обнаружении сбоев в новой версии.

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
| `failure_action` | `pause` (остановить деплой), `continue` (игнорировать), `rollback` (вернуть старую версию). |
| `order` | `start-first` (сначала новые), `stop-first` (сначала остановить старые). |
| `monitor` | Время ожидания стабильной работы контейнера после запуска (например, `20s`). |

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

## Устранение неисправностей

### Ошибка "depends_on" и порядок запуска

Так как Swarm игнорирует `depends_on`, приложения должны быть устойчивы к отсутствию зависимостей (БД, очередь) в момент старта.

**Решение:**
1.  Использование **Healthchecks** в Docker-файле или Compose.
2.  Использование скриптов ожидания (`wait-for-it.sh`, `dockerize -wait`) в `entrypoint`.
3.  Настройка циклов переподключения в коде приложения.

### Проблемы с обновлением секретов и конфигов

В Docker Swarm **Config** и **Secret** неизменяемы (immutable). Чтобы обновить их содержимое, нужно создать новый объект с новым именем (например, `config-v2`) и обновить ссылку в YAML-файле. Это инициирует Rolling Update сервиса.

## Дополнительная информация

### Лучшие практики

- **Фиксация версий**: Всегда указывайте конкретный тег образа вместо `latest`.
- **Registry Auth**: Всегда используйте флаг `--with-registry-auth` в CI/CD пайплайнах.
- **Очистка**: Для полного удаления стека используйте `docker stack rm <name>`. Это удалит все связанные сервисы и сети, кроме внешних (`external: true`).
- **Секреты**: Никогда не храните пароли в переменных окружения в YAML, используйте `secrets`.

### Смотрите также

- **[Продвинутые стратегии развертывания](./swarm_stack_advanced.md)** — Canary, Blue-Green, Spread.
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)** — управление конфигами.
- **[Справочник CLI для Swarm](./swarm_management_cli.md)** — диагностика и управление.
- **[Стратегии Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md)** — общие принципы.
