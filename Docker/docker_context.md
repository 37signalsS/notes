# Docker Context

## Определения

- **Docker Context:** Механизм Docker CLI для управления профилями подключения к различным окружениям (Docker Engine, Swarm, Kubernetes). Контекст инкапсулирует адрес хоста (Endpoint), сертификаты безопасности и метаданные в именованный профиль.
- **Endpoint:** Точка входа для взаимодействия с Docker API. Поддерживаются:
  - Локальный Unix-сокет (`unix:///var/run/docker.sock`).
  - Удаленный доступ через SSH (`ssh://user@host`).
  - Удаленный TCP-порт с TLS (`tcp://host:2376`).
- **Context Switching:** Мгновенное переключение активного профиля в CLI без изменения глобальных переменных окружения.

## Основные концепции

### Зачем нужен Docker Context?

1. **Удаленное управление:** Позволяет управлять контейнерами на сервере так же просто, как и локально.
2. **Безопасность (SSH):** Нативный проброс команд через SSH без необходимости открывать TCP-порты Docker-демона наружу.
3. **Управление несколькими рантаймами:** Удобное переключение между Docker Desktop, Colima, OrbStack или Rootless Docker.
4. **Абстракция для CI/CD:** Команды деплоя (`docker stack deploy`, `docker compose up`) остаются неизменными, меняется только активный контекст.

### Компоненты контекста

Контекст состоит из двух основных частей:
- **Метаданные:** Имя, описание, текущий стек (Docker/Kubernetes).
- **Конфигурация (Endpoints):** Параметры подключения к движку.

## Практические сценарии

### Сценарий 1: Удаленное управление через SSH (Рекомендуемый)

Самый безопасный и простой способ управления удаленным сервером. Не требует настройки TLS-сертификатов.

1. Убедитесь, что у вас есть SSH-доступ к серверу по ключу.
2. Создайте контекст:
   ```bash
   docker context create remote-vps --docker "host=ssh://user@server-ip"
   ```
3. Переключитесь на него:
   ```bash
   docker context use remote-vps
   ```
4. Проверьте подключение:
   ```bash
   docker info
   ```

### Сценарий 2: Локальные рантаймы (Colima/OrbStack)

При использовании альтернатив Docker Desktop (например, Colima на macOS), контексты позволяют быстро переключаться между ними:

```bash
# Список контекстов покажет, кто сейчас активен
docker context ls

# Переключение на Colima
docker context use colima

# Возврат на стандартный сокет
docker context use default
```

### Сценарий 3: Rootless Docker

Для работы с Docker в режиме без root-прав (Rootless) контекст помогает указать путь к пользовательскому сокету:

```bash
docker context create rootless --docker "host=unix:///run/user/1000/docker.sock"
docker context use rootless
```

### Сценарий 4: Удаленное управление через mTLS (Classic/CI-CD)

Используется в корпоративных средах или сложных CI/CD пайплайнах (см. подробнее в **[Docker Context для CI/CD](../Docker_swarm/CI_CD/docker_context_setup.md)**).

```bash
docker context create prod-swarm \
  --docker "host=tcp://manager:2376,ca=ca.pem,cert=cert.pem,key=key.pem"
```

## Справочник CLI

| Команда | Описание |
|:---|:---|
| `docker context ls` | Список всех контекстов (активный отмечен `*`) |
| `docker context show` | Показать имя текущего активного контекста |
| `docker context use <NAME>` | Переключить активный контекст |
| `docker context create <NAME> --docker "host=..."` | Создать новый контекст |
| `docker context update <NAME> --description "..."` | Обновить описание или параметры |
| `docker context inspect <NAME>` | Детальная JSON-информация о контексте |
| `docker context rm <NAME>` | Удалить контекст |

## Дополнительная информация

### Взаимодействие с переменными окружения

Переменная `DOCKER_HOST` имеет **приоритет** над активным контекстом.
- Если установлена `DOCKER_HOST`, Docker CLI будет использовать её, игнорируя настройки `docker context use`.
- Чтобы контексты работали корректно, убедитесь, что `DOCKER_HOST` пуста: `unset DOCKER_HOST`.

### Файловая структура

Метаданные контекстов хранятся в домашней директории пользователя:
- Linux/macOS: `~/.docker/contexts/`
- Windows: `%USERPROFILE%\.docker\contexts\`

### См. также
- **[Docker Context для CI/CD с Swarm](../Docker_swarm/CI_CD/docker_context_setup.md)** — глубокая настройка mTLS.
- **[Безопасность Docker-демона](./Docker_security/host_daemon_hardening.md)** — зачем использовать SSH вместо TCP.
