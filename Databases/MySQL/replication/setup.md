# Настройка репликации MySQL: безопасность репликационного пользователя и SSL

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation

Единственный файл раздела по двум темам: привилегии репликационной учётной
записи и защита TLS канала репликации. Пошаговый запуск репликации (seeding,
`my.cnf`, GTID) — в [setup_guide.md](./setup_guide.md); механизм репликации —
в [overview.md](./overview.md) и [master_slave_mechanism.md](./master_slave_mechanism.md);
host-уровень TLS (`require_secure_transport`, `tls_version`, keyring) — в
[security.md](../security.md).

## Определения

**Репликационный пользователь** — учётная запись, от имени которой I/O-поток
(receiver) реплики подключается к источнику и читает бинарный лог.

**Репликационный канал (channel)** — именованный набор параметров подключения
к источнику. Канал по умолчанию имеет пустое имя `""` и всегда присутствует;
именованные каналы используются только в multi-source (см.
[multi-source.md](./multi-source.md)).

**Репозиторий метаданных репликации** — таблица `mysql.slave_master_info`, в
которой хранятся параметры подключения канала, включая зашифрованный пароль.

**Account-level TLS** — требование TLS на уровне учётной записи
(`REQUIRE SSL` / `REQUIRE X509` в `CREATE USER`/`ALTER USER`).
**Channel-level TLS** — требование TLS на уровне канала (`SOURCE_SSL=1` в
`CHANGE REPLICATION SOURCE TO`). Уровни независимы и должны быть согласованы.

## Базовые концепции

### Принцип минимальных привилегий

Репликационному пользователю для работы I/O-потока достаточно одной статической
привилегии — `REPLICATION SLAVE`. Не выдавайте `SUPER` (deprecated),
`SELECT/INSERT/UPDATE/DELETE` и прочие привилегии «на всякий случай»:
скомпрометированная учётная запись с ними превращает канал репликации в
путь полного доступа к данным источника.

### Два независимых уровня защиты канала

- **Привилегии** ограничивают, что аккаунт может делать на источнике.
- **TLS** защищает трафик: бинарный лог передаётся целиком, то есть по
  незашифрованному каналу доступны все изменения данных в cleartext.

Уровни верификации TLS-канала соответствуют клиентским `--ssl-mode`:
`SOURCE_SSL=1` — это `--ssl-mode=REQUIRED` (соединение устанавливается только
зашифрованное, отката на plaintext нет — значения `PREFERRED` для репликации
не предусмотрено); `SOURCE_SSL=0` — это `--ssl-mode=DISABLED`. Добавление
`SOURCE_SSL_CA` с `SOURCE_SSL_VERIFY_SERVER_CERT=1` даёт защиту уровня
`VERIFY_CA`/`VERIFY_IDENTITY`: реплика проверяет сертификат источника по CA,
что защищает от MITM.

### Где хранятся учётные данные

`SOURCE_USER` и `SOURCE_PASSWORD` сохраняются в репозитории метаданных
(`mysql.slave_master_info`, InnoDB-таблица). Пароль зашифрован и маскируется
в логах сервера, таблицах Performance Schema и выводе `SHOW PROCESSLIST`.
`CHANGE REPLICATION SOURCE TO` записывает в error log предыдущие значения
`SOURCE_HOST`, `SOURCE_PORT`, `SOURCE_LOG_FILE`, `SOURCE_LOG_POS` — но не
пароль. Ограничение: `SOURCE_PASSWORD` принимает максимум **32 символа**
(бо́льший пароль приведёт к ошибке инструкции), `SOURCE_USER` — 96.

### FLUSH PRIVILEGES — когда нужен, а когда нет

`CREATE USER`, `GRANT`, `REVOKE`, `ALTER USER` — account-management
инструкции: сервер сразу замечает изменения grant-таблиц и перезагружает их в
память, `FLUSH PRIVILEGES` после них **не требуется**. `FLUSH PRIVILEGES`
нужен только после прямых `INSERT/UPDATE/DELETE` по grant-таблицам
(не рекомендуется) или для включения access control после старта сервера с
`--skip-grant-tables`.

## Практические сценарии

### 1. Создание репликационного пользователя

```sql
-- На источнике (Source). Host — конкретный IP реплики, не '%'
CREATE USER 'repl'@'10.0.1.20' IDENTIFIED BY 'long_unique_password';
-- Единственная привилегия, требуемая I/O-потоку реплики
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.1.20';
-- Требование TLS на уровне аккаунта (тогда канал обязан иметь SOURCE_SSL=1)
ALTER USER 'repl'@'10.0.1.20' REQUIRE SSL;
-- FLUSH PRIVILEGES здесь не нужен: GRANT/ALTER USER применяются немедленно
```

