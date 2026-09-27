# Руководство по установке Vault

## Определения

**Установка Vault** — процесс развёртывания бинарного файла **HashiCorp Vault**, настройки его как системной службы, инициализации и приведения в рабочее состояние через процедуру распечатывания (unseal) или настройки автоматического распечатывания (auto-unseal).

**Инициализация Vault** — однократная операция, в рамках которой генерируются криптографические материалы (ключи Шамира или Recovery Keys), создаётся начальный root-токен и инициализируется хранилище. После инициализации Vault переходит в состояние `Sealed` и требует распечатывания перед обслуживанием запросов.

**Auto-unseal** — механизм автоматического распечатывания Vault при старте посредством внешнего доверенного сервиса (KMS, HSM, Transit Engine), исключающий необходимость участия оператора в штатных процедурах перезапуска.

**Seal Migration** — операция перехода с одного механизма seal на другой (например, с Shamir на Auto-unseal или наоборот) без потери данных и изменения корневого токена. Выполняется через `vault operator rekey` и `vault operator seal`/`unseal` с параметром `-migrate`.

**Integrated Storage (Raft)** — встроенное хранилище на базе протокола консенсуса Raft, являющееся стандартом для продуктивных сред Vault. Оно исключает внешние зависимости (такие как Consul) и обеспечивает высокую доступность данных.

**Хранилище на базе Raft** — набор узлов, составляющих кластер из нечётного числа участников (3, 5, …), который хранит зашифрованный барьер шифрования вместе с открытыми данными. В любой момент времени работает одна лидер-реплика, остальные — следящие; записи, подтверждённые лидером до ответа, считаются durable-коммитами. Нарушение кворума (потеря более половины узлов) переводит Vault в состояние Sealed даже при активном Auto-unseal.

## Основные концепции

### Лицензирование и версии

Vault распространяется в двух редакциях:
* **Vault Open Source (OSS)** — бесплатная версия с базовым функционалом (Raft, базовые auth-методы, audit).
* **Vault Enterprise** — коммерческая версия с расширенными возможностями (много DC, Secret Recovery, Namespaces, Performance Replication, Sentinel).

