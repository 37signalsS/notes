# Миграция Docker Compose стека между VPS без простоя

**Актуально для:** Docker Compose v5+ (Compose Specification)

## Определения

- **Бесшовная миграция (Zero-Downtime Migration)** — перенос работающей инфраструктуры с одного сервера на другой с сохранением доступности сервиса для пользователей (отсутствие 5xx ошибок в логах).
- **Proxy Bridge** — временная конфигурация реверс-прокси на исходном (Source) сервере, перенаправляющая трафик на целевой (Target) сервер до полного обновления DNS-кэшей у клиентов.
- **Graceful Shutdown (Плавное завершение)** — процесс остановки приложения, при котором оно перестает принимать новые запросы, но завершает обработку уже принятых в течение заданного лимита времени.
- **Source (Исходный сервер)** — VPS, на котором в данный момент работает продакшен-стек перед началом миграции.
- **Target (Целевой сервер)** — новый VPS, на который переносится стек после завершения подготовки.
- **Rollback (Откат)** — процесс возврата к предыдущему стабильному состоянию при возникновении критических ошибок после переключения трафика.
- **Stateful-сервис** — сервис с persistent-состоянием (базы данных, очереди, хранилища), требующий специальной стратегии переноса данных.
- **Stateless-сервис** — сервис без persistent-состояния (веб-приложения, API, прокси), который можно перенести независимо от данных.

## Архитектура и принципы работы

### Жизненный цикл миграции

Миграция состоит из последовательных фаз, каждая из которых имеет четкие критерии перехода:

1. **Подготовка (Provisioning):** Развертывание Target VPS, установка Docker Engine, базовое усиление безопасности, настройка firewall.
2. **Развертывание стека (Stack Deployment):** Запуск Compose-стеков на обоих серверах. На Source остается production-стек, на Target разворачивается новая копия.
3. **Установление защищенного канала (Secure Channel):** Настройка VPN-туннеля (WireGuard) между серверами для безопасного доступа к базе данных на Source.
4. **Синхронизация данных (Data Sync):** Настройка репликации или создание дампа базы данных на Source с последующей загрузкой на Target.
5. **Валидация (Validation):** Проверка готовности Target-стеков через healthcheck и smoke-тесты.
6. **Переключение трафика (Traffic Cutover):** Обновление конфигурации Nginx на Source для проксирования на Target. Обновление DNS A-записи.
7. **Стабилизация (Stabilization):** Мониторинг метрик на обоих серверах, ожидание полного обновления DNS-кэшей.
8. **Завершение (Cutover Finalization):** Перенос stateful-сервисов на Target, отключение Proxy Bridge.
9. **Деактивация Source (Decommissioning):** После периода наблюдения Source VPS выводится из эксплуатации.

### Компоненты архитектуры

```
[Клиенты] → [DNS] → [Source VPS: Nginx Proxy Bridge] → [Target VPS: Compose Stack]
                                                    ↓
                                              [Source VPS: Database]
                                                    ↑
                                              [WireGuard Tunnel]
```

### Ключевые принципы

- **Разделение stateless и stateful:** Перенос кода выполняется до переноса данных. Это минимизирует окно простоя.
- **Защищенный канал:** Прямой доступ к базе данных между VPS должен осуществляться только через зашифрованный туннель (WireGuard), а не через публичный интерфейс.
- **Идемпотентность:** Все скрипты и команды должны быть безопасными для повторного выполнения.
- **Наблюдаемость:** Каждая фаза должна иметь четкие метрики для принятия решения о переходе к следующей фазе.

## Базовые концепции

### Разделение Stateless и Stateful

Главное правило бесшовного переезда: **stateful-сервисы (базы данных, очереди, хранилища) не переезжают одновременно с приложением.**

1. На первом этапе переносится только код приложения и статические файлы (stateless).
2. Новое приложение подключается к базе данных, остающейся на старом сервере, через защищенный канал.
3. Перенос данных (stateful) выполняется как отдельный, последующий этап после стабилизации приложения на новом хосте.

### Механизм «Прокси-моста» (Proxy Bridge)

