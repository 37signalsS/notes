# Руководство по установке Vault

## Определения

**Установка Vault** — процесс развёртывания бинарного файла **HashiCorp Vault**, настройки его как системной службы, инициализации и приведения в рабочее состояние через процедуру распечатывания (unseal) или настройки автоматического распечатывания (auto-unseal).

**Integrated Storage (Raft)** — встроенное хранилище на базе протокола консенсуса Raft, являющееся стандартом для продуктивных сред Vault. Оно исключает внешние зависимости (такие как Consul) и обеспечивает высокую доступность данных.

**Хранилище на базе Raft** — набор узлов, составляющих кластер из нечётного числа участников (3, 5, …), который хранит зашифрованный барьер шифрования вместе с открытыми данными. В любой момент времени работает одна лидер-реплика, остальные — следящие; записи, подтверждённые лидером до ответа, считаются durable-коммитами. Нарушение кворума (потеря более половины узлов) переводит Vault в состояние Sealed даже при активном Auto-unseal.

## Основные концепции

### Подготовка операционной системы

Безопасность Vault начинается с изоляции процесса на уровне ядра и файловой системы.

1.  **Системный пользователь:** Запуск сервиса от имени выделенного пользователя `vault`.
    ```bash
    sudo useradd --system --home /etc/vault.d --shell /bin/false vault
    ```
2.  **Структура директорий:**
    *   `/etc/vault.d` — конфигурационные файлы (права `640`, владелец `vault:vault`).
    *   `/opt/vault/data` — данные Raft (права `700`, владелец `vault:vault`).
    *   `/var/log/vault` — логи аудита.
3.  **Отключение Swap:** Для предотвращения попадания секретов из оперативной памяти на диск необходимо полностью отключить раздел подкачки или использовать `mlock`.
    ```bash
    sudo swapoff -a
    # Удалить упоминания swap из /etc/fstab
    ```

### Безопасная конфигурация (vault.hcl)

Современная установка (на актуальной линейке Vault 2.x, преемника серии 1.x) предполагает использование Raft и TLS для всех коммуникаций. С 2023 года в apt-репозитории HashiCorp действует единый GPG-ключ с отпечатком `798A EC65 4E5C 1542 8C8E 42EE AA16 FCBC A621 E701`.

```hcl
ui = true

listener "tcp" {
  address       = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_cert_file = "/etc/vault.d/tls/vault.crt"
  tls_key_file  = "/etc/vault.d/tls/vault.key"
  
  # Рекомендуется использовать mTLS для максимальной безопасности
  tls_disable   = 0
}

storage "raft" {
  path    = "/opt/vault/data"
  node_id = "vault-node-1"
  
  # Автоматическое присоединение узлов к кластеру
  retry_join {
    leader_api_addr = "https://vault-node-2.example.com:8200"
  }
}

# Настройка Auto-unseal (пример для AWS KMS)
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unseal-key"
}

api_addr     = "https://vault.example.com:8200"
cluster_addr = "https://10.0.0.1:8201"
```

### Харденинг службы Systemd

Файл `/etc/systemd/system/vault.service` должен максимально ограничивать возможности процесса.

```ini
[Unit]
Description="HashiCorp Vault - A tool for managing secrets"
Requires=network-online.target
After=network-online.target
ConditionFileNotEmpty=/etc/vault.d/vault.hcl

[Service]
User=vault
Group=vault
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
SecureBits=keep-caps
AmbientCapabilities=CAP_IPC_LOCK
CapabilityBoundingSet=CAP_IPC_LOCK
NoNewPrivileges=yes
MemoryDenyWriteExecute=yes
LimitMEMLOCK=infinity
LimitCORE=0
ExecStart=/usr/bin/vault server -config=/etc/vault.d/vault.hcl
ExecReload=/bin/kill --signal HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Практические сценарии

### Шаг 1: Установка бинарного файла и прав доступа

```bash
# Установка через пакетный менеджер (рекомендуется)
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install vault

# Настройка CAP_IPC_LOCK (разрешить блокировку памяти)
sudo setcap cap_ipc_lock=+eip /usr/bin/vault
```

### Шаг 2: Запуск службы и проверка статуса

После установки пакет регистрирует сервис `vault`, но не запускает его. Включите автозапуск и запустите службу:

> При ручной (бинарной) установке бинарник кладется в `/usr/local/bin/vault`; тогда в unit-файле задаётся `ExecStart=/usr/local/bin/vault`, а `setcap cap_ipc_lock=+eip` применяется к тому же пути. В примерах этого руководства используется стандартный путь из пакета `/usr/bin/vault`.

```bash
# Перечитать unit-файлы systemd
sudo systemctl daemon-reload

