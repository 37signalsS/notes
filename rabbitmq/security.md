# RabbitMQ: Безопасность (Security)

## Определения

- **Access Control List (ACL):** Правила доступа, определяющие, какие операции (configure, write, read) разрешены пользователю для конкретных ресурсов (очереди, обменники) в рамках vhost.
- **SASL (Simple Authentication and Security Layer):** Фреймворк аутентификации, поддерживаемый RabbitMQ. Включает механизмы PLAIN, AMQPLAIN, EXTERNAL (TLS), OAUTHBEARER.
- **LDAP (Lightweight Directory Access Protocol):** Протокол доступа к каталогам. RabbitMQ может использовать LDAP для внешней аутентификации и авторизации пользователей.
- **OAuth 2.0:** Протокол делегированной авторизации. RabbitMQ поддерживает OAuth 2.0 через плагин `rabbitmq_auth_mechanism_oauth2` для аутентификации клиентов через JWT-токены.
- **TLS (Transport Layer Security):** Протокол шифрования транспортного уровня. Используется для шифрования AMQP-соединений и межузлового трафика.
- **Peer Verification:** Проверка сертификата клиента сервером (и наоборот) для обеспечения взаимной аутентификации (mTLS).
- **Vhost Isolation:** Логическая изоляция ресурсов (очереди, обменники, пользователи) внутри одного инстанса RabbitMQ.

## Основные концепции

### Модель безопасности RabbitMQ

Безопасность RabbitMQ строится на трех уровнях:

1. **Аутентификация (Authentication):** Кто вы? — Проверка личности (PLAIN, SASL, TLS, LDAP, OAuth).
2. **Авторизация (Authorization):** Что вам разрешено? — ACL-правила на уровне vhost.
3. **Шифрование (Encryption):** Как защитить данные? — TLS для транспорта.

### Уровни изоляции

| Уровень | Механизм | Защита |
|:---|:---|:---|
| **Instance** | Порты, firewall | Доступ к брокеру |
| **Vhost** | Vhost permissions | Логическая изоляция ресурсов |
| **Queue/Exchange** | ACL (configure/write/read) | Доступ к конкретным ресурсам |
| **Connection** | TLS + peer verification | Шифрование и аутентификация |

## Практические сценарии

### 1. Настройка пользователей и ACL

```bash
# Создание пользователя
sudo rabbitmqctl add_user app_user 's3cur3_p@ss'

# Установка тегов (administrator, monitoring, management, none)
sudo rabbitmqctl set_user_tags app_user monitoring

# Установка прав на vhost (configure, write, read)
# Формат: set_permissions -p <vhost> <user> <configure> <write> <read>
sudo rabbitmqctl set_permissions -p production app_user \
  "^app\\..*" "^app\\..*" "^app\\..*"

# Просмотр прав
sudo rabbitmqctl list_permissions -p production
# → app_user  ^app\..*  ^app\..*  ^app\..*

# Просмотр прав конкретного пользователя
sudo rabbitmqctl list_user_permissions app_user
```

### 2. Настройка TLS (mTLS)

**Генерация сертификатов:**

```bash
# CA (Certificate Authority)
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -out ca.pem -subj "/CN=RabbitMQ CA"

# Серверный сертификат
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/CN=rabbitmq.local"
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key \
  -CAcreateserial -out server.pem -days 3650 -sha256

# Клиентский сертификат
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr \
  -subj "/CN=app_client"
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key \
  -CAcreateserial -out client.pem -days 3650 -sha256
```

**Конфигурация RabbitMQ:**

```ini
# /etc/rabbitmq/rabbitmq.conf

# TLS слушатель
listeners.ssl.default = 5671

# Сертификаты сервера
ssl_options.cacertfile = /etc/rabbitmq/tls/ca.pem
ssl_options.certfile = /etc/rabbitmq/tls/server.pem
ssl_options.keyfile = /etc/rabbitmq/tls/server.key

# Верификация клиента (mTLS)
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = true

# Дополнительные опции
ssl_options.versions.1 = tlsv1.2
ssl_options.versions.2 = tlsv1.3
```

**Перезапуск:**

```bash
sudo systemctl restart rabbitmq-server
```

### 3. Настройка LDAP аутентификации

