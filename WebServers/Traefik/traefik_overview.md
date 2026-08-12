# Обзор Traefik

## Определения

**Traefik** — современный облачно-ориентированный (cloud-native) обратный прокси-сервер и балансировщик нагрузки для микросервисных архитектур с поддержкой автоматического обнаружения сервисов (service discovery).

**Ключевые отличия:**
- **Динамичность:** Traefik разработан для сред, где контейнеры запускаются и останавливаются постоянно. Он «слушает» API оркестраторов (Docker, Kubernetes, Nomad, Consul) и автоматически обновляет конфигурацию без перезагрузки.
- **Single Binary:** Написан на Go, поставляется в виде одного бинарного файла или легковесного Docker-образа.
- **Встроенная визуализация:** Имеет веб-интерфейс (Dashboard) для мониторинга маршрутов, сервисов и статуса здоровья в реальном времени.

## Базовые концепции

### Архитектура компонентов

Архитектура Traefik v3 построена на цепочке обработки запроса:
`Entrypoint → Router (with Middlewares) → Service → Server (Backend)`

1.  **Providers** — источники данных. Опрашивают API (Docker, K8s, File) и поставляют динамическую конфигурацию.
2.  **Entrypoints** — слушатели сети (порты). Определяют, какие протоколы (HTTP, HTTPS, UDP, TCP) и порты открыты для приема трафика.
3.  **Routers** — логика анализа входящих запросов. Сопоставляют запрос (по Host, Path, Header) с конкретным Service. К роутеру можно прикрепить Middleware.
4.  **Middlewares** — компоненты трансформации запроса. Могут изменять заголовки, ограничивать скорость, проверять аутентификацию или перенаправлять трафик.
5.  **Services** — абстракция над бэкендами. Определяют способ балансировки между физическими серверами (Round Robin, Sticky sessions) и параметры проверки здоровья (Health Checks).

### Типы конфигурации

Traefik строго разделяет конфигурацию на два слоя, что критично для понимания:

#### 1. Статическая конфигурация
Определяет «фундамент» прокси. Загружается один раз при старте.
- **Параметры:** Entrypoints, Providers, Certificates Resolvers, логирование, интеграция с метриками.
- **Источники:** Файл `traefik.yml` (или `.toml`), переменные окружения, CLI-флаги.

*Пример (traefik.yml):*
```yaml
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  docker:
    exposedByDefault: false
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  myresolver:
    acme:
      email: admin@example.com
      storage: acme.json
      httpChallenge:
        entryPoint: web
```

#### 2. Динамическая конфигурация
Определяет правила маршрутизации. Обновляется «на лету» без прерывания соединений.
- **Параметры:** Routers, Services, Middlewares.
- **Источники:** Метки (labels) в Docker, CRD/Ingress в Kubernetes, отдельные файлы в `providers.file`.

*Пример (YAML для провайдера file):*
```yaml
http:
  routers:
    my-app:
      rule: "Host(`app.example.com`)"
      service: app-service
      entryPoints:
        - websecure
      tls:
        certResolver: myresolver

  services:
    app-service:
      loadBalancer:
        servers:
          - url: "http://192.168.1.10:8080"
```

### SSL/TLS и автоматизация сертификатов (ACME)

Traefik имеет встроенную поддержку Let's Encrypt и ZeroSSL. Поддерживаемые методы валидации:

| Метод | Описание | Основной кейс |
| :--- | :--- | :--- |
| **HTTP Challenge** | Проверка владения доменом через временный endpoint на порту 80. | Стандартный публичный веб-сайт. |
| **TLS Challenge** | Валидация через протокол ALPN на порту 443. | Использование только HTTPS. |
| **DNS Challenge** | Проверка через создание TXT-записи в DNS. | Wildcard-сертификаты (`*.example.com`) и внутренние сети. |

### Промежуточное ПО (Middlewares)

Middlewares позволяют модифицировать запрос до того, как он попадет в сервис, или ответ после обработки.