# Включить автозапуск и запустить
sudo systemctl enable --now vault

# Проверить состояние службы
systemctl status vault

# Статус Vault (ожидается Sealed, т.к. инициализация ещё не выполнена)
VAULT_ADDR='https://127.0.0.1:8200' vault status
# → Sealed        true
# → Seal Type     shamir | awskms | ...
# → Initialized   false
```

### Шаг 3: Инициализация с Auto-unseal

При использовании механизма Auto-unseal (KMS/HSM) Vault не генерирует ключи распечатывания, а создает **Recovery Keys** (ключи восстановления).

```bash
export VAULT_ADDR='https://127.0.0.1:8200'

# Инициализация (3 ключа из 5 для восстановления)
vault operator init -recovery-shares=5 -recovery-threshold=3
```

**Важно:** Ключи восстановления необходимы для выполнения критических операций (rekeying, генерация нового root-токена), если механизм Auto-unseal станет недоступен.

### Шаг 4: Инициализация без Auto-unseal (Shamir)

Если внешний KMS/HSM не используется, Vault запускается с конфигурацией, где отсутствует блок `seal`, и применяется классический алгоритм Шамира: **Unseal Keys** делятся по схеме `k-of-n` (по умолчанию 3 из 5).

```bash
export VAULT_ADDR='https://127.0.0.1:8200'

# Инициализация с генерацией 5 Unseal Keys (порог — 3)
vault operator init -key-shares=5 -key-threshold=3
# → Unseal Key 1: <base64_код>
# → Unseal Key 2: <base64_код>
# → ...
# → Initial Root Token: <root_токен>

# Первичное распечатывание — подать ключи по очереди (3 из 5)
vault operator unseal
# → Unseal Progress: 1/3
vault operator unseal
# → Unseal Progress: 2/3
vault operator unseal
# → Sealed         false (Vault распечатан)
# → Unseal Progress    3/3
```

**Важно:** Unseal Keys и Root Token выводятся однократно. Их нужно сразу распределить по разным ответственным лицам (кворум) и хранить в защищённом хранилище. Подробнее — [процесс Seal/Unseal](../concepts.md#процесс-запечатывания-seal-и-распечатывания-unseal).

### Шаг 5: Настройка устройств аудита

После входа в Vault (`vault login`) первым шагом необходимо включить журналирование:

```bash
# Локальный файл аудита
vault audit enable file file_path=/var/log/vault/audit.log

# Отправка в Syslog
vault audit enable syslog
```

### Шаг 6: Проверка кластера (Raft)

Для кластерной конфигурации (несколько узлов с `retry_join`) проверьте формирование кворума и статус реплик:

```bash
# Список участников кластера (лидер и followers)
vault operator raft list-peers
# → Node       Address                        State       Voter
# → vault-node-1  10.0.0.1:8201                 leader      true
# → vault-node-2  10.0.0.2:8201                 follower    true
# → vault-node-3  10.0.0.3:8201                 follower    true

# Текущее состояние Raft (записи, применяемые коммиты)
vault operator raft info
```

## Дополнительная информация

### Решение типовых проблем

| Проблема | Причина и решение |
| :--- | :--- |
| **Error locking memory** | Ошибка `mlock`. Проверьте `CAP_IPC_LOCK` и `LimitMEMLOCK=infinity` в системной службе. |
| **Raft Quorum Lost** | Потеря кворума в кластере. Требуется восстановление из снимка (snapshot) или ручная правка `peers.json`. |
| **TLS Certificate Expired** | Истечение сертификата. Vault не запустится, если `tls_disable=0`. Используйте внутренний [PKI Engine](../concepts.md#движки-секретов-secret-engines) для авто-ротации. |

### Связанные документы

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и ключевые преимущества.
*   **[Основные концепции](../concepts.md)** — детали Seal/Unseal, хранилища и HA.
*   **[Vault с Consul в качестве бэкенда](./vault_with_consul_backend.md)** — альтернативный (Legacy) метод для сложных распределённых топологий.
