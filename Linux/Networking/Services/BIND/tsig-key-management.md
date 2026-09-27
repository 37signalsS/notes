# BIND: Управление TSIG-ключами и автоматизация ротации

---

## Определения

**TSIG (Transaction Signature, RFC 8945)** — механизм аутентификации DNS-транзакций на основе общего секретного ключа (HMAC). Ключ используется для подписи DNS-сообщений при трансферах зон (AXFR/IXFR), динамических обновлениях (RFC 2136) и управлении через `rndc`. Работает на уровне транзакции, а не соединения.

**Key Rotation (ротация ключей)** — плановая замена TSIG-ключей с целью ограничения времени компрометации ключа. Если ключ утёк, злоумышленник сможет аутентифицировать DNS-транзакции только до момента ротации. Рекомендуемый интервал: 30-90 дней.

**Dual-Key Method** — метод ротации, при котором два ключа активны одновременно: новый ключ добавляется, старый удаляется после распространения. Гарантирует непрерывность трансферов в процессе ротации.

**HMAC (Hash-based Message Authentication Code)** — алгоритм аутентификации сообщений, используемый TSIG. BIND поддерживает: HMAC-MD5 (устаревший), HMAC-SHA1, HMAC-SHA256 (рекомендуется), HMAC-SHA512.

---

## Базовые концепции

### Зачем ротировать TSIG-ключи

| Угроза | Описание | Решение через ротацию |
| :--- | :--- | :--- |
| **Компрометация ключа** | Утечка ключа позволяет атакующим делать ложные трансферы/обновления | Регулярная замена ограничивает окно уязвимости |
| **Insider Threat** | Сотрудник с доступом к ключу может манипулировать зонами | Ротация при увольнении/смене ответственных |
| **Compliance** | Требования безопасности (PCI-DSS, ISO 27001) требуют регулярной ротации | Автоматизация ротации |
| **Устаревший алгоритм** | HMAC-MD5 считается небезопасным | Ротация с обновлением алгоритма |

### Цикл жизни TSIG-ключа

```text
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Генерация │────>│ Распрост-│────>│ Активное  │────>│ Удаление │
│ нового    │     │ранение   │     │использование│    │ старого  │
│ ключа     │     │ ключа    │     │ (два ключа)│    │ ключа    │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
     │                │                │                │
     │                │                │                │
  tsig-keygen    scp/rsync      master + slave      rndc tsig-list
  + конфиг        на все          работают с          + удаление
                   серверы        двумя ключами       из конфига
```

### Алгоритмы TSIG

| Алгоритм | RFC | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| HMAC-MD5 | RFC 2845 | Устаревший | Не использовать |
| HMAC-SHA1 | RFC 4635 | Допустимый | Для совместимости со старыми серверами |
| HMAC-SHA256 | RFC 4635 | Рекомендуется | Использовать по умолчанию |
| HMAC-SHA512 | RFC 4635 | Современный | Максимальная безопасность |

---

## Практические сценарии

### Предусловия

```bash
# Установка утилит
sudo apt install bind9utils dnsutils

# Проверка текущих ключей
sudo rndc tsig-list
# → transfer-key. HMAC-SHA256: ACTIVE
```

### 1. Генерация нового TSIG-ключа

```bash
# Генерация ключа с алгоритмом HMAC-SHA256
tsig-keygen -a hmac-sha256 transfer-key-2026 > /etc/bind/keys/transfer-key-2026.key

# Просмотр ключа
cat /etc/bind/keys/transfer-key-2026.key
# → key "transfer-key-2026" {
# →     algorithm hmac-sha256;
# →     secret "base64encodedSecret==";
# → };
```

### 2. Двухключевой метод ротации (двойной ключ)

**Шаг 1: Генерация нового ключа (на master):**

```bash
tsig-keygen -a hmac-sha256 transfer-key-new > /tmp/transfer-key-new.key
```

**Шаг 2: Копирование нового ключа на slave-серверы:**

```bash
# Копирование на slave
scp /tmp/transfer-key-new.key ns2:/etc/bind/keys/
scp /tmp/transfer-key-new.key ns3:/etc/bind/keys/

# Установка прав
for ns in ns2 ns3; do
  ssh $ns "chown bind:bind /etc/bind/keys/transfer-key-new.key && chmod 640 /etc/bind/keys/transfer-key-new.key"
done
```

**Шаг 3: Подключение нового ключа на master:**

```conf
// named.conf.local — master
include "/etc/bind/keys/transfer-key.key";       // Старый ключ
include "/etc/bind/keys/transfer-key-new.key";   // Новый ключ

zone "example.com" {
    type master;
    file "/var/lib/bind/db.example.com";
    allow-transfer {
        key "transfer-key";       // Старый ключ (пока работает)
        key "transfer-key-new";   // Новый ключ (добавлен)
    };
};
```

**Шаг 4: Подключение нового ключа на slave:**

