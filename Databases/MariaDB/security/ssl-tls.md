# SSL/TLS в MariaDB: шифрование трафика

Шифрование трафика в MariaDB 12.3 LTS является стандартом де-факто для любых сред, отличных от локальной разработки.

## Генерирование сертификатов (OpenSSL)

Для работы TLS требуется CA (центр сертификации), сертификат сервера и приватный ключ.

```bash
# 1. Создание CA
openssl genrsa 2048 > ca-key.pem
openssl req -new -x509 -nodes -days 3650 -key ca-key.pem -out ca.pem

# 2. Создание ключа и запроса сервера
openssl req -newkey rsa:2048 -days 3650 -nodes -keyout server-key.pem -out server-req.pem
openssl rsa -in server-key.pem -out server-key.pem
openssl x509 -req -in server-req.pem -days 3650 -CA ca.pem -CAkey ca-key.pem -set_serial 01 -out server-cert.pem

# 3. Создание клиентского сертификата (для mTLS / REQUIRE X509)
openssl req -newkey rsa:2048 -days 3650 -nodes -keyout client-key.pem -out client-req.pem
openssl rsa -in client-key.pem -out client-key.pem
openssl x509 -req -in client-req.pem -days 3650 -CA ca.pem -CAkey ca-key.pem -set_serial 02 -out client-cert.pem
```

## Настройка сервера (`my.cnf`)

```ini
[mariadb]
# Пути к файлам сертификатов
ssl_ca   = /etc/mysql/ssl/ca.pem
ssl_cert = /etc/mysql/ssl/server-cert.pem
ssl_key  = /etc/mysql/ssl/server-key.pem

# Запрет незашифрованных соединений (глобально)
require_secure_transport = ON

# Использование современных версий TLS
tls_version = TLSv1.2,TLSv1.3
```

## Принудительное использование TLS для конкретных пользователей

```sql
-- Требование SSL для существующего пользователя
ALTER USER 'app_user'@'%' REQUIRE SSL;

-- Требование X509 (проверка валидности клиентского сертификата - mTLS)
ALTER USER 'admin_user'@'%' REQUIRE X509;
```

## Верификация TLS-соединения

```sql
-- Проверка, что текущее соединение использует шифрование
SHOW STATUS LIKE 'Ssl_cipher';
-- → Ssl_cipher | AES256-SHA256

SHOW STATUS LIKE 'Ssl_version';
-- → Ssl_version | TLSv1.3

-- Просмотр всех активных соединений и их статуса шифрования
SELECT SCHEMA, USER, HOST, SSL_TYPE, SSL_CIPHER
FROM information_schema.PROCESSLIST
JOIN information_schema.USER_PRIVILEGES USING (USER);
```

```bash
# Проверка TLS-соединения через CLI-клиент
mariadb --ssl --ssl-ca=/etc/mysql/ssl/ca.pem -e "SHOW STATUS LIKE 'Ssl_cipher';"
```

## Отзыв сертификатов (CRL)

Если ключ клиента скомпрометирован, его необходимо отозвать через список отзыва (Certificate Revocation List).

### Создание CRL с помощью OpenSSL

```bash
# Создание файла серийных номеров для отзыва
echo "02" > crl.txt

# Генерация CRL на основе CA
openssl ca -gencrl -config openssl.cnf -keyfile ca-key.pem -cert ca.pem -out ca.crl.pem

# Проверка содержимого CRL
openssl crl -in ca.crl.pem -noout -text
```

### Настройка сервера для использования CRL

```ini
[mariadb]
ssl_crl = /etc/mysql/ssl/ca.crl.pem
```

### Проверка отзыва

```sql
-- После добавления ssl_crl в конфигурацию и перезапуска сервера,
-- попытка подключения отозванным сертификатом будет отклонена
SHOW STATUS LIKE 'Ssl_cipher';
-- → (пусто, если соединение отклонено из-за отзыва)
```

**Важно:** CRL должен регулярно обновляться. Настройте крон-задачу для перегенерации CRL и перезапуска сервера (или используйте `SET GLOBAL ssl_crl = ...` в MariaDB 10.6+).

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Аутентификация](authentication.md)** — плагины аутентификации и `REQUIRE SSL`.
- **[Сетевая безопасность](network-security.md)** — ограничение сетевого доступа.
- **[Начальная закалка](hardening.md)** — первичная настройка после установки.
