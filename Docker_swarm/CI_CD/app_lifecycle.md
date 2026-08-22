# Управление жизненным циклом приложения в Docker Swarm

## Определения

- **[Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md):** Стратегия поэтапного обновления реплик сервиса. Позволяет минимизировать время простоя (Zero Downtime) путем постепенной замены старых экземпляров новыми под контролем оркестратора.
- **Rollback (Автоматический откат):** Защитный механизм Swarm, который возвращает сервис к предыдущей стабильной версии конфигурации (включая образ, переменные и секреты), если процесс обновления признан неудачным.
- **Health Check (Проверка жизнеспособности):** Инструкция внутри Dockerfile или Stack-файла, позволяющая оркестратору определить реальную готовность приложения принимать трафик. Является триггером для продолжения обновления или запуска отката.
- **Graceful Shutdown (Плавное завершение):** Механизм корректной остановки приложения, при котором процесс получает сигнал `SIGTERM`, прекращает прием новых запросов, завершает текущие транзакции и освобождает ресурсы перед завершением.

## Базовые концепции

### Стратегии развертывания в кластере

Docker Swarm нативно реализует **Rolling Update**. Другие стратегии требуют внешних инструментов или специфических конфигураций:

| Стратегия | Метод реализации в Swarm | Рекомендация |
|:---|:---|:---|
| **Rolling Update** | Встроенный (секция `update_config`). | Стандарт для CI/CD. |
| **Blue-Green** | Манипуляция метками (labels) Ingress-прокси (Traefik) или использование двух параллельных стеков с переключением внешнего CNAME. | Высокая надежность, двойное потребление ресурсов. |
| **Canary** | Создание "канареечного" сервиса с 1 репликой, использующего ту же Overlay-сеть и метки маршрутизации, что и основной сервис. | Идеально для тестов на продакшене. |

### Детальная настройка обновления (update_config)

Секция `deploy.update_config` управляет поведением оркестратора при изменении спецификации сервиса:

```yaml
deploy:
  update_config:
    parallelism: 2            # Обновлять по 2 реплики за раз
    delay: 30s                # Ждать 30с между группами реплик
    failure_action: rollback  # При ошибке — немедленно откатываться (не pause!)
    monitor: 45s              # Время наблюдения за новой репликой (должно быть > времени прогрева)
    max_failure_ratio: 0.15   # Допускается 15% ошибок перед признанием деплоя неудачным
    order: start-first        # Сначала запустить новую, затем убить старую (Zero Downtime)
```

**Критический нюанс `order: start-first`:**
В этом режиме Swarm создает *дополнительные* контейнеры. Если у сервиса настроены жесткие лимиты ресурсов (`resources.reservations`), на узлах должно быть достаточно свободного места для временного размещения +1 реплики. В противном случае обновление зависнет в статусе `Pending`.

### Настройка автоматического отката (rollback_config)

Многие упускают секцию `rollback_config`, которая определяет поведение Swarm *во время* процесса отката. Она должна быть максимально агрессивной для быстрого восстановления:

```yaml
deploy:
  rollback_config:
    parallelism: 0           # 0 означает "обновить все реплики одновременно" (быстрый возврат)
    failure_action: pause    # Если даже откат упал — остановиться и ждать вмешательства
    monitor: 10s
    order: stop-first        # При откате важнее очистить место от сбойных контейнеров
```

### Корректное завершение (Graceful Shutdown)

Чтобы избежать ошибок `502 Bad Gateway` во время Rolling Update, приложение должно успевать доработать запросы.

1. **Сигналы:** Swarm отправляет `SIGTERM`. Если ваше приложение (например, Node.js или Python) запущено через оболочку `sh -c`, оно может не получить сигнал. Используйте `exec` форму в Dockerfile: `ENTRYPOINT ["exec", "node", "app.js"]`.
2. **Параметры YAML:**
```yaml
services:
  app:
    stop_grace_period: 1m    # Даем приложению 60 секунд на завершение дел
    stop_signal: SIGTERM     # Можно заменить на SIGQUIT для Nginx
```

## Практические сценарии

### Сценарий 1: Конфигурация для высоконагруженного Stateless API

Оптимальные параметры для обеспечения доступности 99.99%:

```yaml
services:
  api:
    image: registry.example.com/api:${TAG}
    stop_grace_period: 45s
    deploy:
      replicas: 4
      update_config:
        parallelism: 1
        delay: 20s
        failure_action: rollback
        monitor: 1m
        order: start-first
      rollback_config:
        parallelism: 0
        order: stop-first
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/ready"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s
```

### Сценарий 2: Отладка "зависшего" обновления

Если деплой в CI/CD пайплайне не завершается, используйте диагностический набор:

```bash
# 1. Посмотреть текущее состояние и ошибки планировщика
docker service ps --no-trunc <service_name>

# 2. Проверить причины, по которым контейнеры не запускаются (например, "insufficient resources")
docker service inspect --format '{{json .UpdateStatus}}' <service_name> | jq

# 3. Анализ логов именно новой версии (фильтрация по желаемому состоянию)
docker service logs -f <service_name>
```

