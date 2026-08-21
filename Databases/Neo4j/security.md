# Neo4j: Безопасность

## Аутентификация и авторизация

```bash
# Создание пользователя (cypher-shell)
CREATE USER app_user IDENTIFIED BY 'StrongPassword2026'
SET PASSWORD CHANGE REQUIRED;

# Предоставление прав на конкретную базу
GRANT MATCH ON GRAPH neo4j NODES Person TO app_user;
GRANT CREATE ON GRAPH neo4j RELATIONSHIPS TO app_user;

# Роли по умолчанию
# - admin: полный доступ
# - reader: только чтение
# - editor: чтение + запись
```

**Принцип наименьших привилегий:** предоставляйте драйверам приложений только права на чтение/запись нужных узлов и связей, без DDL-привилегий.

## Шифрование (TLS)

```conf
# neo4j.conf
server.ssl.enabled=true
server.ssl.policy=bolt
server.ssl.key_file=/etc/neo4j/certs/server.key
server.ssl.certificate_file=/etc/neo4j/certs/server.crt
```

**Генерация самоподписанного сертификата (для тестов):**
```bash
# Генерация ключа и сертификата
openssl req -x509 -newkey rsa:4096 -keyout server.key -out server.crt \
  -days 365 -nodes -subj "/CN=neo4j"

# Копирование в директорию сертификатов
sudo mkdir -p /etc/neo4j/certs
sudo cp server.key server.crt /etc/neo4j/certs/
sudo chown neo4j:neo4j /etc/neo4j/certs/*
sudo chmod 600 /etc/neo4j/certs/server.key
```

**Проверка TLS-соединения:**
```bash
cypher-shell -a bolt+s://localhost:7687 -u neo4j -p YourPassword \
  "RETURN 1 AS test;"
# → +------+
#    | test |
#    +------+
#    | 1    |
#    +------+
```

## Дополнительные рекомендации

- **Сетевая изоляция:** привязывайте Neo4j к внутреннему интерфейсу (`server.listen_address=0.0.0.0` только за reverse proxy).
- **Отключение небезопасных функций:** запретите доступ к файловой системе через `dbms.security.procedures.unrestricted`.
- **Аудит:** включите `dbms.security.audit.enabled=true` для логирования аутентификации и DDL-операций.

## См. также
- **[Обзор Neo4j](./overview.md)** — определения и место в экосистеме.
- **[Обслуживание и эксплуатация](./operations.md)** — память, бэкап, диагностика.
- **[Безопасная установка СУБД](../installation_security.md)** — общие принципы закалки БД.
