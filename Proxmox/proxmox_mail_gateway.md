# Proxmox Mail Gateway (PMG)

## Определения

**Proxmox Mail Gateway (PMG)** -- бесплатный open-source почтовый шлюз с веб-интерфейсом для защиты почтовой инфраструктуры. Работает как промежуточный узел между интернетом и почтовым сервером, фильтруя входящий и исходящий трафик.

**Antispam** -- система фильтрации нежелательной почты (спама). PMG использует SpamAssassin, Rspamd и другие инструменты для оценки и блокировки спам-сообщений.

**Antivirus** -- система обнаружения и блокировки вирусов в вложениях电子邮件. PMG интегрируется с ClamAV и другими антивирусными движками.

**SpamAssassin** -- open-source antispam движок, использующий эвристический анализ, 규칙ベース 필터링 и Bayesian classification для определения спама.

**DKIM (DomainKeys Identified Mail)** -- протокол аутентификации электронной почты, позволяющий получателям проверять, что письмо действительно отправлено заявленным доменом и не было изменено в пути.

**SPF (Sender Policy Framework)** -- протокол аутентификации, определяющий, какие серверы имеют право отправлять почту от имени домена. Публикуется в DNS-записи TXT.

**DMARC (Domain-based Message Authentication, Reporting & Conformance)** -- протокол, объединяющий SPF и DKIM с политикой обработки писем, которые не прошли проверку. Позволяет настроить отчётность и действия.

**Quarantine** -- карантин (изоляция) подозрительных сообщений для последующего анализа. Позволяет администратору проверить и при необходимости выпустить заблокированное письмо.

## Теоретический блок

### Архитектура PMG

```
┌─────────────────────────────────────────┐
│  Интернет                                │
│  ├── SMTP (входящий трафик)              │
│  └── DNS (MX-записи)                     │
├─────────────────────────────────────────┤
│  Proxmox Mail Gateway                    │
│  ├── Postfix (MTA)                       │
│  ├── SpamAssassin / Rspamd              │
│  ├── ClamAV (antivirus)                  │
│  ├── Content Filter (pve-smtp-filter)   │
│  ├── DKIM signing/verification          │
│  ├── SPF/DMARC checking                 │
│  ├── Quarantine                          │
│  └── Веб-интерфейс (port 8006)           │
├─────────────────────────────────────────┤
│  Почтовый сервер (внутренний)            │
│  ├── Postfix/Dovecot                     │
│  └── Mailboxes                           │
└─────────────────────────────────────────┘
```

### Фильтрация сообщений

```
Входящее письмо
    │
    ├── 1. SMTP Connection Filtering
    │   ├── DNSBL (RBL) проверка
    │   ├── Sender rate limiting
    │   └── TLS enforcement
    │
    ├── 2. Header Filtering
    │   ├── SPF check
    │   ├── DKIM verify
    │   ├── DMARC policy
    │   └── Sender rewriting
    │
    ├── 3. Content Filtering
    │   ├── SpamAssassin scoring
    │   ├── ClamAV scanning
    │   ├── Regex rules
    │   └── Whitelist/Blacklist
    │
    └── 4. Delivery
        ├── Quarantine (если score > threshold)
        ├── Deliver to mailbox
        └── Bounce/NDR
```

### Уровни фильтрации

| Уровень | Механизм | Назначение |
| :--- | :--- | :--- |
| **Connection** | DNSBL, rate limit | Блокировка на этапе SMTP-соединения |
| **Header** | SPF, DKIM, DMARC | Аутентификация отправителя |
| **Content** | SpamAssassin, ClamAV | Анализ содержимого письма |
| **Attachment** | File type filtering | Блокировка опасных вложений |

## Практические сценарии

### 1. Установка PMG

```bash
# Добавление репозитория
echo "deb http://download.proxmox.com/debian/pmg bookworm pmg-no-subscription" > /etc/apt/sources.list.d/pmg.list

# Импорт ключа
wget https://enterprise.proxmox.com/debian/proxmox-release-bookworm.gpg -O /etc/apt/trusted.gpg.d/proxmox-release-bookworm.gpg

# Обновление и установка
apt update
apt install proxmox-mailgateway

# Или через ISO-установщик (рекомендуется для нового сервера)
# Скачать с proxmox.com и загрузить с USB
```

### 2. Базовая конфигурация

```bash
# Веб-интерфейс: https://<pmg-ip>:8006

# Конфигурация домена
pmgconfig set --mail-domain example.com

# Настройка relay host (куда пересылать почту)
pmgconfig set --relay-host mail.example.com

# Настройка DNS
cat > /etc/resolv.conf << EOF
nameserver 10.0.0.1
search example.com
EOF
```

### 3. Настройка antispam (SpamAssassin)