```conf
// named.conf.local — slave
include "/etc/bind/keys/transfer-key.key";       // Старый ключ
include "/etc/bind/keys/transfer-key-new.key";   // Новый ключ

zone "example.com" {
    type slave;
    file "/var/lib/bind/db.example.com";
    masters {
        10.0.0.1 key "transfer-key";       // Старый ключ
        10.0.0.1 key "transfer-key-new";   // Новый ключ
    };
};
```

**Шаг 5: Применение конфигурации:**

```bash
# На master
sudo named-checkconf && sudo rndc reconfig

# На slave
sudo named-checkconf && sudo rndc reconfig

# Проверка обоих ключей
sudo rndc tsig-list
# → transfer-key. HMAC-SHA256: ACTIVE
# → transfer-key-new. HMAC-SHA256: ACTIVE
```

**Шаг 6: Проверка трансфера с новым ключом:**

```bash
# Тест AXFR с новым ключом
dig @10.0.0.1 example.com AXFR -k /etc/bind/keys/transfer-key-new.key
# → Данные зоны (трансфер успешен)
```

**Шаг 7: Удаление старого ключа (через 24-48 часов):**

```bash
# Удаление из конфига master
# Закомментировать строку: allow-transfer { key "transfer-key"; };

# Удаление из конфига slave
# Закомментировать строку: masters { 10.0.0.1 key "transfer-key"; };

# Удаление файлов
rm /etc/bind/keys/transfer-key.key
ssh ns2 "rm /etc/bind/keys/transfer-key.key"
ssh ns3 "rm /etc/bind/keys/transfer-key.key"

# Перезагрузка
sudo rndc reconfig
```

### 3. Автоматизация ротации через скрипт

**Файл `/opt/bind-key-rotation/rotate-tsig.sh`:**

```bash
#!/bin/bash
# rotate-tsig.sh — автоматическая ротация TSIG-ключа
set -euo pipefail

# Конфигурация
OLD_KEY="transfer-key"
NEW_KEY="transfer-key-$(date +%Y%m%d)"
KEY_DIR="/etc/bind/keys"
ALGORITHM="hmac-sha256"
SLAVES=("ns2" "ns3")
MASTER="ns1"
LOG_FILE="/var/log/bind-key-rotation.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# Шаг 1: Генерация нового ключа
log "Generating new key: $NEW_KEY"
tsig-keygen -a "$ALGORITHM" "$NEW_KEY" > "$KEY_DIR/$NEW_KEY.key"
chmod 640 "$KEY_DIR/$NEW_KEY.key"
chown bind:bind "$KEY_DIR/$NEW_KEY.key"

# Шаг 2: Распространение на slave-серверы
log "Distributing key to slaves..."
for slave in "${SLAVES[@]}"; do
    scp -q "$KEY_DIR/$NEW_KEY.key" "$slave:$KEY_DIR/"
    ssh "$slave" "chown bind:bind $KEY_DIR/$NEW_KEY.key && chmod 640 $KEY_DIR/$NEW_KEY.key"
    log "Key distributed to $slave"
done

# Шаг 3: Подключение нового ключа на master
log "Updating master configuration..."
cat >> /etc/bind/named.conf.local <<EOF

// Auto-generated: $NEW_KEY added $(date)
include "$KEY_DIR/$NEW_KEY.key";
EOF

# Шаг 4: Обновление allow-transfer (добавить новый ключ)
sed -i "s/key \"$OLD_KEY\";/key \"$OLD_KEY\";\n        key \"$NEW_KEY\";/" /etc/bind/named.conf.local

# Шаг 5: Применение на master
named-checkconf || { log "ERROR: named-checkconf failed on master"; exit 1; }
rndc reconfig
log "Master reconfigured"

# Шаг 6: Применение на slave-серверах
for slave in "${SLAVES[@]}"; do
    ssh "$slave" "
        sed -i 's/key \"$OLD_KEY\";/key \"$OLD_KEY\";\n        key \"$NEW_KEY\";/' /etc/bind/named.conf.local
        named-checkconf && rndc reconfig
    "
    log "Slave $slave reconfigured"
done

# Шаг 7: Проверка
log "Verifying new key..."
for ns in "$MASTER" "${SLAVES[@]}"; do
    result=$(dig @"$ns" example.com +short +time=2)
    if [ -n "$result" ]; then
        log "OK: $ns responds"
    else
        log "ERROR: $ns not responding"
    fi
done

log "Key rotation completed. Old key ($OLD_KEY) will be removed after 48h."
log "Run: $0 --remove-old to remove the old key after the grace period."
```

**Планирование через cron:**

```bash
# Ротация каждые 90 дней
0 2 1 */3 * /opt/bind-key-rotation/rotate-tsig.sh >> /var/log/bind-key-rotation.log 2>&1

# Удаление старого ключа (через 48 часов после ротации)
0 3 3 */3 * /opt/bind-key-rotation/remove-old-key.sh >> /var/log/bind-key-rotation.log 2>&1
```

### 4. Ротация ключа для rndc

** rndc использует отдельный ключ** (не для трансферов):

