# Traefik Overview

## Definitions

**Traefik** — современный обратный прокси и балансировщик нагрузки для микросервисных архитектур с поддержкой автоматического service discovery.

**Ключевое отличие** от традиционных веб-серверов (Nginx, HAProxy): Traefik "слушает" бэкенды (Docker, Kubernetes, Consul и др.) и динамически перенастраивает маршруты без перезапуска.

> **Актуальная версия:** Traefik v3.x (текущая стабильная — v3.6+, Changelog: [traefik/traefik](https://github.com/traefik/traefik))

## Basic Concepts

Архитектура Traefik v3 построена на пяти компонентах:

1. **Providers** — источники конфигурации (Docker, Kubernetes, Consul, File). Traefik опрашивает их API и строит динамическую конфигурацию.
2. **Entrypoints** — сетевые порты для входящего трафика (HTTP/80, HTTPS/443).
3. **Routers** — правила маршрутизации на основе хоста, пути, заголовков; связывают entrypoints с сервисами.
4. **Services** — определяют конечные бэкенды (адреса, порты, стратегию балансировки).
5. **Middleware** — цепочка обработчиков запроса до отправки сервису (BasicAuth, StripPrefix, RateLimit, RedirectScheme).

### Конфигурация

Traefik v3 разделяет конфигурацию на два типа:

- **Статическая** (`traefik.yml` / CLI-флаги) — entrypoints, providers, certificatesResolvers. Загружается при старте, требует перезапуска для изменений.
- **Динамическая** (labels в Docker, Ingress в K8s, файл `dynamic.yml`) — routers, services, middleware. Обновляется на лету без перезапуска.

### SSL/TLS автоматизация

Traefik получает и обновляет сертификаты Let's Encrypt через ACME-протокол. Поддерживаемые методы валидации:

| Метод | Описание | Use-case |
|---|---|---|
| **HTTP Challenge** | Traefik создаёт временный endpoint для проверки домена | Стандартный случай |
| **TLS Challenge** | Валидация через TLS handshake | Альтернатива HTTP |
| **DNS Challenge** | Создание TXT-записи в DNS (требует provider credentials) | Wildcard-сертификаты, internal DNS |

> **Примечание:** Wildcard-сертификаты (`*.example.com`) поддерживаются только через DNS Challenge.

## Practical Scenarios

Основные платформы развертывания и ссылки на руководства:

- **Docker Compose** — [Traefik with Docker Compose](./traefik_with_docker_compose.md)
- **Docker Swarm** — [Swarm Ingress Traffic with Traefik](../../Docker_swarm/swarm_ingress_traefik.md)
- **Kubernetes** — Traefik как Ingress-контроллер: [Ingress Overview](../../Kubernetes/Networking/Ingress/overview.md), [BasicAuth в K8s](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md)

## Additional Information

### Сравнение с альтернативами

| Решение | Сложность | Service Discovery | SSL Automation | Экосистема |
|---|---|---|---|---|
| **Traefik** | Низкая | Встроенная | Let's Encrypt из коробки | Растущая |
| **Nginx** | Средняя | Через модули/внешние | cert-manager (в K8s) | Огромная |
| **HAProxy** | Высокая | Через consul-template | Внешние скрипты | Большая |

### Связанные документы

- [Traefik v3 Migration (v2→v3)](../../Docker_swarm/swarm_ingress_traefik.md)
- [CI/CD с Traefik в Swarm](../../Docker_swarm/CI_CD/overview.md)
- [Infrastructure Deployment](../../Docker_swarm/CI_CD/infra_deployment.md)
- [Обратный прокси (концепция)](../../Networking/Concepts/proxy.md)
