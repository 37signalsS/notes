# Docker Swarm: Продвинутые стратегии развертывания стеков

## Определения

**[Rolling Update (Поэтапное обновление)](../../CI-CD/Deployment_Strategies/rolling_update.md)** — стратегия постепенного обновления реплик сервиса без полной остановки обслуживания.

**[Canary Deployment (Канареечное развертывание)](../../CI-CD/Deployment_Strategies/canary_deployment.md)** — метод выпуска, при котором новая версия приложения направляется на небольшую группу пользователей для тестирования перед полным развертыванием.

**[Blue-Green Deployment (Сине-зеленое развертывание)](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)** — стратегия, предполагающая наличие двух идентичных сред (Blue и Green) с мгновенным переключением трафика.

## Базовые концепции

### Управление процессом обновления

Docker Swarm позволяет декларативно описывать поведение сервисов при обновлении через секции `update_config` и `rollback_config` в файле `docker-compose.yml`. Это обеспечивает автоматизацию процесса и минимизирует риски при деплое.

Общие концепции стратегий развертывания подробно описаны в разделе **[Стратегии развертывания](../../CI-CD/Core_Concepts/deployment_strategies.md)**.

### Наблюдаемость и отладка

При использовании продвинутых стратегий критически важен мониторинг метрик. Swarm предоставляет встроенные механизмы проверки здоровья (health checks), которые интегрируются с процессом Rolling Update для автоматической остановки или отката изменений при обнаружении проблем.

## Практические сценарии

### Настройка стратегии Rolling Update

Конфигурация поэтапного обновления в `docker-compose.yml`:

```yaml
services:
  web:
    image: nginx:1.26.3
    deploy:
      replicas: 5
      update_config:
        parallelism: 2        # Количество реплик для одновременного обновления
        delay: 30s            # Задержка между группами обновлений
        failure_action: pause # Действие при ошибке (continue, pause, rollback)
        monitor: 60s          # Время мониторинга здоровья после обновления
        max_failure_ratio: 0.3 # Допустимая доля сбоев перед паузой
        order: start-first    # Сначала запустить новую реплику (stop-first — сначала остановить)
      rollback_config:
        parallelism: 1
        delay: 10s
        failure_action: pause
        order: stop-first
```

Подробнее о деталях стратегии — в **[Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md)**.

### Реализация Canary-развертывания

В Docker Swarm канареечное развертывание часто реализуется путем запуска отдельного сервиса для новой версии и использования Ingress-контроллера (например, Traefik) для распределения весов трафика.

```yaml
version: '3.8'

services:
  # Основная версия (Stable)
  web-stable:
    image: myapp:v1.0
    deploy:
      replicas: 9
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.web.rule=Host(`app.example.com`)"
        - "traefik.http.services.web.loadbalancer.server.port=80"
  
  # Canary версия
  web-canary:
    image: myapp:v1.1
    deploy:
      replicas: 1
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.web.rule=Host(`app.example.com`)"
```

Подробнее о настройке Traefik — в **[swarm_ingress_traefik.md](./swarm_ingress_traefik.md)**. Общая концепция — в **[Canary Deployment](../../CI-CD/Deployment_Strategies/canary_deployment.md)**.

### Реализация Blue-Green развертывания

Для Blue-Green в Swarm обычно используются два отдельных стека или сервиса с переключением трафика на уровне внешнего балансировщика.

```sh
# 1. Развертывание новой (Green) версии рядом со старой (Blue)
docker stack deploy -c green.yml myapp-green

# 2. Проверка работы новой версии через отдельный URL или прямой запрос к узлу

# 3. Переключение трафика на уровне DNS или Ingress-контроллера

# 4. Удаление старой версии после подтверждения стабильности
docker stack rm myapp-blue
```

Общая концепция — в **[Blue-Green Deployment](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)**.

### Устранение неисправностей (Troubleshooting)

#### Стек (Stack) не развертывается

| Проблема | Причина | Решение |
|---|---|---|
| `invalid YAML` | Ошибки синтаксиса в файле | Проверить через `docker compose config` |
| `image not found` | Образ недоступен в Registry | Проверить доступность и авторизацию |
| `no suitable node` | Недостаточно ресурсов на узлах | Проверить `docker node ls` и лимиты |
| `network not found` | Сеть не создана заранее | Создать внешнюю (external) сеть |

#### Сервис не запускается или постоянно перезапускается

**Инструменты диагностики:**

- `docker stack ps <stack_name> --no-trunc` — просмотр подробных ошибок задач.
- `docker service logs <service_name> --follow` — анализ логов приложения.
- `docker node inspect <node_id>` — проверка состояния узла (диск, память).

**Частые ошибки:**

- `OOMKilled`: Превышен лимит оперативной памяти (увеличить `resources.limits.memory`).
- `exit code 1`: Внутренняя ошибка приложения (проверить переменные окружения).
- `unhealthy`: Не проходит проверка здоровья (проверить `healthcheck` в YAML).

## Дополнительная информация

### Сравнение с Kubernetes

| Параметр | Docker Stack | Kubernetes |
|---|---|---|
| **Масштабируемость** | До ~1000 узлов | До ~5000 узлов |
| **Сложность** | Низкая (native Docker) | Высокая |
| **Service Discovery** | Встроенный DNS (Domain Name System) | CoreDNS |
| **Управление конфигами** | Secrets / Configs | ConfigMaps / Secrets |
| **Rolling Update** | Встроенная поддержка в YAML (Yet Another Markup Language) | Объект Deployment |

### Смотрите также

- **[Базовое развертывание стеков](./swarm_stack_deployment.md)**
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)**
- **[Справочник CLI для Swarm](./swarm_management_cli.md)**
