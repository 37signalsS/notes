# CI/CD в Docker Swarm: Лучшие практики и стандарты эксплуатации

## Определения

- **Лучшие практики (Best Practices):** Набор проверенных архитектурных и операционных паттернов, направленных на обеспечение безопасности, масштабируемости и отказоустойчивости систем.
- **Неизменяемая инфраструктура (Immutable Infrastructure):** Принцип, согласно которому серверы и контейнеры никогда не модифицируются после развертывания. Любое изменение требует сборки нового образа и замены старого инстанса.
- **[GitOps](../../GitOps/GitOps_overview.md):** Операционная модель, в которой Git является "единственным источником истины" (SSoT) для инфраструктуры и приложений. Изменения в кластере инициируются исключительно через Pull Requests.
- **[Принцип минимальных привилегий (POLP)](../../CI-CD/DevSecOps/secrets_management.md#1-принцип-минимальных-привилегий-least-privilege):** Стратегия безопасности, при которой субъекту (пайплайну, сервису) предоставляется только тот набор прав, который необходим для выполнения его функций.

## Базовые концепции

### Принципы построения надежных конвейерных конвейеров доставки

Для достижения уровня Senior DevOps в эксплуатации Swarm необходимо придерживаться следующих фундаментальных правил:

1. **Изоляция процесса сборки (Safe Build):**
   - Полный отказ от использования `privileged` режима на CI-раннерах.
   - Использование **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)** для сборки образов в userspace. Это предотвращает атаки типа "Container Escape" на инфраструктуру CI.
2. **Эшелонированная защита секретов:**
   - **Секреты деплоя:** Хранятся в GitLab Variables (тип File) с ограниченным доступом (Protected/Masked).
   - **Секреты выполнения:** Передаются в контейнеры только через нативный механизм **[Swarm Secrets](../swarm_secrets_configs.md)**. Приложения должны считывать их из `/run/secrets/`, а не из переменных окружения (чтобы избежать утечки в логи и `docker inspect`).
3. **Декларативное управление состоянием:**
   - Запрет на использование `docker service update` из терминала. Все изменения — только через `docker stack deploy`.
   - Инфраструктура самого кластера (ноды, сети) управляется через IaC инструменты (Ansible/Terraform).
4. **Атомарность и версионирование образов:**
   - Запрет тега `latest`. Использование уникальных тегов (`${CI_COMMIT_SHA}`) гарантирует, что на всех узлах запущена идентичная версия кода.
   - Использование Immutable Tags в реестре (например, в Harbor) для предотвращения перезаписи образов с тем же тегом.
5. **Наблюдаемость (Observability) как часть CD:**
   - Каждый деплой должен сопровождаться отправкой аннотации в Grafana.
   - Использование **[Prometheus/Grafana](../../Grafana/grafana-dashboards.md)** для контроля метрик после деплоя (Error Rate, Latency).

## Практические сценарии

### Сценарий 1: Управление версиями и динамические переменные

Использование фиксированных тегов гарантирует повторяемость деплоя и корректную работу Rollback.

```yaml
services:
  app:
    # Использование хеша коммита вместо latest
    image: ${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}
    # Передача динамических метаданных через метки
    deploy:
      labels:
        - "com.example.version=${CI_COMMIT_TAG:-latest}"
        - "com.example.build_url=${CI_PIPELINE_URL}"
```

### Сценарий 2: Управление ресурсами и планирование

Корректное указание ресурсов — залог выживаемости кластера при всплесках нагрузки.

```yaml
services:
  api:
    deploy:
      resources:
        # Резервирование: Swarm не запустит сервис, если нет этого объема ресурсов
        reservations:
          cpus: '0.25'
          memory: 256M
        # Лимиты: Жесткое ограничение. При превышении памяти — OOM Kill.
        limits:
          cpus: '1.0'
          memory: 1G
      placement:
        # Размещение БД только на узлах с SSD
        constraints:
          - node.labels.disk_type == ssd
```

### Сценарий 3: Безопасный деплой через Registry Auth и mTLS

Для того чтобы воркеры могли скачать образ из приватного реестра, команда деплоя должна включать флаг передачи токена авторизации.

