# Безопасность

## Аутентификация (Authentication)

Cassandra/ScyllaDB поддерживают несколько провайдеров:

```yaml
# cassandra.yaml
authenticator: PasswordAuthenticator      # По умолчанию AllowAllAuthenticator
authorizer: CassandraAuthorizer           # По умолчанию AllowAllAuthorizer
role_manager: CassandraRoleManager
```

**Создание пользователя и ролей:**
```sql
-- Создание роли с паролем
CREATE ROLE app_user WITH PASSWORD = 'secure_password_2026' AND LOGIN = true;

-- Предоставление прав на Keyspace
GRANT SELECT, INSERT, UPDATE, DELETE ON KEYSPACE my_app TO app_user;

-- Предоставление прав на конкретную таблицу
GRANT SELECT ON TABLE my_app.user_events TO app_user;

-- Просмотр прав
LIST ALL PERMISSIONS OF app_user;
```

---

## TLS/SSL шифрование

```yaml
# cassandra.yaml
client_encryption_options:
    enabled: true
    keystore: /etc/cassandra/ssl/keystore.jks
    keystore_password: changeit
    require_client_auth: false

server_encryption_options:
    internode_encryption: all
    keystore: /etc/cassandra/ssl/keystore.jks
    keystore_password: changeit
    truststore: /etc/cassandra/ssl/truststore.jks
    truststore_password: changeit
```

```bash
# Генерация самоподписанного сертификата (для тестов)
keytool -genkeypair -keyalg RSA -keysize 2048 \
    -alias cassandra -validity 365 \
    -keystore keystore.jks -storepass changeit

# Подключение с TLS
cqlsh --ssl <node_ip> 9042
```

---

## Network Encryption (межузловой)

Для шифрования трафика между узлами кластера используйте `server_encryption_options`. В production рекомендуется `internode_encryption: all`.

---

## Firewall правила

```bash
# Минимально необходимые порты
9042  # CQL (клиенты)
7000  # Межузловой трафик (Storage)
7001  # Межузловой SSL (опционально)
9160  # Thrift (устаревший, рекомендуется отключить)
```

---

## См. также
- **[Установка и настройка](./installation.md)** — cassandra.yaml, порты.
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — модель безопасности.
- **[Тюнинг производительности](./performance.md)** — JVM, I/O.
