# Жизненный цикл приложения в Docker Swarm

## Определения

- **Rolling Update** — стратегия постепенного обновления реплик сервиса без простоя. Каждая реплика обновляется последовательно с проверкой работоспособности.
- **Rollback** — откат сервиса к предыдущей версии образа при обнаружении ошибок в новой версии.
- **Health Check** — механизм проверки работоспособности контейнера через HTTP, TCP или CMD-проверки.
- **Update Config** — конфигурация обновления сервиса в Docker Swarm, включающая параллелизм, задержки и действия при ошибках.

## Базовые концепции

### Стратегии обновления

Docker Swarm поддерживает несколько стратегий обновления сервисов:

| Стратегия | Описание | Время простоя | Риск |
|---|---|---|---|
| **Rolling Update** | Постепенное обновление реплик | Нет | Низкий |
| **Blue-Green** | Параллельный запуск новой версии | Минимальный | Средний |
| **Canary** | Постепенное увеличение трафика | Нет | Низкий |

**Rolling Update (по умолчанию):**

- Обновляет реплики по одной или группами
- Сохраняет доступность сервиса во время обновления
- Автоматический откат при ошибке health check

### Конфигурация обновления

Параметры `update_config` в `docker-compose.yml`:

```yaml
deploy:
  update_config:
    parallelism: 1        # Количество реплик для одновременного обновления
    delay: 10s            # Задержка между группами обновлений
    failure_action: rollback  # Действие при ошибке (continue/pause/rollback)
    order: start-first    # Порядок: start-first или stop-first
  rollback_config:
    parallelism: 1
    delay: 10s
    failure_action: pause
```

**Параметры:**

- `parallelism: 1` — обновлять по одной реплике за раз (минимальный риск)
- `delay: 10s` — задержка для стабилизации перед следующей репликой
- `failure_action: rollback` — автоматический откат при ошибке
- `order: start-first` — запуск новой реплики перед остановкой старой

### Health Check для обновлений

Health checks критически важны для безопасного обновления:

```yaml
healthcheck:
  test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/health"]
  interval: 30s       # Проверка каждые 30 секунд
  timeout: 10s        # Таймаут проверки
  retries: 3          # Количество попыток перед пометкой unhealthy
  start_period: 40s   # Время на запуск перед проверками
```

**Принцип работы:**

1. Swarm ждет `start_period` перед началом проверок
2. Проверки выполняются каждые `interval`
3. После `retries` неудач контейнер помечается unhealthy
4. При обновлении Swarm ждет healthy статуса перед продолжением

## Практические сценарии

### Сценарий 1: Настройка безопасного обновления

**Шаг 1: Добавление health check в `docker-compose.yml`**

```yaml
version: '3.8'

services:
  app:
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
        failure_action: rollback
        order: start-first
      rollback_config:
        parallelism: 1
        delay: 10s
        failure_action: pause
      restart_policy:
        condition: on-failure
        max_attempts: 3
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**Шаг 2: Создание эндпоинта health check в приложении**

```javascript
// Node.js пример
app.get('/health', (req, res) => {
  // Проверка подключения к БД, кэшу и т.д.
  res.status(200).json({ status: 'healthy' });
});
```

**Шаг 3: Тестирование обновления**

```bash
# Обновление сервиса
docker service update --image my-app:v2 my-app_app

# Мониторинг прогресса
docker service ps my-app_app
```

### Сценарий 2: Мониторинг обновления

**Отслеживание прогресса в реальном времени:**

```bash
# Watch за задачами
watch -n 2 'docker service ps my-app_app --format "table {{.Name}}\t{{.CurrentState}}\t{{.DesiredState}}"'
```

**Пример вывода:**

```
NAME                CURRENT STATE            DESIRED STATE
my-app_app.1        Running 2 minutes ago    Running
my-app_app.2        Starting 5 seconds ago   Running
my-app_app.3        Running 2 minutes ago    Running
```

**Проверка журналов:**

```bash
# Журналы всех реплик
docker service logs my-app_app --tail 50

