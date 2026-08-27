# SMTP — протокол передачи почты

## Определения

**SMTP (Simple Mail Transfer Protocol — простой протокол передачи почты)** — сетевой протокол прикладного уровня, предназначенный для передачи сообщений электронной почты в сетях TCP/IP. Описан в **RFC 5321** (актуальная версия маршрутизации) и **RFC 5322** (формат сообщения).

**ESMTP (Extended SMTP)** — расширение базового протокола SMTP, добавляющее поддержку аутентификации, шифрования (STARTTLS) и передачи больших мультимедийных вложений (MIME). Все современные почтовые серверы (MTA) общаются исключительно по ESMTP.

**Ключевые характеристики:**
- **Транспорт:** использует [TCP](../Protocols/TCP/overview.md) для обеспечения надежной доставки.
- **Тип протокола:** текстовый, командно-ориентированный (состояния сессии управляются последовательностью команд и ответов).
- **Синхронность:** Полушаг (Half-duplex) — клиент отправляет команду и ждет ответа. Оптимизируется через расширение PIPELINING.

> **См. также:** **[Обзор DNS](./DNS/dns.md)**, **[Записи DNS для почты](./DNS/dns_records.md)**, **[Модель OSI](../OSI_TCP_IP_Model/osi_model.md)**

## Основные концепции

### Порты и шифрование (STARTTLS vs Implicit TLS)

Исторически SMTP работал в открытом виде. Сегодня шифрование обязательно, но реализуется двумя разными путями:

1. **Порт 25 (SMTP):** Основной порт для связи между серверами (**MTA-to-MTA**). Трафик начинается в открытом текстовом виде, затем (при поддержке) переводится в зашифрованный режим через команду `STARTTLS` (Opportunistic TLS). Часто блокируется провайдерами у клиентов для борьбы с ботнетами.
2. **Порт 587 (Submission):** Рекомендованный порт для отправки почты почтовым клиентом (**MUA**) на сервер. Требует обязательной аутентификации (SMTP AUTH) и использует `STARTTLS` для защиты учетных данных.
3. **Порт 465 (SMTPS / Implicit TLS):** Соединение с самого начала устанавливается поверх TLS/SSL-туннеля. Текстовый обмен начинается *только* после успешного криптографического рукопожатия. В 2018 году (RFC 8314) IETF рекомендовал этот порт как предпочтительный для MUA (вместо 587), так как он предотвращает атаки типа STRIPTLS.

### Роли и компоненты системы доставки

1. **MUA (Mail User Agent):** Почтовый клиент (Outlook, Thunderbird, Apple Mail).
2. **MSA (Mail Submission Agent):** Принимающий сервер (обычно порт 587 или 465). Валидирует отправителя, проверяет авторизацию и передает письмо дальше.
3. **MTA (Mail Transfer Agent):** Сервер маршрутизации (Postfix, Exim, Sendmail). Принимает решения о том, на какой следующий сервер (по MX-записи) нужно переслать письмо.
4. **MDA (Mail Delivery Agent):** Компонент локальной доставки (Dovecot, Cyrus). Размещает входящее письмо в файловой системе получателя (Maildir/mbox) и выдает его по протоколам IMAP/POP3.

### Полный путь письма (End-to-End Flow)

```
[Отправитель]                                    [Получатель]
    MUA (Outlook/Thunderbird)                        MUA
        │                                                ▲
        │ 1. SMTP Submission (порт 465/587)             │ 6. IMAP/POP3 (порт 993/995)
        ▼                                                │
    MSA (Postfix Submission)                        MDA (Dovecot LMTP)
        │                                                ▲
        │ 2. DNS MX Lookup                              │ 5. Local Delivery
        ▼                                                │
    MTA (Postfix)  ─────3. SMTP MTA-to-MTA (порт 25)─────▶  MTA (Remote)
                    ◀─────4. SMTP Response (250/550)─────
```

**Этапы доставки:**

| Этап | Протокол | Порт | Компонент | Описание |
| :--- | :--- | :--- | :--- | :--- |
| **1. Submission** | SMTP (STARTTLS) | 587 | MSA | Клиент отправляет письмо на «свой» сервер. Обязательная аутентификация. |
| **2. DNS Resolution** | DNS | 53 | MTA | MTA запрашивает MX-запись домена получателя. При отсутствии MX — используется A/AAAA (RFC 5321 §5.1). |
| **3. Relay** | SMTP (STARTTLS) | 25 | MTA→MTA | MTA устанавливает соединение с следующим сервером в цепочке (MX). Opportunistic TLS. |
| **4. Acceptance** | SMTP | 25 | Remote MTA | Удалённый MTA проверяет SPF/DKIM/DMARC, принимает или отклоняет письмо. |
| **5. Local Delivery** | LMTP/LDA | — | MDA | MTA передаёт письмо MDA (Dovecot LMTP) для сохранения в Maildir/mbox. |
| **6. Retrieval** | IMAP/POP3 | 993/995 | MUA | Почтовый клиент забирает письмо с сервера (TLS обязателен). |