```bash
# Генерация нового rndc-ключа
tsig-keygen -a hmac-sha256 rndc-key > /etc/bind/rndc.key

# Обновление rndc.conf
cat > /etc/bind/rndc.conf <<EOF
key "rndc-key" {
    algorithm hmac-sha256;
    secret "$(grep secret /etc/bind/rndc.key | awk '{print $2}' | tr -d '";')";
};
options {
    default-key "rndc-key";
    default-server 127.0.0.1;
    default-port 953;
};
EOF

# Синхронизация named.conf
cat >> /etc/bind/named.conf <<EOF
include "/etc/bind/rndc.key";
controls {
    inet 127.0.0.1 port 953
    allow { 127.0.0.1; } keys { "rndc-key"; };
};
EOF

# Перезапуск
sudo rndc reconfig
```

### 5. Мониторинг активности ключей

```bash
# Просмотр всех активных ключей
sudo rndc tsig-list
# → transfer-key. HMAC-SHA256: ACTIVE
# → transfer-key-new. HMAC-SHA256: ACTIVE
# → rndc-key. HMAC-SHA256: ACTIVE

# Проверка последнего трансфера с ключом
sudo rndc zonestatus example.com | grep -i "transfer"
# → last transfer success: ...
# → last transfer from: 10.0.0.1

# Мониторинг через Prometheus (см. logging-and-monitoring.md)
# named_zone_transfer_done_total{key="transfer-key-new"} — счётчик трансферов по ключу
```

---

## Типичные ошибки и их решение

### Трансфер зоны падает после ротации ключа

**Симптом:** `rndc retransfer` возвращает `REFUSED` или `TSIG error`.

**Причина:** Старый ключ удалён до того, как slave обновил конфигурацию.

**Решение:**

```bash
# 1. Временно вернуть старый ключ
# Раскомментировать строку с old key в named.conf.local

# 2. Применить конфиг
sudo rndc reconfig

# 3. Проверить трансфер
dig @ns2 example.com AXFR +noauth | head -5

# 4. Убедиться, что slave обновлён
ssh ns2 "sudo rndc tsig-list"

# 5. Только после этого удалять старый ключ
```

### Clock skew прерывает трансфер

**Симптом:** `TSIG error: signature verification failure`

**Причина:** Разница часов между master и slave превышает 5 минут (по умолчанию).

**Решение:**

```bash
# Синхронизация времени
sudo chronyc makestep

# Проверка
chronyc tracking | grep "System time"

# Увеличение допуска (в named.conf)
server 10.0.0.1 {
    key "transfer-key";
    tsig-clockskew 300;  # 5 минут (по умолчанию)
};
```

### Ключ не распознаётся

**Симптом:** `rndc: key 'transfer-key' unknown`

**Причина:** Файл ключа не включён в `named.conf` или путь неверный.

**Решение:**

```bash
# 1. Проверка наличия include
grep "include.*key" /etc/bind/named.conf /etc/bind/named.conf.local

# 2. Проверка синтаксиса ключа
named-checkconf

# 3. Проверка прав доступа
ls -la /etc/bind/keys/
# → -rw-r----- 1 bind bind ... transfer-key.key
```

---

## Лучшие практики

*   **Ротация каждые 30-90 дней** — зависимость от compliance-требований. Для PCI-DSS — 90 дней, для высоких требований безопасности — 30 дней.
*   **Двухключевой метод** — всегда добавляйте новый ключ перед удалением старого. Период перекрытия: 24-48 часов.
*   **HMAC-SHA256 минимум** — не используйте HMAC-MD5. Для максимальной безопасности — HMAC-SHA512.
*   **Автоматизация** — ручная ротация容易 забывается. Используйте скрипты + cron или Ansible.
*   **Хранение секретов** — TSIG-ключи в HashiCorp Vault или Ansible Vault, не в Git в открытом виде.
*   **Мониторинг** — отслеживайте `rndc tsig-list` и алертируйте при появлении неожиданных ключей.
*   **Документирование** — записывайте: какой ключ используется для чего, когда последняя ротация, кто отвечает.
*   **Логирование** — все операции ротации логируйте в `/var/log/bind-key-rotation.log`.

---

## Дополнительная информация

### Ключевые RFC

*   **RFC 8945:** TSIG (Transaction Signatures) — текущий стандарт.
*   **RFC 2845:** TSIG (устаревший) — HMAC-MD5.
*   **RFC 4635:** TSIG HMAC-SHA-256.
*   **RFC 2136:** Dynamic Updates — использование TSIG для динамических обновлений.

### Связанные разделы

*   [BIND: Slave сервер](./slave_server_configuration.md) — трансферы зон с TSIG.
*   [BIND: Автоматизация (IaC)](./automation-iac.md) — Ansible для управления ключами.
*   [BIND: Обзор](./overview.md) — архитектура и TSIG.
*   [Безопасность DNS](../../../Networking/Protocols/DNS/dns_security.md) — TSIG, DANE, DNSSEC.
