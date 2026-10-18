# ACME и SSL-сертификаты в Proxmox VE

**Актуально для:** Proxmox VE 9.x (клиент ACME / `pvenode`; поведение описано по документации PVE 6.2+ и wiki Certificate Management, актуальной для 8.x/9.x)

## Определения

**ACME (Automatic Certificate Management Environment)** — протокол автоматизации выдачи и продления TLS-сертификатов (RFC 8555). Proxmox VE реализует собственный ACME-клиент, интегрированный в веб-интерфейс, REST API и утилиту `pvenode`.

**Let's Encrypt (LE)** — публичный ACME-сервер, выдающий доверенные сертификаты сроком **90 дней**. В PVE из коробки подключаются два эндпоинта: production и staging. Staging выдаёт недоверенные сертификаты, но имеет мягкие rate-лимиты — обязателен при первых настройках и тестах.

**Self-signed certificate (Самоподписанный сертификат)** — по умолчанию каждый узел PVE подписывает сам себя через кластерный CA. Такой сертификат не доверен браузерам и операционным системам (ошибки «небезопасное соединение», `SSL certificate problem: self signed certificate` при `curl` без `-k`).

**Custom certificate (Пользовательский сертификат)** — внешний сертификат (коммерческий CA, внутренний corporate CA, выпущенный acme.sh/certbot и т.п.), установленный на узел через `pvenode cert set` без встроенного ACME-клиента.