```ini
# /etc/rabbitmq/rabbitmq.conf

# Включение LDAP
auth_ldap.enabled = true

# LDAP серверы
auth_ldap.servers.1 = ldap://ldap1.example.com
auth_ldap.servers.2 = ldap://ldap2.example.com

# Базовый DN для поиска пользователей
auth_ldap.user_dn_pattern = ou=users,dc=example,dc=com

# Bind DN (для поиска)
auth_ldap.bind_dn = cn=admin,dc=example,dc=com
auth_ldap.bind_password = admin_password

# Включение SSL для LDAP
auth_ldap.use_ssl = true
auth_ldap.port = 636

# Таймауты
auth_ldap.timeout = 5000
auth_ldap.log = true
```

**Логин через LDAP:**

```bash
# Пользователь уже должен существовать в LDAP
# RabbitMQ проверит credentials через LDAP
rabbitmqadmin -u ldap_user -p ldap_password list queues
```

### 4. Настройка OAuth 2.0

```ini
# /etc/rabbitmq/rabbitmq.conf

# Включение OAuth 2.0
auth_mechanisms.1 = OAUTHBEARER

# JWKS URI (JSON Web Key Set)
auth_oauth2.jwks_url = https://auth.example.com/.well-known/jwks.json

# Издатель токенов
auth_oauth2.issuer = https://auth.example.com

# Аудитория
auth_oauth2.audience = rabbitmq

# Scopes (права доступа)
auth_oauth2.scopes.1 = rabbitmq.read
auth_oauth2.scopes.2 = rabbitmq.write
auth_oauth2.scopes.3 = rabbitmq.configure
```

**Публикация с OAuth-токеном (Python):**

```python
import pika
import requests

# Получение JWT-токена
token_response = requests.post(
    'https://auth.example.com/oauth/token',
    data={
        'grant_type': 'client_credentials',
        'client_id': 'rabbitmq_client',
        'client_secret': 'secret',
        'scope': 'rabbitmq.read rabbitmq.write'
    }
)
access_token = token_response.json()['access_token']

# Подключение с OAuth-токеном
credentials = pika.OAuth2Credentials(access_token)
connection = pika.BlockingConnection(
    pika.ConnectionParameters(
        host='rabbitmq.local',
        port=5671,
        credentials=credentials,
        ssl_options=pika.SSLOptions()
    )
)
```

### 5. Шифрование межузлового трафика

```ini
# /etc/rabbitmq/rabbitmq.conf

# Inter-node TLS
cluster_formation.peer_discovery_backend = classic_config
cluster_formation.classic_config.nodes.1 = rabbit@node1
cluster_formation.classic_config.nodes.2 = rabbit@node2
cluster_formation.classic_config.nodes.3 = rabbit@node3

# TLS для inter-node
ssl_options.inter_node_tls = true
```

### 6. Ограничение доступа к Management UI

```ini
# /etc/rabbitmq/rabbitmq.conf

# Только localhost
management.tcp.ip = 127.0.0.1

# Или через reverse proxy
management.tcp.ip = 0.0.0.0
management.tcp.port = 15672
```

**Настройка HAProxy для Management UI:**

```
# /etc/haproxy/haproxy.cfg

frontend rabbitmq_management
    bind *:15672 ssl crt /etc/haproxy/tls/rabbitmq.pem
    acl is_admin src 10.0.0.0/8
    http-request deny unless is_admin
    default_backend rabbitmq_mgmt

backend rabbitmq_mgmt
    server mgmt1 node1:15672 check
    server mgmt2 node2:15672 check
```

### 7. Мониторинг безопасности

```bash
# Проверка активных пользователей
sudo rabbitmqctl list_users
# → guest  [administrator]
# → app_user  [monitoring]

# Проверка прав на vhost
sudo rabbitmqctl list_permissions -p production

# Проверка подключений с авторизацией
sudo rabbitmqctl list_connections user client_host state

# Проверка TLS-подключений
sudo rabbitmq-diagnostics listeners
# → 5671 (tls) ...

# Проверка сертификата
openssl s_client -connect localhost:5671 -servername rabbitmq.local
```

### 8. Аудит действий

```ini
# /etc/rabbitmq/rabbitmq.conf

# Включение аудита
audit.log = true
audit.log.dir = /var/log/rabbitmq/audit.log
audit.log.level = info

# Логирование операций управления
audit.log.commands = true
```

### 9. Настройка Vault для управления секретами

