# Жизненный цикл приложения в Docker Swarm

## Определения

- **[Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md):** Стратегия постепенного обновления реплик сервиса без полной остановки системы.
- **Rollback (Откат):** Процесс возврата сервиса к предыдущей версии конфигурации или образа при обнаружении сбоев.
- **Health Check (Проверка состояния):** Механизм, позволяющий оркестратору Swarm определять работоспособность контейнера и принимать решение о продолжении обновления или выполнении отката.
- **Update Config:** Набор параметров в Docker Swarm, определяющий поведение системы во время обновления сервиса (параллелизм, задержки, реакция на ошибки).

## Базовые концепции

### Стратегии развертывания в Swarm

Docker Swarm нативно поддерживает стратегию **Rolling Update**. Другие стратегии реализуются через внешние инструменты (например, Traefik) или манипуляцию сервисами.

| Стратегия | Реализация в Swarm | Риск |
|:---|:---|:---|
| **Rolling Update** | Встроенная (через `update_config`) | Низкий |
| **Blue-Green** | Ручная/Внешняя (через `labels` или переключение имен) | Средний |
| **Canary** | Ручная (через запуск отдельного сервиса с малым числом реплик) | Низкий |

Детальное сравнение подходов — в **[Сравнение стратегий развертывания](../../CI-CD/Deployment_Strategies/comparison.md)**.

### Конфигурация обновления

Параметры блока `update_config` в `docker-compose.yml` критически важны для стабильности CI/CD:

```yaml
deploy:
  update_config:
    parallelism: 1            # Сколько реплик обновлять одновременно
    delay: 10s                # Пауза между группами обновлений
    failure_action: rollback  # Что делать при ошибке (continue, pause, rollback)
    monitor: 30s              # Время наблюдения за новой репликой
    max_failure_ratio: 0.1    # Допустимая доля ошибок при обновлении
    order: start-first        # start-first (сначала новая) или stop-first
```

- **`order: start-first`** предпочтителен для stateless приложений, так как минимизирует снижение пропускной способности.
- **`failure_action: rollback`** обеспечивает автоматический возврат к стабильному состоянию без вмешательства оператора.

### Взаимосвязь с Health Check

Для корректной работы Rolling Update в Swarm обязательна настройка `healthcheck`. Оркестратор не перейдет к обновлению следующей реплики, пока текущая не перейдет в статус `healthy`.

Подробности синтаксиса проверок в Dockerfile — в **[Инструкция HEALTHCHECK](../../Docker/Dockerfile/Instructions/health_signals.md)**.

## Практические сценарии

### Сценарий 1: Настройка отказоустойчивого обновления

Пример конфигурации в `docker-compose.yml`:

```yaml
version: '3.8'
services:
  app:
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 15s
        failure_action: rollback
        order: start-first
      rollback_config:
        parallelism: 2
        delay: 5s
        failure_action: pause
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s
```

### Сценарий 2: Мониторинг процесса обновления

Отслеживание статуса задач сервиса во время деплоя:

```bash
# Список задач сервиса с отображением ошибок
docker service ps --no-trunc my-stack_app

# Проверка статуса в реальном времени
watch -n 1 "docker service ps my-stack_app | grep -v 'Shutdown'"

# Просмотр журналов всех реплик (агрегированный поток)
docker service logs -f my-stack_app
```

### Сценарий 3: Управление откатами

#### Автоматический откат

Происходит, если новая реплика не проходит Health Check в течение периода `monitor` или завершается с ошибкой. Причина будет видна в `docker service inspect`.

#### Ручной откат

Если обновление завершилось, но обнаружены логические ошибки:

```bash
# Возврат к предыдущей конфигурации через CLI
docker service rollback my-stack_app

# Откат через GitLab CI
# Перезапустите (Retry) предыдущий успешный Job деплоя
```

### Сценарий 4: Реализация Blue-Green через Traefik

Схема переключения трафика между двумя независимыми стеками:

1. Развертывание новой версии (`green`) с `traefik.enable=false`.
2. Проверка работоспособности `green` стека вручную.
3. Переключение меток:

   ```bash
   docker service update --label-rm traefik.enable stack-blue_app
   docker service update --label-add traefik.enable=true stack-green_app
   ```

4. Удаление старого (`blue`) стека после успешной проверки.

Подробнее о работе с Ingress — в **[Traefik в Swarm](../swarm_ingress_traefik.md)**.

## Дополнительная информация

### Диагностика проблем

| Симптом | Причина | Решение |
|:---|:---|:---|
| Обновление "зависло" | Health Check не переходит в `healthy` | Проверить логи контейнера, увеличить `start_period` |
| Сразу происходит Rollback | Ошибка в конфигурации или образе | Проверить `docker service ps` на наличие ошибок запуска |
| Снижение производительности | `parallelism` слишком велик или `order: stop-first` | Оптимизировать параметры `update_config` |

### Связанные документы

- **[app_deployment.md](./app_deployment.md)** — общая схема пайплайнов деплоя.
- **[swarm_management_cli.md](../swarm_management_cli.md)** — справочник команд управления сервисами.
- **[deployment_health_checks_and_rollback.md](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** — общие концепции проверок здоровья в CI/CD.
- **[mTLS + healthcheck: исключение /health из проверки](../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md#сценарий-4-исключение-healthcheck-из-mtls-docker-swarm)** — настройка nginx при mTLS и Swarm healthcheck.
- **[swarm_ingress_traefik.md](../swarm_ingress_traefik.md)** — управление входящим трафиком.