> **Важно:** Письмо может проходить через несколько MTA (hops) при маршрутизации через промежуточные серверы (backups, smarthosts). Каждый MTA добавляет заголовок `Received:` — цепочка этих заголовков является основой для аудита доставки.

### Сравнение MTA

| MTA | Тип | Язык | Конфигурация | Особенности | Применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Postfix** | Fast, Secure | C | `main.cf` + `master.cf` | Modular architecture, built-in anti-spam, Milter-совместимость | Стандарт для большинства Linux-дистрибутивов |
| **Exim** | Flexible | C | Monolithic config file | Гибкая маршрутизация,мощные ACL, Content-Scanning | Debian/Ubuntu (по умолчанию до 2022) |
| **Sendmail** | Legacy | C | `sendmail.cf` (M4) | Историческая основа, сложная конфигурация | Legacy-системы, не рекомендуется для новыхразвёртывания |
| **Haraka** | Modern | JavaScript | `haraka.cfg` + plugins | Плагинная архитектура, Node.js, высокая производительность | Высоконагруженные среды, кастомные фильтры |
| **OpenSMTPD** | Minimalist | C | `smtpd.conf` | Простота, portable (BSD/Linux), акцент на безопасность | BSD-системы, minimalist setups |
| **Chasquid** | Modern | Go | YAML config | Простой, быстрый, встроенные проверки | Small-to-medium deployments |

**Критерии выбора MTA:**
- **Простота:** Postfix (modular, понятная конфигурация)
- **Гибкость маршрутизации:** Exim (complex routing rules)
- **Производительность:** Haraka (Node.js, concurrent connections)
- **Безопасность по умолчанию:** OpenSMTPD (secure defaults)
- **Масштабируемость:** Postfix +content-сканеры (DCC, SpamAssassin, Rspamd)

### Формат сообщения (RFC 5322 и MIME)

Само сообщение в SMTP (то, что передается после команды `DATA`) концептуально отделено от команд маршрутизации (конверта).
Оно состоит из:
*   **Заголовков (Headers):** `From:`, `To:`, `Subject:`, `Date:`, `Message-ID:`. Они предназначены *только* для отображения пользователю. SMTP-сервер маршрутизирует письмо на основе команд `MAIL FROM` и `RCPT TO`, а не заголовков (поэтому реальный отправитель спама часто не совпадает с полем `From:`).
*   **Тела (Body):** Отделено от заголовков пустой строкой (`\r\n\r\n`).
*   **MIME (Multipurpose Internet Mail Extensions):** Стандарт кодирования (обычно Base64) для передачи HTML, картинок и файлов внутри 7-битного текстового протокола SMTP. Задается заголовком `Content-Type: multipart/mixed; boundary="..."`.

### Команды протокола ESMTP

| Команда | Описание |
| :--- | :--- |
| **EHLO** | Расширенное приветствие клиента. Сервер возвращает список поддерживаемых функций (STARTTLS, AUTH, PIPELINING, 8BITMIME). |
| **MAIL FROM** | Адрес отправителя конверта (Envelope-From). Сюда будут приходить отчеты об ошибках (NDR/Bounces). |
| **RCPT TO** | Адрес получателя конверта (Envelope-To). Определяет реальный маршрут доставки. |
| **DATA** | Инициация передачи тела письма. Завершается точкой на пустой строке (`\r\n.\r\n`). |
| **AUTH** | Аутентификация пользователя (см. ниже). |
| **QUIT** | Корректное завершение TCP-сессии. |

### Расширения ESMTP (Extended SMTP)

После команды `EHLO` сервер возвращает список поддерживаемых расширений. Основные:

| Расширение | RFC | Описание |
| :--- | :--- | :--- |
| **STARTTLS** | RFC 3207 | Переключение соединения на TLS. Клиент отправляет `STARTTLS`, сервер отвечает `220`, начинается TLS handshake. |
| **AUTH** | RFC 4954 | Аутентификация. Поддерживает PLAIN, LOGIN, CRAM-MD5, XOAUTH2. |
| **PIPELINING** | RFC 2926 | Позволяет клиенту отправлять несколько команд подряд без ожидания ответа на каждую. Увеличивает пропускную способность в 2-3 раза. |
| **8BITMIME** | RFC 6152 | Передача 8-битных данных (MIME). Разрешает Content-Type спроизвольной кодировкой. |
| **SMTPUTF8** | RFC 6531 | Поддержка Unicode (UTF-8) в заголовках и адресах. Используется для международных доменов (IDN). |
| **CHUNKING** | RFC 3030 | Передача данных блоками (chunks) вместо одного потока. Позволяет передавать файлы >2GB. Завершается командой `BDOT`. |
| **SIZE** | RFC 1870 | Объявление максимального размера сообщения (`SIZE 10240000`). Клиент проверяет размер перед отправкой. |
| **DSN** | RFC 3461 | Delivery Status Notification — уведомления о доставке (-success, -failure, -delay). Аналоги: `MAIL FROM:<sender@example.com> RET=FULL ENVID=abc123`. |
| **BURL** | RFC 4468 | Позволяет отправлять письма со ссылкой на внешний URL (для webmail, URI-based submission). |
| **CONNEG** | RFC 6153 | Согласование фильтров (content filters) между клиентом и сервером. |