`REPLICATION CLIENT` репликационному пользователю **не требуется** — это
привилегия оператора/мониторинга (см. сценарий 2). Выдавайте её тому же
аккаунту только если он целенаправленно используется для диагностических
`SHOW`-запросов.

### 2. Привилегии для эксплуатации и диагностики

| Привилегия | Тип | Что даёт | Кому и где |
| :--- | :--- | :--- | :--- |
| `REPLICATION SLAVE` | статическая | Доступ к бинарному логу источника (`SHOW REPLICAS`, `SHOW RELAYLOG EVENTS`, `SHOW BINLOG EVENTS`, `mysqlbinlog --read-from-remote-server`). Именно её требует I/O-поток реплики | репликационный пользователь **на источнике** |
| `REPLICATION CLIENT` | статическая | `SHOW BINARY LOG STATUS`, `SHOW REPLICA STATUS`, `SHOW BINARY LOGS` | оператор/мониторинг: на источнике (позиция binlog) и на реплике (статус каналов) |
| `REPLICATION_SLAVE_ADMIN` | динамическая | `CHANGE REPLICATION SOURCE TO`, `START REPLICA`, `STOP REPLICA` | оператор **на реплике** (заменяет deprecated `SUPER`) |
| `REPLICATION_APPLIER` | динамическая | Привилегия для `PRIVILEGE_CHECKS_USER` — security context канала | продвинутое усиление (сценарий 5) |

Имен `REPLICATION REPLICA` и `REPLICATION_APPLY` **не существует**: статические
привилегии `REPLICATION SLAVE` и `REPLICATION CLIENT` сохраняются под теми же
именами в 8.0, 8.4 и 9.x. Переименования затронули операторы, но не привилегии:
`SHOW SLAVE STATUS` → `SHOW REPLICA STATUS` — с MySQL 8.0.22;
`CHANGE MASTER TO` → `CHANGE REPLICATION SOURCE TO` — с MySQL 8.0.23;
`RESET MASTER` → `RESET BINARY LOGS AND GTIDS` — с MySQL 8.1 (Innovation);
`SHOW MASTER STATUS` → `SHOW BINARY LOG STATUS` — с MySQL 8.2.0
(Innovation); в 8.4 имена `RESET MASTER` и `SHOW MASTER STATUS` уже
не поддерживаются.

### 3. TLS-канал репликации

**Требования:**
- TLS включён на источнике: заданы `ssl_cert`/`ssl_key` (опции `mysqld`).
  `require_secure_transport=ON` — опциональное server-wide ограничение (все
  подключения, включая X Protocol), а не требование репликации — настройка в
  [security.md](../security.md).
- CA, клиентский сертификат и ключ — на реплике; серверный сертификат и ключ —
  на источнике (стандартная TLS-конфигурация MySQL).

**Настройка на реплике** (начальная настройка канала с GTID-позиционированием —
обе нити должны быть остановлены для `SOURCE_AUTO_POSITION=1`):

```sql
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='master_host',
  SOURCE_PORT=3306,
  SOURCE_USER='repl',
  SOURCE_PASSWORD='long_unique_password',
  SOURCE_AUTO_POSITION=1,
  SOURCE_SSL=1,
  SOURCE_SSL_CA='/etc/mysql/ssl/ca.pem',
  SOURCE_SSL_CERT='/etc/mysql/ssl/client-cert.pem',
  SOURCE_SSL_KEY='/etc/mysql/ssl/client-key.pem',
  SOURCE_SSL_VERIFY_SERVER_CERT=1,
  SOURCE_TLS_VERSION='TLSv1.2,TLSv1.3';
START REPLICA;
```

Пояснения:
- `SOURCE_SSL_VERIFY_SERVER_CERT=1` вместе с `SOURCE_SSL_CA` — реплика проверяет
  сертификат источника по доверенному CA (уровень `VERIFY_CA`); без этого CA
  шифрование есть, а подлинность источника — нет.
- `SOURCE_TLS_VERSION` / `SOURCE_TLS_CIPHERSUITES` — контроль протоколов и
  наборов шифров (полезно запретить TLS 1.0/1.1). Длина строковых
  `SOURCE_SSL_*`/`SOURCE_TLS_*` опций — до 511 символов,
  `SOURCE_TLS_CIPHERSUITES` — до 4000.
- Опции `SOURCE_SSL_*`/`SOURCE_TLS_*` можно задать даже на реплике, собранной
  без поддержки SSL: они сохраняются в репозиторий метаданных, но игнорируются.
- Если пользователь аутентифицируется плагином `caching_sha2_password`
  (по умолчанию для новых пользователей) **без** TLS, необходим обмен RSA-ключами:
  `GET_SOURCE_PUBLIC_KEY=1` или `SOURCE_PUBLIC_KEY_PATH='...'`. По TLS-каналу
  это не нужно.