```bash
# Использование Docker Context для переключения на удаленный кластер через mTLS
docker context use remote-swarm

# Деплой с обязательной передачей учетных данных воркерам
docker stack deploy -c docker-compose.yml my-app --with-registry-auth --prune
```
# → Результат: Менеджер шифрует учетные данные и безопасно передает их на целевые узлы.

### Сценарий 4: Настройка Rolling Updates и Health Checks

Обеспечение Zero Downtime (99.9% uptime) при обновлении требует правильной последовательности запуска и контроля здоровья.

```yaml
deploy:
  update_config:
    parallelism: 1
    delay: 15s
    # start-first: Сначала запуск новой реплики, затем стоп старой.
    # Обеспечивает отсутствие просадки по RPS во время деплоя.
    order: start-first
    failure_action: rollback
    monitor: 45s
healthcheck:
  # Проверка готовности приложения принимать трафик
  test: ["CMD", "wget", "-qO-", "http://localhost:8080/health"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 40s # Ожидание "прогрева" приложения до начала проверок
```

### Сценарий 5: Сетевая изоляция (Network Hardening)

Использование принципа "один стек — одна сеть" для минимизации радиуса поражения при взломе.

```yaml
networks:
  # Публичная сеть для Ingress (Traefik)
  public_net:
    external: true
  # Внутренняя сеть только для компонентов этого приложения
  backend_net:
    driver: overlay
    attachable: false # Запрет ручного подключения контейнеров
    internal: true    # Запрет выхода в интернет для этой сети
```

### Сценарий 6: Логирование и автоматизированная очистка (Garbage Collection)

Для предотвращения переполнения диска на всех узлах кластера (Managers + Workers) необходимо настроить регулярную очистку.

```bash
# Пример настройки ротации логов в daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}

# Команда для системного таймера (удаление старых образов и слоев)
docker image prune -a --force --filter "until=48h"
docker system prune --volumes --force
```

### Сценарий 7: Ротация секретов в CI/CD

Swarm Secrets не поддерживают версионирование "из коробки" — при обновлении секрета все сервисы получают новое значение только после перезапуска контейнеров. Рекомендуемый паттерн для автоматической ротации:

```bash
# 1. Обновление секрета в Swarm (создает новую версию)
echo "NEW_DB_PASSWORD" | docker secret create db_password_v2 - \
  && docker secret rm db_password_v1

# 2. Обновление сервиса для подхвата нового секрета
# (--force пересоздает контейнеры, которые подхватят свежий секрет)
docker service update --force --secret-rm db_password_v1 --secret-add db_password_v2 my_app

# 3. Проверка, что сервис использует новый секрет
docker service inspect --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}' my_app
```

**Интеграция с GitLab CI (автоматическая ротация):**

```yaml
rotate-secrets:
  stage: security
  script:
    - |
      NEW_PASS=$(openssl rand -base64 32)
      echo "$NEW_PASS" | docker secret create --template-name my_template db_password_${CI_COMMIT_SHA} -
      docker service update --force --secret-rm db_password --secret-add db_password_${CI_COMMIT_SHA} my_app
      docker secret rm db_password 2>/dev/null || true
  only:
    - schedules  # Запуск по расписанию (например, раз в 30 дней)
  when: manual  # Ручной триггер для безопасности
```

**Важно:** Никогда не удаляйте старый секрет trước успешного обновления сервиса. Сначала создайте новый, обновите сервис, затем удалите старый.

### Сценарий 8: Стратегия резервного к管理和 Stateful-сервисы

Docker Swarm не имеет встроенного бэкапа кластера (в отличие от Kubernetes etcd snapshot). Рекомендуемая стратегия:

```yaml
# Пример BackUp-задачи как сервиса
services:
  backup_postgres:
    image: alpine:3.19
    volumes:
      - pg_data:/source:ro
      - /mnt/nfs/backups:/backup
    entrypoint: >
      sh -c "tar czf /backup/pg_$(date +%Y%m%d_%H%M).tar.gz -C /source . &&
             find /backup -name 'pg_*.tar.gz' -mtime +7 -delete"
    deploy:
      placement:
        constraints:
          - node.labels.disk_type == ssd
      restart_policy:
        condition: none
```

**Чек-лист резервного копирования:**