**Пример расширенного диалога с PIPELINING:**
```bash
S: 250-PIPELINING
S: 250-SIZE 10240000
S: 250-8BITMIME
S: 250-AUTH PLAIN LOGIN
S: 250 STARTTLS

# Клиент использует PIPELINING:
C: MAIL FROM:<a@b.com> SIZE=1234
C: RCPT TO:<c@d.com>
C: DATA
S: 250 2.1.0 Ok
S: 250 2.1.5 Ok
S: 354 End data with <CR><LF>.<CR><LF>
# ... передача данных ...
```

### Queue Management (Управление очередью)

MTA хранит письма в очередях до успешной доставки. Типичная структура очереди Postfix:

| Очередь | Назначение | Содержимое |
| :--- | :--- | :--- |
| **Active** | Письма, обрабатываемые прямо сейчас | Макс. `smtpd_client_connection_count_limit` (по умолчанию 50) |
| **Deferred** | Письма с временной ошибкой (4xx) | Повторные попытки доставки с экспоненциальной задержкой |
| **Hold** | Письма, задержанные вручную (администратором) | Не обрабатываются до снятия с hold |
| **Incoming** | Новые письма, принятые от MSA | Ожидают обработки MTA |
| **Corrupt** | Повреждённые записи очереди | Для отладки |

**Управление очередью в Postfix:**
```bash
# Просмотр очереди
postqueue -p

# Повторная обработка всей очереди
postqueue -f

# Повторная обработка для конкретного домена
postqueue -s example.com

# Удаление письма из очереди
postsuper -d <queue_id>

# Удержание всех письмо (hold)
postsuper -H ALL

# Снятие с hold
postsuper -H ALL

# Отмена доставки (удаление)
postsuper -d ALL

# Ограничение размера очереди
postconf -e "queue_run_delay=300s"  # Интервал между попытками (5 мин)
postconf -e "maximal_queue_lifetime=5d"  # Макс. время жизни в очереди
postconf -e "bounce_queue_lifetime=1d"  # Время жизни bounce
```

### Механизмы аутентификации (SMTP AUTH)

*   **PLAIN:** Логин и пароль передаются одной строкой в Base64. Абсолютно несекьюрно без применения TLS.
*   **LOGIN:** Похож на PLAIN, но логин и пароль запрашиваются сервером раздельно.
*   **CRAM-MD5 / DIGEST-MD5:** Аутентификация по схеме Challenge-Response (хэши без передачи пароля). В современных сетях вытесняются PLAIN+TLS (так как TLS защищает лучше).
*   **XOAUTH2:** Использование токенов OAuth (применяется в Google Workspace, Microsoft 365).

### Коды ответов сервера

- **2xx (Success):** Операция выполнена успешно (например, `250 2.0.0 Ok: queued as ABC12345`).
- **3xx (Intermediate):** Сервер готов к приему данных (например, `354 End data with <CR><LF>.<CR><LF>`).
- **4xx (Transient Failure):** Временная ошибка (Greylisting, перегрузка). Отправитель должен поставить письмо в очередь и повторить попытку позже.
- **5xx (Permanent Failure):** Фатальная ошибка (Пользователь не найден, блок по IP). Попытки прекращаются, генерируется Bounce (отлуп).

## Практические сценарии

### Тестирование SMTP вручную (Raw Session)

Для диагностики проблем с TLS (порт 465) используется OpenSSL. Для порта 25/587 можно использовать `telnet` (без шифрования) или добавить опцию `-starttls smtp` в OpenSSL.

```bash
# Подключение к Submission порту (Implicit TLS)
openssl s_client -connect smtp.example.com:465 -quiet

# Типовой диалог (S: сервер, C: клиент)
S: 220 smtp.example.com ESMTP Postfix
C: EHLO myclient.local
S: 250-smtp.example.com
S: 250-PIPELINING
S: 250-SIZE 10240000
S: 250 AUTH PLAIN LOGIN
C: AUTH PLAIN AHVzZXIAcGFzc3dvcmQ=  # Base64 строка (\0user\0password)
S: 235 2.7.0 Authentication successful
C: MAIL FROM:<sender@example.com>
S: 250 2.1.0 Ok
C: RCPT TO:<recipient@domain.com>
S: 250 2.1.5 Ok
C: DATA
S: 354 End data with <CR><LF>.<CR><LF>
C: Subject: SRE Test Message
C: From: sender@example.com
C: To: recipient@domain.com
C:
C: Technical check of SMTP delivery path.
C: .
S: 250 2.0.0 Ok: queued as ABC12345
C: QUIT
S: 221 2.0.0 Bye
```

