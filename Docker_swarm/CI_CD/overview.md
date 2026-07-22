# CI/CD с Docker Swarm: Обзор и концепции

## Определения

- **[Docker Swarm](../docker_swarm_overview.md):** Нативная система оркестровки контейнеров от Docker, позволяющая объединять несколько хостов в единый виртуальный Docker-хост (кластер).
- **[GitLab CI/CD](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_basics.md):** Инструмент автоматизации жизненного цикла ПО, интегрированный в GitLab. Использует `.gitlab-ci.yml` для описания пайплайнов.
- **[GitHub Actions](../../Github_CI/Core_Concept.md):** Альтернативная система автоматизации от GitHub, использующая рабочие процессы (Workflows) на базе YAML.
- **[Traefik](../../WebServers/Traefik/traefik_overview.md):** Динамический обратный прокси и балансировщик, обеспечивающий Service Discovery в Swarm и автоматическое управление SSL (Let's Encrypt).
- **[mTLS (mutual TLS)](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls):** Механизм взаимной проверки сертификатов для защиты канала между CI-раннером и Docker API кластера.
- **[Жизненный цикл приложения](./app_lifecycle.md):** Процесс, включающий стратегии развертывания (Rolling Update), проверку здоровья (Health Checks) и механизмы отката (Rollback).
- **[Секреты и конфиги](../swarm_secrets_configs.md):** Объекты Swarm для безопасного хранения и доставки чувствительных данных (пароли, ключи) и файлов конфигурации в контейнеры.

## Базовые концепции

### Архитектура решения

Современный CI/CD для Docker Swarm строится на связке инструментов автоматизации, защищенного канала управления и динамического Ingress-прокси.

Ключевые принципы:

1. **Безопасное управление (Remote API):** Взаимодействие с кластером происходит через TCP-порт 2376 с обязательной **mTLS-аутентификацией**. Это исключает риски использования `/var/run/docker.sock` внутри пайплайнов.
2. **Декларативность:** Описание всей инфраструктуры и приложений в виде `docker-compose.yml` (Stack файлов), что соответствует принципу Infrastructure as Code (IaC).
3. **Динамический Ingress:** Балансировщик (Traefik) автоматически считывает метки (`labels`) из развернутых сервисов через Docker API, настраивая маршрутизацию и SSL без перезагрузки.
4. **Изоляция и контексты:** Использование `docker context` для переключения между окружениями (dev, stage, prod) без изменения логики пайплайна.

### Жизненный цикл и надежность

Для обеспечения Zero-downtime Deployment (развертывание без простоя) критически важны:

- **Rolling Updates:** Постепенная замена реплик старой версии на новую.
- **Health Checks:** Сигналы от приложения оркестратору о готовности принимать трафик.
- **Automated Rollback:** Автоматический возврат к предыдущей версии при сбое проверки здоровья новой реплики.

Подробное руководство — в **[Жизненный цикл приложения в Swarm](./app_lifecycle.md)**.

## Практические сценарии

### Сценарий 1: Организация защищенного канала (mTLS)

Настройка доверенного соединения между CI-системой и менеджером Swarm:

1. Создание внутреннего CA и выпуск клиентских сертификатов.
2. Настройка Docker Daemon на менеджере для работы по TLS.
3. Передача сертификатов в CI (GitLab Variables / GitHub Secrets).
4. Подробная инструкция в **[swarm_setup.md](./swarm_setup.md)**.

### Сценарий 2: Развертывание базовой инфраструктуры

Управление общими компонентами (Ingress, Monitoring, Registry Auth):

1. Выделение инфраструктуры в отдельный технологический стек.
2. Использование общих сетей (`overlay`, `external: true`) для связи прокси с приложениями.
3. Автоматизация деплоя через отдельный системный пайплайн.
4. Детали в **[infra_deployment.md](./infra_deployment.md)**.

### Сценарий 3: Пайплайн доставки (GitLab CI / GitHub Actions)

Типовые этапы (stages) доставки кода в кластер:

1. **Build:** Сборка образа (рекомендуется Kaniko для безопасности).
2. **Push:** Загрузка в Registry.
3. **Deploy:** Выполнение `docker stack deploy` через настроенный контекст.
4. **Verify:** Проверка статуса сервиса после деплоя.

Примеры конфигурации пайплайнов — в **[app_deployment.md](./app_deployment.md)**.

### Сценарий 4: Маршрутизация трафика через Traefik

Пример меток в `docker-compose.yml` для автоматической публикации сервиса:

```yaml
services:
  app:
    image: my-app:latest
    deploy:
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.app.rule=Host(`app.example.com`)"
        - "traefik.http.routers.app.entrypoints=websecure"
        - "traefik.http.routers.app.tls.certresolver=le"
        - "traefik.http.services.app.loadbalancer.server.port=8080"
```

Детальная настройка балансировщика — в **[Traefik в Swarm](../swarm_ingress_traefik.md)**.

## Дополнительная информация

### Сравнение с другими подходами

| Характеристика | Docker Swarm CI/CD | Kubernetes CI/CD |
|:---|:---|:---|
| Сложность настройки | Низкая (нативно в Docker) | Высокая (требует Helm/Kustomize) |
| Скорость внедрения | Высокая | Средняя |
| Безопасность | Хорошая (mTLS) | Отличная (RBAC, Network Policies) |
| Масштабируемость | До 1000 узлов | До 5000+ узлов |

### Рекомендации по эксплуатации

- **Версионирование:** Всегда используйте теги образов вместо `latest` для обеспечения повторяемости деплоя.
- **Registry Auth:** Используйте флаг `--with-registry-auth` в команде `docker stack deploy` для передачи учетных данных на все узлы кластера.
- **Секреты:** Не передавайте пароли через переменные окружения (`environment`), используйте **[Swarm Secrets](../swarm_secrets_configs.md)**.
- **Очистка:** Настройте `docker system prune` на узлах (через Cron или системный сервис) для удаления старых слоев образов.

### Связанные документы

- **[swarm_setup.md](./swarm_setup.md)** — подготовка кластера и TLS.
- **[infra_deployment.md](./infra_deployment.md)** — деплой системных сервисов.
- **[app_deployment.md](./app_deployment.md)** — шаблоны пайплайнов приложений.
- **[app_lifecycle.md](./app_lifecycle.md)** — стратегии обновления и Health Checks.
- **[best_practices.md](./best_practices.md)** — безопасность и оптимизация.
- **[../docker_swarm_overview.md](../docker_swarm_overview.md)** — общие сведения о Swarm.
- **[../swarm_secrets_configs.md](../swarm_secrets_configs.md)** — управление секретами.
- **[../swarm_ingress_traefik.md](../swarm_ingress_traefik.md)** — глубокая настройка Ingress.