Вместо того чтобы полагаться на мгновенное обновление DNS (которое может занимать от нескольких минут до 48 часов), трафик перехватывается на сетевом уровне:

1. Nginx на старом сервере перенастраивается как прокси, транслирующий запросы на публичный IP нового сервера.
2. В панели DNS меняется A-запись.
3. Старый сервер остается активным в роли прокси для «хвоста» клиентов с закэшированными старыми IP до истечения TTL.

### Роль Healthchecks и Readiness

В Docker Compose нет нативного Readiness Probe, но имитация этого механизма критична:

- Контейнеры на Target-сервере должны иметь статус `healthy` до начала переключения трафика.
- Nginx на Source-сервере должен использовать `max_fails` и `fail_timeout`, чтобы не отправлять трафик на «упавший» Target.
- Команда `docker compose up --wait` (доступна с Compose v2.2.0) гарантирует, что все сервисы достигли состояния `running|healthy` до возврата управления.

### Наблюдаемость (Observability)

В момент переключения необходимо мониторить:

- **HTTP 5xx ошибки** на Source и Target серверах.
- **Latency (задержку)**: проксирование между VPS добавляет задержку, зависящую от RTT между дата-центрами.
- **Количество активных соединений** на старом сервере (цель — дождаться нуля перед выключением).
- **Состояние healthcheck:** `docker compose ps` на Target для проверки статуса `healthy`.
- **Потребление ресурсов:** `docker compose stats` для мониторинга CPU и памяти во время стабилизации.

### Стратегии переноса базы данных

Выбор стратегии зависит от объема данных и допустимого времени простоя:

- **Репликация (Replication):** Настройка Target как Slave, дождаться синхронизации, перевести приложение в Read-only, переключить Master на Target. Минимальное downtime, но сложность настройки.
- **Логический дамп (Logical Dump):** `pg_dump | pg_restore` для средних объемов. Требует остановки приложения на несколько минут.
- **Физическое копирование (Physical Copy):** Копирование data directory с остановкой PostgreSQL. Минимальное downtime для небольших баз.

## Практические сценарии

### Сценарий: Пошаговый переезд Docker Compose стека

#### 1. Подготовка (Target VPS)

Развернуть новую VPS, выполнить базовую настройку безопасности и установить Docker.

- **Системная подготовка:**
  ```bash
  # Обновление пакетов
  apt update && apt upgrade -y
  
  # Установка Docker
  curl -fsSL https://get.docker.com | sh
  
  # Установка Docker Compose plugin
  apt install docker-compose-plugin -y
  
  # Настройка firewall
  ufw allow ssh
  ufw allow http
  ufw allow https
  ufw enable
  ```

- **Развертывание Compose стека.** В `compose.yml` обязательно добавьте проверку здоровья:
  ```yaml
  services:
    web:
      image: my-app:latest
      healthcheck:
        test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
        interval: 10s
        timeout: 5s
        retries: 3
        start_period: 30s
      stop_grace_period: 60s # Увеличиваем время на доработку запросов
  ```

- **Проверка готовности:**
  ```bash
  docker compose up -d --wait --remove-orphans
  docker compose ps
  # → все сервисы должны быть healthy
  ```

#### 2. Организация защищенного канала (VPN)

Чтобы новое приложение безопасно работало со «старой» базой, используется WireGuard.

**Установка WireGuard на обоих серверах:**
```bash
apt install wireguard -y
```

**Конфиг Source (/etc/wireguard/wg0.conf):**
```ini
[Interface]
PrivateKey = <SOURCE_PRIVATE_KEY>
Address = 10.0.0.1/24
ListenPort = 51820

[Peer]
PublicKey = <TARGET_PUBLIC_KEY>
AllowedIPs = 10.0.0.2/32
```

**Конфиг Target (/etc/wireguard/wg0.conf):**
```ini
[Interface]
PrivateKey = <TARGET_PRIVATE_KEY>
Address = 10.0.0.2/24
ListenPort = 51820

[Peer]
PublicKey = <SOURCE_PUBLIC_KEY>
AllowedIPs = 10.0.0.1/32
```

**Активация туннеля:**
```bash
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# Проверка соединения
ping 10.0.0.2
```