### Конфигурация Postfix (основы)

**Postfix** — наиболее распространённый MTA для Linux. Архитектура: модульная (smtpd, cleanup, qmgr, trivial-rewrite, smtp).

**Установка:**
```bash
# Debian/Ubuntu
sudo apt install postfix

# Fedora/RHEL
sudo dnf install postfix

# При установке выбрать "Internet Site" или "Satellite"
```

**Основные файлы конфигурации:**
```
/etc/postfix/
├── main.cf          # Основная конфигурация (параметры, домены, TLS)
├── master.cf        # Определение сервисов (smtpd, smtp, pickup, etc.)
├── canonical        # Маппинг адресов (sender/recipient rewrite)
├── virtual          # Виртуальные домены и ящики
├── transport        # Таблица транспорта (для multi-hop routing)
└── header_checks    # Правила проверки заголовков (antispam)
```

**Базовая конфигурация (`/etc/postfix/main.cf`):**
```bash
# === Основные параметры ===
myhostname = mail.example.com
mydomain = example.com
myorigin = $mydomain
mydestination = $myhostname, localhost.$mydomain, localhost, $mydomain
relay_domains =  # Не является relay для третьих лиц

# === Сетевые параметры ===
inet_interfaces = all
inet_protocols = ipv4, ipv6

# === TLS (обязательно для современных серверов) ===
smtpd_tls_cert_file = /etc/letsencrypt/live/mail.example.com/fullchain.pem
smtpd_tls_key_file = /etc/letsencrypt/live/mail.example.com/privkey.pem
smtpd_tls_security_level = may  # Opportunistic TLS (порт 25)
smtp_tls_security_level = may   # Для исходящих соединений

# Принудительный TLS для Submission (порт 587):
# (настраивается в master.cf через -o smtpd_tls_security_level=encrypt)

# === Аутентификация ===
smtpd_sasl_type = dovecot
smtpd_sasl_path = private/auth
smtpd_sasl_auth_enable = yes
smtpd_sasl_security_options = noanonymous
smtpd_sasl_local_domain = $myhostname

# === Ограничения размера ===
message_size_limit = 10240000  # 10 MB
mailbox_size_limit = 0  # Без ограничений (для Maildir)

# === Антиспам (базовые) ===
smtpd_helo_required = yes
smtpd_helo_restrictions =
    permit_mynetworks,
    reject_invalid_helo_hostname,
    reject_non_fqdn_helo_hostname

smtpd_sender_restrictions =
    permit_mynetworks,
    reject_non_fqdn_sender,
    reject_unknown_sender_domain

smtpd_recipient_restrictions =
    permit_mynetworks,
    permit_sasl_authenticated,
    reject_unauth_destination,
    reject_non_fqdn_recipient,
    reject_unknown_recipient_domain

# === Anti-bludding/ANTI-FLOOD ===
smtpd_client_connection_rate_limit = 10
smtpd_client_message_rate_limit = 100
anvil_rate_time_unit = 60s

# === Milter (DKIM signing, SpamAssassin) ===
milter_default_action = accept
milter_protocol = 6
smtpd_milters = local:opendkim/opendkim.sock, local:spamass/spamass.sock
non_smtpd_milters = local:opendkim/opendkim.sock
```

**Настройка порта 587 (Submission) в `master.cf`:**
```bash
# Добавить в конец /etc/postfix/master.cf:
submission     inet  n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt  # Принудительный TLS
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
```

**Настройка порта 465 (SMTPS) в `master.cf`:**
```bash
# Добавить в конец /etc/postfix/master.cf:
smtps     inet  n       -       y       -       -       smtpd
  -o syslog_name=postfix/smtps
  -o smtpd_tls_wrappermode=yes  # Implicit TLS
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject
  -o milter_macro_daemon_name=ORIGINATING
```

**Настройка Milter (DKIM через OpenDKIM):**
```bash
# Установка OpenDKIM
sudo apt install opendkim opendkim-tools

# Добавить Postfix в группу opendkim
sudo usermod -a -G opendkim postfix

# /etc/opendkim.conf
Mode                    sv
Canonicalization        relaxed/simple
ExternalIgnoreList      refile:/etc/opendkim/TrustedHosts
InternalHosts           refile:/etc/opendkim/TrustedHosts
KeyTable                refile:/etc/opendkim/KeyTable
SigningTable             refile:/etc/opendkim/SigningTable
Socket                  local:/var/spool/postfix/opendkim/opendkim.sock

# Генерация ключей для example.com
sudo opendkim-genkey -D /etc/opendkim/keys -d example.com -s default
sudo chown -R opendkim:opendkim /etc/opendkim
```

