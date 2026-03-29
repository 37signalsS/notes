# CI/CD с Docker Swarm: Обзор и концепции

## Определения

- **[Docker Swarm](../docker_swarm_overview.md):** Нативная система оркестровки контейнеров от Docker, позволяющая объединять несколько хостов в единый виртуальный Docker-хост (кластер). Используется для развертывания и масштабирования сервисов.
- **[GitLab CI/CD](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md):** Встроенный в GitLab инструмент для автоматизации сборки, тестирования и развертывания приложений (CI/CD). Пайплайны описываются в файле `.gitlab-ci.yml`.
- **[Traefik](../../WebServers/Traefik/traefik_overview.md):** Современный обратный прокси и балансировщик нагрузки, который автоматически обнаруживает сервисы (Service Discovery) и управляет маршрутизацией трафика к ним, включая автоматическое управление SSL-сертификатами.
- **[mTLS (mutual TLS)](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md):** Протокол безопасной связи, при котором клиент и сервер взаимно аутентифицируют друг друга с помощью сертификатов. В контексте CI/CD обеспечивает защищенное соединение между GitLab Runner и Docker Daemon.
- **[Environment Scope](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md):** Механизм GitLab CI для привязки переменных к конкретным окружениям (например, `production`, `development`). Позволяет использовать один пайплайн для развертывания на разные кластеры с различными учетными данными.

## Базовые концепции

### Архитектура решения

Предлагаемая архитектура представляет собой полный CI/CD-процесс, где **GitLab CI** выступает в роли системы автоматизации, **Docker Swarm** — в качестве платформы для выполнения приложений, а **Traefik** — как точка входа для внешнего трафика (Ingress).

Ключевые принципы:

1. **Удаленное и безопасное управление Swarm:** GitLab Runner не устанавливается напрямую на узлы кластера. Вместо этого он взаимодействует с Docker Engine удаленно по TCP, используя **[mTLS (mutual TLS)](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**. И клиент (GitLab Runner), и сервер (Docker Daemon) проверяют сертификаты друг друга, что обеспечивает безопасное соединение.
2. **Динамическая маршрутизация с Traefik:** Traefik отслеживает Docker API. Когда в Swarm запускается новый сервис с определенными метками (`labels`), Traefik автоматически создает для него маршрут и может выпустить SSL-сертификат от Let's Encrypt. Это устраняет необходимость ручной настройки reverse proxy.
3. **Разделение инфраструктуры и приложений:** Общие сервисы (Traefik, базы данных) выносятся в отдельный "инфраструктурный" стек (например, `shared-infra`), управляемый из своего репозитория. Приложения развертываются независимо, используя общую сетевую инфраструктуру.
4. **Управление окружениями в GitLab CI:** Используя **[переменные с привязкой к окружению (environment scope)](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**, один и тот же пайплайн может развертывать приложение на разные кластеры (например, `development` и `production`), автоматически подставляя нужные адреса (`DOCKER_HOST`) и учетные данные.

## Практические сценарии

### Сценарий 1: Настройка безопасного доступа к кластеру

GitLab Runner взаимодействует с Docker Swarm удаленно через TCP с mTLS-аутентификацией:

1. Генерация сертификатов (CA, сервер, клиент) — см. **[swarm_setup.md](./swarm_setup.md)**
2. Настройка Docker Daemon для приема TLS-соединений
3. Создание Docker Context для удобного переключения между окружениями
4. Сохранение клиентских сертификатов в переменных GitLab CI (`CA_PEM`, `CERT_PEM`, `KEY_PEM`)

**Результат:** GitLab Runner безопасно подключается к кластеру без установки на узлы Swarm.

### Сценарий 2: Развертывание инфраструктуры (Traefik)

Инфраструктурные сервисы выносятся в отдельный стек (`shared-infra`):

1. Создание `docker-compose.yml` с конфигурацией Traefik
2. Настройка `.gitlab-ci.yml` для автоматического деплоя
3. Определение переменных окружения (ACME_EMAIL, DOCKER_HOST, сертификаты)
4. Ручной или автоматический запуск пайплайна

**Результат:** Traefik автоматически обнаруживает сервисы и управляет SSL-сертификатами. Подробно в **[infra_deployment.md](./infra_deployment.md)**.

### Сценарий 3: CI/CD пайплайн для приложения

Пайплайн с сборкой образа и развертыванием в Swarm:

1. **Stage: Build** — сборка Docker-образа через Kaniko (без Docker-in-Docker)
2. **Stage: Deploy** — развертывание через `docker stack deploy` с флагом `--with-registry-auth`
3. Использование `environment scope` для разделения `development` и `production`
4. Labels-driven конфигурация Traefik для маршрутизации по доменам

**Результат:** Коммит в `dev` → деплой на dev-кластер, коммит в `main` → деплой на prod-кластер. Подробно в **[app_deployment.md](./app_deployment.md)**.

### Сценарий 4: Маршрутизация трафика через Traefik

Приложение получает автоматическую маршрутизацию через Docker labels:

```yaml
deploy:
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.my-app.rule=Host(`app.example.com`)"
    - "traefik.http.routers.my-app.entrypoints=websecure"
    - "traefik.http.routers.my-app.tls.certresolver=myresolver"
    - "traefik.http.services.my-app.loadbalancer.server.port=3000"
```

**Результат:** Traefik автоматически создает маршрут, выпускает SSL-сертификат от Let's Encrypt. Детали в **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)**.

## Дополнительная информация

### Преимущества архитектуры

- **Безопасность:** mTLS защищает соединение между CI/CD и кластером
- **Автоматизация:** Traefik устраняет ручную настройку reverse proxy
- **Масштабируемость:** Разделение инфраструктуры и приложений позволяет независимое масштабирование
- **Гибкость:** Environment scope позволяет использовать единый пайплайн для нескольких окружений

### Рекомендации

- **Сборка образов:** Использовать Kaniko вместо Docker-in-Docker для безопасности
- **Управление секретами:** Хранить сертификаты и токены в GitLab CI Variables (File type)
- **Флаг `--with-registry-auth`:** Критически важен для доступа узлов Swarm к приватным образам
- **Версионирование Traefik:** Зафиксировать версию образа (например, `traefik:v3.6`) для воспроизводимости

### Связанные документы

- **Настройка кластера:** **[swarm_setup.md](./swarm_setup.md)** — инициализация Swarm, mTLS, Docker Context
- **Инфраструктура:** **[infra_deployment.md](./infra_deployment.md)** — развертывание Traefik и общих сервисов
- **Приложения:** **[app_deployment.md](./app_deployment.md)** — пайплайн для развертывания приложений
- **Лучшие практики:** **[best_practices.md](./best_practices.md)** — рекомендации по безопасности и оптимизации
- **Docker Swarm:** **[../docker_swarm_overview.md](../docker_swarm_overview.md)** — основы оркестрации
- **Traefik:** **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)** — детальная настройка маршрутизации
- **GitLab CI:** **[../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md)** — основы пайплайнов