На Source-сервере база данных должна слушать `10.0.0.1`.

#### 3. Переключение трафика через Proxy Bridge

На Source-сервере обновить конфиг Nginx:
```nginx
upstream target_vps {
    server <TARGET_PUBLIC_IP>:443 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name example.com;

    location / {
        proxy_pass https://target_vps;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # Увеличиваем таймауты для межсерверного взаимодействия
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
    }
}
```

После `nginx -s reload` трафик уходит на новый сервер. Затем обновите A-запись в DNS.

#### 4. Стратегия отката (Rollback)

Если после переключения обнаружены критические ошибки:

1. Немедленно верните старую конфигурацию Nginx на Source-сервере.
2. Проверьте логи Target-сервера.
3. DNS менять не нужно (он все еще может указывать на старый IP).

#### 5. Перенос базы данных (Stateful)

Выполняется после стабилизации трафика на Target:

- **Метод репликации:** Настроить Target как Slave, дождаться синхронизации, перевести приложение в Read-only, переключить Master на Target, обновить конфиги приложения.
- **Метод окна:** Если БД мала, остановить приложение на 1-2 минуты, сделать `pg_dump | pg_restore`, запустить приложение.

### Сценарий 2: Миграция с использованием Docker Compose profiles для отката

Использование profiles для быстрого переключения между старым и новым стеком без изменения DNS.

**compose.yml:**
```yaml
name: production-stack

services:
  proxy:
    image: nginx:1.30-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - frontend_net
    deploy:
      resources:
        limits:
          memory: 256M

  app:
    image: my-app:1.0.0
    networks:
      - frontend_net
      - backend_net
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 512M

networks:
  frontend_net:
  backend_net:
    internal: true
```

**compose.source.yml (старый сервер):**
```yaml
services:
  app:
    image: my-app:0.9.0
```

**compose.target.yml (новый сервер):**
```yaml
services:
  app:
    image: my-app:1.0.0
    deploy:
      replicas: 2
```

**Переключение:**
```bash
# Source сервер
docker compose -f compose.yml -f compose.source.yml up -d --wait

# Target сервер
docker compose -f compose.yml -f compose.target.yml up -d --wait

# После валидации
# На Source сервере: переключить nginx.conf на проксирование к Target
# На Target сервере: сделать приложение основным
```

### Сценарий 3: Автоматизированная валидация перед переключением

Перед любым переключением трафика необходимо убедиться в готовности Target-стеков.

**Smoke-test скрипт (`smoke_test.sh`):**
```bash
#!/bin/bash
set -e

TARGET_IP="<TARGET_PUBLIC_IP>"
HEALTH_ENDPOINT="https://${TARGET_IP}/health"

# Ожидание готовности healthcheck
echo "Waiting for services to become healthy..."
docker compose --wait --wait-timeout 120 ps

# Smoke-test: проверка HTTP endpoint
echo "Running smoke tests..."
for i in {1..10}; do
  if curl -sf "${HEALTH_ENDPOINT}" > /dev/null; then
    echo "Smoke test passed"
    exit 0
  fi
  sleep 5
done

echo "Smoke test failed"
exit 1
```

**Запуск:**
```bash
chmod +x smoke_test.sh
./smoke_test.sh
```

### Сценарий 4: Перенос базы данных с минимальным downtime

Стратегия для баз данных PostgreSQL до 50 GB.

**Подготовка на Target:**
```bash
# Создание базового дампа на Source
ssh source-vps "pg_dump -U postgres app_db" > /tmp/base_dump.sql

# Загрузка дампа на Target
scp /tmp/base_dump.sql target-vps:/tmp/

# Восстановление на Target
ssh target-vps "psql -U postgres app_db < /tmp/base_dump.sql"
```

**Настройка репликации для синхронизации изменений:**
```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_DB=app_db
    volumes:
      - postgres_data:/var/lib/postgresql/data
    command: >
      postgres -c
      wal_level=replica
      -c max_wal_senders=10
      -c max_replication_slots=10
    networks:
      - backend_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:

networks:
  backend_net:
    internal: true
```