**Перезапуск и проверка:**
```bash
# Проверка конфигурации
postfix check

# Перезапуск
sudo systemctl restart postfix

# Мониторинг логов
sudo tail -f /var/log/mail.log

# Проверка очереди
postqueue -p

# Тестирование
swaks --to user@example.com --from sender@mydomain.com --server mail.example.com --port 587 --auth PLAIN --auth-user user --auth-password pass --tls
```

### Конфигурация Dovecot (MDA + IMAP/POP3)

**Dovecot** — современный MDA/IMAP/POP3-сервер. Используется как локальный агент доставки (LMTP) и сервер для почтовых клиентов.

**Установка:**
```bash
# Debian/Ubuntu
sudo apt install dovecot-core dovecot-imapd dovecot-pop3d dovecot-lmtpd

# Fedora/RHEL
sudo dnf install dovecot
```

**Основные файлы конфигурации:**
```
/etc/dovecot/
├── dovecot.conf         # Главный конфиг (обычно includes)
├── conf.d/
│   ├── 10-auth.conf     # Аутентификация
│   ├── 10-ssl.conf      # SSL/TLS
│   ├── 10-mail.conf     # Mailbox format
│   ├── 10-master.conf   # Service definitions (LMTP, imap, pop3)
│   ├── 10-logging.conf  # Логирование
│   └── 15-mailboxes.conf # Mailbox definitions (Sent, Drafts, etc.)
└── sieve.d/             # Sieve фильтры (server-side sorting)
```

**Базовая конфигурация LMTP (для доставки от Postfix):**

`/etc/dovecot/conf.d/10-master.conf`:
```bash
service lmtp {
  unix_listener /var/spool/postfix/private/dovecot-lmtp {
    mode = 0600
    user = postfix
    group = postfix
  }
}
```

`/etc/dovecot/conf.d/10-mail.conf`:
```bash
# Формат mailbox
mail_location = maildir:/var/mail/vhosts/%d/%n/Maildir

# uid/gid для доставки
first_valid_uid = 500
last_valid_uid = 5000
```

**Настройка SSL:**

`/etc/dovecot/conf.d/10-ssl.conf`:
```bash
# Принудительный SSL (рекомендуется)
ssl = required
ssl_cert = </etc/letsencrypt/live/mail.example.com/fullchain.pem
ssl_key = </etc/letsencrypt/live/mail.example.com/privkey.pem

# Минимальные TLS-версии
ssl_min_protocol = TLSv1.2
ssl_prefer_server_ciphers = yes

# Шифры
ssl_cipher_list = ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
```

**Настройка аутентификации (LDAP/PAM/passwd-file):**

`/etc/dovecot/conf.d/10-auth.conf`:
```bash
# Отключить plaintext (требовать SSL)
disable_plaintext_auth = yes

# Драйверы аутентификации
auth_mechanisms = plain login

# PAM (стандартный Linux)
!include auth-system.conf.ext

# Или LDAP:
# !include auth-ldap.conf.ext

# Или passwd-file:
# !include auth-passwdfile.conf.ext
```

**Настройка Postfix для LMTP-доставки:**
```bash
# В /etc/postfix/main.cf:
dovecot_destination_recipient_limit = 1
virtual_transport = lmtp:unix:private/dovecot-lmtp
```

**Создание пользователей (для passwd-file):**
```bash
# Генерация пароля
doveadm pw -s SHA256-CRYPT -u user@example.com

# Создание /etc/dovecot/users
user@example.com:{SHA256-CRYPT}$5$...  :500:500::/var/mail/vhosts/example.com/user
```

**Проверка конфигурации:**
```bash
# Проверка синтаксиса
doveconf -n

# Тест аутентификации
doveadm auth test user@example.com password

# Перезапуск
sudo systemctl restart dovecot

# Мониторинг
sudo tail -f /var/log/dovecot.log
```

## Безопасность и борьба со спамом

### Bounce, NDR и DSN

**Bounce (Отлуп)** — возврат письма отправителю при невозможности доставки. Определяется кодом ответа:

| Код | Тип | Описание | Действие MTA |
| :--- | :--- | :--- | :--- |
| **2.x.x** | Success | Успешная доставка | Письмо доставлено |
| **4.x.x** | Transient | Временная ошибка (перегрузка, greylisting) | Повторная попытка через очередь |
| **5.x.x** | Permanent | Фатальная ошибка (адрес не найден, домен не существует) | Немедленный Bounce отправителю |

**Расширенные коды ошибок (RFC 3463):**