**Проверка использования TLS:**

```sql
SHOW REPLICA STATUS\G
-- Source_SSL_Allowed: Yes            -- канал настроен на TLS
-- Source_SSL_Verify_Server_Cert: Yes
-- Source_SSL_CA_File: /etc/mysql/ssl/ca.pem
-- Replica_IO_Running: Yes
```

Поля SSL в выводе: `Source_SSL_Allowed` (`Yes`/`No`/`Ignored` — `Ignored` означает,
что TLS разрешён, но на реплике нет поддержки SSL), `Source_SSL_CA_File`,
`Source_SSL_CA_Path`, `Source_SSL_Cert`, `Source_SSL_Cipher`, `Source_SSL_Key`,
`Source_SSL_Crl`, `Source_SSL_Crlpath`, `Source_SSL_Verify_Server_Cert`,
`Source_TLS_Version`. Поля `Source_SSL_Using` в выводе **нет**.

Конфигурацию TLS-канала в табличном виде зеркалит Performance Schema:

```sql
SELECT CHANNEL_NAME, SSL_ALLOWED, SSL_CIPHER, SSL_CERTIFICATE, SSL_VERIFY_SERVER_CERTIFICATE
FROM performance_schema.replication_connection_configuration;
-- → CHANNEL_NAME='', SSL_ALLOWED='Yes', SSL_CIPHER='TLS_AES_256_GCM_SHA384',
--   SSL_VERIFY_SERVER_CERTIFICATE=1
```

> **Внимание:** `performance_schema.session_status` для этой цели не подходит —
> таблица содержит только столбцы `VARIABLE_NAME` и `VARIABLE_VALUE` и отражает
> **текущую** сессию, а не репликационные подключения. Для значений по
> конкретным потокам есть `status_by_thread` (`THREAD_ID`, `VARIABLE_NAME`,
> `VARIABLE_VALUE`).

### 4. Ротация учётных данных

```sql
-- 1. На источнике: новая учётная запись (либо ALTER USER ... IDENTIFIED BY для старой)
CREATE USER 'repl2'@'10.0.1.20' IDENTIFIED BY 'new_password';
GRANT REPLICATION SLAVE ON *.* TO 'repl2'@'10.0.1.20';
ALTER USER 'repl2'@'10.0.1.20' REQUIRE SSL;

-- 2. На реплике: остановить I/O-поток — для смены параметров подключения
--    (HOST/USER/PASSWORD/SSL_*) достаточно остановить receiver-поток
STOP REPLICA IO_THREAD;

-- 3. Обновить учётные данные канала (пароль сохранится зашифрованным)
CHANGE REPLICATION SOURCE TO SOURCE_USER='repl2', SOURCE_PASSWORD='new_password';

-- 4. Возобновить приём бинарного лога
START REPLICA IO_THREAD;

-- 5. Проверить, затем удалить старую учётную запись
SHOW REPLICA STATUS\G  -- → Replica_IO_Running: Yes, Last_IO_Error пуст
-- На источнике, после подтверждения работы канала:
DROP USER 'repl'@'10.0.1.20';
```

### 5. Дополнительное усиление

- **`REQUIRE X509`** вместо `REQUIRE SSL` на аккаунте: реплика должна
  предъявить клиентский сертификат — защита от использования украденного пароля
  без сертификата.
- **`PRIVILEGE_CHECKS_USER`** в `CHANGE REPLICATION SOURCE TO` (нужна динамическая
  привилегия `REPLICATION_APPLIER`): security context канала — применение
  транзакций идёт от имени отдельного пользователя с минимальными правами;
  в паре с `REQUIRE_ROW_FORMAT=1` ограничивает поверхность атаки на applier.
  Детали — в разделе «Replication Privilege Checks» мануала.
- Сетевая изоляция: порт 3306 источника открыт только для подсети реплик
  (nftables/iptables/security groups).

## Валидация

1. **Привилегии** — на источнике:

   ```sql
   SHOW GRANTS FOR 'repl'@'10.0.1.20';
   -- → GRANT REPLICATION SLAVE ON *.* TO `repl`@`10.0.1.20`
   --   (и REQUIRE SSL в выводе SHOW CREATE USER)
   ```

2. **TLS-канал** — на реплике:

   ```sql
   SHOW REPLICA STATUS\G
   -- Replica_IO_Running: Yes
   -- Source_SSL_Allowed: Yes
   -- Source_SSL_Verify_Server_Cert: Yes
   ```

   Механизм подтверждает корректность: при `SOURCE_SSL=1` незашифрованный
   fallback невозможен, поэтому работающий I/O-поток при
   `Source_SSL_Allowed: Yes` означает, что транспорт зашифрован. Дополнительно
   — таблица `performance_schema.replication_connection_configuration`
   (сценарий 3) и сетевая проверка: на порте 3306 трафик не читаем в cleartext
   (`tcpdump`/Wireshark).