### Сценарий 3: Вывод узла из эксплуатации (Maintenance)

При выполнении работ на сервере (например, обновление ядра ОС), используйте `drain`. Swarm перенесет контейнеры на другие узлы, соблюдая все правила `update_config` (включая задержки и проверки здоровья).

```bash
# Перевод в режим обслуживания (задачи начнут переезжать)
docker node update --availability drain <NODE_NAME>

# После завершения работ (новые задачи снова могут назначаться)
docker node update --availability active <NODE_NAME>
```

### Сценарий 4: Управление обновлением через CLI

Помимо конфигурации в YAML, жизненный цикл сервиса управляется через CLI-команды:

```bash
# Ручное обновление образа (перезаписывает update_config)
docker service update --image registry.example.com/api:v2.3.0 my_service

# Принудительное обновление (мгновенная замена всех реплик без соблюдения задержек)
docker service update --force my_service

# Обновление с новым parallelism и delay
docker service update \
  --update-parallelism 3 \
  --update-delay 15s \
  --update-order start-first \
  my_service

# Откат к предыдущей версии
docker service rollback my_service

# Пауза обновления (если оно в процессе)
docker service update --update-pause my_service

# Продолжение приостановленного обновления
docker service update --update-continue my_service

# Отмена текущего обновления (возврат к текущей стабильной версии)
docker service update --update-abort my_service
```

**Важно:** Команда `docker service update --force` пересоздает все контейнеры даже если образ не изменился. Полезно для применения изменений, которые не отслеживаются оркестратором (например, обновление секрета или конфига).

### Сценарий 5: Мониторинг состояния обновления

Для отслеживания прогресса Rolling Update в реальном времени:

```bash
# Текущее состояние и история задач
docker service ps my_service

# Включая остановленные задачи (для анализа истории)
docker service ps --no-trunc --filter desired-state=running my_service

# Детальная информация о статусе обновления
docker service inspect --format '{{json .UpdateStatus}}' my_service | jq
# Пример вывода:
# {
#   "State": "updating",
#   "Message": "update in progress",
#   "StartedAt": "2026-08-22T10:30:00Z",
#   "CompletedAt": "0001-01-01T00:00:00Z",
#   "Error": ""
# }

# Логи конкретной задачи (по ID из service ps)
docker service logs <TASK_ID>

# События Swarm (все изменения в кластере)
docker events --filter 'type=service' --filter 'name=my_service' --since 1h

# Проверка, какие узлы заняты репликами
docker service ps my_service --format "{{.Node}} -> {{.CurrentState}}"
```

## Дополнительная информация

### Влияние Placement Constraints

Ограничения размещения (`node.labels`) могут конфликтовать со стратегией `start-first`. Если сервис привязан к конкретному узлу (`node.hostname == worker1`), Swarm не сможет запустить новую реплику рядом со старой в режиме `start-first`, если на узле недостаточно ресурсов или нарушаются другие ограничения. В таких случаях используйте `stop-first`.

### Типичные проблемы и решения

| Проблема | Причина | Решение |
|:---|:---|:---|
| Обновление зависло на 1/3 реплик | Health Check возвращает ошибку или порт не слушается | Проверить логи контейнера, увеличить `start_period`. |
| Rollback срабатывает сразу | Значение `monitor` меньше, чем время инициализации приложения | Увеличить `monitor` в `update_config`. |
| Ошибки 502 при обновлении | Приложение убивается мгновенно, не закрыв коннекты | Настроить обработку `SIGTERM` и `stop_grace_period`. |
| Нет ресурсов для деплоя | `start-first` требует двойного объема ресурсов на время обновления одной реплики | Проверить `reservations` или переключиться на `stop-first`. |
| `update paused` в status | Кто-то выполнил `--update-pause` или `max_failure_ratio` превышен | Выполнить `docker service update --update-continue` или исправить причину паузы. |
| Обновление отменяется само | `failure_action: rollback` сработал из-за Health Check | Увеличить `monitor`, проверить логи новой версии. |
| `task: no suitable node` | Нет узлов, удовлетворяющих placement constraints | Проверить `docker node ls`, `docker service inspect --format '{{.Spec.TaskTemplate.Placement}}'`. |
| Реплики "мергают" при обновлении | `order: stop-first` + `parallelism: 1` = длительное обновление | Использовать `order: start-first` для Zero Downtime. |

### Связанные документы

- **[Деплой приложения через GitLab CI](./app_deployment.md)** — интеграция жизненного цикла в пайплайн.
- **[Секреты и конфигурации](../swarm_secrets_configs.md)** — как обновление секретов триггерит жизненный цикл.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — управление трафиком при сложных стратегиях (Blue-Green).
- **[Стратегии развертывания](../../CI-CD/Deployment_Strategies/rolling_update.md)** — общие принципы Rolling Update (Kubernetes-контекст).

