# Жизненный цикл приложения в Docker Swarm

## Определения

- **[Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md):** Стратегия постепенного обновления реплик сервиса, при которой новая версия заменяет старую без полной остановки системы.
- **Rollback (Откат):** Автоматический или ручной процесс возврата сервиса к предыдущей стабильной конфигурации при обнаружении сбоев.
- **Health Check (Проверка состояния):** Механизм контроля работоспособности контейнера, на основе которого Swarm принимает решение о продолжении обновления или выполнении отката.
- **Graceful Shutdown (Корректное завершение):** Процесс плановой остановки приложения, при котором оно успевает завершить текущие запросы и закрыть соединения.

## Базовые концепции

### Стратегии развертывания в Swarm

Docker Swarm нативно поддерживает стратегию **Rolling Update**. Другие стратегии (Blue-Green, Canary) реализуются на уровне манипуляции сервисами или через внешние балансировщики (Traefik).

| Стратегия | Реализация в Swarm | Риск |
|:---|:---|:---|
| **Rolling Update** | Встроенная (секция `update_config`) | Низкий |
| **Blue-Green** | Внешняя (переключение меток `traefik.enable` или имен сервисов) | Средний |
| **Canary** | Ручная (создание отдельного сервиса с 1 репликой для тестов) | Низкий |

Детальное сравнение подходов — в **[Сравнение стратегий развертывания](../../CI-CD/Deployment_Strategies/comparison.md)**.

### Тонкая настройка обновления (update_config)

Параметры секции `deploy.update_config` определяют стабильность процесса CI/CD:

```yaml
deploy:
  update_config:
    parallelism: 1            # Количество реплик, обновляемых за один шаг
    delay: 10s                # Интервал между обновлением групп реплик
    failure_action: rollback  # Реакция на ошибку (continue, pause, rollback)
    monitor: 30s              # Время наблюдения за новой репликой после запуска
    max_failure_ratio: 0.1    # Допустимый процент ошибок при обновлении
    order: start-first        # start-first (сначала новая) или stop-first (сначала удалить старую)
```

- **`order: start-first`**: Новая реплика запускается рядом со старой. Рекомендуется для stateless-сервисов, так как исключает снижение пропускной способности.
- **`order: stop-first`**: Рекомендуется при дефиците ресурсов или для singleton-задач, где недопустим запуск двух экземпляров одновременно.

### Корректное завершение (Graceful Shutdown)

Для предотвращения разрыва клиентских соединений при обновлении необходимо настроить параметры завершения:

- **`stop_grace_period`**: Время, которое Swarm дает контейнеру после отправки `SIGTERM` перед принудительным `SIGKILL` (по умолчанию 10s).
- **`stop_signal`**: Сигнал, используемый для остановки (например, `SIGQUIT` для Nginx).

```yaml
services:
  app:
    stop_grace_period: 45s
    stop_signal: SIGQUIT
```

### Взаимосвязь с Health Check

Оркестратор переходит к обновлению следующей реплики только после того, как текущая перейдет в статус `healthy`. Без `healthcheck` Swarm считает контейнер готовым сразу после запуска процесса, что может привести к "дропу" трафика.

Подробности синтаксиса проверок — в **[Инструкция HEALTHCHECK](../../Docker/Dockerfile/Instructions/health_signals.md)**.

## Практические сценарии

### Сценарий 1: Конфигурация отказоустойчивого стека

Пример для `docker-compose.yml`, объединяющий все механизмы защиты:

```yaml
version: '3.8'
services:
  api:
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
    stop_grace_period: 30s
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 15s
        failure_action: rollback
        monitor: 20s
        order: start-first
      rollback_config:
        parallelism: 0         # 0 = обновить все реплики сразу при откате
        order: stop-first
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 40s       # Время на "прогрев" приложения
```

### Сценарий 2: Диагностика и мониторинг деплоя

Если обновление зависло или произошел откат, используйте следующие команды для анализа:

```bash
# Просмотр детального статуса обновления сервиса
docker service inspect --pretty my-stack_api

# Список всех задач (контейнеров) сервиса с ошибками
docker service ps --no-trunc my-stack_api

# Просмотр логов конкретной (упавшей) задачи
docker inspect --format '{{.Status.ContainerStatus.ContainerID}}' <task_id>
```

### Сценарий 3: Управление узлами (Node Drain)

При выводе узла на обслуживание Swarm автоматически переносит (reschedule) задачи на другие узлы, соблюдая правила `update_config`.

```bash
# Перевод узла в режим обслуживания
docker node update --availability drain my-worker-01

# Возврат узла в строй
docker node update --availability active my-worker-01
```

### Сценарий 4: Ручное управление откатом

Если автоматика не сработала (например, ошибка логическая, а не техническая):

```bash
# Мгновенный откат к предыдущей версии через CLI
docker service rollback my-stack_api
```

## Дополнительная информация

### Влияние ограничений (Placement Constraints)

Параметры `placement` могут заблокировать обновление, если на подходящих узлах недостаточно ресурсов для `start-first` деплоя. Всегда проверяйте наличие свободных ресурсов в кластере перед запуском `parallelism > 1`.

### Диагностика проблем

| Симптом | Причина | Решение |
|:---|:---|:---|
| Статус `STARTING` завис | Health Check не проходит | Проверить логи, увеличить `start_period` |
| Ошибка `No such image` | Узлы не авторизованы в Registry | Проверить флаг `--with-registry-auth` |
| Циклический Rollback | `monitor` слишком мал | Увеличить время наблюдения после запуска |
| Разрыв соединений | Малый `stop_grace_period` | Настроить Graceful Shutdown в приложении и YAML |

### Связанные документы

- **[app_deployment.md](./app_deployment.md)** — общая схема CI/CD пайплайнов.
- **[swarm_management_cli.md](../swarm_management_cli.md)** — справочник команд управления.
- **[deployment_health_checks_and_rollback.md](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** — общие концепции проверок здоровья.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — реализация Blue-Green и маршрутизация.
- **[nginx_mtls_configuration.md](../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md#сценарий-4-исключение-healthcheck-из-mtls-docker-swarm)** — нюансы Health Check при использовании mTLS.
