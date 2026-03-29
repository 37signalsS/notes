# Docker Swarm: Stack Advanced Strategies

## Rolling Update

Rolling Update — стратегия постепенного обновления реплик сервиса без простоя.

```yaml
services:
  web:
    image: nginx:1.26.3
    deploy:
      replicas: 5
      update_config:
        parallelism: 2        # Обновлять по 2 реплики одновременно
        delay: 30s            # Задержка между обновлениями
        failure_action: pause # Пауза при ошибке (continue, pause, rollback)
        monitor: 60s          # Время мониторинга после обновления
        max_failure_ratio: 0.3 # Допустимый процент сбоев
        order: start-first    # Сначала запустить новую реплику
      rollback_config:
        parallelism: 1
        delay: 10s
        failure_action: pause
        order: stop-first
```

**Параметры `update_config`:**

| Параметр | Описание | Значения |
|---|---|---|
| `parallelism` | Количество реплик для одновременного обновления | Число |
| `delay` | Задержка между группами обновлений | `10s`, `1m` |
| `failure_action` | Действие при ошибке | `continue`, `pause`, `rollback` |
| `monitor` | Время ожидания здоровья после обновления | `60s`, `5m` |
| `max_failure_ratio` | Макс. доля сбоев перед паузой | `0.0`–`1.0` |
| `order` | Порядок обновления | `start-first`, `stop-first` |

**CLI-обновление:**
```sh
docker service update --image nginx:1.27 web
```

## Canary-развертывание

Canary — развертывание новой версии для небольшой части трафика.

```yaml
version: '3.8'

services:
  # Основная версия (90% трафика)
  web-stable:
    image: myapp:v1.0
    deploy:
      replicas: 9
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.web.rule=Host(`app.example.com`)"
        - "traefik.http.services.web.loadbalancer.server.port=80"
  
  # Canary версия (10% трафика)
  web-canary:
    image: myapp:v1.1
    deploy:
      replicas: 1
      labels:
        - "traefik.enable=true"
```

**Принцип работы:**
1. Развернуть обе версии одновременно
2. Traefik распределяет трафик пропорционально репликам
3. При успехе — увеличить количество canary-реплик
4. При ошибке — удалить canary-сервис

**Масштабирование canary:**
```sh
docker service scale web-canary=3 web-stable=7
```

Подробнее о Traefik — в **[swarm_ingress_traefik.md](./swarm_ingress_traefik.md)**.

## Blue-Green развертывание

Blue-Green — развертывание новой версии параллельно со старой с мгновенным переключением.

### Файл `blue.yml`

```yaml
version: '3.8'
services:
  web:
    image: myapp:v1.0
    deploy:
      replicas: 5
      labels:
        - "traefik.http.routers.web.rule=Host(`app.example.com`)"
```

### Файл `green.yml`

```yaml
version: '3.8'
services:
  web:
    image: myapp:v2.0
    deploy:
      replicas: 5
      labels:
        - "traefik.http.routers.web.rule=Host(`app.example.com`)"
```

### Переключение

```sh
# Развернуть green-версию
docker stack deploy -c green.yml myapp

# Проверить работу
curl https://app.example.com

# Удалить blue-стек
docker stack rm myapp-blue
```

**Преимущества:**
- Мгновенное переключение
- Быстрый откат (развернуть blue заново)
- Тестирование перед переключением

**Недостатки:**
- Требует двойных ресурсов
- Ручное переключение трафика

## Troubleshooting

### Стек не развертывается

**Проверка:**
```sh
# Проверить синтаксис YAML
docker compose config

# Проверить логи сервиса
docker service logs myapp_<service>

# Проверить задачи
docker stack ps myapp --no-trunc
```

**Возможные причины:**

| Проблема | Причина | Решение |
|---|---|---|
| `invalid YAML` | Ошибки синтаксиса | `docker compose config` |
| `image not found` | Образ недоступен | Проверить registry, auth |
| `no suitable node` | Недостаточно ресурсов | `docker node ls`, `docker service ps` |
| `network not found` | Сеть не существует | Создать external-сеть |

### Сервис не запускается

**Проверка:**
```sh
# Детали задачи
docker service ps <service> --no-trunc

# Журналы
docker service logs <service> --follow

# Проверить ограничения
docker node ls
docker node inspect <node>
```

**Частые ошибки:**

| Ошибка | Причина | Решение |
|---|---|---|
| `exit code 1` | Ошибка приложения | Проверить логи |
| `OOMKilled` | Недостаточно RAM | Увеличить `resources.limits.memory` |
| `unhealthy` | Health check failed | Проверить `healthcheck` |

### Проблемы с сетью

**Проверка:**
```sh
# Список сетей
docker network ls

# Инспекция сети
docker network inspect myapp_default

# Проверка DNS
docker exec <container> nslookup <service>
```

**Возможные проблемы:**

| Проблема | Решение |
|---|---|
| DNS не разрешает имя | Проверить overlay-сеть |
| Контейнеры не видят друг друга | Убедиться, что в одной сети |
| Нет внешнего доступа | Проверить `docker_gwbridge` |

### Диагностика ресурсов

```sh
# Статистика узлов
docker node ls

# Детали узла
docker node inspect <node>

# Задачи на узле
docker node ps <node>

# Статистика сервиса
docker service stats <service>
```

## Сравнение с Kubernetes

| Параметр | Docker Stack | Kubernetes |
|---|---|---|
| **Масштабирование** | До ~1000 узлов | До ~5000 узлов |
| **Сложность** | Низкая | Высокая |
| **Service Discovery** | Встроенный DNS | CoreDNS |
| **Config Management** | Secrets/Configs | ConfigMaps/Secrets |
| **Rolling Update** | Встроенный | Deployment |
| **Canary** | Ручное (Traefik) | Istio/Flagger |
| **Blue-Green** | Ручное | Argo Rollouts |

## Связанные документы

- **Базовое развертывание** — **[swarm_stack_deployment.md](./swarm_stack_deployment.md)**
- **Traefik Ingress** — **[swarm_ingress_traefik.md](./swarm_ingress_traefik.md)**
- **Secrets and Configs** — **[swarm_secrets_configs.md](./swarm_secrets_configs.md)**