# Журналы конкретной реплики
docker logs my-app_app.2 --tail 50
```

**Проверка событий Swarm:**

```bash
docker system events --filter type=service --filter scope=swarm
```

### Сценарий 3: Автоматический откат

**Триггеры автоматического отката:**

- Health check не проходит в течение `start_period + (retries × interval)`
- Контейнер завершается с ошибкой во время обновления
- Новая реплика не запускается

**Мониторинг отката:**

```bash
# Проверка статуса обновления
docker service ps my-app_app --no-trunc

# Просмотр причины отката
docker service logs my-app_app --since 5m | grep -i "rollback\|error"
```

**Пример логов при откате:**

```
my-app_app.2 rollback: health check failed
my-app_app.2 shutting down
my-app_app.2 updated to previous version
```

### Сценарий 4: Ручной откат

**Откат к предыдущей версии:**

```bash
# Переключение на контекст
docker context use prod-swarm

# Откат сервиса
docker service rollback my-app_app

# Проверка статуса
docker service ps my-app_app
```

**Откат через обновление образа:**

```bash
# Возврат к предыдущему тегу
docker service update --image my-app:v1 my-app_app

# Принудительное обновление (если образ не изменился)
docker service update --force my-app_app
```

**Откат через GitLab CI:**

1. Найдите предыдущий успешный пайплайн в **CI/CD → Pipelines**
2. Нажмите **Retry** — пайплайн развернет образ с предыдущим тегом

### Сценарий 5: Blue-Green развертывание

Краткая схема:

```bash
# 1. Запуск green-версии параллельно
docker service create --name my-app-green --replicas 3 --network public \
  --label traefik.enable=false my-app:v2

# 2. Тестирование
curl http://my-app-green:3000/health

# 3. Переключение трафика через Traefik labels
docker service update --label-rm traefik.enable my-app_app
docker service update --label traefik.enable=true my-app-green

# 4. Удаление старой версии
docker service rm my-app_app
docker service update --name my-app_app my-app-green
```

### Сценарий 6: Canary-развертывание

Краткая схема:

```bash
# 1. Запуск canary-реплики
docker service scale my-app_app=2
docker service create --name my-app-canary --replicas 1 --network public my-app:v2

# 2. Мониторинг
docker service logs my-app-canary --tail 100
docker stats my-app-canary

# 3. Постепенное увеличение
docker service scale my-app-canary=3
docker service rm my-app_app
docker service update --name my-app_app my-app-canary
```

## Дополнительная информация

### Отладка проблем обновления

**Диагностические команды:**

```bash
# Проверка конфигурации сервиса
docker service inspect my-app_app --format '{{.Spec.UpdateConfig}}'

# Проверка health check
docker inspect --format='{{json .State.Health}}' $(docker ps -q -f name=my-app_app) | jq

# Проверка событий
docker events --filter service=my-app_app --since 10m
```

**Частые проблемы:**

| Проблема | Причина | Решение |
|---|---|---|
| Обновление застряло | Health check не проходит | Увеличить `start_period`, проверить эндпоинт |
| Циклический откат | Образ битый | Проверить логи приложения, откатиться вручную |
| Реплика не запускается | Нехватка ресурсов | Проверить `docker node ls`, лимиты ресурсов |
| Долгое обновление | Большой `delay` | Уменьшить задержку, увеличить `parallelism` |

### Связанные документы

- **Развертывание приложения** — **[app_deployment.md](./app_deployment.md)**
- **Развертывание инфраструктуры** — **[infra_deployment.md](./infra_deployment.md)**
- **Traefik в Swarm** — **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**
- **Управление сервисами (CLI)** — **[../swarm_management_cli.md](../swarm_management_cli.md)**
- **Продвинутые темы Swarm** — **[../swarm_advanced_topics.md](../swarm_advanced_topics.md)**