```bash
# Установка и настройка SpamAssassin
apt install spamassassin

# Конфигурация (/etc/spamassassin/local.cf)
required_score 5.0
use_bayes 1
bayes_auto_learn 1
add_header all Spam-Score _SCORE_
add_header all Status _YESNOCAPS_

# Оптимизация
echo "skip_rbl_checks 0" >> /etc/spamassassin/local.cf
echo "skip_URIBL_checks 0" >> /etc/spamassassin/local.cf
```

### 4. Настройка ClamAV

```bash
# Установка ClamAV
apt install clamav clamav-daemon

# Обновление баз
freshclam

# Настройка
cat > /etc/clamav/clamd.conf << EOF
MaxFileSize 50M
MaxScanSize 100M
StreamMaxLength 50M
EOF

# Перезапуск
systemctl restart clamav-daemon
```

### 5. Настройка DKIM

```bash
# Генерация DKIM ключа
apt install opendkim-tools
opendkim-genkey -s mail -d example.com -b 2048

# Размещение ключей
mkdir -p /etc/opendkim/keys/example.com
mv mail.private /etc/opendkim/keys/example.com/
chown -R opendkim:opendkim /etc/opendkim

# Конфигурация OpenDKIM (/etc/opendkim.conf)
Mode sv
Canonicalization relaxed/simple
ExternalIgnoreList refile:/etc/opendkim/TrustedHosts
InternalHosts refile:/etc/opendkim/TrustedHosts
KeyTable refile:/etc/opendkim/KeyTable
SigningTable refile:/etc/opendkim/SigningTable

# KeyTable (/etc/opendkim/KeyTable)
example.com mail._domainkey.example.com:example.com:/etc/opendkim/keys/example.com/mail.private

# SigningTable (/etc/opendkim/SigningTable)
*@example.com mail._domainkey.example.com

# DNS-запись для DKIM (TXT)
# mail._domainkey.example.com TXT "v=DKIM1; k=rsa; p=<public_key>"
```

### 6. Настройка SPF

```bash
# DNS-запись SPF (TXT)
# example.com TXT "v=spf1 mx ip4:10.0.0.0/24 -all"

# Проверка SPF
dig example.com TXT | grep spf
```

### 7. Настройка DMARC

```bash
# DNS-запись DMARC (TXT)
# _dmarc.example.com TXT "v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com; ruf=mailto:dmarc-forensics@example.com; fo=1"

# Проверка DMARC
dig _dmarc.example.com TXT
```

### 8. Мониторинг и логи

```bash
# Просмотр логов antispam
tail -f /var/log/spamassassin/spamd.log

# Просмотр логов ClamAV
tail -f /var/log/clamav/clamd.log

# Просмотр логов Postfix
tail -f /var/log/mail.log

# Статистика карантина
pmgreport

# Веб-интерфейс: Dashboard -> Statistics
```

## Диагностика и устранение неполадок

| Проблема | Причина | Rешение |
| :--- | :--- | :--- |
| Письма не доходят | DNS-проблемы | Проверьте MX-записи: `dig example.com MX` |
| Слишком много спама | Низкий порог antispam | Увеличьте `required_score` в SpamAssassin |
| Легитимные письма в карантине | Ложные срабатывания | Добавьте отправителя вwhitelist |
| DKIM не работает | Неправильная DNS-запись | Проверьте: `opendkim-testkey -d example.com -s mail` |
| ClamAV не сканирует | Базы устарели | `freshclam` и перезапуск clamav-daemon |
| PMG не пересылает почту | Relay host недоступен | Проверьтеconnectivity: `telnet mail.example.com 25` |

## Лучшие практики

1. **Разделяйте PMG и почтовый сервер**: PMG -- это шлюз, а не сервер. Почтовый сервер (Postfix/Dovecot) должен быть отдельным узлом.
2. **Настраивайте SPF, DKIM, DMARC**: Все три протокола необходимы для защиты от подделки отправителя.
3. **Регулярно обновляйте базы**: SpamAssassin rules, ClamAV signatures, DNSBL списки.
4. **Мониторьте карантин**: Регулярно проверяйтеfalse positives и настраивайте whitelist.
5. **Бэкапы конфигурации**: Регулярно экспортируйте настройки PMG.
6. **Используйте TLS**: Шифруйте SMTP-соединения между PMG и почтовым сервером.
7. **Настройте алерты**: Уведомления о критических ошибках (ClamAV update failure, disk space).

## Граничные случаи

- **Large attachments**: ClamAV может замедлять фильтрацию больших вложений; настройте `MaxFileSize`.
- **greylisting**: Может задерживатьlegitimate письма第一次; используйте с осторожностью.
- **Multi-tenancy**: PMG поддерживает несколько доменов, но настройки antispam общие для всех.
- **High availability**: PMG не имеет встроенного HA; используйте clustered MTA или DNS-based redundancy.

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Безопасность и Hardening Proxmox VE](./proxmox_security.md)
- [Диагностика DNS](../Linux/Diagnostics/Networking/dns.md)
- [TLS/SSL -- SSoT](../Linux/Networking/Concepts/tls_ssl.md)
