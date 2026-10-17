# Key Escrow — политика хранения копий ключей

**Актуально для:** Key Escrow policy (NIST SP 800-57 Rev. 5, ISO 27001, PCI DSS 4.0, FIPS 140-3; инструменты: ssss 0.5, OpenSSL 3.0+)

## Определения

**Key Escrow** — механизм доверенного хранения копий криптографических ключей третьей стороной (escrow-агентом). Позволяет восстановить доступ к зашифрованным данным при потере ключа, увольнении сотрудника или по требованию компетентных органов.

**Escrow Agent** — юридическое или техническое лицо, хранящее копии ключей и предоставляющее их в соответствии с политикой (например, при судебном запросе или утере оригинала).

**Key Recovery** — процесс восстановления ключа из escrow-хранилища. Требует выполнения условий политики (многофакторное одобрение, юридический запрос).

**Shamir's Secret Sharing (SSS)** — криптографический алгоритм разделения секрета на N частей, где для восстановления достаточно K частей (threshold). Основан на полиномиальных интерполяциях над конечным полем. Описан в работе А. Шамира «How to Share a Secret» (1979).

**Secret Splitting** — разделение ключа/пароля на несколько частей, каждая из которых хранится у разных лиц. Типичная схема: 3 из 5, 2 из 3.

## Концепции и архитектура

### Зачем нужен Key Escrow

| Сценарий | Без escrow | С escrow |
| :--- | :--- | :--- |
| Потеря ключа CA | Полная потеря доступа к зашифрованным данным | Восстановление из escrow |
| Увольнение сотрудника с ключом | Потеря доступа к ресурсам | Восстановление ключа |
| Юридический запрос | Невозможность расшифровки | Предоставление ключа по ордеру |
| Смерть сотрудника | Безвозвратная потеря | Восстановление из escrow |

### Модели Key Escrow

| Модель | Описание | Использование |
| :--- | :--- | :--- |
| **Trusted Third Party** | Независимая организация хранит ключи | Корпоративная среда |
| **Key Splitting (SSS)** | Ключ разделён на части, хранящиеся у разных лиц | CA passphrase, master key |
| **Hardware Security Module (HSM)** | Ключ генерируется и хранится в HSM, escrow через backup ключей HSM | Production PKI |
| **M-of-N Multi-Signature** | Для использования ключа нужно M подписей из N | Критичные операции |

### Архитектура Escrow для CA

```text
┌─────────────────────┐
│     Root CA Key     │
│   (зашифрован)      │
└──────────┬──────────┘
           │
    ssss-split (2-of-3)
           │
    ┌──────┼──────────┐
    │      │          │
    ▼      ▼          ▼
┌───────┐ ┌───────┐ ┌───────┐
│ USB #1│ │ USB #2│ │ USB #3│
│ CEO   │ │ CTO   │ │ CISO  │
└───────┘ └───────┘ └───────┘
    │         │         │
    ▼         ▼         ▼
  Банк     Сейф     Хранилище
 ячейка   в офисе   за границей
```

### Требования compliance

| Стандарт | Требование к ключам |
| :--- | :--- |
| PCI DSS 4.0 | Ключи шифрования должны иметь процедуру восстановления |
| ISO 27001 | Политика управления ключами (A.10.1.2) |
| ГОСТ Р 34.10-2012 | Криптографические средства должны обеспечивать безопасное хранение ключей |
| FIPS 140-3 | Key storage requirements for Level 2+ |
| SOC 2 | Key management and recovery procedures |

## Практические сценарии

### Пререквизиты

- **Для Root CA escrow:** офлайн-носитель с зашифрованным ключом, USB-накопители для split-частей, банковская ячейка для одной из частей
- **Для service escrow:** HashiCorp Vault (standalone, не cloud) или аналогичное локальное HSM-решение
- **Инструменты:** ssss, openssl 3.0+, ssss-combine
- **Лица:** минимум 3 escrow-агента (CEO, CTO, CISO) с разными ролями и юридическим статусом
- **Регламент:** документированная политика доступа (см. ниже), подпись всех агентов

### Разделение ключа через Shamir's Secret Sharing

#### Установка ssss

```bash
# Debian/Ubuntu
sudo apt install ssss

# RHEL/CentOS
sudo dnf install ssss

# macOS
brew install ssss
```

#### Разделение пароля Root CA

```bash
# Разделение на 3 части, достаточно 2 для восстановления
echo -n "MySecretRootCA2026!" | ssss-split -t 2 -n 3
# → И будет выведено 3 шестнадцатеричных строки:
# → 2e34f8a1b9c0d5e6f7a8b9c0d1e2f3a4
# → 5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d
# → 8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c

# Запишите каждую часть на отдельный носитель
# и передайте разным людям
```

#### Восстановление ключа

```bash
# Соберите 2 из 3 частей
echo "2e34f8a1b9c0d5e6f7a8b9c0d1e2f3a4" | ssss-combine -t 2
echo "5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d" | ssss-combine -t 2
# → MySecretRootCA2026!
```

### Автоматизированный workflow для Root CA