Перед установкой убедитесь, что используемая версия ещё поддерживается HashiCorp (смотрите [Pricing & Support](https://www.hashicorp.com/products/vault/pricing)). Для production рекомендуется использовать последнюю стабильную patch-версию текущей мажорной линейки.

### Минимальные системные требования

Рекомендации приведены для single-node установки. Для HA-кластеров требования масштабируются линейно.

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 2 vCPU | 4+ vCPU (HA-лидер) |
| **RAM** | 4 GB | 8+ GB |
| **Диск** | 10 GB SSD | 50+ GB SSD (Raft + аудит + снапшоты) |
| **Сеть** | 1 Gbps | 10 Gbps (межузловая Raft-коммуникация) |
| **Файловые дескрипторы** | 65536 | 65536+ |
| **vm.max_map_count** | 65536 | 65536+ |

Vault является memory-intensive при операциях с большим количеством секретов (динамические credentials,leases). При использовании `mlock` требуется, чтобы размер заблокированной памяти не ограничивался `ulimit` или политиками SELinux/AppArmor.

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
4.  **Ядерные параметры (sysctl):**
    ```bash
    sudo sysctl -w vm.max_map_count=65536
    echo "vm.max_map_count=65536" | sudo tee -a /etc/sysctl.d/99-vault.conf
    sudo sysctl --system
    ```
5.  **Ограничения файловых дескрипторов (ulimit):**
    ```bash
    # Проверить текущий лимит для vault
    sudo systemctl show vault | grep LimitNOFILE
    # Должен быть >= 65536
    ```

### Проверка целостности бинарного файла

Перед установкой бинарника из Интернета необходимо проверить его подлинность.

```bash
# 1. Скачать бинарник и контрольную сумму
wget https://releases.hashicorp.com/vault/2.0.0/vault_2.0.0_linux_amd64.zip
wget https://releases.hashicorp.com/vault/2.0.0/vault_2.0.0_SHA256SUMS
wget https://releases.hashicorp.com/vault/2.0.0/vault_2.0.0_SHA256SUMS.sig

# 2. Проверить подпись (требуется gnupg)
gpg --verify vault_2.0.0_SHA256SUMS.sig vault_2.0.0_SHA256SUMS
# → Good signature from "HashiCorp Software Packaging <packaging@hashicorp.com>"

# 3. Проверить контрольную сумму
sha256sum -c vault_2.0.0_SHA256SUMS --ignore-missing
# → vault_2.0.0_linux_amd64.zip: OK
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
  max_request_size = 33554432  # 32 MB — защита от переполнения
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

# Performance tuning
default_lease_ttl_seconds = 2764800  # 32 дня
max_lease_ttl_seconds     = 31536000  # 365 дней
```

### Seal Migration (переход между механизмами seal)

Vault поддерживает изменение механизма seal без переинициализации и потери данных. Типичные сценарии:
* **Shamir → Auto-unseal** (переход в production с HSM/KMS).
* **Auto-unseal → Shamir** (деградация при недоступности KMS).
* **Смена KMS-ключа** (ротация ключа в AWS KMS / HSM).

**Общий алгоритм:**
1.  Подготовить новый блок `seal` в конфигурации (новый KMS ключ или HSM).
2.  Выполнить `vault operator rekey` с новыми Recovery Keys (если переходим на Auto-unseal) или сохранить старые Unseal Keys (если переходим на Shamir).
3.  Перезапустить Vault с новой конфигурацией.
4.  Выполнить `vault operator unseal -migrate` (при смене seal-механизма).
5.  Проверить `vault status` (поле `Seal Type`).

```bash
# Пример: переключение с Shamir на Transit Engine (другой кластер Vault)
vault operator rekey -init -key-shares=5 -key-threshold=3
# Подать 3 из 5 старых Unseal Keys
vault operator rekey -key-share=<key1> -key-share=<key2> -key-share=<key3>
# Обновить конфигурацию с новым блоком seal "transit"
sudo systemctl restart vault
vault operator unseal -migrate
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

### Шаг 0: Предварительные требования (sysctl, ulimit, swap)

Перед установкой Vault необходимо подготовить ОС.

```bash
# 1. Отключить swap
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# 2. Настроить sysctl
sudo sysctl -w vm.max_map_count=65536
echo "vm.max_map_count=65536" | sudo tee /etc/sysctl.d/99-vault.conf
sudo sysctl --system

# 3. Проверить лимиты файловых дескрипторов (должно быть >= 65536)
ulimit -n
# Если меньше — добавить в /etc/security/limits.conf:
# vault soft nofile 65536
# vault hard nofile 65536
```

### Шаг 1: Установка бинарного файла и прав доступа

#### Вариант A: APT (Debian/Ubuntu)

```bash
# Установка через пакетный менеджер (рекомендуется)
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install vault

# Настройка CAP_IPC_LOCK (разрешить блокировку памяти)
sudo setcap cap_ipc_lock=+eip /usr/bin/vault
```

#### Вариант B: Бинарная установка (универсальная)

```bash
# Скачать и проверить целостность
VAULT_VERSION="2.0.0"
wget https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_linux_amd64.zip
wget https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_SHA256SUMS
wget https://releases.hashicorp.com/vault/${VAULT_VERSION}/vault_${VAULT_VERSION}_SHA256SUMS.sig
gpg --verify vault_${VAULT_VERSION}_SHA256SUMS.sig vault_${VAULT_VERSION}_SHA256SUMS
sha256sum -c vault_${VAULT_VERSION}_SHA256SUMS --ignore-missing

# Распаковать и установить
unzip vault_${VAULT_VERSION}_linux_amd64.zip
sudo install -m 0755 vault /usr/local/bin/vault
sudo setcap cap_ipc_lock=+eip /usr/local/bin/vault
```

#### Вариант C: RPM (RHEL/CentOS/Alma/Rocky/Fedora)

```bash
# Установка репозитория HashiCorp
sudo rpm --import https://rpm.releases.hashicorp.com/gpg
sudo tee /etc/yum.repos.d/hashicorp.repo <<EOF
[hashicorp]
name=HashiCorp - Linux Packages
baseurl=https://rpm.releases.hashicorp.com/fedora/\\$releasever/\\$basearch
gpgcheck=1
gpgkey=https://rpm.releases.hashicorp.com/gpg
enabled=1
EOF

sudo dnf install -y vault
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

### Шаг 3: Валидация установки

Перед инициализацией убедитесь, что Vault доступен и TLS работает корректно.

```bash
# Health check (не требует аутентификации)
curl -k https://127.0.0.1:8200/v1/sys/health
# → {"initialized":false,"sealed":true,"standby":false,...}

# Проверка Metrics endpoint (опционально, требует включения metrics)
curl -k https://127.0.0.1:8200/v1/sys/metrics
# → {"telemetry": {...}}
```

### Шаг 4: Инициализация с Auto-unseal

При использовании механизма Auto-unseal (KMS/HSM) Vault не генерирует ключи распечатывания, а создает **Recovery Keys** (ключи восстановления).

```bash
export VAULT_ADDR='https://127.0.0.1:8200'

# Инициализация (3 ключа из 5 для восстановления)
vault operator init -recovery-shares=5 -recovery-threshold=3
```

**Важно:** Ключи восстановления необходимы для выполнения критических операций (rekeying, генерация нового root-токена), если механизм Auto-unseal станет недоступен.

### Шаг 5: Инициализация без Auto-unseal (Shamir)

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

### Шаг 6: Создание снапшота и тестирование восстановления

После успешной инициализации создайте первый снапшот Raft-хранилища для отказоустойчивости.

```bash
# Создание снапшота (требует root-токен или sudo capability)
vault operator raft snapshot save /opt/vault/backups/vault-$(date +%Y%m%d).snap

# Проверка целостности снапшота (read-only)
vault operator raft snapshot inspect /opt/vault/backups/vault-$(date +%Y%m%d).snap

# Тестовое восстановление (на отдельном сервере или ВМ)
# 1. Установить Vault
# 2. Остановить службу
sudo systemctl stop vault
# 3. Заменить содержимое /opt/vault/data на содержимое снапшота
# 4. Запустить службу и распечатать
sudo systemctl start vault
vault operator unseal ...
```

### Шаг 7: Настройка устройств аудита

После входа в Vault (`vault login`) первым шагом необходимо включить журналирование:

```bash
# Локальный файл аудита
vault audit enable file file_path=/var/log/vault/audit.log

# Отправка в Syslog
vault audit enable syslog
```

### Шаг 8: Проверка кластера (Raft)

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

### Стратегия резервного копирования и восстановления

Для production сред необходимо настроить регулярное создание снапшотов Raft-хранилища.

```bash
# Создание снапшота (требует root-токен или capability sudo)
vault operator raft snapshot save /opt/vault/backups/vault-$(date +%Y%m%d-%H%M).snap

# Плановая ротация снапшотов (cron)
0 2 * * * vault operator raft snapshot save /opt/vault/backups/vault-$(date +\%Y\%m\%d).snap && find /opt/vault/backups -name "vault-*.snap" -mtime +7 -delete
```

**Восстановление:**
1.  Остановите Vault на целевом сервере.
2.  Замените содержимое `/opt/vault/data` на данные из снапшота.
3.  Запустите Vault и выполните `vault operator unseal` (Shamir) или убедитесь в работоспособности Auto-unseal.
4.  Проверьте статус кластера: `vault operator raft list-peers`.

> В Enterprise-версии доступна функция **Secret Recovery** (начиная с 1.20+), позволяющая восстанавливать отдельные секреты без полного восстановления кластера.

### Мониторинг и health-проверки

Vault предоставляет встроенные endpoints для мониторинга.

```bash
# Health check (доступен без аутентификации)
curl -k https://127.0.0.1:8200/v1/sys/health
# → {"initialized":true,"sealed":false,"standby":false,"performance_standby":false,"replication_performance_mode":"disabled",...}

# Metrics в формате Prometheus (включается в конфигурации)
metrics {
  prometheus_enabled = true
  prometheus_retention_time = "30s"
}
curl -k https://127.0.0.1:8200/v1/sys/metrics
```

**Ключевые метрики для мониторинга:**
* `vault.core.unsealed` — 1 если Vault распечатан, 0 если запечатан.
* `vault.raft.leader` — 1 если узел является лидером, 0 если follower.
* `vault.raft.commitTime` — время коммита записи в Raft (рост указывает на проблемы с сетью/диском).

### Крайние случаи и аварийные сценарии

#### Потеря кворума Raft (Quorum Lost)

При потере более половины узлов кластер переходит в состояние `Sealed`. Восстановление:

```bash
# Вариант 1: восстановление из снапшота (если есть)
vault operator raft snapshot restore /opt/vault/backups/vault-latest.snap

# Вариант 2: ручная правка peers.json (при отсутствии снапшота)
# Остановите Vault, отредактируйте /opt/vault/data/raft/peers.json,
# удалите недоступные узлы, запустите и распечатайте оставшийся узел.
```

#### Недоступность Auto-unseal (KMS/HSM)

При недоступности KMS Vault остаётся в состоянии `Sealed`. Действия:
1.  Восстановите доступ к KMS (проверьте сеть, IAM, сетевые политики).
2.  Если KMS не восстановим — перейдите на Shamir: добавьте в конфигурацию блок `seal "shamir"` (или удалите блок `seal`), перезапустите Vault и выполните `vault operator unseal` с сохранёнными Unseal Keys.

#### Переход на Enterprise или обратно

Лицензия Enterprise не требует переинициализации. Достаточно установить пакет `vault-enterprise` и перезапустить службу. Функции Enterprise активируются при наличии валидного лицензионного файла (`/etc/vault.d/vault.hclic`).

### Решение типовых проблем

| Проблема | Причина и решение |
| :--- | :--- |
| **Error locking memory** | Ошибка `mlock`. Проверьте `CAP_IPC_LOCK` и `LimitMEMLOCK=infinity` в системной службе. |
| **Raft Quorum Lost** | Потеря кворума в кластере. Требуется восстановление из снимка (snapshot) или ручная правка `peers.json`. |
| **TLS Certificate Expired** | Истечение сертификата. Vault не запустится, если `tls_disable=0`. Используйте внутренний [PKI Engine](../concepts.md#движки-секретов-secret-engines) для авто-ротации. |
| **Sealed despite Auto-unseal** | KMS/HSM недоступен или изменён ключ. Проверьте `vault status` (поле `Seal Type`) и логи KMS. |
| **Cannot unseal with -migrate** | `-migrate` работает только при совпадении порога key-shares/recovery-threshold. Убедитесь, что подаётся правильное количество ключей. |
| **High commit latency** | Рост `vault.raft.commitTime`. Проверьте диск (IOPS), сеть между узлами и размер Raft-лога. |
| **Root token revoked** | root-токен одноразовый для входа. Генерируйте новый через `vault operator generate-root` с использованием Recovery/Unseal Keys. |

### Связанные документы

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и ключевые преимущества.
*   **[Основные концепции](../concepts.md)** — детали Seal/Unseal, хранилища и HA.
*   **[Vault с Consul в качестве бэкенда](./vault_with_consul_backend.md)** — альтернативный (Legacy) метод для сложных распределённых топологий.
