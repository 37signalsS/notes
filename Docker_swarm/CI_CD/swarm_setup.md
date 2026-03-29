# CI/CD с Docker Swarm: Настройка кластера

## Определения

- **Docker Swarm Mode** — режим оркестрации Docker Engine для создания и управления кластером из нескольких хостов. Инициализируется командой `docker swarm init`.
- **mTLS (mutual TLS)** — протокол безопасной связи, при котором клиент и сервер взаимно аутентифицируют друг друга с помощью сертификатов. В контексте CI/CD обеспечивает защищенное соединение между GitLab Runner и Docker Daemon.
- **Docker Context** — механизм Docker для управления несколькими удаленными окружениями. Позволяет переключаться между локальным и удаленными кластерами без указания хоста и сертификатов в каждой команде.
- **Join Token** — криптографический токен для безопасного присоединения новых узлов к кластеру. Существуют отдельные токены для рабочих узлов и менеджеров. Подробнее в **[swarm_advanced_topics.md](../swarm_advanced_topics.md)**.

## Базовые концепции

### Архитектура безопасного доступа

Для CI/CD с Docker Swarm требуется удаленное управление кластером из GitLab Runner. Прямая установка Runner на узлы Swarm не рекомендуется по следующим причинам:

- **Безопасность:** Изоляция CI/CD от инфраструктуры кластера
- **Гибкость:** Возможность управления несколькими кластерами из одного пайплайна
- **Масштабируемость:** Независимое масштабирование CI/CD и Swarm

**Принцип работы:**
1. Docker Daemon настраивается для приема TLS-соединений по TCP (порт 2376)
2. Генерируются сертификаты для взаимной аутентификации (mTLS)
3. GitLab Runner использует сертификаты для подключения к Docker API
4. Docker Context упрощает управление подключением

### Компоненты инфраструктуры

| Компонент | Назначение | Порт |
|---|---|---|
| Docker Daemon | Прием API-запросов от GitLab Runner | 2376 (TLS) |
| CA Certificate | Проверка подлинности сервера и клиента | — |
| Server Certificate | Аутентификация Docker Daemon | — |
| Client Certificate | Аутентификация GitLab Runner | — |
| Docker Context | Профиль подключения (хост + сертификаты) | — |

### Требования к кластеру

- **Менеджеры:** Нечетное количество (3 или 5) для обеспечения кворума
- **Сеть:** Статический IP-адрес для менеджера (или VIP для HA)
- **Firewall:** Открытый порт 2376 для TLS-соединений
- **Хранение:** Защищенное хранилище для сертификатов (`/etc/docker/certs`)

## Практические сценарии

### Сценарий 1: Инициализация Swarm-кластера

**Шаг 1: Инициализация на менеджере**

```bash
# Замените <MANAGER-IP> на реальный IP вашего узла
docker swarm init --advertise-addr <MANAGER-IP>
```

**Параметры:**
- `--advertise-addr` — IP-адрес для связи с другими узлами (обязательно для многохостовых конфигураций)
- `--listen-addr` — адрес прослушивания (по умолчанию `:2377`)

**Шаг 2: Проверка кластера**

```bash
docker node ls
```

**Шаг 3: Сохранение токена для подключения узлов**

```bash
# Токен для worker-узлов
docker swarm join-token worker

# Токен для manager-узлов
docker swarm join-token manager
```

Сохраните команду `docker swarm join` с токеном для последующего подключения рабочих узлов.

### Сценарий 2: Настройка mTLS для Docker Daemon

Эта настройка позволяет GitLab Runner безопасно управлять Docker Swarm.

**Шаг 1: Создание директории для сертификатов**

```bash
mkdir -p ~/docker-certs && cd ~/docker-certs
```

**Шаг 2: Генерация ключа и сертификата для CA**

```bash
# Генерация ключа CA
openssl genrsa -aes256 -out ca-key.pem 4096

# Генерация самоподписанного сертификата CA
openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem
```

**Шаг 3: Генерация серверного сертификата (для Docker Daemon)**

```bash
# Генерация ключа сервера
openssl genrsa -out server-key.pem 4096

# Создание CSR (Certificate Signing Request)
# ВАЖНО: В поле "Common Name (CN)" укажите IP или FQDN менеджера Swarm
openssl req -subj "/CN=$(hostname -f)" -sha256 -new -key server-key.pem -out server.csr

# Добавление Subject Alternative Names
echo "subjectAltName = DNS:$(hostname -f),IP:$(hostname -I | awk '{print $1}')" > extfile.cnf

# Подписание сертификата CA
openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
  -CAcreateserial -out server-cert.pem -extfile extfile.cnf
```

