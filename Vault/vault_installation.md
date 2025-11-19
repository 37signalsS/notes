# Установка и базовая настройка Vault

Vault — инструмент от HashiCorp для безопасного хранения и доступа к секретам.

## 1. Загрузка и установка

1.  **Скачайте бинарный файл** с [официального сайта](https://developer.hashicorp.com/vault/downloads).
2.  Распакуйте архив и переместите исполняемый файл `vault` в директорию, доступную в `PATH`, например, `/usr/local/bin`.

    ```bash
    unzip vault_*_linux_amd64.zip
    sudo mv vault /usr/local/bin/
    ```
### Примечание: Проблемы с доступом
Если у вас возникают проблемы со скачиванием с официального сайта из-за сетевых ограничений, вы можете скачать архив на локальную машину, а затем скопировать его на целевой сервер с помощью `scp`.

## 2. Подготовка системы

Vault должен запускаться от непривилегированного пользователя.

1.  **Создайте пользователя `vault`**:
    ```bash
    sudo useradd --system --home /etc/vault.d --shell /bin/false vault
    ```

2.  **Создайте директории** для конфигурации и данных:
    ```bash
    sudo mkdir --parents /etc/vault.d /var/lib/vault/data
    ```

3.  **Назначьте права** на директории:
    ```bash
    sudo chown --recursive vault:vault /etc/vault.d /var/lib/vault/
    sudo chmod 750 /var/lib/vault/data
    ```

4.  **Установите capabilities** на бинарный файл. Это необходимо, чтобы Vault мог заблокировать свою память от выгрузки в swap (через системный вызов `mlock()`), не требуя при этом root-прав.
    ```bash
    sudo setcap cap_ipc_lock=+eip /usr/local/bin/vault
    ```

## 3. Базовая конфигурация

Создайте конфигурационный файл `/etc/vault.d/vault.hcl`.

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
// Для production рекомендуется использовать Consul, см. vault_with_consul_backend.md
storage "raft" {
  path    = "/var/lib/vault/data"
  node_id = "vault_node_1"
}

// Адрес для коммуникации между узлами кластера
api_addr = "http://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"
```
*   **Важно:** Установите права на конфигурационный файл: `sudo chown vault:vault /etc/vault.d/vault.hcl` и `sudo chmod 640 /etc/vault.d/vault.hcl`.

## 4. Создание Systemd Unit

Создайте файл `/etc/systemd/system/vault.service` для управления Vault как системной службой.

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

## 5. Запуск и инициализация

1.  **Перезагрузите конфигурацию systemd** и запустите сервис Vault:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start vault
    sudo systemctl enable vault # Для автозапуска при загрузке системы
    ```

2.  **Экспортируйте адрес Vault** в переменную окружения для удобства:
    ```bash
    export VAULT_ADDR='http://127.0.0.1:8200'
    ```

3.  **Инициализируйте Vault**:
    Эта команда создает мастер-ключ, делит его на части (ключи распечатывания) и генерирует корневой токен (root token).
    ```bash
    vault operator init
    ```
    **Обязательно сохраните ключи распечатывания и корневой токен в надежном месте!** Они не могут быть восстановлены.

## 6. Распечатывание (Unseal)

См. подробное описание в документе [Процесс "запечатывания" (Seal) и "распечатывания" (Unseal) в Vault](./vault_seal_unseal_process.md).

1.  **Выполните команду `unseal`** несколько раз (по умолчанию 3 раза) с разными ключами.
    ```bash
    vault operator unseal <unseal_key_1>
    vault operator unseal <unseal_key_2>
    vault operator unseal <unseal_key_3>
    ```
2.  После успешного ввода необходимого количества ключей Vault перейдет в рабочее состояние (`Sealed: false`).

3.  **Войдите в систему** с помощью корневого токена:
    ```bash
    vault login <root_token>
    ```

Теперь Vault готов к работе.

## 7. Поиск и устранение неисправностей

Если сервис Vault не запускается, первым делом проверьте его статус и логи.

1.  **Проверка статуса:**
    Покажет, активен ли сервис и выведет последние строки лога.
    ```bash
    sudo systemctl status vault
    ```

2.  **Просмотр полных логов:**
    Для получения более детальной информации используйте `journalctl`.
    ```bash
    sudo journalctl -u vault -f --no-pager
    ```
    *   `-u vault`: Показать логи только для юнита `vault.service`.
    *   `-f`: Следить за логами в реальном времени.

### Частые ошибки
*   **Опечатки в `vault.hcl`:** Vault чувствителен к синтаксису HCL. Распространенные ошибки — пропущенные кавычки или скобки.
*   **Ошибки в `vault.service`:** Неправильные пути к файлам, ошибки в директивах.
*   **Проблемы с правами:** Убедитесь, что пользователь `vault` имеет права на чтение конфигурации и на чтение/запись в директорию данных.
*   **Конфликт `storage`:** Если вы переключаетесь между разными бэкендами (например, `raft` и `consul`), убедитесь, что активен только один блок `storage`.
