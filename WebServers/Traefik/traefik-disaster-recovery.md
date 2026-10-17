# Disaster Recovery и Backup Traefik: RTO, RPO, failover

**Актуально для:** Traefik v3.x (с обратной совместимостью с Traefik v2.x)

## Определения

**RTO (Recovery Time Objective)** — целевое максимальное допустимое время простоя сервиса с момента возникновения аварии до полного восстановления приема входящего клиентского трафика.

**RPO (Recovery Point Objective)** — целевая максимальная граница допустимой потери данных (разница во времени между моментом аварии и точкой последней сохраненной резервной копии). Для Traefik ключевым объектом RPO является хранилище приватных ключей и TLS-сертификатов (`acme.json`).

**Disaster Recovery (DR, аварийное восстановление)** — документированный комплекс организационных и инженерных мер, сценариев и автоматизированных регламентов для восстановления работоспособности инфраструктуры обратного прокси после катастрофических сбоев (аппаратный отказ сервера, повреждение файловой системы, сетевая изоляция ЦОД).

**Failover (аварийное переключение)** — автоматический или автоматизированный перевод входящего сетевого трафика с деградировавшего или вышедшего из строя узла Traefik на резервный узел или запасную локацию.

**Cold Standby (холодный резерв)** — резервный сервер или экземпляр Traefik, находящийся в выключенном состоянии; запуск и применение резервной конфигурации требуют выполнения ручных или скриптовых процедур восстановления (RTO: 10–30 минут).

**Warm Standby (теплый резерв)** — предварительно настроенный и запущенный резервный инстанс Traefik с актуальной конфигурацией, не принимающий рабочий трафик до переключения сетевого шлюза, DNS-записи или таблицы маршрутизации (RTO: 1–3 минуты).

**Hot Standby (горячий резерв)** — параллельно функционирующий активный экземпляр Traefik за локальным балансировщиком или в составе VRRP-кластера, готовый принять нагрузку в течение долей секунды при срабатывании healthcheck-триггеров (RTO: < 3 секунд).

**ACME Storage (`acme.json`)** — локальный файл формата JSON со строгими правами доступа `0600`, содержащий закрытые ключи аккаунтов, метаданные регистрации и TLS-сертификаты, выпущенные встроенным клиентом `lego`. Единственное критическое персистентное состояние Traefik OSS.

**Split-Brain (расщепление кластера)** — аномальное состояние инфраструктуры высокой доступности при нарушении сетевой связности между нодами, когда оба узла ошибочно считают соседа отказавшим и одновременно активируют один и тот же виртуальный IP-адрес (VIP), вызывая коллизию ARP/IP.

**BGP Anycast (L3 failover)** — метод сетевой маршрутизации на уровне Autonomous System (AS), при котором один и тот же IP-адрес шлюза одновременно анонсируется независимыми маршрутизаторами в разных сегментах сети или дата-центрах; при падении узла маршрут отзывается протоколом динамической маршрутизации (BIRD/FRR).

**VRRP (Virtual Router Redundancy Protocol)** — стандартизированный сетевой протокол (RFC 5798), объединяющий группу физических серверов в один виртуальный маршрутизатор с плавающим IP-адресом (VIP), используемый в Keepalived для локального failover на bare-metal.

**DR Drill (учения по аварийному восстановлению)** — регулярная плановая симуляция аварийных отказов (уничтожение ноды, повреждение `acme.json`, обрыв сетевого линка) для валидации работоспособности резервных копий и проверки готовности дежурной смены SRE/Sysadmin.