| Префикс | Категория | Пример |
| :--- | :--- | :--- |
| **5.1.x** | Адрес | `5.1.1` — Mailbox not found; `5.1.2` — Bad destination system |
| **5.2.x** | Mailbox | `5.2.1` — Mailbox disabled; `5.2.2` — Mailbox full |
| **5.3.x** | Система | `5.3.0` — Mail system full; `5.3.1` — Storage exceeded |
| **5.4.x** | Маршрутизация | `5.4.1` — No answer; `5.4.4` — Unable to route |
| **5.5.x** | Протокол | `5.5.0` — Syntax error; `5.5.1` — Invalid command |
| **5.6.x** | Содержание | `5.6.0` — Message content; `5.6.1` — Media not supported |
| **5.7.x** | Политика | `5.7.1` — Delivery not authorized; `5.7.25` — DNS lookup failed |

**DSN (Delivery Status Notification, RFC 3461):**
```bash
# Запрос уведомления об успешной доставке:
MAIL FROM:<sender@example.com> RET=FULL ENVID=abc123.456

# Коды RET:
# RET=FULL   — полный заголовок + тело в уведомлении
# RET=HDRS   — только заголовки

# Коды ENVID — уникальный идентификатор для трекинга
```

**Типичные ошибки доставки:**

| Ошибка | Код | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **User unknown** | 550 5.1.1 | Ящик не существует на целевом сервере | Проверить адрес получателя |
| **Mailbox full** | 552 5.2.2 | Нет места на диске получателя | Освободить место или связаться с администратором |
| **Relay denied** | 554 5.7.1 | Отправка от unauthenticated клиента | Аутентифицироваться на порту 587 |
| **Blocked** | 554 5.7.1 | IP отправителя в RBL | Проверить IP на mxtoolbox.com, запросить delist |
| **SPF fail** | 550 5.7.1 | Отправитель не авторизован по SPF | Проверить SPF-запись DNS |
| **Greylisted** | 451 4.7.1 | Серый список — первая попытка | Повторить доставку через 5-15 минут |

### Диагностика SMTP

#### Инструменты

| Инструмент | Назначение | Установка |
| :--- | :--- | :--- |
| **swaks** | Swiss Army Knife для SMTP — полное тестирование | `apt install swaks` |
| **telnet** | Ручной SMTP-диалог (без шифрования) | Стандартный |
| **openssl** | Тест TLS-соединений | Стандартный |
| **mxtoolbox.com** | Онлайн-проверка MX, SPF, DKIM, DMARC, blacklists | Веб |
| **mailx/mail** | Отправка письма из CLI | `apt install mailutils` |
| **postqueue/postcat** | Управление и просмотр очереди Postfix | `aptic postfix` |
| **doveadm** | Диагностика Dovecot (пользователи, auth, mailbox) | `aptic dovecot-core` |

#### Тестирование с swaks

```bash
# Базовый тест доставки
swaks --to user@example.com --from sender@mydomain.com --server mail.example.com

# Тест с аутентификацией (порт 587)
swaks --to user@example.com --from sender@mydomain.com \
  --server mail.example.com --port 587 \
  --auth PLAIN --auth-user user --auth-password pass

# Тест с TLS
swaks --to user@example.com --from sender@mydomain.com \
  --server mail.example.com --port 465 --tls

# Тест STARTTLS (порт 25)
swaks --to user@example.com --from sender@mydomain.com \
  --server mail.example.com --port 25 --tls

# Тест DKIM-подписи
swaks --to user@example.com --from sender@mydomain.com \
  --server mail.example.com --header "DKIM-Signature: v=1; a=rsa-sha256; ..."

# Проверка MX-записи
dig MX example.com +short

# Проверка SPF
dig TXT example.com +short | grep "v=spf1"

# Проверка DKIM
dig TXT default._domainkey.example.com +short

# Проверка DMARC
dig TXT _dmarc.example.com +short

# Проверка DANE/TLSA
dig TLSA _25._tcp.mail.example.com +short
```

#### Мониторинг логов

**Postfix:**
```bash
# Основные логи
sudo tail -f /var/log/mail.log

# Фильтрация по ключевым словам
sudo grep "reject" /var/log/mail.log
sudo grep "warning" /var/log/mail.log
sudo grep "fatal" /var/log/mail.log

# Статистика доставки
sudo grep "status=sent" /var/log/mail.log | wc -l
sudo grep "status=bounced" /var/log/mail.log | wc -l
sudo grep "status=deferred" /var/log/mail.log | wc -l

# Просмотр конкретного письма по queue_id
sudo grep "ABC12345" /var/log/mail.log

# Postfix-specific
postcat -q ABC12345  # Просмотр содержимого письма в очереди
postcat -h ABC12345  # Только заголовки
```

**Dovecot:**
```bash
# Основные логи
sudo tail -f /var/log/dovecot.log

# Аутентификация
sudo grep "auth" /var/log/dovecot.log
sudo grep "login" /var/log/dovecot.log

# Ошибки
sudo grep "Error" /var/log/dovecot.log
sudo grep "Fatal" /var/log/dovecot.log

# Статистика
sudo doveadm log find
```

