# ACME и SSL-сертификаты в Proxmox VE

## Определения

**ACME (Automatic Certificate Management Environment)** — протокол автоматизации взаимодействия с центром сертификации (RFC 8555). В Proxmox VE встроенный ACME-клиент позволяет автоматически получать и обновлять TLS-сертификаты от внешних CA, таких как Let's Encrypt.

**Let's Encrypt** — бесплатный центр сертификации, автоматизирующий выдачу и обновление TLS-сертификатов через ACME-протокол. Выпускает сертификаты со сроком действия 90 дней, что делает автоматическое обновление обязательным.

**Self-signed certificate (Самоподписанный сертификат)** — сертификат, подписанный собственным ключом сервера, а не доверенным CA. По умолчанию Proxmox VE использует самоподписанные сертификаты для веб-интерфейса и API, что вызывает предупреждения браузера о небезопасном соединении.

**DNS-01 challenge** — метод валидации домена через ACME, при котором CA проверяет наличие специальной TXT-записи в DNS-зоне домена. Позволяет получать сертификаты без открытия портов 80/443 во внешнюю сеть.

**DNS API-провайдер** — хостинг-провайдер, предоставляющий программный интерфейс для управления DNS-записями. Proxmox VE поддерживает плагины для Cloudflare, DuckDNS, DigitalOcean и других провайдеров.

