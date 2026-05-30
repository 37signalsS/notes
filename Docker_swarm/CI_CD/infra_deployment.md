# CI/CD с Docker Swarm: Развертывание инфраструктуры

## Определения

- **Инфраструктурный стек (infrastructure stack):** Набор общих сервисов (Traefik, базы данных, системы мониторинга), развертываемых в Docker Swarm как единый логический блок.
- **Общие сервисы (Shared Services):** Компоненты инфраструктуры, используемые несколькими приложениями одновременно (например, Ingress-прокси или централизованное хранилище).
- **Оверлейная сеть (Overlay Network):** Виртуальная сеть Docker Swarm, обеспечивающая сетевую связность между контейнерами на разных узлах кластера.
- **[Traefik](../swarm_ingress_traefik.md):** Динамический обратный прокси-сервер, выступающий в роли Ingress-контроллера для Swarm-кластера.

## Базовые концепции

### Архитектура инфраструктурного стека

Вынос инфраструктурных сервисов в отдельный репозиторий (`infra-stack`) обеспечивает:
- **Изоляцию изменений:** Модернизация прокси или БД не затрагивает пайплайны приложений.
- **Контроль версий:** Отдельная история конфигураций инфраструктуры.
- **Безопасность:** Разграничение прав доступа к критическим настройкам кластера.
- **Стабильность:** Единая точка входа для трафика и общие сетевые политики.

### Механизм развертывания через CI/CD

1. **Декларативное описание:** Конфигурация хранится в виде Docker Compose файлов.
2. **Безопасное соединение:** GitLab Runner подключается к Swarm Manager через **[mTLS](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls)**.
3. **Использование контекстов:** **[Docker Context](./docker_context_setup.md)** абстрагирует параметры подключения для команд CLI.
4. **Оркестрация стека:** Команда `docker stack deploy` обновляет состояние сервисов в кластере без их полной остановки.

## Практические сценарии

### Сценарий 1: Подготовка инфраструктурного репозитория

Структура проекта:
```text
infra-stack/
├── docker-compose.yml      # Описание сервисов (Traefik, DB)
├── .gitlab-ci.yml          # Автоматизация деплоя
└── .env.example            # Шаблон переменных окружения
```

Пример базового `docker-compose.yml` для Traefik:
```yaml
version: '3.8'
services:
  traefik:
    image: traefik:v3.6
    command:
      - "--providers.swarm=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Редирект HTTP -> HTTPS
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
    networks:
      - public
    deploy:
      placement:
        constraints:
          - "node.role==manager"

networks:
  public:
    external: true
    name: public
```

### Сценарий 2: Настройка переменных GitLab CI

Для работы пайплайна необходимо задать переменные в **Settings → CI/CD → Variables**:

| Переменная | Тип | Назначение |
|:---|:---|:---|
| `DOCKER_HOST` | Variable | Адрес Docker API (tcp://<IP>:2376) |
| `CA_PEM` | File | Корневой сертификат CA |
| `CERT_PEM` | File | Клиентский сертификат |
| `KEY_PEM` | File | Клиентский приватный ключ |

Детали генерации сертификатов приведены в **[Настройка кластера](./swarm_setup.md)**.

### Сценарий 3: Создание пайплайна развертывания

Пример `.gitlab-ci.yml` с использованием Docker Context:

```yaml
deploy_infra:
  stage: deploy
  image: docker:24
  before_script:
    - mkdir -p ~/.docker
    - cp "$CA_PEM" ~/.docker/ca.pem
    - cp "$CERT_PEM" ~/.docker/cert.pem
    - cp "$KEY_PEM" ~/.docker/key.pem
    - docker context create swarm-ctx \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm-ctx
  script:
    - docker stack deploy -c docker-compose.yml shared-infra --with-registry-auth
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Сценарий 4: Верификация и обновление

После запуска пайплайна проверьте статус сервисов:
```bash
# Проверка списка сервисов в стеке
docker stack services shared-infra

# Просмотр задач сервиса Traefik
docker service ps shared-infra_traefik
```

При обновлении конфигурации (например, версии Traefik) Swarm выполнит Rolling Update согласно параметрам деплоя.

## Дополнительная информация

### Безопасность

- **Защита Dashboard:** По умолчанию панель Traefik должна быть закрыта. Рекомендуется использовать BasicAuth через Middleware.
- **Минимизация привилегий:** Ограничьте сетевой доступ к порту 2376 только для IP-адресов GitLab Runner.
- **Секреты:** Используйте механизмы Docker Secrets для передачи паролей в базы данных инфраструктурного стека.

### Диагностика типовых проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| `context "swarm-ctx" not found` | Ошибка в `before_script` | Проверить путь к сертификатам и синтаксис команды `create` |
| `permission denied` | Неверный клиентский ключ | Убедиться, что `KEY_PEM` имеет права `600` |
| Traefik не видит сервисы | Отсутствие общей сети | Проверить, что приложения подключены к сети `public` |

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов.
- **[Docker Context для CI/CD](./docker_context_setup.md)** — управление профилями подключения.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — детальная настройка маршрутизации.
- **[Развертывание приложения](./app_deployment.md)** — интеграция с инфраструктурным стеком.
- **[Лучшие практики](./best_practices.md)** — рекомендации по эксплуатации.
- **[Обзор Traefik](../../WebServers/Traefik/traefik_overview.md)** — общие концепции проксирования.