```bash
# Включение секретного движка RabbitMQ
vault secrets enable -path=rabbitmq rabbitmq

# Конфигурация подключения
vault write rabbitmq/config/connection \
  connection_uri="http://localhost:15672" \
  username="guest" \
  password="guest"

# Создание роли для генерации credentials
vault write rabbitmq/roles/app-role \
  vhosts='{"production": {"configure": "app\\..*", "write": "app\\..*", "read": "app\\..*"}}'

# Получение временных credentials
vault read rabbitmq/creds/app-role
# → username: "user-v-abc123"
# → password: "password-v-def456"
```

### 10. Firewall правила

```bash
# iptables: разрешить только необходимые порты
sudo iptables -A INPUT -p tcp --dport 5672 -s 10.0.0.0/8 -j ACCEPT  # AMQP
sudo iptables -A INPUT -p tcp --dport 5671 -s 10.0.0.0/8 -j ACCEPT  # AMQP TLS
sudo iptables -A INPUT -p tcp --dport 15672 -s 10.0.0.0/8 -j ACCEPT # Management
sudo iptables -A INPUT -p tcp --dport 15692 -s 10.0.0.0/8 -j ACCEPT # Prometheus
sudo iptables -A INPUT -p tcp --dport 4369 -s 10.0.0.0/8 -j ACCEPT  # epmd
sudo iptables -A INPUT -p tcp --dport 25672 -s 10.0.0.0/8 -j ACCEPT # Inter-node
sudo iptables -A INPUT -j DROP  # Всё остальное
```

## Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `ACCESS_REFUSED` | Неверные права или vhost | Проверьте `list_permissions -p <vhost>` |
| TLS handshake failure | Несовместимые версии TLS | Убедитесь, что клиент поддерживает TLS 1.2+ |
| LDAP bind failed | Неверный bind_dn или password | Проверьте LDAP-конфигурацию и сертификаты |
| OAuth token expired | JWT-токен истек | Настройте обновление токена до истечения |
| Management UI недоступен | IP-ограничение или firewall | Проверьте `management.tcp.ip` и правила iptables |

## Лучшие практики

1. **Удалите гостевого пользователя** — `sudo rabbitmqctl delete_user guest` после начальной настройки.
2. **Используйте mTLS** — взаимная аутентификация через сертификаты надежнее паролей.
3. **Разделяйте vhosts** — изоляция сред (dev/staging/prod) в одном кластере.
4. **Настройте ACL** —最小权限 principle: только необходимые права для каждого пользователя.
5. **Используйте Vault** — динамические credentials с автоматическим отзывом.
6. **Включите аудит** — логирование всех операций управления.
7. **Ограничьте Management UI** — только доверенные IP, через reverse proxy с TLS.
8. **Ротируйте сертификаты** — автоматизация через cert-manager или Vault PKI.
9. **Мониторьте подключения** — алерты на неизвестные IP или аномальное количество.
10. **Тестируйте ACL** — регулярная проверка прав доступа.

## Чеклист безопасности для production

### Базовый уровень
- [ ] Удалить гостевого пользователя `guest`
- [ ] Настроить уникальных пользователей для каждого сервиса
- [ ] Использовать сложные пароли (минимум 16 символов)
- [ ] Ограничить доступ к Management UI (только доверенные IP)
- [ ] Настроить firewall (открытые порты: 5672, 15672, 25672)

### Средний уровень
- [ ] Включить TLS для AMQP и Management UI
- [ ] Настроить ACL с минимальными правами
- [ ] Разделить vhosts по средам (dev/staging/prod)
- [ ] Включить аудит действий
- [ ] Настроить мониторинг подключений

### Продвинутый уровень
- [ ] Настроить mTLS (взаимная аутентификация)
- [ ] Интегрировать с LDAP/OAuth для централизованного управления
- [ ] Использовать Vault для динамических credentials
- [ ] Автоматизировать ротацию сертификатов
- [ ] Регулярно тестировать ACL и disaster recovery

## Дополнительная информация

### См. также

- **[Установка и кластеризация](./installation_and_clustering.md)** — настройка TLS для межузлового трафика.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — мониторинг подключений и авторизации.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика ошибок авторизации.
- **[Vault: RabbitMQ](../Vault/concepts.md)** — интеграция с HashiCorp Vault.