**ACME Rate Limits** — жесткие квоты центров сертификации (Let's Encrypt), ограничивающие количество выпусков дубликатов (5 в неделю) и новых сертификатов на регистрируемый домен (50 в неделю), превышение которых при холодном старте с утерянным `acme.json` блокирует выпуск сертификатов на срок до 7 дней.

---

## Архитектура и базовые концепции

### Компоненты состояния Traefik (Stateless vs Stateful)

В отличие от традиционных баз данных, Traefik спроектирован по идеологии stateless-прокси. Однако при эксплуатации в production-среде необходимо строго разделять конфигурационные артефакты и изменяемое персистентное состояние:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           Traefik Architecture                          │
├───────────────────────────────────┬─────────────────────────────────────┤
│         Stateless (GitOps)        │           Stateful (Data)           │
│  - traefik.yml (статическая конф) │  - /var/lib/traefik/acme.json       │
│  - /etc/traefik/dynamic/*.yml     │    (приватные ключи, сертификаты)   │
│  - Systemd unit / Docker Compose  │  - Пользовательские TLS-сертификаты │
│  - Провайдеры (Consul, K8s CRD)   │    (/etc/ssl/traefik/*.crt, *.key)  │
└───────────────────────────────────┴─────────────────────────────────────┘
```

| Компонент | Тип | Критичность | RTO | RPO | Источник и метод восстановления |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`acme.json`** | Stateful | **Критическая** | 5–15 мин | < 1–24 ч | Ежедневные/почасовые атомарные бэкапы с проверкой целостности JSON |
| **Статическая конфигурация (`traefik.yml`)** | Stateless | **Высокая** | 1–5 мин | 0 | Репозиторий Git, Ansible/Salt/Puppet playbook |
| **Динамическая конфигурация (`dynamic/*.yml`)** | Stateless | **Высокая** | 1–5 мин | 0 | Репозиторий Git, автоматический pull или синхронизация через KV-хранилище |
| **Внешние TLS-сертификаты (Custom PKI)** | Stateful | **Высокая** | 5–10 мин | 0 | Корпоративное хранилище секретов (HashiCorp Vault, офлайн PKI) |
| **Systemd Unit / Контейнерный манифест** | Stateless | **Средняя** | 1–2 мин | 0 | Шаблоны инфраструктуры как кода (IaC) |
| **Access и Error логи** | Telemetry | **Низкая** | Не применимо | Допустима потеря | Внешний агрегатор логов (Vector, Promtail, Fluent Bit) |

### Матрица сценариев катастроф и целевые показатели RTO/RPO

| Сценарий отказа | Уровень риска | RTO | RPO | Архитектурное решение и реализация |
| :--- | :--- | :--- | :--- | :--- |
| **Аварийный сбой процесса Traefik** | Локальный процесс | 2–5 сек | 0 | Перезапуск службы systemd (`Restart=always`, `RestartSec=2s`) |
| **Аппаратный отказ сервера / ноды** | Физический хост | 2–5 сек | 0 | Автоматический failover через Keepalived VRRP с плавающим VIP |
| **Повреждение / усечение `acme.json`** | Файловая система | 5–10 мин | < 24 ч | Восстановление из валидированного снапшота бэкапа, экстренный fallback |
| **Катастрофическая потеря сервера** | Полный хост | 15–30 мин | < 24 ч | Холодное развертывание (Cold-site Restore) из бэкапа и Git-репозитория |
| **Отказ дата-центра / сетевого линка** | Периметр / ЦОД | 3–60 сек | 0 | Межсайтовый failover: BGP Anycast (BIRD/FRR) или On-Premise GeoDNS |
| **Плановые работы / эвакуация ноды K8s** | Кластер On-Prem | 0 (Zero-downtime) | 0 | PodDisruptionBudget (`minAvailable: 1`), drain узла, RollingUpdate |

### Механика повреждения `acme.json` и запрет параллельного доступа

Traefik Open Source **не поддерживает распределенное хранение сертификатов** и распределенные блокировки файловой системы.

1. **Модель работы с файлом:** Встроенный клиент `lego` загружает содержимое `acme.json` в память при старте процесса. При выпуске или продлении сертификата Traefik выполняет полную перезапись файла новой JSON-структурой с последующим сбросом буфера на диск.
2. **Риски параллельной записи:** Если несколько экземпляров Traefik запущены с монтированием одного и того же файла `acme.json` (например, через NFS, GlusterFS или общий bind mount в Docker), одновременная попытка обновления сертификата приводит к гонке процессов (race condition), перезаписи дескрипторов и гарантированному повреждению файла до нулевого размера (`0 bytes`).
3. **Аварийные сигналы (SIGKILL / OOM):** Завершение процесса Traefik аварийным сигналом `SIGKILL` (включая срабатывание Linux OOM-killer) непосредственно в момент вызова `write()` оставляет файл усеченным или с невалидным синтаксисом JSON (`unexpected end of JSON input`). При последующем запуске Traefik аварийно прекращает работу:
   `field not found, invalid character ... looking for beginning of value`.

### Катастрофа исчерпания лимитов Let's Encrypt (Rate Limit Disaster)

Если хост Traefik уничтожен, а резервная копия `acme.json` отсутствует или повреждена, Traefik при холодном старте попытается одновременно заказать сертификаты для всех обслуживаемых доменов.

В production-среде это вызывает мгновенное столкновение с лимитами центров сертификации (Let's Encrypt):

- **Duplicate Certificate Limit:** Не более **5 одинаковых сертификатов** (содержащих абсолютно идентичный набор доменных имен) в неделю.
- **Certificates per Registered Domain:** Не более **50 новых сертификатов** на один базовый домен (например, `example.com` и любые его поддомены) за скользящее окно в 7 дней.
- **Failed Validation Limit:** Не более **5 неудачных попыток валидации** challenge на один аккаунт и домен в течение 1 часа.
- **New Orders:** Не более **300 новых заказов** на аккаунт за 3 часа.

**Последствия катастрофы:** Публичные сервисы компании теряют валидный TLS на срок до 7 суток. Браузеры пользователей блокируют доступ с ошибкой `NET::ERR_CERT_COMMON_NAME_INVALID` или `SEC_ERROR_EXPIRED_ISSUER_CERTIFICATE`.

**Стратегии защиты и ликвидации последствий:**
1. **Регулярный атомарный бэкап:** Наличие актуального `acme.json` полностью исключает обращение к ACME CA при перезапусках.
2. **Экстренное переключение на альтернативный ACME CA:** Если лимиты Let's Encrypt исчерпаны, переключить статический конфиг на независимый центр сертификации (ZeroSSL, BuyPass, Smallstep / Step-CA) через директиву `certificatesResolvers.<name>.acme.caServer`.
3. **Модификация SAN-списка:** Для обхода лимита дубликатов (5 в неделю) в список доменов роутера временно добавляется дополнительный псевдоним (SAN), например `dr-fallback.example.com`, что создает новый уникальный набор имен и инициирует выпуск в рамках недельного окна.
4. **Аварийный fallback на статические сертификаты:** Экстренная генерация самоподписанного wildcard-сертификата или использование корпоративного внутреннего CA через секцию `tls.certificates` файлового провайдера.

---

## Практические сценарии

### Сценарий 1: Производственный скрипт атомарного бэкапа и верификации

Резервное копирование `acme.json` на работающем сервере требует защиты от копирования частично записанного файла. Скрипт использует утилиту `flock`, проверяет валидность JSON через `jq empty`, вычисляет контрольную сумму SHA-256 и выполняет ротацию архивов.

#### 1. Скрипт резервного копирования `/usr/local/bin/traefik-backup.sh`

```bash
#!/usr/bin/env bash
# /usr/local/bin/traefik-backup.sh
# Production Disaster Recovery Backup для Traefik (Bare-Metal / VM)
set -euo pipefail

BACKUP_ROOT="/var/backups/traefik"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TARGET_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
LOCK_FILE="/var/run/traefik-backup.lock"
RETENTION_DAYS=14

STATIC_CONF="/etc/traefik/traefik.yml"
DYNAMIC_DIR="/etc/traefik/dynamic"
ACME_FILE="/var/lib/traefik/acme.json"

# Предотвращение параллельного запуска через дескриптор блокировки
exec 200>"$LOCK_FILE"
flock -n 200 || { echo "ERROR: Резервное копирование уже выполняется." >&2; exit 1; }

echo "[$(date +'%F %T')] Запуск процедуры резервного копирования Traefik..."

# Проверка целостности acme.json перед сохранением
if [ -f "$ACME_FILE" ]; then
    if ! jq empty "$ACME_FILE" 2>/dev/null; then
        echo "CRITICAL: Файл $ACME_FILE поврежден или имеет невалидный JSON синтаксис! Отмена создания бэкапа." >&2
        exit 2
    fi
    # Проверка, что файл не пустой
    if [ ! -s "$ACME_FILE" ]; then
        echo "CRITICAL: Файл $ACME_FILE имеет нулевой размер! Отмена создания бэкапа." >&2
        exit 3
    fi
else
    echo "WARNING: Файл $ACME_FILE отсутствует. Пропускаем сохранение сертификатов ACME."
fi

mkdir -p "$TARGET_DIR"
chmod 700 "$TARGET_DIR"

# Копирование статической конфигурации
if [ -f "$STATIC_CONF" ]; then
    cp -p "$STATIC_CONF" "${TARGET_DIR}/traefik.yml"
fi

# Копирование динамической конфигурации
if [ -d "$DYNAMIC_DIR" ]; then
    cp -rp "$DYNAMIC_DIR" "${TARGET_DIR}/dynamic"
fi

# Атомарное копирование acme.json с фиксацией прав 0600
if [ -f "$ACME_FILE" ]; then
    cp -p "$ACME_FILE" "${TARGET_DIR}/acme.json"
    chmod 600 "${TARGET_DIR}/acme.json"
fi

# Формирование сжатого архива
ARCHIVE_PATH="${BACKUP_ROOT}/traefik-backup-${TIMESTAMP}.tar.gz"
tar -czf "$ARCHIVE_PATH" -C "$BACKUP_ROOT" "$TIMESTAMP"
chmod 600 "$ARCHIVE_PATH"
rm -rf "$TARGET_DIR"

# Вычисление контрольной суммы
sha256sum "$ARCHIVE_PATH" > "${ARCHIVE_PATH}.sha256"

# Ротация старых локальных архивов
find "$BACKUP_ROOT" -maxdepth 1 -name "traefik-backup-*.tar.gz*" -mtime +"$RETENTION_DAYS" -delete

echo "[$(date +'%F %T')] Резервная копия успешно создана: $ARCHIVE_PATH"
echo "[$(date +'%F %T')] SHA256: $(cat "${ARCHIVE_PATH}.sha256")"
```

#### 2. Настройка прав и автоматизации через systemd timer

```bash
# Установка прав на исполнение
sudo chmod 750 /usr/local/bin/traefik-backup.sh
sudo chown root:root /usr/local/bin/traefik-backup.sh

# Создание systemd service
sudo tee /etc/systemd/system/traefik-backup.service > /dev/null << 'EOF'
[Unit]
Description=Automated Traefik Backup Service
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/traefik-backup.sh
EOF

# Создание systemd timer (запуск каждые 6 часов)
sudo tee /etc/systemd/system/traefik-backup.timer > /dev/null << 'EOF'
[Unit]
Description=Run Traefik Backup every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now traefik-backup.timer

# Проверка расписания таймера
systemctl list-timers traefik-backup.timer
# → NEXT                        LEFT          LAST PASSED UNIT                 ACTIVATES
# → Fri 2026-10-17 18:00:00 MSK 2h 30min left n/a  n/a    traefik-backup.timer traefik-backup.service
```

#### 3. Репликация бэкапов на удаленный сервер хранения (Off-site replication)

```bash
# Синхронизация защищенных архивов по SSH на изолированный сервер бэкапов
rsync -avz -e "ssh -i /root/.ssh/id_ed25519_backup -p 22" \
  --include="traefik-backup-*.tar.gz*" \
  --exclude="*" \
  /var/backups/traefik/ backup-node.corp.internal:/data/backups/traefik/
# → sending incremental file list
# → traefik-backup-20261017_150000.tar.gz
# → traefik-backup-20261017_150000.tar.gz.sha256
# → sent 12,410 bytes  received 64 bytes  24,948.00 bytes/sec
# → total size is 45,120  speedup is 3.62
```

---

### Сценарий 2: Аварийное извлечение сертификатов и ключей из `acme.json` (PEM Fallback)

При повреждении Traefik или необходимости экстренно перенести сертификаты на другой балансировщик (например, аварийный инстанс HAProxy или Nginx) ключи и сертификаты извлекаются напрямую из JSON-структуры.

```bash
#!/usr/bin/env bash
# /usr/local/bin/traefik-extract-certs.sh
# Извлечение сертификатов X.509 и приватных ключей из acme.json в PEM-файлы
set -euo pipefail

ACME_FILE="/var/lib/traefik/acme.json"
OUTPUT_DIR="/etc/ssl/traefik-extracted"
RESOLVER_NAME="letsencrypt" # Имя резолвера в static config

mkdir -p "$OUTPUT_DIR"
chmod 700 "$OUTPUT_DIR"

if [ ! -f "$ACME_FILE" ]; then
    echo "ERROR: Файл $ACME_FILE не найден." >&2
    exit 1
fi

# Получение списка всех доменов из хранилища
DOMAINS=$(jq -r ".${RESOLVER_NAME}.Certificates[]?.domain.main" "$ACME_FILE")

for DOMAIN in $DOMAINS; do
    echo "Извлечение сертификатов для: $DOMAIN"
    
    # Извлечение открытого сертификата (Base64 -> PEM)
    jq -r ".${RESOLVER_NAME}.Certificates[] | select(.domain.main==\"$DOMAIN\") | .certificate" "$ACME_FILE" \
        | base64 -d > "${OUTPUT_DIR}/${DOMAIN}.crt"
    chmod 644 "${OUTPUT_DIR}/${DOMAIN}.crt"
    
    # Извлечение закрытого ключа (Base64 -> PEM)
    jq -r ".${RESOLVER_NAME}.Certificates[] | select(.domain.main==\"$DOMAIN\") | .key" "$ACME_FILE" \
        | base64 -d > "${OUTPUT_DIR}/${DOMAIN}.key"
    chmod 600 "${OUTPUT_DIR}/${DOMAIN}.key"
    
    # Верификация срока действия извлеченного сертификата
    openssl x509 -in "${OUTPUT_DIR}/${DOMAIN}.crt" -noout -dates
done

echo "Экстракция завершена. Сертификаты сохранены в $OUTPUT_DIR"
```

Применение извлеченных сертификатов в аварийном динамическом файле `/etc/traefik/dynamic/dr-fallback-tls.yml`:

```yaml
tls:
  certificates:
    - certFile: /etc/ssl/traefik-extracted/app.example.com.crt
      keyFile: /etc/ssl/traefik-extracted/app.example.com.key
      stores:
        - default
```

---

### Сценарий 3: Полное восстановление после катастрофической потери хоста (Cold-site Restore)

Регламент восстановления узла Traefik на вновь развернутом физическом сервере или ВМ (Ubuntu 24.04 / Debian 12 / Rocky Linux 9).

#### 1. Подготовка окружения и установка бинарника Traefik

```bash
# 1. Создание системного пользователя и групп без шелла
sudo useradd -r -U -d /var/lib/traefik -s /usr/sbin/nologin traefik

# 2. Создание системных директорий
sudo mkdir -p /etc/traefik/dynamic /var/lib/traefik /var/log/traefik
sudo chown -R root:traefik /etc/traefik
sudo chown -R traefik:traefik /var/lib/traefik /var/log/traefik
sudo chmod 750 /etc/traefik /var/log/traefik
sudo chmod 700 /var/lib/traefik

# 3. Скачивание и установка бинарного файла Traefik v3
TRAEFIK_VERSION="v3.3.4"
curl -sSL "https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION}_linux_amd64.tar.gz" \
  | sudo tar -xz -C /usr/local/bin traefik
sudo chmod 755 /usr/local/bin/traefik

# 4. Предоставление возможности привязки к портам 80/443 непривилегированному процессу
sudo setcap 'cap_net_bind_service=+ep' /usr/local/bin/traefik
```

#### 2. Развертывание systemd unit-файла

```bash
sudo tee /etc/systemd/system/traefik.service > /dev/null << 'EOF'
[Unit]
Description=Traefik Edge Router
Documentation=https://doc.traefik.io/traefik/
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=traefik
Group=traefik
ExecStartPre=/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml
Restart=always
RestartSec=3s
TimeoutStopSec=45s

# Безопасность и изоляция процесса
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
LimitNOFILE=1048576
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/traefik /var/log/traefik
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
```

#### 3. Восстановление данных из резервной копии и валидация

```bash
LATEST_BACKUP="/var/backups/traefik/traefik-backup-20261017_150000.tar.gz"

# 1. Проверка контрольной суммы
sha256sum -c "${LATEST_BACKUP}.sha256"
# → traefik-backup-20261017_150000.tar.gz: OK

# 2. Распаковка во временный каталог
TEMP_RESTORE=$(mktemp -d)
tar -xzf "$LATEST_BACKUP" -C "$TEMP_RESTORE"

# 3. Восстановление конфигурационных файлов
sudo cp "$TEMP_RESTORE"/*/traefik.yml /etc/traefik/
sudo cp -rp "$TEMP_RESTORE"/*/dynamic/* /etc/traefik/dynamic/
sudo cp "$TEMP_RESTORE"/*/acme.json /var/lib/traefik/

# 4. СТРОГОЕ восстановление владельцев и прав доступа
sudo chown -R root:traefik /etc/traefik
sudo chown -R traefik:traefik /var/lib/traefik
sudo chmod 600 /var/lib/traefik/acme.json

# Проверка фактических прав на acme.json
stat -c "%a %U:%G" /var/lib/traefik/acme.json
# → 600 traefik:traefik

# 5. Очистка временных файлов
rm -rf "$TEMP_RESTORE"

# 6. Валидация статической конфигурации бинарником Traefik
/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml
# → Configuration OK

# 7. Запуск службы и проверка статуса
sudo systemctl daemon-reload
sudo systemctl enable --now traefik.service
sudo systemctl status traefik.service --no-pager
# → Active: active (running) ...

# 8. Финальная верификация готовности через /ping
curl -i http://127.0.0.1:8080/ping
# → HTTP/1.1 200 OK
# → OK
```

---

### Сценарий 4: Локальный Failover на базе Keepalived VRRP (On-Premise HA)

Схема обеспечивает автоматическое переключение общего виртуального IP (VIP) `192.168.1.100` между двумя физическими узлами Traefik (Master: `192.168.1.11`, Backup: `192.168.1.12`) при отказе службы или сервера.

```text
       [ Входящий клиентский трафик ]
                      │
                      ▼
         [ Виртуальный IP: 192.168.1.100 ]
                      │
         ┌────────────┴────────────┐
         │ (VRRP Master)           │ (VRRP Backup)
         ▼                         ▼
┌─────────────────┐       ┌─────────────────┐
│ Traefik Node 1  │       │ Traefik Node 2  │
│ 192.168.1.11    │       │ 192.168.1.12    │
│ keepalived: M   │◄─────►│ keepalived: B   │
│ Traefik: active │ unicast│ Traefik: active │
└─────────────────┘       └─────────────────┘
```

#### 1. Конфигурация Keepalived на узле 1 (`/etc/keepalived/keepalived.conf`)

```text
global_defs {
    router_id traefik_node1
    enable_script_security
    script_user root
}

# Скрипт проверки доступности Traefik через локальный /ping
vrrp_script check_traefik_health {
    script "/usr/local/bin/check_traefik.sh"
    interval 2     # Проверка каждые 2 секунды
    weight -20     # Снижение приоритета при сбое
    fall 2         # Число неудач для фиксации аварии
    rise 2         # Число успешных проверок для восстановления
}

vrrp_instance VI_TRAEFIK {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1

    # Защита от Multicast-проблем: строгий Unicast
    unicast_src_ip 192.168.1.11
    unicast_peer {
        192.168.1.12
    }

    authentication {
        auth_type PASS
        auth_pass Secr3tVrrpPass
    }

    virtual_ipaddress {
        192.168.1.100/24 dev eth0
    }

    track_script {
        check_traefik_health
    }
}
```

На резервном узле (`192.168.1.12`) параметры меняются на:
- `state BACKUP`
- `priority 90`
- `unicast_src_ip 192.168.1.12`
- `unicast_peer { 192.168.1.11 }`

#### 2. Скрипт мониторинга состояния `/usr/local/bin/check_traefik.sh`

```bash
#!/usr/bin/env bash
# Проверка жизнеспособности Traefik для Keepalived
set -euo pipefail

# Опрос внутреннего эндпоинта ping с жестким таймаутом в 1 секунду
if curl -sf --max-time 1 http://127.0.0.1:8080/ping > /dev/null 2>&1; then
    exit 0
else
    exit 1
fi
```

```bash
sudo chmod 755 /usr/local/bin/check_traefik.sh
sudo systemctl restart keepalived
```

#### 3. Тестирование отработки сбоя (Failover Test)

```bash
# 1. Проверка наличия VIP на Master узле
ip -4 addr show eth0 | grep "inet "
# → inet 192.168.1.11/24 brd 192.168.1.255 scope global eth0
# → inet 192.168.1.100/24 scope global secondary eth0

# 2. Симуляция падения службы Traefik на Master
sudo systemctl stop traefik

# 3. Инспекция системного журнала Keepalived
sudo journalctl -u keepalived -n 5 --no-pager
# → Keepalived_vrrp[1234]: Script `check_traefik_health` failed with status 1
# → Keepalived_vrrp[1234]: VRRP_Instance(VI_TRAEFIK) Changing effective priority from 100 to 80
# → Keepalived_vrrp[1234]: (VI_TRAEFIK) Entering BACKUP STATE
# → Keepalived_vrrp[1234]: (VI_TRAEFIK) removing VIPs.

# 4. Проверка на Backup узле (192.168.1.12)
ip -4 addr show eth0 | grep "inet "
# → inet 192.168.1.12/24 brd 192.168.1.255 scope global eth0
# → inet 192.168.1.100/24 scope global secondary eth0
# Результат: Переключение VIP выполнено за 2 секунды без потери пакетов на клиентах.
```

---

### Сценарий 5: Межсайтовый/Multi-DC Failover без облаков (BGP Anycast с BIRD)

В корпоративных инфраструктурах с двумя независимыми ЦОД (DC1 и DC2) маршрутизация клиентского трафика строится на базе **BGP Anycast**. Один и тот же публичный или корпоративный IP-адрес шлюза (`198.51.100.1/32`) настраивается на loopback-интерфейсе серверов Traefik в обоих дата-центрах и анонсируется на пограничные маршрутизаторы (ToR / Spine) через BGP-демон **BIRD**.

```text
                      [ Клиентский трафик ]
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            [ Router DC1 ]            [ Router DC2 ]
            AS 65000                  AS 65000
                    │ (BGP)                 │ (BGP)
                    ▼                       ▼
          ┌──────────────────┐    ┌──────────────────┐
          │ Traefik Node DC1 │    │ Traefik Node DC2 │
          │ dummy0:          │    │ dummy0:          │
          │ 198.51.100.1/32  │    │ 198.51.100.1/32  │
          │ BIRD: Announce   │    │ BIRD: Announce   │
          └──────────────────┘    └──────────────────┘
```

#### 1. Создание виртуального Anycast-интерфейса

```bash
# Добавление dummy-интерфейса на узле Traefik
sudo ip link add dummy0 type dummy
sudo ip addr add 198.51.100.1/32 dev dummy0
sudo ip link set dummy0 up
```

Для персистентности создается unit systemd-networkd или файл `/etc/network/interfaces`.

#### 2. Настройка BGP-демона BIRD 2 (`/etc/bird/bird.conf`)

```text
log syslog all;
router id 10.0.1.10;

# Проверка доступности Traefik
protocol direct {
    interface "dummy0";
}

protocol kernel {
    ipv4 {
        export none;
    };
}

protocol device {
}

# Шаблон проверки маршрута Anycast
protocol static traefik_anycast {
    ipv4;
    route 198.51.100.1/32 via "dummy0";
}

# Сессия BGP с маршрутизатором ToR (Top-of-Rack)
protocol bgp tor_router {
    local 10.0.1.10 as 65001;
    neighbor 10.0.1.1 as 65000;
    ipv4 {
        import none;
        export filter {
            # Анонсировать Anycast-маршрут только если интерфейс активен
            if proto = "traefik_anycast" then accept;
            reject;
        };
    };
}
```

#### 3. Сторожевой скрипт отзыва BGP-анонса `/usr/local/bin/traefik-bgp-watchdog.sh`

```bash
#!/usr/bin/env bash
# Сторожевой процесс: отзывает Anycast IP при отказе Traefik
set -euo pipefail

ANYCAST_IF="dummy0"

if curl -sf --max-time 1 http://127.0.0.1:8080/ping > /dev/null 2>&1; then
    # Traefik здоров: поднимаем интерфейс, BIRD анонсирует маршрут
    if [ "$(cat /sys/class/net/${ANYCAST_IF}/operstate)" != "up" ]; then
        ip link set "$ANYCAST_IF" up
        birdc reload > /dev/null
    fi
else
    # Traefik не отвечает: гасим интерфейс, BIRD мгновенно отзывает BGP-маршрут
    if [ "$(cat /sys/class/net/${ANYCAST_IF}/operstate)" = "up" ]; then
        echo "ALERT: Traefik деградировал. Отзываем BGP Anycast анонс!" >&2
        ip link set "$ANYCAST_IF" down
        birdc reload > /dev/null
    fi
fi
```

**Результат:** При отказе Traefik в DC1 маршрут отзывается по протоколу BGP в течение 1–3 секунд. Магистральные маршрутизаторы автоматически перенаправляют клиентские пакеты на узел Traefik в DC2. RTO = 1–3 секунды, RPO = 0.

---

### Сценарий 6: Disaster Recovery в On-Premise Kubernetes

В Bare-Metal / On-Premise кластерах Kubernetes Traefik развертывается через Helm или манифесты IngressRoute. Состояние конфигурации хранится в объектах etcd, а сертификаты — в K8s Secrets.

#### 1. PodDisruptionBudget и защита от одновременного падения

Для гарантии доступности во время планового обновления нод или непредвиденного сбоя пода создается PDB:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik-pdb
  namespace: traefik
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
```

Deployment с защитой от размещения реплик на одной физической ноде (Anti-Affinity):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: traefik
  namespace: traefik
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
  template:
    metadata:
      labels:
        app.kubernetes.io/name: traefik
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchExpressions:
                  - key: app.kubernetes.io/name
                    operator: In
                    values: ["traefik"]
              topologyKey: "kubernetes.io/hostname"
      containers:
        - name: traefik
          image: traefik:v3.3.4
          readinessProbe:
            httpGet:
              path: /ping
              port: 8080
            initialDelaySeconds: 2
            periodSeconds: 3
```

#### 2. Резервное копирование и восстановление ресурсов Traefik через Velero

```bash
# Резервное копирование пространства имен Traefik (CRD, Secrets, Deployments, Service)
velero backup create traefik-full-backup \
  --include-namespaces traefik \
  --include-cluster-resources=true \
  --wait
# → Backup completed with status: Completed.

# Проверка резервной копии
velero backup describe traefik-full-backup
# → Phase: Completed

# Восстановление после полной аварии кластера K8s
velero restore create --from-backup traefik-full-backup --wait
# → Restore completed with status: Completed.
```

---

### Сценарий 7: Автоматизированный DR Drill (Плановые учения)

Скрипт выполняет контролируемое плановое учение по симуляции катастрофы и восстановлению из бэкапа на резервном тестовом хосте.

```bash
#!/usr/bin/env bash
# /usr/local/bin/traefik-dr-drill.sh
# Автоматизированный сценарий проверки плана аварийного восстановления
set -euo pipefail

echo "=========================================================="
echo "      СТАРТ ПЛАНОВЫХ УЧЕНИЙ DISASTER RECOVERY (TRAEFIK)   "
echo "=========================================================="

BACKUP_ARCHIVE="/var/backups/traefik/latest.tar.gz"

if [ ! -f "$BACKUP_ARCHIVE" ]; then
    echo "CRITICAL: Тестовый архив $BACKUP_ARCHIVE не найден." >&2
    exit 1
fi

# 1. Создание защитного снапшота текущего рабочего состояния
echo "[ШАГ 1] Фиксация пред-аварийного снапшота..."
SNAPSHOT_DIR="/tmp/traefik-pre-drill-snapshot"
rm -rf "$SNAPSHOT_DIR"
mkdir -p "$SNAPSHOT_DIR"
cp -rp /etc/traefik /var/lib/traefik "$SNAPSHOT_DIR/"

# 2. Имитация катастрофического отказа (Data Loss & Process Death)
echo "[ШАГ 2] Симуляция аварии: остановка Traefik и стирание данных..."
sudo systemctl stop traefik
sudo rm -rf /etc/traefik/dynamic/*
sudo rm -f /var/lib/traefik/acme.json

# 3. Восстановление из архива
echo "[ШАГ 3] Восстановление из резервного архива..."
TEMP_RESTORE=$(mktemp -d)
tar -xzf "$BACKUP_ARCHIVE" -C "$TEMP_RESTORE"

sudo cp "$TEMP_RESTORE"/*/traefik.yml /etc/traefik/
sudo cp -rp "$TEMP_RESTORE"/*/dynamic/* /etc/traefik/dynamic/
sudo cp "$TEMP_RESTORE"/*/acme.json /var/lib/traefik/

# 4. Проверка и принудительное выставление прав
echo "[ШАГ 4] Фиксация прав доступа..."
sudo chown -R root:traefik /etc/traefik
sudo chown -R traefik:traefik /var/lib/traefik
sudo chmod 600 /var/lib/traefik/acme.json
rm -rf "$TEMP_RESTORE"

# 5. Проверка синтаксиса
echo "[ШАГ 5] Синтаксическая валидация конфигурации..."
/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml

# 6. Запуск службы и тестирование отклика
echo "[ШАГ 6] Запуск сервиса Traefik..."
sudo systemctl start traefik
sleep 3

# 7. Функциональные тесты
echo "[ШАГ 7] Проверка готовности (Readiness Verification)..."
PING_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ping)

