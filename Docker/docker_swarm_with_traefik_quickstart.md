# Быстрый старт с Docker Swarm и Traefik

Это руководство основано на практическом вебинаре и показывает, как быстро развернуть легковесный и эффективный кластер на базе Docker Swarm с Traefik в качестве Ingress-контроллера для автоматической маршрутизации и управления TLS-сертификатами.

Такой подход является отличной альтернативой Kubernetes для небольших и средних проектов, где важна простота и скорость развертывания.

## Ключевые компоненты

- **[Docker Swarm](./docker_swarm.md):** Нативный инструмент оркестрации от Docker. Превращает несколько хостов в единый кластер.
- **[Docker Compose](./docker_compose.md):** Инструмент для описания и запуска многоконтейнерных приложений. Файлы `docker-compose.yml` используются для развертывания "стеков" в Swarm.
- **Traefik:** Современный reverse proxy и балансировщик нагрузки, который автоматически обнаруживает сервисы и управляет сетевой маршрутизацией.

## Шаг 1: Инициализация Swarm кластера

Для создания кластера понадобится как минимум один узел-менеджер. Остальные узлы будут рабочими (worker).

1.  **Инициализация менеджера:**
    На главном узле выполните команду, указав IP-адрес, по которому другие узлы смогут к нему подключиться.

    ```bash
    # Замените <MANAGER-IP> на реальный IP вашего узла
    docker swarm init --advertise-addr <MANAGER-IP>
    ```

    После выполнения Docker выведет команду для присоединения рабочих узлов, включающую токен.

2.  **Присоединение рабочих узлов (workers):**
    На каждом рабочем узле выполните команду, полученную на предыдущем шаге.

    ```bash
    docker swarm join --token <TOKEN> <MANAGER-IP>:<PORT>
    ```

3.  **Проверка состояния кластера:**
    На узле-менеджере можно посмотреть список всех узлов в кластере.

    ```bash
    docker node ls
    ```

## Шаг 2: Развертывание Traefik

Traefik будет запущен как сервис в Swarm и станет единой точкой входа для всего трафика. Он будет слушать Docker Socket, чтобы автоматически обнаруживать новые сервисы и настраивать для них роутинг.

Создайте файл `docker-compose.yml` для Traefik:

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v2.7 # Рекомендуется проверить актуальную версию
    command:
      - "--log.level=DEBUG"
      - "--api.dashboard=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.swarmmode=true"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=your-email@example.com"
      - "--certificatesresolvers.myresolver.acme.storage=/certificates/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "traefik-public-certificates:/certificates"
    networks:
      - traefik-public
    deploy:
      placement:
        constraints:
          - "node.role==manager"
      labels:
        - "traefik.enable=true"
        # Роутер для Dashboard по HTTP
        - "traefik.http.routers.traefik-dashboard.rule=Host(`traefik.your-domain.com`)"
        - "traefik.http.routers.traefik-dashboard.entrypoints=web"
        - "traefik.http.routers.traefik-dashboard.middlewares=https-redirect"
        # Роутер для Dashboard по HTTPS
        - "traefik.http.routers.traefik-dashboard-secure.rule=Host(`traefik.your-domain.com`)"
        - "traefik.http.routers.traefik-dashboard-secure.entrypoints=websecure"
        - "traefik.http.routers.traefik-dashboard-secure.tls=true"
        - "traefik.http.routers.traefik-dashboard-secure.tls.certresolver=myresolver"
        - "traefik.http.routers.traefik-dashboard-secure.service=api@internal"
        # Middleware для редиректа HTTP на HTTPS
        - "traefik.http.middlewares.https-redirect.redirectscheme.scheme=https"
        - "traefik.http.middlewares.https-redirect.redirectscheme.permanent=true"

networks:
  traefik-public:
    external: true

volumes:
  traefik-public-certificates:
```

### Как работает Traefik: Entrypoints, Routers, Middlewares, Services

Traefik обрабатывает входящие запросы, пропуская их через цепочку компонентов:

1.  **Entrypoints (Точки входа):** Это сетевые порты, которые Traefik слушает для входящего трафика (например, 80 для HTTP, 443 для HTTPS). В нашем `docker-compose.yml` мы определили `web` (порт 80) и `websecure` (порт 443).
2.  **Routers (Маршрутизаторы):** Анализируют входящие запросы (по доменному имени, пути, заголовкам и т.д.) и определяют, какой сервис должен их обработать. Каждый роутер привязан к одной или нескольким точкам входа. Например, роутер для дашборда Traefik (`traefik-dashboard-secure`) привязан к `websecure` entrypoint и срабатывает при обращении к `traefik.your-domain.com`.
3.  **Middlewares (Промежуточное ПО):** Модифицируют запросы или ответы перед тем, как они достигнут сервиса, или после того, как сервис ответит. Примеры: перенаправление HTTP на HTTPS (`https-redirect`), добавление аутентификации, изменение заголовков. Middlewares могут быть применены к одному или нескольким роутерам.
4.  **Services (Сервисы):** Это конечные точки, куда Traefik направляет трафик после обработки роутерами и middlewares. Сервис обычно соответствует вашему приложению (например, контейнеру Nginx или `whoami`). Traefik может балансировать нагрузку между несколькими экземплярами одного сервиса.

Эта цепочка позволяет гибко управлять маршрутизацией и обработкой трафика.

**Перед развертыванием:**

1.  Замените `traefik.your-domain.com` и `your-email@example.com` на ваши реальные данные.
2.  Создайте оверлейную сеть для Traefik:

    ```bash
    docker network create --driver=overlay traefik-public
    ```

**Развертывание стека Traefik:**

```bash
docker stack deploy -c docker-compose.yml traefik
```

Теперь Dashboard Traefik будет доступен по адресу `https://traefik.your-domain.com`.

