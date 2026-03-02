# Установка и базовая настройка Vault

## Определения

* **Установка Vault**: Процесс развертывания бинарного файла Vault, его настройка как системной службы и первоначальная инициализация для подготовки к работе.

## Основные концепции

### 1. Подготовка системы

1. **Непривилегированный пользователь:** Запуск от выделенного пользователя `vault` изолирует сервис от других процессов.

    ```bash
    sudo useradd --system --home /etc/vault.d --shell /bin/false vault
    ```

2. **Выделенные директории:** Создание отдельных каталогов для конфигурации (`/etc/vault.d`) и данных (`/var/lib/vault/data`) позволяет гранулярно управлять правами доступа.

    ```bash
    sudo mkdir --parents /etc/vault.d /var/lib/vault/data
    sudo chown --recursive vault:vault /etc/vault.d /var/lib/vault/
    sudo chmod 750 /var/lib/vault/data
    ```

### 2. Базовая конфигурация (`vault.hcl`)

Основной файл, определяющий поведение Vault.

```hcl
// /etc/vault.d/vault.hcl

ui = true // Включить веб-интерфейс

// Настройки слушателя для API
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1 // Отключить TLS для первоначальной настройки
}

// Конфигурация хранилища (storage).
// В данном примере используется файловое хранилище Raft.
// Для production с внешним бэкендом см. [vault_with_consul_backend.md](./vault_with_consul_backend.md).
storage "raft" {
  path    = "/var/lib/vault/data"
  node_id = "vault_node_1"
}

// Адрес для коммуникации между узлами кластера
api_addr = "http://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"
```

* **Важно:** Установите права на конфигурационный файл: `sudo chown vault:vault /etc/vault.d/vault.hcl` и `sudo chmod 640 /etc/vault.d/vault.hcl`.

### 3. Systemd Unit

Создание файла `/etc/systemd/system/vault.service` для управления Vault как системной службой.

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
ProtectHome=read-only
PrivateTmp=yes
PrivateDevices=yes
SecureBits=keep-caps
AmbientCapabilities=CAP_IPC_LOCK
CapabilityBoundingSet=CAP_SYSLOG CAP_IPC_LOCK
NoNewPrivileges=yes
ExecStart=/usr/local/bin/vault server -config=/etc/vault.d/vault.hcl
ExecReload=/bin/kill --signal HUP $MAINPID
KillMode=process
KillSignal=SIGINT
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

## Практические сценарии

### Шаг 1: Загрузка и размещение бинарного файла

1. **Скачайте бинарный файл** с [официального сайта](https://developer.hashicorp.com/vault/downloads).
2. Распакуйте архив и переместите исполняемый файл `vault` в директорию, доступную в `PATH`, например, `/usr/local/bin`.

    ```bash
    unzip vault_*_linux_amd64.zip
    sudo mv vault /usr/local/bin/
    ```

### Шаг 2: Запуск и инициализация

1. **Перезагрузите конфигурацию systemd** и запустите сервис Vault:

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start vault
    sudo systemctl enable vault # Для автозапуска при загрузке системы
    ```

2. **Экспортируйте адрес Vault** в переменную окружения для удобства:

    ```bash
    export VAULT_ADDR='http://127.0.0.1:8200'
    ```

3. **Инициализируйте Vault**:
    Эта команда создает мастер-ключ, делит его на части (ключи распечатывания) и генерирует корневой токен (root token).

    ```bash
    vault operator init
    ```

    **Обязательно сохраните ключи распечатывания и корневой токен в надежном месте!** Они не могут быть восстановлены.

### Шаг 3: Распечатывание (Unseal) и вход

Процесс "распечатывания" подробно описан в документе [основных концепций Vault](../concepts.md#процесс-запечатывания-seal-и-распечатывания-unseal).

1. **Выполните команду `unseal`** несколько раз (по умолчанию 3 раза) с разными ключами.

    ```bash
    vault operator unseal <unseal_key_1>
    vault operator unseal <unseal_key_2>
    vault operator unseal <unseal_key_3>
    ```

2. После успешного ввода необходимого количества ключей Vault перейдет в рабочее состояние (`Sealed: false`).

3. **Войдите в систему** с помощью корневого токена:

    ```bash
    vault login <root_token>
    ```

## Дополнительная информация

### Capabilities для блокировки памяти

**Установите capabilities** на бинарный файл. Это необходимо, чтобы Vault мог заблокировать свою память от выгрузки в swap (через системный вызов `mlock()`), не требуя при этом root-прав. Этот шаг критичен для безопасности, так как предотвращает попадание чувствительных данных на диск.

```bash
sudo setcap cap_ipc_lock=+eip /usr/local/bin/vault
```

### Частые ошибки

* **Проблемы с правами:** Убедитесь, что пользователь `vault` имеет права на чтение конфигурации и на чтение/запись в директорию данных.
* **Конфликт `storage`:** Если вы переключаетесь между разными бэкендами (например, `raft` и `consul`), убедитесь, что активен только один блок `storage`.

### Связанные документы

* **[HashiCorp Vault Overview](../overview.md):** Общее описание технологии, ее назначения и ключевых компонентов.
* **[Основные концепции Vault](../concepts.md):** Подробное описание архитектуры, Seal/Unseal, бэкендов.
* **[Использование Consul в качестве бэкенда](./vault_with_consul_backend.md):** Настройка HA-кластера с внешним хранилищем.
* **[Официальная документация по установке](https://developer.hashicorp.com/vault/tutorials/getting-started/getting-started-install):** Руководство от HashiCorp.