if [ "$PING_STATUS" -eq 200 ]; then
    echo "-> /ping эндпоинт вернул HTTP 200 OK"
else
    echo "CRITICAL: Traefik не отвечает на /ping! Код: $PING_STATUS" >&2
    exit 2
fi

# 8. Проверка локального TLS-хендшейка
echo "[ШАГ 8] Проверка TLS Handshake..."
if echo | openssl s_client -connect 127.0.0.1:443 -servername app.example.com 2>/dev/null | grep -q "CONNECTED"; then
    echo "-> TLS соединение на порту 443 успешно установлено."
else
    echo "WARNING: Не удалось подтвердить TLS handshake (проверьте наличие роутеров в динамической конфигурации)."
fi

# 9. Очистка снапшота
rm -rf "$SNAPSHOT_DIR"

echo "=========================================================="
echo "     УЧЕНИЯ УСПЕШНО ЗАВЕРШЕНЫ. ПЛАН DR РАБОТОСПОСОБЕН     "
echo "=========================================================="
```

---

## Операции и команды

Сводный справочник команд дежурного инженера SRE и системного администратора при ликвидации аварий:

| Категория | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Синтаксис** | `/usr/local/bin/traefik config validate --configfile=/etc/traefik/traefik.yml` | Проверка статического конфига (`# → Configuration OK`) |
| **Целостность ACME** | `jq empty /var/lib/traefik/acme.json` | Проверка JSON синтаксиса хранилища (`# → code 0` при успехе) |
| **Инспекция прав** | `stat -c "%a %U:%G" /var/lib/traefik/acme.json` | Проверка строгих прав доступа (`# → 600 traefik:traefik`) |
| **Статус службы** | `systemctl status traefik.service` | Проверка состояния сервиса (`# → Active: active (running)`) |
| **Healthcheck** | `curl -i http://127.0.0.1:8080/ping` | Проверка готовности прокси (`# → HTTP/1.1 200 OK`, тело: `OK`) |
| **Срок TLS** | `echo \| openssl s_client -connect 127.0.0.1:443 -servername app.example.com 2>/dev/null \| openssl x509 -noout -enddate` | Проверка даты окончания сертификата (`# → notAfter=...`) |
| **Keepalived VIP** | `ip addr show dev eth0 \| grep 192.168.1.100` | Проверка присутствия виртуального IP на интерфейсе |
| **Keepalived Status** | `systemctl status keepalived` | Проверка статуса демона VRRP |
| **BGP Сессии** | `birdc show protocols` | Проверка состояния пиринга BGP Anycast (`# → BGP state: Established / up`) |
| **Поиск ошибок ACME** | `journalctl -u traefik -e \| grep -i "acme"` | Анализ ошибок валидации или исчерпания лимитов Let's Encrypt |

