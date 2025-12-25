# Docker Swarm - Ingress Traffic Management with Traefik

Когда в кластере работает несколько веб-сервисов, возникает проблема: как направить входящий трафик на порты 80 и 443 на нужный сервис в зависимости от доменного имени (например, `app1.example.com` -> сервис App1, `app2.example.com` -> сервис App2)? Стандартный `Routing Mesh` направляет трафик на опубликованный порт, но не анализирует доменные имена.

Решением является использование **динамического обратного прокси (reverse proxy)**, такого как **Traefik**.

## Как работает Traefik в Swarm?

1.  **Прослушивание Docker Socket:** Traefik запускается как сервис в Swarm и получает доступ к Docker Socket (`/var/run/docker.sock`).
2.  **Обнаружение сервисов:** Он "слушает" события Docker API (создание, удаление, обновление сервисов).
3.  **Динамическая конфигурация:** Когда Traefik обнаруживает новый сервис со специальными **метками (labels)**, он автоматически создает для него правила маршрутизации.
4.  **Маршрутизация трафика:** Весь внешний трафик на порты 80/443 приходит на Traefik, который, согласно созданным правилам, перенаправляет его на нужные контейнеры нужного сервиса.
5.  **Автоматический SSL:** Traefik может автоматически запрашивать и обновлять SSL-сертификаты от Let's Encrypt для ваших сервисов.

## Пример: Развертывание Traefik и сервиса Nginx

### 1. Создание сети для Traefik
Сначала создадим общую overlay-сеть, через которую Traefik будет общаться с другими сервисами.
```sh
docker network create --driver=overlay traefik-public
```

### 2. Файл `docker-compose.traefik.yml` для развертывания Traefik

```yaml
version: '3.8'

services:
  traefik:
    image: traefik:v2.11
    ports:
      - "80:80"
      - "443:443"
    command:
      - "--api.insecure=true" # Для доступа к дашборду Traefik (не для прода!)
      - "--providers.docker.swarmMode=true"
      - "--providers.docker.exposedByDefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--certificatesresolvers.myresolver.acme.tlschallenge=true"
      - "--certificatesresolvers.myresolver.acme.email=your-email@example.com"
      - "--certificatesresolvers.myresolver.acme.storage=/letsencrypt/acme.json"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "letsencrypt-data:/letsencrypt"
    networks:
      - traefik-public
    deploy:
      placement:
        constraints:
          - node.role == manager # Рекомендуется запускать Traefik на manager-ноде

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

### 3. Файл `docker-compose.app.yml` для развертывания Nginx

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
        - "traefik.enable=true"
        - "traefik.http.routers.nginx-router.rule=Host(`nginx.your-domain.com`)"
        - "traefik.http.routers.nginx-router.entrypoints=websecure"
        - "traefik.http.routers.nginx-router.tls.certresolver=myresolver"
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

### Описание меток (Labels)

*   `traefik.enable=true`: Включает Traefik для этого сервиса.
*   `traefik.http.routers.nginx-router.rule=Host(\`nginx.your-domain.com\`)`: Определяет правило маршрутизации (по доменному имени). Имя роутера `nginx-router` может быть произвольным.
*   `traefik.http.routers.nginx-router.entrypoints=websecure`: Указывает, что роутер работает на точке входа `websecure` (HTTPS).
*   `traefik.http.routers.nginx-router.tls.certresolver=myresolver`: Указывает, какой `Certificate Resolver` использовать для получения SSL-сертификатов.
*   `traefik.http.services.nginx-service.loadbalancer.server.port=80`: Указывает порт, на котором работает приложение внутри контейнера. Имя сервиса `nginx-service` может быть произвольным.