3. **После ротации** — `Replica_IO_Running: Yes`, `Last_IO_Error` и
   `Last_IO_Error_Timestamp` пусты; в error log реплики нет ошибок подключения.

## Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Last_IO_Error: ... SSL connection error` (Error 2026) | TLS не включён на источнике (нет `ssl_cert`/`ssl_key`), неверные пути к CA/сертификатам, несовпадение `tls_version` | `SHOW VARIABLES LIKE 'ssl%'` на источнике; проверить пути в `SOURCE_SSL_*` и `SOURCE_TLS_VERSION` |
| `Source_SSL_Allowed: Ignored` | `SOURCE_SSL=1` задан, но реплика не поддерживает SSL | Включить TLS на реплике (ssl-опции `mysqld`) |
| `Access denied` после ротации | Не остановлен I/O-поток перед `CHANGE REPLICATION SOURCE TO`; пароль длиннее 32 символов; не совпадает host аккаунта | `STOP REPLICA IO_THREAD` → повторить; сократить пароль до 32 символов; проверить `'user'@'host'` |
| Ошибка обмена RSA-ключами при `caching_sha2_password` | Канал без TLS, а публичный ключ не запрошен | Включить TLS либо `GET_SOURCE_PUBLIC_KEY=1` / `SOURCE_PUBLIC_KEY_PATH` |
| `ERROR 3159 (HY000): Connections using insecure transport are prohibited` | На источнике `require_secure_transport=ON`, а канал без `SOURCE_SSL=1` | Перевести канал на TLS (`SOURCE_SSL=1`) |
| Подключение невозможно при `REQUIRE SSL` на аккаунте | На канале `SOURCE_SSL=0` — противоречие уровней | Привести уровни к единому виду: `SOURCE_SSL=1` на канале |

## Лучшие практика и очистка

- Всегда указывайте конкретный `host` в `CREATE USER` (IP реплики), не `%`.
- Длинные уникальные пароли; ротация — по сценарию 4; помните лимит 32
  символа для `SOURCE_PASSWORD`.
- TLS с верификацией (`SOURCE_SSL_VERIFY_SERVER_CERT=1`) в любых ненадёжных
  сетях; мониторить `Source_SSL_Allowed` (должно быть `Yes`).
- Мониторинг репликации в целом — в [lag_monitoring.md](./lag_monitoring.md).

**Откат TLS на канале** (только если сеть защищена иным образом):

```sql
STOP REPLICA IO_THREAD;
CHANGE REPLICATION SOURCE TO SOURCE_SSL=0;
START REPLICA IO_THREAD;
```

**Удаление репликационной учётной записи:** остановить канал
(`STOP REPLICA`), затем `DROP USER 'repl'@'10.0.1.20';` на источнике —
`FLUSH PRIVILEGES` не нужен.

## Дополнительная информация

### Граничные случаи

- `SOURCE_USER=''` допустимо, но канал не запустится без учётных данных — их
  придётся передавать в `START REPLICA` вручную (операторское вмешательство при
  каждом старте; используется, чтобы не записывать пароль в репозиторий).
- `SOURCE_SSL=1` на канале не требует, чтобы TLS был настроен на реплике —
  только на источнике; но `Source_SSL_Allowed` покажет `Ignored`, если реплика
  сама не поддерживает SSL.
- `SHOW REPLICA STATUS` не блокируется параллельным `STOP REPLICA` — безопасен
  для мониторинга.

### Внешние ресурсы

- [CHANGE REPLICATION SOURCE TO Statement (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/change-replication-source-to.html)
- [Privileges Provided by MySQL (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/privileges-provided.html)
- [SHOW REPLICA STATUS Statement (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/show-replica-status.html)
- [Setting Up Replication to Use Encrypted Connections (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-encrypted-connections.html)
- [When Privilege Changes Take Effect (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/privilege-changes.html)

### См. также

- **[Пошаговая настройка репликации](./setup_guide.md)** — запуск, seeding, `my.cnf`, GTID.
- **[Обзор репликации](./overview.md)** — архитектура и компоненты.
- **[Безопасность MySQL](../security.md)** — host-уровень TLS, keyring, `require_secure_transport`.
- **[GTID-репликация](./gtid.md)** — автопозиционирование (`SOURCE_AUTO_POSITION=1`).
- **[Переключение источника](./failover_switchover.md)** — failover/switchover.
- **[Полусинхронная репликация](./semi-sync-replication.md)** — гарантии доставки.
