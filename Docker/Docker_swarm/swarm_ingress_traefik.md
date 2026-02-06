# Управление Ingress-трафиком в Docker Swarm с помощью Traefik

При работе с несколькими веб-сервисами в кластере **[Docker Swarm](docker_swarm_overview.md)** возникает проблема маршрутизации. Стандартный механизм **[Routing Mesh](swarm_core_concepts.md)** направляет трафик на опубликованные порты, но не умеет различать запросы по доменным именам (например, `app1.example.com` и `app2.example.com`).

Для решения этой задачи используются динамические обратные прокси, и **[Traefik](../../WebServers/Traefik/traefik_overview.md)** является одним из самых популярных решений в этой области. Он автоматически обнаруживает сервисы и настраивает для них правила маршрутизации.

## Определения

* **Ingress-трафик:** Входящий сетевой трафик, поступающий извне в кластер.
* **Динамический обратный прокси (Dynamic Reverse Proxy):** Прокси-сервер, который автоматически обнаруживает изменения в бэкенд-сервисах (например, запуск нового контейнера) и перенастраивает правила маршрутизации на лету, без необходимости ручного перезапуска или изменения конфигурации.

## Базовые концепции

1. **Прослушивание Docker Socket:** Traefik запускается как сервис в Swarm и получает доступ к Docker Socket (`/var/run/docker.sock`).
2. **Обнаружение сервисов (Service Discovery):** Он "слушает" события Docker API (создание, удаление, обновление сервисов).
3. **Динамическая конфигурация через метки (Labels):** Когда Traefik обнаруживает сервис со специальными **метками (labels)**, он автоматически создает для него правила маршрутизации.
4. **Маршрутизация трафика:** Весь внешний трафик, поступающий на порты 80/443, приходит на Traefik. Он, в свою очередь, согласно созданным правилам, перенаправляет его на контейнеры нужного сервиса.
5. **Автоматизация SSL:** Traefik может автоматически запрашивать и обновлять SSL-сертификаты от Let's Encrypt для всех обнаруженных сервисов.

## Практические сценарии

### Развертывание Traefik и веб-сервиса

#### 1. Создание сети для Traefik

Сначала создадим общую `overlay`-сеть, через которую Traefik будет общаться с другими сервисами.

```sh
docker network create --driver=overlay traefik-public
```

#### 2. Файл `docker-compose.traefik.yml` для развертывания Traefik

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v2.11
    ports:
      # Открываем стандартные HTTP и HTTPS порты
      - "80:80"
      - "443:443"
    command:
      # --- Конфигурация Traefik ---
      # Включаем Docker Swarm Provider
      - "--providers.docker.swarmMode=true"
      # Указываем, что Traefik не должен автоматически работать со всеми сервисами, а только с теми, у которых есть label "traefik.enable=true"
      - "--providers.docker.exposedByDefault=false"
      # Определяем точки входа (entrypoints)
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Настраиваем редирект с HTTP на HTTPS
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      # Настраиваем ACME (Let's Encrypt) для автоматического получения SSL-сертификатов
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=your-email@example.com" # Укажите ваш email
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
      # Включаем Dashboard (только для демонстрации, в проде защитить паролем)
      - "--api.insecure=true"
    volumes:
      # Подключаем Docker-сокет для обнаружения сервисов
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      # Том для хранения SSL-сертификатов
      - "letsencrypt-data:/letsencrypt"
    networks:
      # Подключаем Traefik к созданной ранее сети
      - traefik-public
    deploy:
      placement:
        constraints:
          # Рекомендуется запускать Traefik на manager-ноде
          - node.role == manager

volumes:
  letsencrypt-data:

networks:
  traefik-public:
    external: true
```

**Развертывание Traefik:**

```sh
docker stack deploy -c docker-compose.traefik.yml traefik-stack
```

#### 3. Файл `docker-compose.app.yml` для развертывания Nginx

Теперь запустим сервис Nginx, используя метки, которые Traefik поймет.

```yaml
version: '3.8'

services:
  nginx-app:
    image: nginx:1.25.5
    networks:
      - traefik-public
    deploy:
      replicas: 2
      labels:
        # Включаем Traefik для этого сервиса
        - "traefik.enable=true"
        # Создаем роутер и указываем правило (по домену)
        - "traefik.http.routers.nginx-router.rule=Host(`nginx.your-domain.com`)"
        # Указываем, что роутер работает на HTTPS
        - "traefik.http.routers.nginx-router.entrypoints=websecure"
        # Включаем SSL и указываем резолвер для получения сертификата
        - "traefik.http.routers.nginx-router.tls.certresolver=myresolver"
        # Указываем Traefik, на какой порт направлять трафик внутри контейнера
        - "traefik.http.services.nginx-service.loadbalancer.server.port=80"

networks:
  traefik-public:
    external: true
```

**Развертывание приложения:**

```sh
docker stack deploy -c docker-compose.app.yml my-app
```

После этого Traefik обнаружит сервис `nginx-app`, увидит его метки, создаст правило для хоста `nginx.your-domain.com`, запросит для него SSL-сертификат и начнет перенаправлять на него трафик.

## Дополнительная информация

### Описание меток (Labels)

Метки (labels) являются основным способом конфигурации маршрутизации для сервисов в Traefik.

* `traefik.enable=true`: Главный "переключатель", который активирует Traefik для данного сервиса.
* `traefik.http.routers.<router-name>.rule=Host(\`...\`)`: Определяет правило для **роутера**. Имя роуtera (`<router-name>`) может быть произвольным, но должно быть уникальным для сервиса. Чаще всего используется правило`Host()` для маршрутизации по доменному имени.
* `traefik.http.routers.<router-name>.entrypoints=<entrypoint-name>`: Указывает, через какую **точку входа** (например, `websecure` для HTTPS) будет доступен роутер.
* `traefik.http.routers.<router-name>.tls.certresolver=<resolver-name>`: Включает TLS и указывает, какой **Certificate Resolver** (например, настроенный для Let's Encrypt) использовать для получения SSL-сертификатов.
* `traefik.http.services.<service-name>.loadbalancer.server.port=<port>`: Определяет, на какой порт внутри контейнера Traefik должен перенаправлять трафик. Имя сервиса (`<service-name>`) может быть произвольным.
