# Key Escrow — политика хранения копий ключей

## Определения

**Key Escrow** — механизм доверенного хранения копий криптографических ключей третьей стороной (escrow-агентом). Позволяет восстановить доступ к зашифрованным данным при потере ключа, увольнении сотрудника или по требованию компетентных органов.

**Escrow Agent** — юридическое или техническое лицо, хранящее копии ключей и предоставляющее их в соответствии с политикой (например, при судебном запросе или утере оригинала).

**Key Recovery** — процесс восстановления ключа из escrow-хранилища. Требует выполнения условий политики (многофакторное одобрение, юридический запрос).

**Shamir's Secret Sharing (SSS)** — криптографический алгоритм разделения секрета на N частей, где для восстановления достаточно K частей (threshold). Используется для безопасного хранения passphrase ключей CA.

**Secret Splitting** — разделение ключа/пароля на несколько частей, каждая из которых хранится у разных лиц. Типичная схема: 3 из 5, 2 из 3.

---

## Теоретический блок

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

---

## Практический блок

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

#### Автоматизированный workflow для Root CA

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

### Политика доступа к ключам

```markdown
## Политика доступа к криптографическим ключам

### Условия предоставления ключа из Escrow

1. **Потеря ключа:** Запрос от владельца + одобрение 2 из 3 escrow-агентов
2. **Увольнение:** Обязательный возврат ключа; при невозможности — немедленный отзыв сертификата
3. **Юридический запрос:** Только по судебному ордеру, одобрение юридического отдела + CEO
4. **Инцидент:** По запросу CISO + одобрение incident response team

### Процедура восстановления

1. Запрос в письменной форме (или зашифрованный email)
2. Проверка личности запросившего
3. Проверка полномочий (RBAC)
4. Сбор.threshold-частей от escrow-агентов
5. Восстановление ключа на изолированном узле
6. Проверка целостности (SHA-512)
7. Использование для целевого назначения
8. Немедленное уничтожение восстановленной копии
9. Логирование инцидента

### Ротация ключей

- Root CA: каждые 10–15 лет (сSSIP-ротацией)
- Intermediate CA: каждые 3–5 лет
- Сервисные ключи: каждые 90–180 дней
- При ротации: немедленное обновление escrow-хранилища
```

### Шифрование backup-носителей

```bash
# Шифрование USB перед записью ключей
# На macOS
diskutil eraseVolume JHFS+ "EscrowUSB" /dev/disk2
hdiutil create -volname "Escrow" -size 1g -fs JHFS+ -encryption AES-256 -spawn -- /Volumes/Escrow

# На Linux (LUKS)
sudo cryptsetup luksFormat /dev/sdb1
sudo cryptsetup luksOpen /dev/sdb1 escrow_usb
sudo mkfs.ext4 /dev/mapper/escrow_usb
sudo mount /dev/mapper/escrow_usb /mnt/escrow
```

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Все escrow-агенты недоступны | Все хранители ключей уволились/потеряны | Регулярно проводите drill по восстановлению; ротация escrow-агентов |
| Escrow-носитель повреждён | Физическое повреждение USB/диска | Используйте ≥3 носителя в разных локациях; регулярная проверка целостности |
| Ключ восстановлен, но сертификат уже отозван | Медленная реакция на потерю | Восстановленный ключ бесполезен; перевыпускайте сертификат |
| Escrow-агент скомпрометирован | Утечка одной части ключа | Используйте threshold ≥2; регулярная ротация |

---

## Лучшие практики

1. **Threshold 2-of-3** — рекомендуемая схема для Root CA (баланс безопасности и доступности)
2. **Географическое разделение** — храните escrow-носители в разных зданиях/городах
3. **Регулярные drill** — минимум раз в квартал проверяйте процедуру восстановления
4. **Шифрование носителей** — все USB/диски с ключами должны быть зашифрованы (AES-256, LUKS, FileVault)
5. **Ротация escrow-агентов** — при увольнении/смене роли немедленно передавайте share новому агенту
6. **Логирование** — записывайте все обращения к escrow-хранилищу
7. **Не храните** passphrase рядом с зашифрованным ключом
8. **Для HSM** — escrow-ключей HSM через manufacturer key ceremony; backup key card в банк

---

## Дополнительная информация

- **NIST SP 800-57** — [Key Management Recommendation](https://csrc.nist.gov/publications/detail/sp/800-57-part-1/rev-5/final)
- **RFC 3986** — [Shamir's Secret Sharing](https://datatracker.ietf.org/doc/html/rfc3986)
- **[Shamir's Secret Sharing в Root CA](../Tools/openssl_ca/two_tier/root_ca_setup.md#shamirs-secret-sharing-ssss)** — практическое применение в PKI
- **[Обзор PKI](./pki_overview.md)** — управление ключами в PKI
- **[Secrets Management](./secrets_management_overview.md)** — общие практики управления секретами
- **[Zero Trust](../../Vault/zero_trust.md)** — архитектура zero trust с Vault
