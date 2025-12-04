# Развертывание приложений с помощью Docker Compose (Docker Stack) в Docker Swarm

Docker Swarm Mode позволяет использовать файлы `docker-compose.yml` для развертывания многоконтейнерных приложений как "стеков" (stacks). Это значительно упрощает управление сложными приложениями.

**Ключевые отличия при использовании Compose в Swarm:**

*   **Команда:** Вместо `docker compose up` используется `docker stack deploy`.
*   **Секция `deploy`:** Для Swarm-специфичных настроек (количество реплик, ограничения ресурсов, стратегии обновления) используется секция `deploy` в файле `docker-compose.yml`. Подробнее см. [Docker Compose: Секция Deploy](../docker_compose.md#секция-deploy).
*   **Игнорируемые параметры:** Параметры `container_name` и `restart` игнорируются, так как Swarm управляет именованием контейнеров и их перезапуском.

**Пример `docker-compose.yml` для Swarm:**

```yaml
version: '3.8'
services:
  web:
    image: nginx:1.25.5
    ports:
      - "80:80"
    deploy:
      replicas: 3
      placement:
        constraints:
          - node.role == worker
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
  backend:
    image: my-backend-app:1.0
    deploy:
      replicas: 2
      placement:
        constraints:
          - node.labels.app == backend
```

**Развертывание стека:**

```sh
docker stack deploy -c docker-compose.yml my-app-stack
```

**Просмотр стеков:**

```sh
docker stack ls
```

**Просмотр сервисов в стеке:**

```sh
docker stack services my-app-stack
```

**Удаление стека:**

```sh
docker stack rm my-app-stack
```