## Шаг 3: Развертывание приложения

Теперь можно развернуть любое приложение, добавив к нему специальные лейблы, которые Traefik использует для настройки маршрутизации.

Пример `docker-compose.yml` для простого сервиса `whoami`:

```yaml
version: '3.8'

services:
  whoami:
    image: traefik/whoami
    networks:
      - traefik-public
    deploy:
      replicas: 2
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.whoami.rule=Host(`whoami.your-domain.com`)"
        - "traefik.http.routers.whoami.entrypoints=websecure"
        - "traefik.http.routers.whoami.tls=true"
        - "traefik.http.routers.whoami.tls.certresolver=myresolver"
        - "traefik.http.services.whoami.loadbalancer.server.port=80"
        - "traefik.docker.network=traefik-public"

networks:
  traefik-public:
    external: true
```

**Развертывание стека приложения:**

1.  Замените `whoami.your-domain.com` на желаемый домен.
2.  Выполните команду:

    ```bash
    docker stack deploy -c docker-compose.yml my-app
    ```

Traefik автоматически обнаружит новый сервис, получит для него TLS-сертификат от Let's Encrypt и начнет направлять на него трафик, приходящий на `https://whoami.your-domain.com`.

### Управление конфигурационными файлами с Docker Configs

Docker Swarm предоставляет встроенный механизм для централизованного управления нечувствительными конфигурационными файлами, такими как конфигурации веб-серверов. Это позволяет легко обновлять конфигурации без пересборки образов и гарантирует, что правильная конфигурация будет доступна сервису независимо от того, на каком узле Swarm он запущен.

**Пример: Использование `docker config` для Nginx**

1.  **Создайте файл конфигурации Nginx** (например, `nginx_simple.conf`):

    ```nginx
    server {
        listen 80;
        server_name example.com;

        location / {
            return 200 'Hello from Nginx configured by Docker Configs!';
            add_header Content-Type text/plain;
        }
    }
    ```

2.  **Создайте Docker Config** из этого файла:

    ```bash
    docker config create nginx_config_example nginx_simple.conf
    ```

    Теперь конфигурация `nginx_config_example` хранится в Swarm.

3.  **Используйте Docker Config в `docker-compose.yml`** для вашего сервиса Nginx:

    ```yaml
    version: '3.8'

    configs:
      nginx_config_example:
        external: true # Указываем, что конфиг уже создан вручную

    services:
      nginx_web:
        image: nginx:1.25.5 # Используйте конкретную версию, например, nginx:1.25.5
        configs:
          - source: nginx_config_example
            target: /etc/nginx/conf.d/default.conf # Путь, куда конфиг будет смонтирован внутри контейнера
        networks:
          - traefik-public
        deploy:
          labels:
            - "traefik.enable=true"
            - "traefik.http.routers.nginx-example.rule=Host(`nginx.your-domain.com`)"
            - "traefik.http.routers.nginx-example.entrypoints=websecure"
            - "traefik.http.routers.nginx-example.tls=true"
            - "traefik.http.routers.nginx-example.tls.certresolver=myresolver"
            - "traefik.http.services.nginx-example.loadbalancer.server.port=80"
            - "traefik.docker.network=traefik-public"

    networks:
      traefik-public:
        external: true
    ```

    **Развертывание стека Nginx:**

    ```bash
    docker stack deploy -c docker-compose.yml my-nginx-app
    ```

    Traefik автоматически обнаружит этот сервис Nginx, получит для него TLS-сертификат и начнет направлять трафик на `https://nginx.your-domain.com`, используя конфигурацию, предоставленную через Docker Config.

## Заключение

Данный подход позволяет создать простую, но мощную и масштабируемую платформу для развертывания приложений. Вы описываете свои сервисы в `docker-compose.yml`, а Swarm и Traefik берут на себя оркестрацию, маршрутизацию и безопасность.