**Популярные Middlewares:**
- **Безопасность:** `BasicAuth` (базовая аутентификация), `ForwardAuth` (делегирование аутентификации внешнему сервису, например Authelia), `IPAllowList` (белый список IP).
- **Трансформация:** `AddPrefix` / `StripPrefix` (манипуляции с путями URL), `Headers` (добавление/удаление HTTP-заголовков).
- **Ограничение:** `RateLimit` (защита от перегрузки), `CircuitBreaker` (разрыв цепи при отказах бэкенда).
- **Ошибки:** `ErrorPage` (перенаправление на кастомные страницы ошибок).

### Управление трафиком

Traefik поддерживает продвинутые сценарии развертывания без использования Service Mesh:

1.  **Канареечные релизы (Weighted Round Robin):** Распределение трафика между разными версиями сервиса в процентном соотношении.
    ```yaml
    # Пример в динамической конфигурации
    services:
      canary-service:
        loadBalancer:
          services:
            - name: app-v1@file
              weight: 90
            - name: app-v2@file
              weight: 10
    ```
2.  **Зеркалирование (Mirroring):** Дублирование входящего трафика на другой сервис (например, для тестирования новой версии на реальных данных без влияния на пользователя).
    ```yaml
    services:
      mirrored-service:
        mirroring:
          service: app-v1@file
          mirrors:
            - name: app-v2@file
              percent: 10
    ```

### Современные возможности и интеграции

-   **Kubernetes Gateway API:** Нативная поддержка стандарта (v1.2+), заменяющая классический Ingress.
-   **WebAssembly (WASM):** Возможность написания кастомных плагинов на Go, Rust или C++.
-   **Observability:** Глубокая интеграция с OpenTelemetry, Prometheus, Datadog и Zipkin.
-   **HTTP/3:** Поддержка QUIC для ускорения загрузки сайтов в нестабильных сетях.
-   **Tailscale:** Автоматическое получение сертификатов для узлов внутри частной сети Tailscale.


### Безопасность и эксплуатация

1.  **Защита Docker Socket:** При использовании провайдера Docker Traefik требует доступа к `/var/run/docker.sock`. Для безопасности рекомендуется использовать `docker-socket-proxy`, чтобы ограничить доступ Traefik только операциями чтения API.
2.  **Защита Dashboard:** По умолчанию дашборд открыт. Всегда защищайте его с помощью `BasicAuth` или `ForwardAuth` и не выставляйте на публичные Entrypoints без TLS.
3.  **Логирование:** Используйте формат JSON для `accessLog`, чтобы облегчить интеграцию с ELK/Loki.
    ```yaml
    accessLog:
      filePath: "/var/log/traefik/access.log"
      format: json
    ```

## Практические сценарии

Traefik адаптируется под разные уровни инфраструктуры:

-   **Локальная разработка и VPS:** Использование Docker Compose для автоматизации SSL и маршрутизации.
    -   См. [Traefik с Docker Compose](./traefik_with_docker_compose.md).
-   **Кластеры Docker Swarm:** Работа в качестве динамического Edge Router.
    -   См. [Docker Swarm Ingress с Traefik](../../Docker_swarm/swarm_ingress_traefik.md).
-   **Kubernetes (K8s):**
    -   В качестве Ingress-контроллера: [Обзор Ingress](../../Kubernetes/Networking/Ingress/overview.md).
    -   Через современный [Traefik Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md).

## Дополнительная информация

### Сравнение с альтернативами

| Характеристика | Traefik | Nginx | Envoy | HAProxy |
| :--- | :--- | :--- | :--- | :--- |
| **Сложность настройки** | Низкая (Auto) | Средняя | Высокая | Высокая |
| **Service Discovery** | Native | Через модули | Native (xDS) | Внешние скрипты |
| **SSL Automation** | Встроенная (ACME) | Внешняя | Внешняя | Внешняя |
| **Конфигурация** | Динамическая | Static/Reload | Динамическая (API) | Static/Runtime API |
| **Основной кейс** | Микросервисы | Static/High Perf | Service Mesh | Load Balancing |

### См. также

-   [Traefik Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md) — глубокое погружение в реализацию стандарта в K8s.
-   [Сетевое взаимодействие в Swarm](../../Docker_swarm/swarm_networking.md) — основы Overlay-сетей для балансировщика.
-   [Обратный прокси (концепция)](../../Networking/Concepts/proxy.md) — теоретические основы работы прокси-серверов.
