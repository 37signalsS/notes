# Настройка лог-драйвера Grafana Loki для Docker

## Определения

**Драйвер логирования Loki (Loki Docker Driver)** — это плагин для Docker Engine, разработанный Grafana Labs. Он позволяет отправлять логи напрямую из контейнеров в [Grafana Loki](../../Loki/loki_overview.md), минуя необходимость развертывания промежуточных агентов (например, Alloy или Promtail) на каждом хосте.

## Базовые концепции

### Архитектура и механизм работы

Данное решение реализует модель прямой отправки логов (Push-модель) на уровне рантайма контейнеров.

**Схема потока данных:**
`Приложение → STDOUT/STDERR → Docker Engine → loki-docker-driver → HTTP/HTTPS → Loki`

**Ключевые особенности:**
*   **Простота внедрения**: Не требует управления жизненным циклом дополнительных контейнеров-агентов.
*   **Поддержка Dual Logging**: В отличие от драйверов `syslog` или `gelf` (в старых версиях), Loki-драйвер поддерживает чтение логов через стандартную команду `docker logs` при сохранении локальной копии (механизм Dual Logging).
*   **Режимы работы**:
    *   **Blocking (по умолчанию)**: Гарантирует доставку, но при недоступности Loki или сетевых проблемах приложение может "зависнуть" при попытке записи в лог.
    *   **Non-blocking**: Рекомендуется для production. Логи буферизируются в памяти; при переполнении буфера старые записи отбрасываются, обеспечивая стабильность приложения.

## Практические сценарии

### Шаг 1: Установка плагина

Плагин устанавливается как расширение Docker Engine на каждом хосте.

```bash
# Установка плагина с псевдонимом 'loki'
docker plugin install grafana/loki-docker-driver:3.1.1 --alias loki --grant-all-permissions
```
*   `grafana/loki-docker-driver:3.1.1`: Рекомендуется использовать фиксированную версию (на август 2026 года актуальна ветка 3.x).
*   `--alias loki`: Позволяет обращаться к драйверу по короткому имени в конфигурациях.

**Проверка статуса:**
```bash
docker plugin ls
# → ID            NAME          DESCRIPTION           ENABLED
# → <id>          loki:latest   Loki Logging Driver   true
```

### Шаг 2: Глобальная конфигурация (`daemon.json`)

Обеспечивает автоматическую отправку логов всех новых контейнеров в централизованную систему.

**Файл `/etc/docker/daemon.json`:**
```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki.example.com:3100/loki/api/v1/push",
    "loki-batch-size": "400",
    "loki-retries": "3",
    "loki-max-backoff": "5s",
    "mode": "non-blocking",
    "max-buffer-size": "10m",
    "loki-external-labels": "env=prod,cluster=main"
  }
}
```
*   **Безопасность**: Если Loki требует аутентификации, используйте формат `http://user:password@loki.example.com:3100/...`.

**Применение настроек:**
```bash
sudo systemctl reload docker
# Внимание: настройки применятся только к новым контейнерам.
```

### Шаг 3: Настройка через Docker Compose

Позволяет гибко управлять метками и параметрами для конкретных сервисов.

```yaml
services:
  web-app:
    image: nginx:1.27
    logging:
      driver: "loki"
      options:
        loki-url: "https://loki.example.com/loki/api/v1/push"
        loki-external-labels: "project=ecommerce,service={{.Name}}"
        loki-retries: "5"
        mode: "non-blocking"
        loki-tls-ca-path: "/etc/docker/certs/ca.crt"
```

**Ключевые параметры `log-opts`:**
| Параметр | Описание |
| :--- | :--- |
| `loki-url` | Эндпоинт Loki. Обязателен. |
| `loki-external-labels` | Пользовательские метки. Поддерживают шаблоны Go (`{{.Name}}`, `{{.ImageName}}`). |
| `loki-batch-size` | Размер пакета в байтах перед отправкой (дефолт: 400). |
| `loki-timeout` | Таймаут HTTP-запроса (дефолт: 10s). |
| `loki-tls-ca-path` | Путь к CA сертификату для HTTPS. |

### Шаг 4: Проверка и чтение логов

**1. Проверка в Grafana Explore:**
*   Выберите источник данных **Loki**.
*   Запрос: `{container_name="web-app"}` или `{project="ecommerce"}`.

**2. Использование CLI:**
Благодаря Dual Logging, локальный доступ сохраняется:
```bash
docker logs -f web-app
```

## Дополнительная информация

### Диагностика и решение проблем

**1. Плагин не запускается:**
Проверьте детальный статус:
```bash
docker plugin inspect loki
```

**2. Ошибка "Entry too far behind":**
Возникает, если часы на Docker-хосте и сервере Loki рассинхронизированы.
*   **Решение**: Настройте NTP (Chrony/systemd-timesyncd) на всех узлах.

**3. Логи не доходят до Loki:**
Проверьте системный лог демона Docker:
```bash
journalctl -u docker | grep loki
```
Частые причины: неверный URL, ошибки аутентификации или блокировка порта 3100 файрволом.

### Сравнение с агентным подходом

| Критерий | Loki Docker Driver | Alloy / Promtail (Агент) |
| :--- | :--- | :--- |
| **Сложность** | Низкая (один плагин). | Средняя (нужен конфиг агента). |
| **Производительность** | Высокая (нет лишнего копирования). | Средняя (чтение файлов с диска). |
| **Гибкость (Pipelines)** | Минимальная. | Максимальная (парсинг JSON, маскирование). |
| **Надежность** | Зависит от Docker Engine. | Высокая (буферизация на диске). |

**Рекомендация:** Используйте драйвер для простых инфраструктур и быстрой отладки. Для сложных enterprise-решений с необходимостью глубокой обработки логов (парсинг логов приложений) переходите на [агентный сбор](./docker_agent_based_logging.md).

### Ссылки на смежные темы
*   **[Обзор системы логирования в Docker](./docker_logging_drivers_overview.md)**
*   **[Grafana Loki: обзор системы](../../Loki/loki_overview.md)**
*   **[Настройка Loki Stack через Docker Compose](../../Loki/Docker_Compose/loki_docker_compose_setup.md)**