#### Типичные ошибки и решения

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Письма не отправляются** | Порт 25 заблокирован провайдером | `telnet smtp.example.com 25` — нет ответа | Использовать port 587/465; настроить smarthost |
| **Письма отклоняются** | SPF/DKIM/DMARC fail | `dig TXT example.com` — проверить записи | Настроить DNS-записи для почты |
| **Белый экран в почтовом клиенте** | Dovecot не запущен | `systemctl status dovecot` | Запустить Dovecot, проверить логи |
| **Аутентификация не работает** | Неправильный path до сокета | `doveconf -n` — проверить socket path | Исправить `smtpd_sasl_path` в Postfix |
| **Письма попадают в спам** | Нет DKIM-подписи | `opendkim-testkey -d example.com -s default` | Настроить OpenDKIM, опубликовать DNS TXT |
| **Доставка задерживается** | Greylisting на целевом сервере | `grep "status=deferred" /var/log/mail.log` | Подождать повторной попытки; попросить whitelist |
| **TLS handshake fails** | Устаревший сертификат | `openssl s_client -connect mail.example.com:465` | Обновить сертификат (Let's Encrypt) |
| **Почта не доходит до MDA** | LMTP-сокет недоступен | `doveadm auth test` — проверить аутентификацию | Проверить ownership сокета, перезапустить Dovecot |

### Блокировка порта 25 провайдерами

**Почему блокируют:** Борьба с ботнетами и спамом. Порт 25 используется для прямой рассылки (MTA-to-MTA), и домашние компьютеры не должны отправлять почту напрямую.

**Как проверить:**
```bash
# Тест доступности порта 25
telnet smtp.gmail.com 25

# Или через nc
nc -zv mail.example.com 25

# Или через swaks
swaks --to test@gmail.com --from user@mydomain.com --server mydomain.com --port 25
```

**Решения и обходы:**

| Решение | Описание | Применение |
| :--- | :--- | :--- |
| **Использовать порт 587** | Submission-порт, не блокируется провайдерами | Почтовые клиенты (MUA) |
| **Использовать порт 465** | Implicit TLS, не блокируется | Почтовые клиенты (MUA) |
| **Smarthost/Relay** | Отправка через промежуточный сервер (Amazon SES, SendGrid, Mailgun) | Серверы без статического IP |
| **VPN/SSH Tunnel** | Обход блокировки через туннель | Временное решение |
| **IPv6** | Некоторые провайдеры блокируют только IPv4 порт 25 | Если есть IPv6-подключение |
| **Запрос разблокировки** | У провайдера можно запросить разблокировку порта 25 | Бизнес-аккаунты |

**Настройка Relay (Smarthost) в Postfix:**
```bash
# /etc/postfix/main.cf
relayhost = [smtp.sendgrid.net]:587
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous
smtp_tls_security_level = encrypt
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt

# Создание файла с учётными данными:
echo "[smtp.sendgrid.net]:587 apikey:SG.xxx" | sudo tee /etc/postfix/sasl_passwd
sudo postmap /etc/postfix/sasl_passwd
sudo systemctl restart postfix
```

Так как SMTP изначально не имел механизмов подтверждения личности, были внедрены надстройки для верификации доменов.

### Триада верификации (SPF, DKIM, DMARC)

1. **SPF (Sender Policy Framework):** DNS-запись (TXT), регламентирующая, какие IP-адреса имеют право отправлять почту с адресом Envelope-From (команда `MAIL FROM`) данного домена. Защищает от прямой подделки сервера отправки.
2. **DKIM (DomainKeys Identified Mail):** Асимметричная криптография. Отправитель (MTA) подписывает письмо приватным ключом и добавляет заголовок `DKIM-Signature`. Получатель берет публичный ключ из DNS домена и проверяет подпись. Гарантирует неизменность тела и заголовков (включая `From:`).
3. **DMARC (Domain-based Message Authentication):** Политика, которая связывает SPF и DKIM с заголовком `From:` (тем, что видит пользователь). DMARC требует "Выравнивания" (Alignment) — домен в SPF или DKIM должен совпадать с доменом в видимом адресе `From:`.
   - **p=none:** Мониторинг.
   - **p=quarantine:** При провале доставить в папку "Спам".
   - **p=reject:** При провале заблокировать на уровне SMTP-сессии (5xx ошибка).

### Методы защиты на стороне MTA

- **Greylisting (Серые списки):** MTA отвечает временной ошибкой `451` первому обращению незнакомой пары (IP-отправителя, отправитель, получатель). Легитимный MTA поставит письмо в очередь и повторит отправку. Спам-бот обычно сбросит соединение.
- **RBL/DNSBL (Real-time Blackhole List):** Черные списки IP-адресов спамеров, проверяемые через DNS-запросы.
- **PTR (Reverse DNS):** Проверка наличия обратной записи IP-адреса отправителя. Одно из базовых требований RFC для почтовых серверов.

### SMTP Smuggling

**SMTP Smuggling** (уязвимость выявлена в 2023 году) — класс атак, использующий расхождения в обработке символа завершения письма (`\r\n.\r\n`) между разными серверами (например, принимающим сервером-фронтендом и внутренним MTA).

- **Принцип:** Злоумышленник отправляет специально сформированные переводы строк (например, `\n.\r\n`), которые фронтенд игнорирует (считая частью тела), а бэкенд воспринимает как конец письма и начало новой SMTP-сессии (команд).
- **Результат:** Позволяет «пронести» (smuggle) поддельное письмо от доверенного домена (например, spoofing `admin@microsoft.com`), успешно проходя проверки SPF.
- **Защита:** Строгое соблюдение RFC (прием только `\r\n`), обновление MTA (Postfix, Exim) и использование параметров вроде `smtpd_forbid_bare_newline`.

## Дополнительная информация

### Связанные протоколы и стандарты

| Протокол | RFC | Описание | Связь с SMTP |
| :--- | :--- | :--- | :--- |
| **IMAP** | RFC 9051 | Доступ к почте (readonly) | MDA → MUA (получение) |
| **POP3** | RFC 1939 | Загрузка почты на клиент | MDA → MUA (получение, alternate) |
| **LMTP** | RFC 2033 | Локальная доставка (альтернатива SMTP для MDA) | MTA → MDA |
| **MIME** | RFC 2045-2049 | Кодирование вложений | Формат сообщения |
| **Sieve** | RFC 5228 | Серверные фильтры | Сортировка на MDA |
| **JMAP** | RFC 8620 | Современная замена IMAP/SMTP | Новый протокол для MUA |
| **MTA-STS** | RFC 8461 | Mandatory TLS для MTA-to-MTA | Защита от downgrade |
| **DANE** | RFC 6698 | Привязка TLS-сертификатов к DNS | Защита от MITM |
| **ARC** | RFC 8617 | Authenticated Received Chain | Аудит цепочки аутентификации |
| **BIMI** | RFC Draft | Brand Indicators for Message Identification | Логотип бренда в почтовом клиенте |

### RFC и стандарты

| RFC | Название | Описание |
| :--- | :--- | :--- |
| **RFC 5321** | Simple Mail Transfer Protocol | Основной стандарт SMTP. Определяет команды, коды ответов, маршрутизацию. |
| **RFC 5322** | Internet Message Format | Структура заголовков и тела сообщения (From, To, Subject, MIME). |
| **RFC 8314** | Cleartext Considered Obsolete | Рекомендация порта 465 (Implicit TLS) вместо STARTTLS на 587. |
| **RFC 3207** | STARTTLS | Механизм переключения на TLS поверх незащищённого соединения. |
| **RFC 4954** | SMTP AUTH | Механизмы аутентификации (PLAIN, LOGIN, XOAUTH2). |
| **RFC 2926** | PIPELINING | Пакетная отправка команд для увеличения throughput. |
| **RFC 3461** | DSN | Delivery Status Notification — уведомления о доставке. |
| **RFC 3463** | Enhanced Status Codes | Расширенные коды ошибок (5.1.x, 5.2.x, etc.). |
| **RFC 6152** | 8BITMIME | Передача 8-битных данных. |
| **RFC 6531** | SMTPUTF8 | Поддержка Unicode (UTF-8) в адресах. |
| **RFC 3030** | CHUNKING | Передача данных блоками (BDOT). |
| **RFC 4468** | BURL | URL-based message submission. |
| **RFC 6153** | CONNEG | Согласование фильтров контента. |
| **RFC 7208** | SPF | Sender Policy Framework — авторизация IP для отправки. |
| **RFC 6376** | DKIM | DomainKeys Identified Mail — криптографическая подпись. |
| **RFC 7489** | DMARC | Domain-based Message Authentication, Reporting & Conformance. |
| **RFC 8461** | MTA-STS | SMTP MTA Strict Transport Security. |
| **RFC 8617** | ARC | Authenticated Received Chain (промежуточная аутентификация). |
| **RFC 2033** | LMTP | Local Mail Transfer Protocol. |
| **RFC 1939** | POP3 | Post Office Protocol. |
| **RFC 9051** | IMAP | Internet Message Access Protocol. |

### См. также

- [DNS-записи для почты](./DNS/dns_records.md) — MX, SPF, DKIM, DMARC, DANE
- [TLS/SSL](./tls.md) — STARTTLS, Implicit TLS, сертификаты
- [TCP](./TCP/overview.md) — транспортная основа SMTP
- [OSI/TCP-IP модель](../OSI_TCP_IP_Model/osi_model.md) — прикладной уровень