**Процедура переключения:**
```bash
# 1. Перевод приложения в read-only режим
docker compose exec app /bin/sh -c "export READ_ONLY=true && kill -HUP 1"

# 2. Ожидание завершения активных транзакций
sleep 10

# 3. Финальная синхронизация
pg_dump -U postgres --data-only --inserts app_db > /tmp/final_delta.sql
scp /tmp/final_delta.sql target-vps:/tmp/
ssh target-vps "psql -U postgres app_db < /tmp/final_delta.sql"

# 4. Обновление конфигурации приложения на подключение к Target
# 5. Переключение трафика
```

## Операции и команды

### Команды Docker Compose для миграции

| Команда | Описание | Использование в миграции |
| :--- | :--- | :--- |
| `docker compose config` | Вывод итоговой конфигурации | Валидация перед развертыванием на Target |
| `docker compose up -d --wait` | Запуск с ожиданием healthcheck | Запуск на Target с проверкой готовности |
| `docker compose ps` | Статус сервисов | Проверка статуса `healthy` на Target |
| `docker compose logs --tail 100 <service>` | Логи сервиса | Диагностика проблем на Target |
| `docker compose down -v` | Остановка и удаление томов | Полная очистка при откате |
| `docker compose up --dry-run` | Валидация без запуска | Проверка конфигурации перед переключением |
| `docker compose stop --timeout 60` | Плавная остановка | Остановка приложения для финального дампа |
| `docker compose exec <service> <cmd>` | Выполнение команды в контейнере | Smoke-тесты и диагностика |

### Скрипт проверки готовности Target

```bash
#!/bin/bash
# validate_target.sh — проверка готовности Target VPS к переключению трафика

TARGET_IP="<TARGET_PUBLIC_IP>"
PROJECT_NAME="production-stack"

# 1. Проверка доступности портов
echo "Checking ports..."
for port in 80 443; do
  if ! ssh target-vps "nc -z localhost ${port}"; then
    echo "Port ${port} not ready on Target"
    exit 1
  fi
done

# 2. Проверка healthcheck всех сервисов
echo "Checking healthcheck..."
ssh target-vps "cd /opt/${PROJECT_NAME} && docker compose --wait --wait-timeout 120 ps"

# 3. Smoke-test HTTP endpoints
echo "Running smoke tests..."
for i in {1..5}; do
  if curl -sf "https://${TARGET_IP}/health" > /dev/null; then
    echo "Target is ready"
    exit 0
  fi
  sleep 5
done

echo "Target validation failed"
exit 1
```

## Устранение неполадок

### Типичные ошибки миграции

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`connection refused`** к базе данных через VPN | База данных не слушает на VPN-интерфейсе | Проверьте `listen_addresses` в `postgresql.conf` |
| **`timeout exceeded`** при `--wait` | Сервис не переходит в `healthy` | Увеличьте `--wait-timeout` или проверьте `healthcheck` |
| **`5xx ошибки`** после переключения | Target не готов или конфигурация неверна | Откатите Nginx, проверьте логи Target |
| **`SSL certificate error`** при проксировании | Отсутствуют или неверны TLS-сертификаты | Скопируйте сертификаты на Target и проверьте пути |
| **DNS не обновляется** | TTL закэширован у клиента | Уменьшите TTL за 24 часа до миграции (рекомендуется 300 сек) |
| **`ОК` на старом сервере, но `502` на новом** | Порт не暴露 или сервис не слушает на `0.0.0.0` | Проверьте `ports` в Compose и firewall на Target |
| **Высокая latency** при проксировании | RTT между VPS слишком велик | Рассмотрите размещение VPS в одном дата-центре |
| **Потеря данных при переносе БД** | Неполный дамп или отсутствие репликации | Проверьте целостность дампа и логи replication |

### Диагностический процесс

При возникновении проблем с миграцией:

1. **Проверить статус сервисов на Target:** `docker compose ps` — найти сервисы не в состоянии `healthy`.
2. **Изучить логи проблемного сервиса:** `docker compose logs <service> --tail 100` — искать `ERROR`, `failed`, `connection refused`.
3. **Проверить сетевую связность:** `ping <target-ip>`, `curl -v https://<target-ip>/health`.
4. **Проверить VPN-туннель:** `wg show`, `ping 10.0.0.2` — убедиться, что WireGuard активен.
5. **Проверить firewall:** `ufw status`, `iptables -L -n` — убедиться, что порты открыты.
6. **Инспектировать контейнер:** `docker inspect <container>` — проверить `Mounts`, `Config`, `HostConfig`.

## Рекомендации

### Безопасность

- **Никогда не хардкодите секреты:** Используйте `secrets:` с файлами, исключенными из Git.
- **Шифруйте канал между VPS:** WireGuard обеспечивает шифрование трафика между серверами.
- **Ограничьте доступ к базе данных:** На Source-сервере настройте `pg_hba.conf` для принятия соединений только с VPN-IP Target.
- **Обновите TLS-сертификаты:** Скопируйте актуальные сертификаты на Target до переключения трафика.
- **Firewall по умолчанию deny:** Разрешайте только необходимые порты (22, 80, 443).

### Надежность

- **Уменьшите DNS TTL:** За 24 часа до миграции установите TTL A-записи на 300 секунд для ускорения распространения изменений.
- **Всегда имейте план отката:** Перед переключением убедитесь, что можно вернуть Nginx к исходной конфигурации за 30 секунд.
- **Тестируйте на staging:** Повторите всю процедуру на тестовом окружении перед production-миграцией.
- **Мониторьте в реальном времени:** Используйте `docker compose logs --follow` во время переключения.
- **Используйте `stop_grace_period`:** Увеличьте время graceful shutdown для баз данных до 60 секунд.

### Производительность

- **Размещайте VPS в одном дата-центре:** Минимизирует RTT и снижает latency при проксировании.
- **Используйте именованные тома для данных:** Bind mounts уязвимы к правам доступа; именованные тома управляются Docker.
- **Настройка `keepalive` в Nginx:** Для межсерверного проксирования установите `keepalive 32` для переиспользования соединений.
- **tmpfs для временных данных:** Снижает I/O на диск для сервисов с интенсивной записью.
- **Используйте `--build` с кэшированием:** При пересборке образов на Target используйте BuildKit для ускорения.

### Поддержка и эксплуатация

- **Версионируйте `compose.yml`:** Храните в Git с четкими коммитами для каждой фазы миграции.
- **Документируйте процедуру:** Создайте runbook с командами и критериями перехода между фазами.
- **Регулярно тестируйте откат:** Убедитесь, что `docker compose down` и повторный `up` восстанавливают работоспособность.
- **Соблюдайте окно обслуживания:** Для финального переноса базы данных выберите время минимальной нагрузки.
- **Архивируйте дампы:** Храните дампы базы данных минимум 7 дней после миграции для возможности восстановления.

## Дополнительная информация

### Связанные документы

- **[Обзор Docker Compose](./docker_compose_overview.md)** — архитектура и ключевые возможности.
- **[Продвинутые возможности](./docker_compose_advanced_topics.md)** — интерполяция переменных, профили, `include`.
- **[Compose extends, include и правила слияния](./docker_compose_extends_include.md)** — модульность и приоритеты.
- **[Тестирование в CI/CD](./docker_compose_ci_cd_testing.md)** — детерминированные окружения для пайплайнов.
- **[Graceful Shutdown в Docker](../Dockerfile/Docker_best_practices/container_execution.md)** — глубокий разбор сигналов TERM и KILL.
- **[Миграция PostgreSQL без простоя](../../Databases/PostgreSQL/Operations/zero_downtime_migration.md)** — детальные шаги по репликации и свитч-оверу.
- **[Blue-Green Deployment](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)** — концептуальная база стратегий развертывания.
- **[Настройка WireGuard](../../Vpn/wireguard.md)** — полное руководство по установке и отладке туннеля.
- **[Стратегии миграции БД](../../Databases/Concepts/migrations/scenarios.md)** — выбор между логической и физической миграцией.

### Источники

- Официальная документация: [Docker Compose File Reference](https://docs.docker.com/reference/compose-file/)
- Исходный код: [docker/compose](https://github.com/docker/compose)
