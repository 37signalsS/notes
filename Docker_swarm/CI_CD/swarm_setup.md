# CI/CD с Docker Swarm: Подготовка кластера

## Определения

- **[Docker Swarm Mode](../docker_swarm_overview.md):** Нативный режим оркестрации Docker Engine для управления кластером из нескольких хостов.
- **[mTLS (mutual TLS)](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls):** Протокол взаимной аутентификации, обеспечивающий защищенное соединение между GitLab Runner и Docker API.
- **[Docker Context](./docker_context_setup.md):** Механизм управления удаленными окружениями, позволяющий абстрагироваться от параметров подключения (хост, сертификаты) в командах CLI.
- **[Join Token](../swarm_advanced_topics.md):** Секретный токен, используемый для безопасного включения новых узлов в состав кластера.

## Базовые концепции

### Архитектура удаленного доступа

Для автоматизации развертывания требуется организовать безопасное взаимодействие GitLab Runner с менеджером кластера. Рекомендуется использовать удаленное управление по TCP (порт 2376) с mTLS-авторизацией.

Преимущества удаленного управления:

- Изоляция среды сборки от продуктивной инфраструктуры.
- Возможность управления несколькими кластерами из одного пайплайна.
- Отсутствие необходимости установки Runner на узлы Swarm.

### Необходимые компоненты

| Компонент | Назначение |
|:---|:---|
| Docker Daemon | Прием и выполнение API-команд по TCP/2376 |
| CA Certificate | Центр сертификации для проверки подлинности участников |
| Server Certificate | Подтверждение личности узла Swarm |
| Client Certificate | Подтверждение личности GitLab Runner |

### Требования к инфраструктуре

- **Кворум:** Рекомендуется нечетное количество менеджеров (3 или 5).
- **Сеть:** Статический IP или DNS-имя для менеджеров Swarm.
- **Доступность:** Открытый порт 2376 (TCP) для входящих TLS-подключений.

## Практические сценарии

### Сценарий 1: Создание Swarm-кластера

1. Инициализация первого менеджера:

   ```bash
   docker swarm init --advertise-addr <MANAGER-IP>
   ```

2. Получение токенов для подключения дополнительных узлов:

   ```bash
   docker swarm join-token worker
   docker swarm join-token manager
   ```

3. Проверка состояния узлов:

   ```bash
   docker node ls
   ```

### Сценарий 2: Генерация сертификатов для mTLS

Процесс создания PKI-инфраструктуры для безопасного доступа:

1. Создание CA (корневого сертификата):

   ```bash
   openssl genrsa -aes256 -out ca-key.pem 4096
   openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem
   ```

2. Подготовка сертификата сервера (Swarm Manager):

   ```bash
   openssl genrsa -out server-key.pem 4096
   openssl req -subj "/CN=$(hostname -f)" -sha256 -new -key server-key.pem -out server.csr
   echo "subjectAltName = DNS:$(hostname -f),IP:$(hostname -I | awk '{print $1}')" > extfile.cnf
   openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
     -CAcreateserial -out server-cert.pem -extfile extfile.cnf
   ```

3. Подготовка сертификата клиента (GitLab Runner):

   ```bash
   openssl genrsa -out key.pem 4096
   openssl req -subj "/CN=client" -new -key key.pem -out client.csr
   echo "extendedKeyUsage = clientAuth" > extfile-client.cnf
   openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
     -CAcreateserial -out cert.pem -extfile extfile-client.cnf
   ```

### Сценарий 3: Настройка Docker Daemon

Для активации TLS-доступа необходимо настроить параметры запуска демона.

**Вариант 1: Файл daemon.json**

```json
{
  "tls": true,
  "tlscert": "/etc/docker/certs/server-cert.pem",
  "tlskey": "/etc/docker/certs/server-key.pem",
  "tlscacert": "/etc/docker/certs/ca.pem",
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
}
```

**Вариант 2: Systemd override (рекомендуется)**
Создайте файл `/etc/systemd/system/docker.service.d/override.conf`:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2376 --tlsverify \
  --tlscacert=/etc/docker/certs/ca.pem \
  --tlscert=/etc/docker/certs/server-cert.pem \
  --tlskey=/etc/docker/certs/server-key.pem
```

После внесения изменений выполните:

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### Сценарий 4: Верификация подключения

Проверка корректности настройки TLS:

```bash
# Проверка конфигурации демона
docker info | grep -i tls

# Тестирование подключения через порт
telnet <MANAGER-IP> 2376
```

## Дополнительная информация

### Меры безопасности

- **Ограничение IP:** Настройте Firewall (iptables/nftables) для разрешения доступа к порту 2376 только с IP-адресов GitLab Runner.
- **Ротация:** Обновляйте клиентские и серверные сертификаты не реже одного раза в год.
- **Конфиденциальность:** Никогда не передавайте `ca-key.pem` и `server-key.pem` в переменные CI/CD.

### Диагностика

| Ошибка | Возможная причина |
|:---|:---|
| `certificate signed by unknown authority` | Клиент не имеет правильного CA сертификата |
| `remote error: tls: bad certificate` | Ошибка в Subject Alternative Names (SAN) серверного сертификата |
| `Cannot connect to the Docker daemon` | Порт 2376 закрыт Firewall или демон не слушает TCP |

### Связанные документы

- **[Docker Context в CI/CD](./docker_context_setup.md)** — настройка профилей подключения.
- **[Обзор Docker Swarm](../docker_swarm_overview.md)** — базовые возможности оркестратора.
- **[Продвинутые темы Swarm](../swarm_advanced_topics.md)** — детали работы Raft и токенов.
- **[Развертывание Traefik](./infra_deployment.md)** — настройка Ingress-прокси.
- **[Пайплайн приложения](./app_deployment.md)** — примеры автоматизации деплоя.
- **[Best Practices](./best_practices.md)** — рекомендации по безопасности.