```bash
#!/bin/bash
# /opt/ca/scripts/escrow_root_key.sh
# Разделение passphrase Root CA и запись на зашифрованные USB

set -euo pipefail

CA_DIR="/opt/ca/root"
BACKUP_DIR="/opt/ca/escrow"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Генерация случайного passphrase
PASSPHRASE=$(openssl rand -base64 32)

# Шифрование Root CA ключа этим passphrase
openssl rsa -in "$CA_DIR/ca.key" \
  -aes256 \
  -passout pass:"$PASSPHRASE" \
  -out "$BACKUP_DIR/ca-encrypted.key"

# Разделение passphrase через SSSS (2-of-3)
echo -n "$PASSPHRASE" | ssss-split -t 2 -n 3 > "$BACKUP_DIR/escrow-shares.txt"

# SHA-512 хэш для проверки целостности
sha512sum "$BACKUP_DIR/ca-encrypted.key" > "$BACKUP_DIR/ca.key.sha512"

# Запись на USB (3 разных устройства)
for i in 1 2 3; do
    USB_MOUNT="/mnt/usb${i}"
    if mountpoint -q "$USB_MOUNT"; then
        cp "$BACKUP_DIR/ca-encrypted.key" "$USB_MOUNT/"
        cp "$BACKUP_DIR/escrow-shares.txt" "$USB_MOUNT/"
        cp "$BACKUP_DIR/ca.key.sha512" "$USB_MOUNT/"
        echo "USB ${i}: backup written"
    else
        echo "ERROR: USB ${i} not mounted at ${USB_MOUNT}"
        exit 1
    fi
done

# Очистка passphrase из памяти
unset PASSPHRASE

# Логирование
logger -t ca-escrow "Root CA key escrow completed: ${TIMESTAMP}"
echo "Escrow completed at ${TIMESTAMP}"
```

### Политика хранения ключей

```yaml
# /etc/ca-escrow-policy.yaml
key_escrow_policy:
  root_ca:
    storage:
      - location: "Bank safety deposit box #1234"
        holder: "CEO"
        escrow_share: 1
      - location: "Office safe (fireproof)"
        holder: "CTO"
        escrow_share: 2
      - location: "Off-site data center"
        holder: "CISO"
        escrow_share: 3
    threshold: "2-of-3"
    review_interval: "quarterly"
    rotation_interval: "5 years"

  intermediate_ca:
    storage:
      - location: "HSM on intermediate CA server"
        holder: "DevOps team"
      - location: "Encrypted backup in vault"
        holder: "Security team"
    threshold: "1-of-2"
    review_interval: "annually"

  service_keys:
    storage:
      - location: "Vault KV engine"
        holder: "Platform team"
    threshold: "1-of-1"
    review_interval: "on rotation"
```

## Политика доступа к криптографическим ключам

### Условия предоставления ключа из Escrow

1. **Потеря ключа:** запрос от владельца + одобрение 2 из 3 escrow-агентов
2. **Увольнение:** обязательный возврат ключа; при невозможности — немедленный отзов сертификата
3. **Юридический запрос:** только по судебному ордеру, одобрение юридического отдела + CEO
4. **Инцидент:** по запросу CISO + одобрение incident response team

### Процедура восстановления

1. Запрос в письменной форме (или зашифрованный email)
2. Проверка личности запросившего
3. Проверка полномочий (RBAC)
4. Сбор threshold-частей от escrow-агентов
5. Восстановление ключа на изолированном узле
6. Проверка целостности (SHA-512)
7. Использование для целевого назначения
8. Немедленное уничтожение восстановленной копии
9. Логирование инциндента

### Ротация ключей

- Root CA: каждые 10–15 лет (cross-certification-путь ротации)
- Intermediate CA: каждые 3–5 лет
- Сервисные ключи: каждые 90–180 дней
- При ротации: немедленное обновление escrow-хранилища

## Операции и команды

### Проверка целостности escrow backup

```bash
# Проверка SHA-512 хэша
sha512sum -c "$BACKUP_DIR/ca.key.sha512"
# → ca-encrypted.key: OK
```

### Извлечение публичного ключа для pinning

```bash
openssl x509 -in leaf.crt -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64
# → YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=
```

### Шифрование USB-накопителей перед записью ключей

```bash
# На macOS
diskutil eraseVolume JHFS+ "EscrowUSB" /dev/disk2
hdiutil create -volname "Escrow" -size 1g -fs JHFS+ -encryption AES-256 -spawn -- /Volumes/Escrow

# На Linux (LUKS)
sudo cryptsetup luksFormat /dev/sdb1
sudo cryptsetup luksOpen /dev/sdb1 escrow_usb
sudo mkfs.ext4 /dev/mapper/escrow_usb
sudo mount /dev/mapper/escrow_usb /mnt/escrow
```

### Health check escrow-системы