- [ ] **Реестр образов (Harbor):** Настроена репликация на вторую ноду или объектное хранилище (S3/MinIO).
- [ ] **Swarm State:** Регулярный экспорт `docker service ls`, `docker node ls`, `docker network ls` в версионируемый Git-репозиторий.
- [ ] **Persistent Volumes:** Для каждой БД — отдельный BackUp-сервис с `schedule` (cron) и `rotation` (удаление старых артефактов).
- [ ] **Secrets:** Секреты не резервируются напрямую — их хранение организуется во внешнем Vault (HashiCorp Vault / AWS Secrets Manager), а не в Swarm.

### Сценарий 9: Мониторинг и алертинг (Observability Stack)

Минимально необходимый стек для продакшена в Swarm:

```yaml
# docker-compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus:v2.53.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    networks:
      - monitoring_net
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G

  grafana:
    image: grafana/grafana:11.1.0
    environment:
      - GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_admin
    secrets:
      - grafana_admin
    ports:
      - "3000:3000"
    networks:
      - monitoring_net

  node_exporter:
    image: prom/node-exporter:v1.8.1
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    networks:
      - monitoring_net

networks:
  monitoring_net:
    driver: overlay
    internal: true

secrets:
  grafana_admin:
    external: true
```

**Ключевые метрики для алертинга:**

| Метрика | Инструмент | Порог алерта |
|:---|:---|:---|
| Error Rate (5xx) | Prometheus + AlertManager | > 1% за 5 минут |
| P99 Latency | Grafana Dashboard | > 500ms за 5 минут |
| CPU/Memory Usage | node_exporter | > 85% за 10 минут |
| Disk Space | node_exporter | < 15% свободного |
| Container Restarts | cAdvisor / Docker API | > 3 перезапуска за 15 минут |
| Swarm Service Down | Prometheus (up metric) | == 0 реплик > 2 минуты |

## Дополнительная информация

### Итоговый чек-лист Senior DevOps

- [ ] **Безопасность:** Пайплайны используют mTLS (порт 2376) и Docker Context.
- [ ] **Сборка:** Используется Kaniko или BuildKit в режиме без привилегий.
- [ ] **Ресурсы:** У всех сервисов заданы `limits` и `reservations`.
- [ ] **Доступность:** Настроены Health Checks и стратегия `order: start-first`.
- [ ] **Секреты:** Приложение считывает данные из `/run/secrets/`.
- [ ] **Сеть:** Используются изолированные `overlay` сети с `internal: true` там, где это возможно.
- [ ] **Логи:** Настроена ротация логов (драйвер `json-file` с лимитами или `loki`).
- [ ] **Очистка:** Настроены системные таймеры на удаление старых образов.

### Типовые ошибки и антипаттерны

| Антипаттерн | Последствие | Правильное решение |
|:---|:---|:---|
| Использование `latest` | Непредсказуемый результат при перезапуске | Тегирование по `${CI_COMMIT_SHA}`. |
| Монтирование `docker.sock` в раннер | Полный root-доступ к хосту раннера | Использование Kaniko. |
| Отсутствие Health Checks | Трафик идет на не готовый контейнер (502/504) | Настройка `healthcheck` и `start_period`. |
| Секреты в переменных окружения | Утечка паролей в логи и метаданные | Использование Swarm Secrets. |
| Деплой без `--with-registry-auth` | Workers не могут скачать образ | Всегда добавлять флаг в `stack deploy`. |
| `docker service update` из терминала | Конфликт с декларативным состоянием в Git | Только `docker stack deploy` через CI/CD. |
| `stop-first` на stateless-сервисах | Долгое обновление, простой в обслуживании | `start-first` + `order: start-first` для Zero Downtime. |
| Нет ограничений ресурсов (`limits`) | OOM Kill.random узлов, нестабильность кластера | Всегда задавать `reservations` и `limits`. |
| Использование Docker Content Trust на dev | Задержка сборки из-за подписи образов | Отключать DCT на dev/staging, включать только на prod. |
| Нет мониторинга после деплоя | Незаметные регрессии (рост latency, ошибок) | Обязательный аннотинг в Grafana + алертинг. |

### Связанные документы

- **[Жизненный цикл приложения](./app_lifecycle.md)** — стратегии обновления и Health Checks.
- **[Деплой через GitLab CI](./app_deployment.md)** — реализация пайплайнов.
- **[Управление секретами](../swarm_secrets_configs.md)** — ротация и хранение секретов.