---

## Устранение неисправностей

| Проблема | Диагностический признак | Первопричина | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| **Повреждение файла `acme.json`** | `failed to unmarshal ACME account: unexpected end of JSON input` | Аварийный `SIGKILL`, выключение питания или одновременная запись двух инстансов в один файл | 1. Остановить Traefik: `systemctl stop traefik`.<br>2. Восстановить `acme.json` из последнего валидного бэкапа.<br>3. Проверить синтаксис: `jq empty /var/lib/traefik/acme.json`.<br>4. Выставить права `chmod 600` и запустить службу. |
| **Сбой запуска из-за прав `acme.json`** | `permissions 0644 for /var/lib/traefik/acme.json are too open, it should be 0600` | Файл восстановлен из архива без сохранения прав или создан вручную без `chmod` | Выполнить: `sudo chmod 600 /var/lib/traefik/acme.json` и `sudo chown traefik:traefik /var/lib/traefik/acme.json`, после чего перезапустить сервис. |
| **Блокировка по квотам Let's Encrypt (Rate Limit)** | `429 urn:ietf:params:acme:error:rateLimited: too many certificates already issued` | Утрата `acme.json` и попытка перевыпустить сертификаты для сотен доменов заново | 1. Добавить временный дополнительный SAN в домен роутера (обход duplicate limit).<br>2. Переключить `caServer` на ZeroSSL (`https://acme.zerossl.com/v2/DV90`) или внутренний Step-CA.<br>3. Использовать аварийный статический сертификат через `tls.certificates`. |
| **Keepalived Split-Brain (два мастера)** | Оба узла держат VIP `192.168.1.100`, коллизия ARP в сети | Межсетевой экран блокирует VRRP пакеты (протокол 112) или несовпадение `auth_pass` / `virtual_router_id` | 1. Разрешить протокол 112 в iptables/nftables: `iptables -A INPUT -p vrrp -j ACCEPT`.<br>2. Перевести Keepalived на строгий unicast (`unicast_peer`).<br>3. Сверить пароль `auth_pass` и ID виртуального роутера. |
| **Просроченные сертификаты после Cold Restore** | Браузеры отдают ошибку `SEC_ERROR_EXPIRED_CERTIFICATE`, хотя Traefik запущен | Сервер восстановлен из устаревшего архива (> 90 дней), автоматический renew заблокирован | 1. Проверить доступность 80 порта для HTTP-01 challenge.<br>2. Проверить DNS-записи.<br>3. Если лимит исчерпан, временно выпустить staging-сертификат или wildcard через корпоративный CA. |
| **BGP Anycast Blackhole (трафик идет в никуда)** | Запросы клиентов уходят на узел Traefik, отдающий ошибки TCP RST / Timeout | Traefik аварийно упал, но интерфейс `dummy0` остался поднят, BIRD продолжает анонсировать префикс | 1. Настроить watchdog-скрипт с `birdc reload` при падении `/ping`.<br>2. Вручную отключить интерфейс: `ip link set dummy0 down`.<br>3. Проверить отзыв маршрута: `birdc show route`. |
| **Отказ HTTP-01 challenge после переноса на новый хост** | `Cannot obtain certificates: error 403: Invalid response from http://.../.well-known/acme-challenge` | Новый сервер не принимает внешний трафик на порту 80 или файрвол блокирует входящие соединения | 1. Открыть порт 80: `ufw allow 80/tcp` или `firewall-cmd --add-port=80/tcp --permanent`.<br>2. Убедиться, что порт 80 слушается Traefik: `ss -tulpn \| grep :80`. |