```bash
#!/bin/bash
# /opt/ca/scripts/escrow_health_check.sh
# Проверка готовности escrow-хранилищ к восстановлению

set -euo pipefail

ESCROW_DIR="/opt/ca/escrow"
SHARES_FILE="$ESCROW_DIR/escrow-shares.txt"
BACKUP_KEY="$ESCROW_DIR/ca-encrypted.key"
HASH_FILE="$ESCROW_DIR/ca.key.sha512"

errors=0

# 1. Проверка наличия файлов
for f in "$SHARES_FILE" "$BACKUP_KEY" "$HASH_FILE"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: $f not found"
        ((errors++))
    fi
done

# 2. Проверка целостности
if [[ -f "$HASH_FILE" && -f "$BACKUP_KEY" ]]; then
    if ! sha512sum -c "$HASH_FILE" --quiet 2>/dev/null; then
        echo "ERROR: SHA-512 hash mismatch"
        ((errors++))
    fi
fi

# 3. Проверка, что минимум threshold частей доступно
share_count=$(grep -c '^[0-9a-f]' "$SHARES_FILE" 2>/dev/null || echo 0)
if [[ "$share_count" -lt 2 ]]; then
    echo "ERROR: only $share_count shares available (minimum 2 for recovery)"
    ((errors++))
fi

# 4. Проверка срока годности backup
if [[ -f "$HASH_FILE" ]]; then
    age_days=$(( ($(date +%s) - $(stat -c %Y "$HASH_FILE" 2>/dev/null || stat -f %m "$HASH_FILE")) / 86400 ))
    if [[ "$age_days" -gt 180 ]]; then
        echo "WARNING: backup older than 180 days ($age_days days)"
    fi
fi

if [[ $errors -eq 0 ]]; then
    echo "OK: escrow is healthy (shares: ${share_count}, backup age: ${age_days}d)"
    exit 0
else
    echo "FAIL: $errors issues detected"
    exit 1
fi
```

### Audit logging для Key Escrow

```bash
# Добавьте в /etc/ca-escrow-policy.yaml
audit:
  log_access: true
  retention: "7 years"
  fields:
    - timestamp
    - requesting_user
    - justification
    - approving_agents
    - share_numbers_used
    - recovery_result
    - post_recovery_action  # destroyed / retained
```

```bash
# Пример audit-записи при восстановлении ключа
logger -t ca-escrow-audit "$(date -Iseconds) user=jdoe action=recovery justification='lost key' approvers='CTO,CISO' result=success post_recovery=destroyed"
```

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Все escrow-агенты недоступны | Все хранители ключей уволились/потеряны | Регулярно проводите drill по восстановлению; ротация escrow-агентов |
| Escrow-носитель повреждён | Физическое повреждение USB/диска | Используйте ≥3 носителя в разных локациях; регулярная проверка целостности |
| Ключ восстановлен, но сертификат уже отозван | Медленная реакция на потерю | Восстановленный ключ бесполезен; перевыпускайте сертификат |
| Escrow-агент скомпрометирован | Утечка одной части ключа | Используйте threshold ≥2; регулярная ротация |
| `sha256sum: WARNING: X lines are malformed` | Файл повреждён или подделан | Сравните с резервной копией; если не совпадает — используйте второй escrow-носитель |
| Health check: `only 1 shares available` | Одна из USB-копий потеряна | Немедленно реплицируйте на новые носители (минимум 3) |
| `ssss-combine: checksum check failed` | Неправильная часть или повреждение данных | Проверьте вводимую часть; используйте другую копию share |

## Лучшие практики

1. **Threshold 2-of-3** — рекомендуемая схема для Root CA (баланс безопасности и доступности)
2. **Географическое разделение** — храните escrow-носители в разных зданиях/городах
3. **Регулярные drill** — минимум раз в квартал проверяйте процедуру восстановления
4. **Шифрование носителей** — все USB/диски с ключами должны быть зашифрованы (AES-256, LUKS, FileVault)
5. **Ротация escrow-агентов** — при увольнении/смене роли немедленно передавайте share новому агенту
6. **Логирование** — записывайте все обращения к escrow-хранилищу
7. **Не храните** passphrase рядом с зашифрованным ключом
8. **Для HSM** — escrow-ключей HSM через manufacturer key ceremony; backup key card в банк
9. **Automated health checks** — запускайте escrow_health_check.sh через cron каждые 24 часа
10. **Audit trail** — сохраняйте audit-логи минимум 7 лет, проверяйте ежемесячно

## Дополнительная информация

- **NIST SP 800-57** — [Key Management Recommendation](https://csrc.nist.gov/publications/detail/sp/800-57-part-1/rev-5/final)
- **Shamir, A.** — [How to Share a Secret](https://dl.acm.org/doi/10.1145/62.96589) (1979)
- **[Shamir's Secret Sharing в Root CA](../Tools/openssl_ca/two_tier/root_ca_setup.md#разделение-парольной-фразы-по-схеме-шамира-ssss)** — практическое применение в PKI
- **[Обзор PKI](./pki_overview.md)** — управление ключами в PKI
- **[Secrets Management](./secrets_management_overview.md)** — общие практики управления секретами
- **[Certificate Transparency](./certificate_transparency.md)** — публичное логирование сертификатов
- **[Zero Trust](../../Vault/zero_trust.md)** — архитектура zero trust с Vault