**Cluster CA (Внутренний CA кластера)** — собственный центр сертификации Proxmox VE для каждого кластера, управляющий внутренними сертификатами узлов. Срок действия по умолчанию — 5 лет. Управление ротацией — через `pvecm updatecerts`. См. также [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md#управление-сертификатами-кластера).

## Основные концепции

### Проблема самоподписанных сертификатов

По умолчанию каждый узел Proxmox VE использует самоподписанный сертификат для HTTPS-интерфейса (порт 8006). Это вызывает в браузерах предупреждения о небезопасном соединении и требует отключения проверки SSL при автоматизации (`-k` в curl, `verify_ssl=False` в API). Для production-среды требуется замена самоподписанного сертификата на доверенный от общеизвестного CA.

### Встроенный ACME-клиент Proxmox VE

Начиная с версии 6.2, Proxmox VE включает встроенную поддержку ACME-клиента, что позволяет автоматически получать и обновлять TLS-сертификаты от Let's Encrypt. ACME-клиент интегрирован в веб-интерфейс и работает через Datacenter → ACME. Процесс получения сертификата полностью автоматизирован после первичной настройки.

### Методы валидации домена

ACME-протокол поддерживает несколько методов валидации домена:

- **HTTP-01 challenge**: CA проверяет наличие файла `.well-known/acme-challenge/<token>` по HTTP на порту 80. Требует открытия порта 80 во внешнюю сеть.
- **DNS-01 challenge**: CA проверяет наличие TXT-записи `_acme-challenge.<домен>` в DNS. Не требует открытия портов 80/443. Подходит для внутренних сервисов и когда веб-интерфейс не доступен из внешней сети.
- **TLS-ALPN-01 challenge**: Аналогично HTTP-01, но через TLS на порту 443. Поддерживается не всеми ACME-серверами.

Для Proxmox VE рекомендуется DNS-01 challenge, особенно если сервер не имеет публичного IP или порты 80/443 закрыты firewall.

### Безопасность DNS-01 challenge

DNS-01 challenge предоставляет возможность получения wildcard-сертификатов (`*.example.com`), что невозможно через HTTP-01 challenge. Однако требует хранения API-ключей DNS-провайдера в конфигурации Proxmox, что увеличивает поверхность атаки при компрометации узла. Рекомендуется использовать API-токены с минимальными правами (только редактирование DNS-записей) и ограничить доступ к веб-интерфейсу Proxmox firewall.

### Архитектура ACME в Proxmox VE

```
┌─────────────────────────────────────────────────────────────┐
│                      Proxmox VE (ACME)                       │
├─────────────────────────────────────────────────────────────┤
│  Datacenter → ACME → Accounts (аккаунт Let's Encrypt)       │
│  Datacenter → ACME → DNS Plugins (DNS API-провайдер)        │
│  Datacenter → node → System → Certificates → ACME (заявка)  │
├─────────────────────────────────────────────────────────────┤
│  /etc/pve/nodes/<node>/pveproxy.pem (сертификат узла)       │
│  /etc/pve/nodes/<node>/pveproxy.key (приватный ключ)       │
└─────────────────────────────────────────────────────────────┘
         │                                   │
         ▼                                   ▼
┌─────────────────────┐          ┌─────────────────────┐
│   Let's Encrypt     │          │   DNS-провайдер      │
│   (ACME сервер)    │          │   (TXT запись)      │
└─────────────────────┘          └─────────────────────┘
```

## Практические сценарии

### Предварительные требования

1. **Публичный домен**, привязанный к IP-адресу сервера с Proxmox VE. DNS-запись A должна разрешать домен в IP-адрес узла.
2. **Доступ к DNS-записям** домена. Требуется возможность создания TXT-записей для валидации ACME.
3. **Proxmox VE версии 6.2 и выше** (актуальные ветки — 8.x/9.x).
4. **DNS-провайдер**, поддерживающий API для автоматического управления записями (Cloudflare, DuckDNS, DigitalOcean, AWS Route53 и др.).
5. **Доступ к Proxmox** по SSH или через веб-интерфейс с правами администратора datacenter.

### Сценарий 1: Получение SSL-сертификата через веб-интерфейс

#### Шаг 1: Создание ACME-аккаунта

1. Откройте веб-интерфейс Proxmox VE.
2. Перейдите в **Datacenter** → **ACME** → **Accounts**.
3. Нажмите **Add** и заполните поля:

   | Поле | Значение |
   |------|----------|
   | Name | `letsencrypt-prod` (или `letsencrypt-staging` для тестирования) |
   | URL | `https://acme-v02.api.letsencrypt.org/directory` (production) |
   | E-Mail | `ops@example.com` |
   | Terms of Service | Принять |

4. Нажмите **Register**. Proxmox создаст аккаунт в Let's Encrypt.

> **Важно**: Для тестирования используйте staging-сервер `https://acme-staging-v02.api.letsencrypt.org/directory`. Staging имеет более высокие лимиты и выдает недоверенные сертификаты, что предотвращает блокировку rate limit в production.

#### Шаг 2: Настройка DNS-плагина

1. Перейдите в **Datacenter** → **ACME** → **DNS Plugin**.
2. Нажмите **Add**.
3. Выберите DNS-хостинг из списка (например, `cloudflare`).

   | Поле | Значение |
   |------|----------|
   | Node | Имя узла Proxmox |
   | Plugin | `cloudflare` |
   | API Key | API-токен Cloudflare с правами `Zone:Read` и `DNS:Edit` |

4. Нажмите **Save**.

> **Рекомендация**: Создавайте отдельные API-токены для каждого DNS-провайдера с минимально необходимыми правами. Не используйте глобальные ключи.

#### Шаг 3: Выпуск сертификата

1. Перейдите в **Datacenter** → **<имя_узла>** → **System** → **Certificates**.
2. Нажмите **ACME** → **Add**.
3. Заполните параметры:

   | Параметр | Значение |
   |-----------|----------|
   | Domains | `proxmox.example.com` |
   | ACME Account | `letsencrypt-prod` |
   | Plugin | `cloudflare` |
   | Validation | `dns-01` |

4. Нажмите **Create**.

Proxmox автоматически запустит валидацию через DNS-01 challenge и, при успешном завершении, установит сертификат для веб-интерфейса узла.

#### Шаг 4: Проверка сертификата

```bash
# Проверка сертификата через openssl
openssl s_client -connect proxmox.example.com:8006 -servername proxmox.example.com < /dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates

# Проверка через curl
curl -v https://proxmox.example.com:8006/api2/json/version
```

Ожидаемый результат: сертификат выдан от Let's Encrypt, срок действия — 90 дней.

### Сценарий 2: Получение сертификата через CLI

Если веб-интерфейс недоступен, ACME-сертификат можно получить через CLI на узле Proxmox:

```bash
# 1. Создание директории для ACME
mkdir -p /root/.acme/accounts /etc/pve/nodes/$(hostname)

# 2. Регистрация аккаунта (через curl)
# Получение nonce
NONCE=$(curl -s https://acme-v02.api.letsencrypt.org/directory | grep -i replay-nonce | head -1 | sed 's/.*replay-nonce": "\([^"]*\)".*/\1/')

# Создание ключевой пары аккаунта
openssl genrsa -out /root/.acme/accounts/letsencrypt.key 2048

# Создание CSR для домена
openssl req -new -key /root/.acme/accounts/letsencrypt.key \
  -subj "/CN=proxmox.example.com" \
  -out /root/.acme/proxmox.csr

# 3. DNS-01 challenge через API Cloudflare
# Получение зоны по домену
ZONE=$(curl -s -X GET "https://api.cloudflare.com/client/v4/zones?name=example.com" \
  -H "Authorization: Bearer $CLOUDFLARE_TOKEN" \
  -H "Content-Type: application/json" | jq -r '.result[0].id')

# Создание TXT-записи
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records" \
  -H "Authorization: Bearer $CLOUDFLARE_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "TXT",
    "name": "_acme-challenge.proxmox",
    "content": "'$ACME_TOKEN'",
    "ttl": 300
  }'

# 4. Запрос сертификата
# (Упрощенная схема; для production используйте acme.sh или certbot)
```

> **Важно**: CLI-метод требует ручного создания TXT-записи и обновления сертификата. Рекомендуется использовать веб-интерфейс Proxmox для автоматического обновления.

### Сценарий 3: Управление несколькими доменами

Для кластера из нескольких узлов создайте отдельный сертификат для каждого узла:

| Узел | Домен |
|------|-------|
| pve1 | `pve1.example.com` |
| pve2 | `pve2.example.com` |
| pve3 | `pve3.example.com` |

Для round-robin доступа через один домен используйте wildcard-сертификат `*.example.com` через DNS-01 challenge.

### Сценарий 4: Восстановление после истечения срока

Если сертификат Let's Encrypt истек, веб-интерфейс и API становятся недоступны по HTTPS. Восстановление:

```bash
# 1. Вход на узел через SSH
ssh root@pve1

# 2. Проверка сертификатов
ls -la /etc/pve/nodes/pve1/
# pveproxy.pem — сертификат
# pveproxy.key — приватный ключ

# 3. Перевыпуск через веб-интерфейс (если доступен HTTP)
# Или через CLI с отключенной проверкой SSL
curl -k -X POST https://pve1:8006/api2/json/nodes/pve1/certificates/letsencrypt/new

# 4. Перезапуск pveproxy
systemctl restart pveproxy
```

## Операции и команды

### Управление ACME-аккаунтами

```bash
# Создание ACME-аккаунта через CLI
# (через pvesh — CLI API Proxmox)
pvesh set /nodes/$(hostname)/certificates/acme/account \
  -name letsencrypt-prod \
  -url https://acme-v02.api.letsencrypt.org/directory \
  -email ops@example.com \
  -directory https://acme-v02.api.letsencrypt.org/directory

# Просмотр списка аккаунтов
pvesh get /nodes/$(hostname)/certificates/acme/account
```

### Управление DNS-плагинами

```bash
# Добавление DNS-плагина через CLI
pvesh set /nodes/$(hostname)/certificates/acme/dns/plugin \
  -name cloudflare \
  -plugin cloudflare \
  -validation dns-01 \
  -data '{"CF_API_TOKEN":"xxx"}'
```

### Управление сертификатами

```bash
# Перевыпуск сертификата
pvesh post /nodes/$(hostname)/certificates/letsencrypt/new \
  -domains proxmox.example.com \
  -account letsencrypt-prod \
  -plugin cloudflare

# Просмотр сертификатов узла
ls -la /etc/pve/nodes/$(hostname)/*.pem

# Проверка срока действия
openssl x509 -in /etc/pve/nodes/$(hostname)/pveproxy.pem -noout -dates

# Ротация внутреннего CA кластера
pvecm updatecerts

# Проверка статуса кластерных сертификатов
pvecm status
```

### Изменение доверенного сертификата

```bash
# Ручная замена сертификата (если ACME не требуется)
# 1. Копирование сертификата и ключа
cp /etc/letsencrypt/live/proxmox.example.com/fullchain.pem /etc/pve/nodes/$(hostname)/pveproxy.pem
cp /etc/letsencrypt/live/proxmox.example.com/privkey.pem /etc/pve/nodes/$(hostname)/pveproxy.key

# 2. Установка прав
chmod 600 /etc/pve/nodes/$(hostname)/pveproxy.key
chown root:root /etc/pve/nodes/$(hostname)/pveproxy.pem

# 3. Перезапуск pveproxy
systemctl restart pveproxy
```

## Диагностика и устранение неполадок

### Rate Limit Let's Encrypt

**Симптомы**: `429 Too Many Requests`, `Error creating new cert :: too many certificates already issued`.

**Причина**: Let's Encrypt ограничивает количество сертификатов на домен (50 в неделю) и на аккаунт.

**Решение**:

```bash
# Использование staging-сервера для тестирования
# Или ожидание сброса лимита (неделя)
# Или использование другого ACME-сервера (ZeroSSL, Buypass)
```

### Таймаут валидации DNS-01

**Симптомы**: `Validation timed out`, `DNS problem: NXDOMAIN`.

**Причина**: DNS-запись не была создана или не распространилась.

**Решение**:

```bash
# 1. Проверка DNS-записи
dig _acme-challenge.proxmox.example.com TXT

# 2. Проверка propagation
dig @8.8.8.8 _acme-challenge.proxmox.example.com TXT

# 3. Проверка прав API-ключа DNS-провайдера
# (Cloudflare: проверить токен в dashboard)

# 4. Ручное создание записи (временное)
# После успешной валидации запись можно удалить
```

### Ошибка валидации домена

**Симптомы**: `Domain not found`, `NXDOMAIN`.

**Причина**: Домен не разрешается в IP-адрес Proxmox VE или DNS-запись A отсутствует.

**Решение**:

```bash
# 1. Проверка DNS-разрешения
dig proxmox.example.com A

# 2. Проверка доступности порта 8006
nc -zv proxmox.example.com 8006

# 3. Проверка firewall
pve-firewall log | grep 8006
```

### Истекший сертификат

**Симптомы**: `SSL: CERTIFICATE_VERIFY_FAILED`, `self-signed certificate in certificate chain`.

**Причина**: Срок действия сертификата Let's Encrypt (90 дней) истек, а автоматическое обновление не сработало.

**Решение**:

```bash
# 1. Перевыпуск через веб-интерфейс
# Datacenter → node → System → Certificates → ACME → Add

# 2. Или через CLI
curl -k -X POST https://proxmox.example.com:8006/api2/json/nodes/$(hostname)/certificates/letsencrypt/new \
  -H "Authorization: PVEAuthCookie=$(cat /var/pve/proxy.egd)" \
  -d '{"domains":"proxmox.example.com","account":"letsencrypt-prod"}'

# 3. Перезапуск pveproxy
systemctl restart pveproxy
```

### Ошибка доступа к ACME-аккаунту

**Симптомы**: `Account not found`, `401 Unauthorized`.

**Причина**: Неверные учетные данные аккаунта Let's Encrypt или аккаунт не зарегистрирован.

**Решение**:

```bash
# 1. Проверка списка аккаунтов
pvesh get /nodes/$(hostname)/certificates/acme/account

# 2. Пересоздание аккаунта
# Удаление старого аккаунта и создание нового
```

## Лучшие практики

1. **Автоматическое обновление**: Используйте встроенный ACME-клиент Proxmox VE. Автоматическое обновление исключает риск истечения срока действия сертификата.

2. **Staging-сервер**: Тестируйте конфигурацию на staging-сервере Let's Encrypt перед production. Это предотвращает блокировку rate limit.

3. **DNS-01 challenge**: Предпочтительнее HTTP-01 challenge, так как не требует открытия портов 80/443 и поддерживает wildcard-сертификаты.

4. **API-токены с минимальными правами**: Для каждого DNS-провайдера создавайте отдельный API-токен с правами только на редактирование DNS-записей нужного домена.

5. **Firewall**: Ограничьте доступ к веб-интерфейсу Proxmox (порт 8006) доверенными IP-адресами через `pve-firewall` или внешний firewall.

6. **Алерты на срок действия**: Настройте алерты за 14–30 дней до истечения срока сертификата. Хотя ACME автоматически обновляет сертификат, сбой обновления может привести к недоступности интерфейса.

7. **Резервное копирование ключей**: Сохраняйте резервную копию приватных ключей ACME-аккаунта и сертификатов Proxmox. При потере ключа невозможно будет продлить сертификат.

8. **Внутренний CA кластера**: Не удаляйте или не изменяйте внутренний CA Proxmox (`/etc/pve/pve-root-ca.pem`). Он управляет внутренними сертификатами кластера и их ротацией через `pvecm updatecerts`. Срок действия внутренних сертификатов — 5 лет.

## Граничные случаи

- **Внутренний CA кластера**: Встроенный ACME-клиент Proxmox VE не заменяет внутренний CA кластера. Он получает внешний доверенный сертификат только для веб-интерфейса и API. Внутренние сертификаты между узлами кластера (Corosync, Ceph) управляются через внутренний CA. См. также [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md#управление-сертификатами-кластера).

- **Сертификаты для VM/LXC**: ACME-клиент Proxmox VE не управляет сертификатами виртуальных машин или контейнеров. Для них используйте Certbot, acme.sh или другие ACME-клиенты внутри гостевой ОС. См. также [Certificate Automation: Let's Encrypt, Internal CA, Rotation](../Ansible/ansible_certificate_management.md).

- **DNS propagation delay**: При использовании DNS-01 challenge учитывайте задержку распространения DNS-записей (от нескольких секунд до нескольких минут в зависимости от TTL). Proxmox VE ожидает до 300 секунд на валидацию.

- **Сертификаты для Proxmox Backup Server**: PBS имеет собственный веб-интерфейс на порту 8007 с самоподписанным сертификатом. ACME-клиент Proxmox VE не управляет сертификатами PBS. Для PBS загрузите доверенный сертификат через веб-интерфейс PBS. См. также [Proxmox Backup Server](./proxmox_backup_server.md).

- **Кластер с одним доменом**: При использовании одного домена для всех узлов кластера (`pve.example.com`) через балансировщик, выберите один узел для получения сертификата и синхронизируйте его на другие узлы через `pmxcfs` или ручное копирование.

- **IPv6-доступ**: Если Proxmox VE доступен только по IPv6, убедитесь, что DNS-запись AAAA разрешает домен в IPv6-адрес узла. DNS-01 challenge работает независимо от протокола IP.

## Дополнительная информация

### Ссылки

- [Документация Proxmox ACME](https://pve.proxmox.com/wiki/Certificate_Management)
- [Список поддерживаемых DNS-плагинов](https://github.com/acmesh-official/acme.sh/wiki/dnsapi)
- [Let's Encrypt](https://letsencrypt.org/)
- [RFC 8555 — ACME Protocol](https://datatracker.ietf.org/doc/html/rfc8555)
- [Certificate Automation: Let's Encrypt, Internal CA, Rotation](../Ansible/ansible_certificate_management.md)
- [Кластеризация и High Availability в Proxmox](./proxmox_cluster.md)
- [Proxmox Backup Server](./proxmox_backup_server.md)

### Связанные темы

- [Безопасность и Hardening Proxmox VE](./proxmox_security.md)
- [Сетевые технологии Proxmox](./proxmox_networking.md)