**Шаг 4: Генерация клиентского сертификата (для GitLab Runner)**

```bash
# Генерация ключа клиента
openssl genrsa -out key.pem 4096

# Создание CSR для клиента
openssl req -subj "/CN=client" -new -key key.pem -out client.csr

# Добавление расширений для клиентской аутентификации
echo "extendedKeyUsage = clientAuth" > extfile-client.cnf

# Подписание сертификата CA
openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
  -CAcreateserial -out cert.pem -extfile extfile-client.cnf
```

**Шаг 5: Очистка и установка прав**

```bash
rm -v *.csr *.srl *.cnf
chmod -v 0400 ca-key.pem key.pem server-key.pem
chmod -v 0444 ca.pem server-cert.pem cert.pem
```

**Шаг 6: Копирование сертификатов и перезапуск Docker**

```bash
sudo mkdir -p /etc/docker/certs
sudo cp ~/docker-certs/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
sudo systemctl restart docker
```

### Сценарий 3: Настройка Docker Daemon для TLS

**Способ 1: Через `daemon.json`**

Создайте или отредактируйте `/etc/docker/daemon.json`:

```json
{
  "tls": true,
  "tlscert": "/etc/docker/certs/server-cert.pem",
  "tlskey": "/etc/docker/certs/server-key.pem",
  "tlscacert": "/etc/docker/certs/ca.pem",
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
}
```

**Способ 2: Через systemd (рекомендуется)**

Этот способ считается более гибким. Создайте `/etc/systemd/system/docker.service.d/override.conf`:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2376 --tlsverify \
  --tlscacert=/etc/docker/certs/ca.pem \
  --tlscert=/etc/docker/certs/server-cert.pem \
  --tlskey=/etc/docker/certs/server-key.pem
```

Примените изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### Сценарий 4: Проверка подключения

**Проверка состояния Docker Daemon:**

```bash
docker info | grep -A 5 "TLS"
```

**Проверка доступности порта:**

```bash
telnet <MANAGER-IP> 2376
```

**Диагностика проблем:**

```bash
# Проверка журналов Docker
sudo journalctl -u docker -f

# Проверка сертификатов
openssl x509 -in /etc/docker/certs/server-cert.pem -text -noout
```

**Подробнее об использовании Docker Context в CI/CD** — в **[docker_context_setup.md](./docker_context_setup.md)**.

## Дополнительная информация

### Безопасность

**Рекомендации для продакшена:**

- **Ограничение доступа:** Настройте firewall для разрешения подключений только с доверенных IP (GitLab Runner)
- **Ротация сертификатов:** Регулярно обновляйте сертификаты (рекомендуется каждые 12 месяцев)
- **Хранение ключей:** Ключи CA храните в защищенном месте, не передавайте в пайплайны
- **Минимальные привилегии:** Используйте отдельные клиентские сертификаты для каждого окружения

**Аудит безопасности:**

```bash
# Проверка прав на файлы сертификатов
ls -la /etc/docker/certs/

# Проверка активных подключений
sudo netstat -tlnp | grep 2376

# Проверка журналов аутентификации
sudo journalctl -u docker | grep TLS
```

### Распространенные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `certificate signed by unknown authority` | Клиент не доверяет CA | Проверить `tlscacert` в конфигурации |
| `remote error: tls: bad certificate` | Сертификат не соответствует хосту | Проверить CN и SAN в сертификате |
| `Cannot connect to the Docker daemon` | Порт 2376 недоступен | Проверить firewall и статус Docker |

### Связанные документы

- **Docker Context для CI/CD** — **[docker_context_setup.md](./docker_context_setup.md)**
- **Обзор Docker Swarm** — **[../docker_swarm_overview.md](../docker_swarm_overview.md)**
- **Основные концепции** — **[../swarm_core_concepts.md](../swarm_core_concepts.md)**
- **Управление через CLI** — **[../swarm_management_cli.md](../swarm_management_cli.md)**
- **Продвинутые темы (Raft, токены)** — **[../swarm_advanced_topics.md](../swarm_advanced_topics.md)**
- **Развертывание инфраструктуры** — **[infra_deployment.md](./infra_deployment.md)**
- **Развертывание приложения** — **[app_deployment.md](./app_deployment.md)**
- **mTLS основы** — **[../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)**