**pvenode** — официальный CLI-инструмент управления узлом PVE (описание, bulk-операции с гостями, история задач, **сертификаты**). Встроенный ACME и custom-сертификаты управляются именно им, не `pvesh` напрямую (см. [CLI-сценарий](#сценарий-2-настройка-acme-через-cli-pvenode)).

**HTTP-01 challenge** — валидация владением доменом: ACME-сервер запрашивает файл `/.well-known/acme-challenge/<token>` по HTTP на порту **80**. В PVE для этого используется неявный плагин `standalone` (встроенный web-сервер на порту 80).

**DNS-01 challenge** — валидация через TXT-запись `_acme-challenge.<домен>` в DNS. Не требует открытого порта 80 и доступен для wildcard-сертификатов (`*.example.com`). PVE переиспользует DNS-плагины проекта acme.sh — поддерживается весь список провайдеров из их документации.

**ACME account** — учётная запись ACME (одна на кластер), связанная с эндпоинтом CA и contact-email. Email используется CA для уведомлений о проблемах с продлением.

**ACME DNS plugin** — конфигурация API-доступа к DNS-провайдеру (токен, endpoint), хранится в pmxcfs (`/etc/pve/priv/acme/plugins.cfg`) и доступна всем узлам кластера.

**Cluster CA (Внутренний CA кластера)** — самоподписанный CA, создаваемый при первом создании кластера. Хранится в pmxcfs: `/etc/pve/pve-root-ca.pem` + `/etc/pve/priv/pve-root-ca.key`. Срок действия CA — **10 лет** (`openssl req -days 3650` в исходниках pve-cluster); узловые `pve-ssl.pem` подписываются максимум на **2 года**. Ротация узловых сертификатов — `pvecm updatecerts`; CA не обновляется этой командой «на новый срок», а только при явной регенерации (см. [Кластеризация](./proxmox_cluster.md#управление-сертификатами-кластера)).

**pveproxy** — HTTPS-прокси API и веб-интерфейса (порт 8006). Использует custom-сертификат `pveproxy-ssl.pem`/`pveproxy-ssl.key` (если установлен) либо узловой `pve-ssl.pem`/`pve-ssl.key`, подписанный кластерным CA.

**pve-daily-update.service** — системный таймер ежедневного обновления PVE; именно он выполняет **автоматическое продление** ACME-сертификатов.

## Основные концепции

### Три варианта сертификата для API и веб-интерфейса

По [Certificate Management (wiki)](https://pve.proxmox.com/wiki/Certificate_Management):

| Вариант | Файлы | Кем подписан | Браузеры |
|---|---|---|---|
| 1. По умолчанию (узловой) | `/etc/pve/nodes/<node>/pve-ssl.pem` + `pve-ssl.key` | Кластерный CA | Недоверен (предупреждения) |
| 2. Custom (внешний) | `/etc/pve/local/pveproxy-ssl.pem` + `pveproxy-ssl.key` | Коммерческий/корпоративный CA | Доверен |
| 3. ACME (Let's Encrypt) | те же `pveproxy-ssl.*` | Let's Encrypt (или другой ACME-CA) | Доверен |

`/etc/pve/local` — симлинк на `/etc/pve/nodes/<имя-узла>`. Приватный ключ **не должен** быть защищён паролем. Разрешение `TLS_KEY_FILE` в `/etc/default/pveproxy` (вынос ключа вне pmxcfs) **не действует** на встроенный ACME — ключ ACME всегда в `pveproxy-ssl.key`.

> **Запрет:** не редактируйте вручную `/etc/pve/local/pve-ssl.pem`, `pve-ssl.key`, `/etc/pve/pve-root-ca.pem`, `/etc/pve/priv/pve-root-ca.key` — они генерируются системой. Управление — только через `pvenode` / `pvecm`.

### Проблема самоподписанных сертификатов

Самоподписанный узловой сертификат — норма для лаборатории, но не для production: TLS-ошибки в браузерах, необходимость `-k` / `verify_ssl=False` в автоматизации, сложности с корпоративным trust store. Внешний доверенный сертификат (ACME или custom) устраняет эти проблемы и повышает безопасность automation-pipeline ([REST API](./proxmox_rest_api.md)).

### Поддерживаемые challenge-методы PVE

Встроенный клиент поддерживает **только**:

- **http-01** — плагин `standalone` (встроенный web-сервер на порту 80);
- **dns-01** — DNS API-плагины acme.sh.

**TLS-ALPN-01** встроенным клиентом PVE **не поддерживается** (распространённое заблуждение — в отличие от Traefik/certbot).

Предпосылки `standalone` (http-01): ToS приняты; **порт 80** узла достижим из интернета; на порту 80 ничего другого не слушает (nginx/HAProxy на том же узле — конфликт); DNS A/AAAA домена указывает на публичный IP узла; при включённом `pve-firewall` порт 80 разрешён на публичных интерфейсах.

DNS-01 предпочтителен, когда: узел за NAT/без публичного 80; нужен wildcard; на одном узле уже живёт другой web-сервер; домены в разных зонах с разными API-ключами.

### Архитектура

```
┌────────────────────────────────────────────────────────────────┐
│                    Proxmox VE (кластер)                         │
│                                                                │
│  /etc/pve/priv/acme/plugins.cfg     — DNS-плагины (все узлы)   │
│  ACME-аккаунты (account)            — на кластер                │
│  /etc/pve/local/pveproxy-ssl.pem    — custom/ACME-сертификат    │
│  /etc/pve/local/pveproxy-ssl.key    — приватный ключ (без пароля)│
│  /etc/pve/local/pve-ssl.pem         — узловой (cluster CA)      │
│  /etc/pve/pve-root-ca.pem           — корень кластерного CA     │
└────────────────────────────────────────────────────────────────┘
        │ order / renew (pvenode / pve-daily-update)
        ▼
┌─────────────────────┐          ┌──────────────────────────────┐
│  ACME-CA            │          │  DNS-провайдер / порт 80     │
│  (LE prod / staging │          │  (dns-01 TXT или http-01     │
│   или custom URL)   │          │   standalone на :80)         │
└─────────────────────┘          └──────────────────────────────┘
```

### Автоматическое продление

Если сертификат успешно заказан через ACME (GUI или `pvenode`), `pve-daily-update.service` продлевает его автоматически, когда сертификат **уже истёк или истечёт в ближайшие 30 дней**. Ручной принудительный перевыпуск: `pvenode acme cert renew --force`.

> При использовании custom ACME-каталога с короткоживущими сертификатами рассмотрите отключение случайной задержки таймера: `systemctl edit pve-daily-update.timer` (RandomizedDelaySec), иначе после reboot продление может пройти позже дедлайна.

## Практические сценарии

### Предварительные требования

1. **Публичный домен.** Для http-01: A/AAAA-запись на публичный IP узла. Для dns-01: доступ к управлению зоной (API-токен).
2. **Сеть:** http-01 — порт 80 из интернета (включая промежуточные firewall/NAT); dns-01 — исходящий HTTPS к CA и к API DNS.
3. **PVE 6.2+** (актуальные ветки 8.x/9.x); права root по SSH или Datacenter Admin в GUI.
4. **DNS API-токен** (для dns-01) с минимальными правами: создание/удаление TXT в нужной зоне. Не используйте глобальные ключи доступа к аккаунту.
5. **Аккаунт LE** — один на кластер; contact-email обязателен.

### Сценарий 1: Получение сертификата через веб-интерфейс

#### Шаг 1: Регистрация ACME-аккаунта

1. **Datacenter** → **ACME** → **Accounts** → **Add**.
2. Заполните:

   | Поле | Значение |
   |------|----------|
   | Name | `letsencrypt` (или `letsencrypt-staging` для тестов) |
   | URL | `https://acme-v02.api.letsencrypt.org/directory` (production) |
   | E-Mail | `ops@example.com` |
   | Terms of Service | принять |

3. **Register** — аккаунт создаётся на кластер и доступен всем узлам.

> Для первых конфигураций всегда используйте staging: `https://acme-staging-v02.api.letsencrypt.org/directory`. Production rate limits жёсткие (например, до 50 сертификатов на registered domain в неделю); исчерпание лимита лечится ожиданием или staging.

#### Шаг 2: Настройка DNS-плагина (dns-01)

1. **Datacenter** → **ACME** → **DNS Plugin** → **Add**.
2. Выберите провайдера (пример Cloudflare):

   | Поле | Значение |
   |------|----------|
   | Node | любой узел (конфиг хранится кластерно) |
   | Plugin | `cloudflare` |
   | API Token | токен с `Zone:Read` + `DNS:Edit` на нужную зону |

3. **Save.** Для провайдеров из списка acme.sh имя API-параметра иногда отличается от «человеческого» названия (у Cloudflare в CLI `--api cf`, не `cloudflare`) — сверяйтесь с help плагина.

Для http-01 плагин добавлять не нужно: всегда существует неявный `standalone`.

#### Шаг 3: Заказ сертификата на узел

1. **Node** → **System** → **Certificates** → **ACME** → **Add**.
2. Укажите домен, аккаунт и (для dns-01) плагин; тип валидации — `dns-01` или `http-01 (standalone)`.
3. **Create** — PVE выполнит валидацию и установит сертификат в `pveproxy-ssl.pem`/`.key`, перезапустит pveproxy.

При успехе GUI перезагружается через ~10 с без предупреждений SSL.

#### Шаг 4: Проверка

```bash
# Цепочка и срок действия
echo | openssl s_client -connect pve1.example.com:8006 -servername pve1.example.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates

# Ожидаемый issuer: R11/E6 (или другой LE-промежуточный), notAfter — 90 дней от выпуска

# Файл на узле
pvenode cert info
# → в таблице: pveproxy-ssl.pem, issuer Let's Encrypt, notafter +90 дней

curl -s https://pve1.example.com:8006/api2/json/version
# → без -k, без ошибок SSL
```

### Сценарий 2: Настройка ACME через CLI (pvenode)

Официальный интерфейс — `pvenode` (см. `man pvenode`). Пример для production LE + DNS-плагина:

```bash
# 1. Регистрация аккаунта (интерактивный выбор эндпоинта; для неинтерактивной регистрации
#    укажите --directory)
pvenode acme account register default ops@example.com
# Directory endpoints:
# 0) Let's Encrypt V2 (https://acme-v02.api.letsencrypt.org/directory)
# 1) Let's Encrypt V2 Staging (https://acme-staging-v02.api.letsencrypt.org/directory)
# 2) Custom
# Enter selection: 0
# ... agree to ToS ...

# Неинтерактивно (staging для теста):
pvenode acme account register staging ops@example.com \
  --directory https://acme-staging-v02.api.letsencrypt.org/directory

# 2. Список и состояние аккаунтов
pvenode acme account list
pvenode acme account info default

# 3. DNS-плагин (данные — файл с токеном вида CF_Token=... / ключами acme.sh)
pvenode acme plugin add dns cloudflare --api cf --data /root/cf-token.txt
pvenode acme plugin list
pvenode acme plugin config cloudflare

# 4. Привязка домена к узлу (plugin обязателен для dns-01)
pvenode config set -acmedomain0 pve1.example.com,plugin=cloudflare
# Несколько SAN: -acmedomain1, -acmedomain2, ...
# Для http-01 (standalone) plugin можно опустить:
# pvenode config set --acme domains=pve1.example.com

# 5. Заказ и установка сертификата (перезапускает pveproxy при успехе)
pvenode acme cert order
# Task OK

# 6. Проверка
pvenode cert info
openssl x509 -in /etc/pve/local/pveproxy-ssl.pem -noout -dates -issuer
```

Принудительный перевыпуск и отзыв:

```bash
pvenode acme cert renew --force   # даже если до истечения > 30 дней
pvenode acme cert revoke
```

Для автоматизации через REST API (без интерактива):

| Действие | Метод и путь |
|---|---|
| TOS / каталоги | `GET /cluster/acme/tos`, `GET /cluster/acme/directories` |
| Регистрация аккаунта | `POST /cluster/acme/account` |
| Заказ сертификата | `POST /nodes/<node>/certificates/acme/certificate` |
| Установка custom-цепочки | `POST /nodes/<node>/certificates/custom` (поля `certificates`, `key`, `restart`, `force`) |

Тот же API используют модули `community.proxmox.proxmox_acme_account` / `proxmox_acme_certificate` ([Ansible](./proxmox_ansible.md)) и deploy-hook acme.sh (`DEPLOY_PROXMOXVE_*`).

### Сценарий 3: Custom-сертификат от корпоративного CA или acme.sh

Когда ACME в PVE не используется (внутренний CA, сертификат от коммерческого CA, выпуск outside):

```bash
# certificate.crt — PEM-цепочка (leaf + intermediates), key — PEM без пароля
pvenode cert set certificate.crt certificate.key --force --restart

pvenode cert info
# → filename: pveproxy-ssl.pem, issuer: <ваш CA>
```

Если сертификат выпущен на узле/вне узла acme.sh/certbot, путь деплоя:

```bash
acme.sh --install-cert -d pve1.example.com \
  --fullchain-file /root/pve1.fullchain.pem \
  --key-file      /root/pve1.key
pvenode cert set /root/pve1.fullchain.pem /root/pve1.key --force --restart
```

Удаление custom-сертификата и возврат на узловой (cluster CA):

```bash
pvenode cert delete --restart
```

### Сценарий 4: Кластер — несколько узлов и wildcard

Сертификат pveproxy — **на каждый узел отдельно** (файлы в `/etc/pve/nodes/<node>/`). ACME-аккаунт и DNS-плагины общекластерные.

| Задача | Подход |
|---|---|
| Отдельный FQDN на узел | `pve1.example.com`, `pve2.example.com`, ... — по одному заказу на узел |
| Один hostname за LB/round-robin | wildcard `*.example.com` (только dns-01) на каждом узле: `-acmedomain0 '*.example.com',plugin=...`; либо SAN-список всех узлов в одном сертификате и `pvenode cert set` на каждый узел |
| Один и тот же файл | `pvenode cert set` на каждом узле (pmxcfs не «раскатывает» custom-сертификат на все узлы автоматически) |

Wildcard через http-01 невозможен — только dns-01.

### Сценарий 5: Восстановление после истёкшего сертификата

Симптом: браузер/CLI сообщают об истёкшем или self-signed сертификате; GUI недоступна «надёжно», но SSH работает.

```bash
# 1. SSH на узел (port 22, не зависит от pveproxy)
ssh root@pve1.example.com

# 2. Что установлено и когда истекло
pvenode cert info
openssl x509 -in /etc/pve/local/pveproxy-ssl.pem -noout -dates 2>/dev/null
openssl x509 -in /etc/pve/local/pve-ssl.pem -noout -dates

# 3. Перевыпуск ACME (аккаунт и плагины должны быть на месте)
pvenode acme cert order --force
systemctl restart pveproxy

# 4. Если ACME недоступен / нужен временный self-signed узловой
pvenode cert delete --restart   # падение на pve-ssl.pem от cluster CA

# 5. pveproxy молчит или TLS-хендшейк падает
journalctl -u pveproxy -n 100 --no-pager
systemctl status pvedaemon pveproxy
```

Веб-API без валидного сертификата вызывать не нужно — `letsencrypt/new` из старых how-to не используйте; штатный путь — `pvenode` по SSH.

## Диагностика и устранение неполадок

### Rate limit Let's Encrypt

**Симптомы:** `429 Too Many Requests`, `too many certificates already issued`.

**Причины и действия:**

- Тестовые прогоны в production-эндпоинте → перейти на staging (лимиты в сотни раз мягче).
- Массовый заказ SAN/wildcard → сузить список доменов, повторять не чаще лимитов [LE rate limits](https://letsencrypt.org/docs/rate-limits/) (в т.ч. 50 сертификатов/нед на registered domain; лимиты failed validations на hostname).
- Смена аккаунта не обходит domain-based лимиты — поможет только выжидание окна или staging.

### Таймаут / ошибка валидации dns-01

**Симптомы:** `Validation timed out`, `NXDOMAIN`, `dns problem`.

```bash
# TXT-запись должна быть видна, включая recursive resolvers
dig +short TXT _acme-challenge.pve1.example.com
dig @1.1.1.1 TXT _acme-challenge.pve1.example.com

# Плагин и его конфиг (токен, endpoint)
pvenode acme plugin config cloudflare
pvenode acme plugin list
```

Причины: неверный/просроченный токен; запись создана в чужой зоне; propagation дольше, чем ждёт клиент (TTL/NS); CAA-запись запрещает выпуск этому CA (`CAA record ... prevents issuance` — проверьте `dig CAA example.com`).

### Ошибка http-01 (standalone)

**Симптомы:** `Connection refused` / timeout на `http://<domain>/.well-known/acme-challenge/...`, `Failed to initialize HTTP daemon`.

Чек-лист:

```bash
# 1. На узле не должно быть другого слушателя 80 во время заказа
ss -tlnp | grep ':80 '
# → пусто (или остановить nginx/HAProxy на время order)

# 2. Доступность из «наружу» (с внешней машины или через проверку LE)
curl -I http://pve1.example.com/   # во время валидации

# 3. pve-firewall: разрешить 80 на публичном интерфейсе
# 4. DNS A/AAAA → именно этот узел
```

Порт standalone нельзя перенести — Let's Encrypt требует 80.

### Истёкший сертификат / браузерные ошибки

См. [сценарий восстановления](#сценарий-5-восстановление-после-истёкшего-сертификата). Дополнительно: `systemctl status pveproxy`; конфликт порта 8006 (`ss -tlnp | grep 8006`).

### Ошибка аккаунта (`Account not found`, `401 Unauthorized`)

```bash
pvenode acme account list
pvenode acme account info default
# При потере ключа аккаунта — деактивация и повторная регистрация:
pvenode acme account deactivate default
pvenode acme account register default ops@example.com
```

### Строгая проверка сертификатов клиентами (Python 3.13+)

Начиная с `pve-cluster 9.1.2` (PVE 9.1+) в корень кластерного CA добавлено расширение `keyUsage` (RFC 5280): без него клиенты с жёсткой проверкой (Ansible на Python 3.13 и др.) отклоняют самоподписанные узловые сертификаты. Обновите `pve-cluster` и, при необходимости, **регенерируйте CA на одном узле** и переподпишите узлы (`pvecm updatecerts -f` + рестарт `pveproxy`/`pvedaemon` на каждом) — процедура описана в трейблшутинге PVE и затрагивает весь кластер (заранее: бэкап `/etc/pve`, окно обслуживания).

## Мониторинг срока действия сертификатов

Автопродление закрывает 90-дневный цикл, но **сбой DNS-токена, rate limit или порча аккаунта** могут привести к истечению без шума. Мониторинг — обязательная практика SRE.

Простой проверочный скрипт (cron/nagios-образно, без сторонних агентов):

```bash
#!/usr/bin/env bash
# check_pve_cert.sh — порог 14 дней
set -euo pipefail
THRESHOLD=14
for f in /etc/pve/local/pveproxy-ssl.pem /etc/pve/local/pve-ssl.pem; do
  [ -f "$f" ] || continue
  end=$(openssl x509 -in "$f" -noout -enddate | cut -d= -f2)
  days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
  if [ "$days" -lt "$THRESHOLD" ]; then
    echo "CRITICAL $f expires in ${days}d ($end)"
    exit 2
  fi
  echo "OK $f expires in ${days}d"
done
# Cluster CA (10 лет) — контроль на деградацию до < 90 дней
end=$(openssl x509 -in /etc/pve/pve-root-ca.pem -noout -enddate | cut -d= -f2)
days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
[ "$days" -lt 90 ] && { echo "CRITICAL cluster CA expires in ${days}d"; exit 2; }
echo "OK cluster CA expires in ${days}d"
```

Порядок реагирования: CRITICAL на `pveproxy-ssl` → незамедлительный `pvenode acme cert renew --force` (или `cert set`); CRITICAL на cluster CA → плановая регенерация CA по runbook из [Кластеризации](./proxmox_cluster.md#управление-сертификатами-кластера), не «в пятницу вечером».

Глубокий мониторинг TLS-эндпоинтов (прометеус, ступенчатые алерты) — в [Traefik: мониторинг сертификатов](../WebServers/Traefik/traefik-cert-monitoring.md); интеграция `pveverify-ssl` для blackbox-checker API — в [Мониторинг](./proxmox_monitoring.md).

## Лучшие практики

1. **Встроенный ACME** — первый выбор для public FQDN; custom-сертификаты — для корпоративных PKI и закрытых зон.
2. **Staging при настройке**, production — только после зелёного прогона.
3. **DNS-01** — дефолт для автоматизации (wildcard, NAT, отсутствие конфликта с :80).
4. **Минимальные токены DNS** — только TXT-edit на целевую зону; отдельный токен на узел/зону; ротация токена — отдельная задача change management.
5. **Не трогать** `pve-ssl.*` и `pve-root-ca.*` руками; только `pvenode` / `pvecm`.
6. **Мониторинг notAfter** — алерт за 14–30 дней; автопродление не отменяет мониторинг.
7. **Firewall:** 8006 — только management-сети; 80 — только на время http-01 или постоянный standalone, если он осознанно используется.
8. **Импорт cluster CA** на рабочие станции администраторов (`scp /etc/pve/pve-root-ca.pem` → trust store) вместо глобального отключения проверки.
9. **Бэкап ключей:** `pveproxy-ssl.key`, аккаунтные ключи ACME, DNS-токены — в secret store; при утрате ключа ACME-аккаунта придётся регистрировать аккаунт заново.
10. **Окно на CA-регенерацию** — редкая, но кластерная операция; не путать с обычным `pvenode acme cert renew`.

## Граничные случаи

- **ACME ≠ cluster CA.** Встроенный ACME заменяет только сертификат pveproxy. Внутренние каналы (pmxcfs, SPICE/console, часть кластерных вызовов) продолжают опираться на кластерный CA и `pve-ssl.pem`.
- **Гости (VM/LXC).** PVE не выпускает сертификаты гостям — внутри ОС гостя: certbot/acme.sh ([Ansible-автоматизация](../Ansible/ansible_certificate_management.md)), либо fronting через reverse proxy с общим сертификатом.
- **PBS (порт 8007).** Узловой ACME PVE не управляет сертификатом PBS — свой сертификат через GUI/CLI PBS ([PBS](./proxmox_backup_server.md)).
- **Заказ «в никуда» при истёкшем сертификате.** Старые curl-рецепты с `certificates/letsencrypt/new` и `/var/pve/proxy.egd` не работают; единственный штатный путь — `pvenode` по SSH.
- **Смешанная валидация.** Одновременно http-01 для одного домена и dns-01 для другого на одном узле — поддерживается (разные `acmedomainN` с разными plugin).
- **IPv6.** DNS-01 не зависит от IP; для http-01 и доступа по AAAA убедитесь, что порт 80/8006 достижим по v6.
- **Кастомный `TLS_KEY_FILE`.** Не влияет на ACME; для custom-путей вне pmxcfs — только ручные `cert set` и учёт того, что ACME-продление перезапишет стандартный путь.
- **PDM fingerprint pinning.** После ротации сертификата remote-узла в Proxmox Datacenter Manager обновите fingerprint ([PDM](./proxmox-datacenter-manager.md)).
- **Отзыв (revoke)** сертификата не удаляет его из браузерных кэшей мгновенно; после `pvenode acme cert revoke` заказывайте новый сертификат сразу.

## Дополнительная информация

### Ссылки

- [Certificate Management — wiki Proxmox](https://pve.proxmox.com/wiki/Certificate_Management)
- [certificate-management.adoc / pvenode(1) — официальная документация](https://pve.proxmox.com/pve-docs/pvenode.1.html)
- [Let's Encrypt rate limits](https://letsencrypt.org/docs/rate-limits/)
- [DNS-плагины acme.sh](https://github.com/acmesh-official/acme.sh/wiki/dnsapi)
- [RFC 8555 — ACME](https://datatracker.ietf.org/doc/html/rfc8555)

### Связанные темы

- [Кластеризация и High Availability](./proxmox_cluster.md#управление-сертификатами-кластера) — cluster CA, `pvecm updatecerts`
- [Proxmox Backup Server](./proxmox_backup_server.md) — отдельный сертификат PBS
- [Автоматизация Proxmox через Ansible](./proxmox_ansible.md) — модули ACME
- [Certificate Automation (общий)](../Ansible/ansible_certificate_management.md) — certbot/acme.sh для гостей и сервисов
- [acme.sh](../WebServers/Concepts/acme_sh.md), [HTTPS и Certbot](../WebServers/Concepts/https_with_certbot.md)
- [REST API Proxmox](./proxmox_rest_api.md) — аутентификация, TLS
- [Безопасность и Hardening](./proxmox_security.md)
