# Autoheal в Docker: Автоматическое восстановление контейнеров

> **Reliability Score: 10** (SSoT + Verified Tooling + Best Practices)

## Определения

**Autoheal** — механизм или специализированный инструмент (например, `willfarrell/autoheal`), который отслеживает состояние контейнеров на основе их **Healthcheck** и автоматически перезапускает те, что перешли в статус `unhealthy`.

**Self-Healing (Самовосстановление)** — архитектурный паттерн, при котором система способна самостоятельно обнаруживать и исправлять ошибки выполнения без вмешательства администратора.

> **Важно:** Autoheal дополняет стандартную политику `restart`, решая проблему «зависших» приложений, которые продолжают работать (status `running`), но не выполняют свои функции (status `unhealthy`).

## Основные концепции

### Связка механизмов восстановления

Для полной защиты контейнера необходимо комбинировать три уровня настроек:

1.  **Restart Policy (`restart`):** Docker Engine перезапускает контейнер, если основной процесс завершился (статус `exited`).
2.  **Healthcheck:** Инструкция, позволяющая Docker Engine понять, что приложение внутри контейнера работоспособно.
3.  **Autoheal:** Внешний монитор (или встроенный в оркестратор механизм), который инициирует `docker restart`, если Healthcheck провален.

### Инструмент willfarrell/autoheal

Это легковесный контейнер, который подключается к `/var/run/docker.sock` хоста и следит за событиями контейнеров.

**Принцип работы:**
* Сканирует контейнеры с определенной меткой (label).
* Проверяет статус здоровья через Docker API.
* При обнаружении `unhealthy` выполняет команду рестарта.

## Практические сценарии

### Сценарий 1: Настройка в одном Docker Compose файле

Пример конфигурации приложения и службы autoheal.

```yaml
services:
  app:
    image: your-app:latest
    restart: unless-stopped
    labels:
      - "autoheal=true" # Разрешаем autoheal следить за этим контейнером
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  autoheal:
    image: willfarrell/autoheal:latest
    restart: always
    network_mode: none
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock # Критически важно для доступа к API
    environment:
      - AUTOHEAL_CONTAINER_LABEL=autoheal   # Искать контейнеры с этой меткой
      - AUTOHEAL_INTERVAL=5                 # Частота проверки в секундах
      - AUTOHEAL_DEFAULT_STOP_TIMEOUT=10    # Таймаут остановки перед рестартом
```

### Сценарий 2: Глобальный запуск Autoheal

Вы можете запустить Autoheal один раз на хосте, чтобы он следил за всеми контейнерами, имеющими метку `autoheal=true`.

```bash
docker run -d \
  --name autoheal \
  --restart=always \
  -e AUTOHEAL_CONTAINER_LABEL=autoheal \
  -v /var/run/docker.sock:/var/run/docker.sock \
  willfarrell/autoheal
```

### Сценарий 3: Тестирование и верификация

Чтобы убедиться, что система работает, создайте контейнер, который гарантированно провалит проверку здоровья:

```bash
docker run -d \
  --name test-autoheal \
  --label autoheal=true \
  --restart=always \
  --health-cmd="exit 1" \
  --health-interval=5s \
  --health-retries=2 \
  alpine sleep 3600
```

**Ожидаемый результат в логах autoheal:**
`Container /test-autoheal (d83a57590993) found to be unhealthy - Restarting container now`

## Дополнительная информация

### Золотое правило настройки
Для надежного самовосстановления всегда используйте триаду:
**`healthcheck`** + **`label: autoheal=true`** + **`restart: unless-stopped`**

### Нюансы использования
* **Логи:** Autoheal пишет в Stdout только информацию о произведенных перезапусках. Если логов нет — значит, всё работает штатно.
* **Безопасность:** Монтирование `/var/run/docker.sock` дает контейнеру полные права на управление Docker на хосте. Используйте только проверенные образы autoheal.
* **Оркестрация:** В **Docker Swarm** и **Kubernetes** функционал autoheal встроен нативно (задачи автоматически перезапускаются при провале проб), поэтому внешние инструменты вроде `willfarrell/autoheal` там не требуются.

### См. также
* **[Инструкции HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)** — как правильно писать проверки.
* **[Политики перезапуска](../docker_commands.md#политики-перезапуска---restart)** — разница между `always` и `unless-stopped`.
* **[Диагностика через Docker Events](./debugging_with_docker_events.md)** — отслеживание событий рестарта.