---

## Рекомендации

- **Правило 3-2-1 для `acme.json`:** Храните минимум 3 копии файла сертификатов на 2 различных типах носителей, из которых 1 копия находится на изолированной off-site площадке (сервер резервного копирования в другом ДЦ).
- **Валидация перед архивацией:** Никогда не делайте бэкап `acme.json` без предварительной проверки валидности синтаксиса через `jq empty`. Запись поврежденного JSON в архив уничтожит валидную резервную копию при ротации.
- **Шифрование резервных копий:** Файл `acme.json` содержит незашифрованные закрытые ключи (RSA/ECDSA). Все архивы бэкапов перед отправкой по сети должны шифроваться асимметричным ключом (GPG или `age`).
- **Разделение прав доступа:** Файл `acme.json` обязан иметь права исключительно `0600` и принадлежать пользователю `traefik`. Конфигурационные файлы `/etc/traefik` должны быть доступны процессу только на чтение (`read-only`).
- **Мониторинг истечения сертификатов через Blackbox:** Поскольку Traefik OSS не экспортирует метрики оставшихся дней жизни сертификатов, используйте **Prometheus Blackbox Exporter** (`probe_ssl_earliest_cert_expiry`) для внешнего контроля срока годности с алертом за 14 дней до истечения. Подробнее: [Мониторинг сертификатов Traefik](./traefik-cert-monitoring.md).
- **Регулярные плановые учения (DR Drills):** Минимум один раз в квартал проводите учения по аварийному восстановлению на изолированном сервере с полным прохождением регламента холодного восстановления.
- **Подготовка аварийного fallback-конфига:** Всегда держите в репозитории заранее подготовленный файл `dr-fallback-tls.yml` со статическими сертификатами на случай блокировки по лимитам Let's Encrypt.

---

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — базовая архитектура, статические и динамические параметры, entryPoints и сервисы.
- [Traefik на bare-metal](./traefik-bare-metal.md) — развертывание под управлением systemd, Linux capabilities, оптимизация сетевого стека.
- [High Availability Traefik](./traefik-high-availability.md) — паттерны высокой доступности, zero-downtime деплой и rolling updates.
- [Мониторинг сертификатов](./traefik-cert-monitoring.md) — проактивный мониторинг дат окончания TLS через Prometheus Blackbox Exporter и Node Exporter.
- [Graceful Shutdown и Zero-Downtime Deploy в Traefik](./traefik-graceful-shutdown.md) — жизненный цикл соединений, перехват сигналов SIGTERM и дренаж трафика.
- [Traefik в Kubernetes](./traefik-kubernetes.md) — архитектура IngressRoute, RBAC, Helm и PodDisruptionBudget.
- [Keepalived — обзор и настройка высокой доступности (HA)](../../Networking/ServicesAndTools/keepalived_overview.md) — детальная настройка протокола VRRP и плавающего IP для bare-metal инфраструктуры.
- [Балансировка нагрузки между локациями с HAProxy](../Concepts/haproxy_multi_location_load_balancing.md) — архитектура multi-DC распределения трафика, BGP Anycast и stick tables.
- [VRRP, HSRP и GLBP](../../Networking/Protocols/vrrp_hsrp_glbp.md) — фундаментальная теория протоколов избыточности первого шлюза (First Hop Redundancy Protocols).
