# Руководство по установке Vault

## Определения

**Установка Vault** — процесс развёртывания бинарного файла **HashiCorp Vault**, настройки его как системной службы, инициализации и приведения в рабочее состояние через процедуру распечатывания (unseal).

## Основные концепции

### Подготовка системы

1. **Непривилегированный пользователь:** Запуск сервиса от имени выделенного системного пользователя `vault` обеспечивает изоляцию процесса от остальной системы.

    ```bash
    sudo useradd --system --home /etc/vault.d --shell /bin/false vault
    ```

2. **Выделенные директории:** Создание отдельных каталогов для конфигурации (`/etc/vault.d`) и данных (`/var/lib/vault/data`) позволяет гранулярно управлять правами доступа.

    ```bash
    sudo mkdir --parents /etc/vault.d /var/lib/vault/data
    sudo chown --recursive vault:vault /etc/vault.d /var/lib/vault/
    sudo chmod 750 /var/lib/vault/data
    ```

### Базовая конфигурация (vault.hcl)

Файл конфигурации `/etc/vault.d/vault.hcl` описывается на языке **HCL (HashiCorp Configuration Language)** и определяет параметры работы сервера:

```hcl
ui = true

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1  // Отключить TLS только для первоначальной настройки
}

storage "raft" {
  path    = "/var/lib/vault/data"
  node_id = "vault_node_1"
}

api_addr     = "http://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"
```

* **TLS (Transport Layer Security):** Протокол защиты передачи данных. В промышленной среде использование TLS обязательно.
* **Права доступа:** `sudo chown vault:vault /etc/vault.d/vault.hcl && sudo chmod 640 /etc/vault.d/vault.hcl`

Для высокодоступных (HA — High Availability) инсталляций с внешним бэкендом см. **[Vault с Consul в качестве бэкенда](./vault_with_consul_backend.md)**.

### Настройка Systemd

Файл `/etc/systemd/system/vault.service` управляет Vault как системной службой Linux:

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

### Механизм CAP_IPC_LOCK

Специальная возможность ядра Linux `cap_ipc_lock` позволяет Vault блокировать оперативную память от выгрузки в раздел подкачки (swap) через системный вызов `mlock()`. Это предотвращает попадание чувствительных данных в открытом виде на диск.

```bash
sudo setcap cap_ipc_lock=+eip /usr/local/bin/vault
```

### Процесс распечатывания (Unseal)

Подробное описание архитектуры процесса приведено в разделе **[Процесс запечатывания и распечатывания](../concepts.md#процесс-запечатывания-seal-и-распечатывания-unseal)**. В основе лежит алгоритм разделения секрета Шамира: для работы сервера требуется ввод порогового значения ключей (обычно 3 из 5).

## Практические сценарии

### Шаг 1: Загрузка и установка бинарного файла

1. Загрузите актуальную версию с официального сайта HashiCorp.
2. Распакуйте архив и переместите файл в директорию, входящую в `PATH`:

    ```bash
    unzip vault_*_linux_amd64.zip
    sudo mv vault /usr/local/bin/
    ```

3. Настройте разрешения ядра (см. раздел **[Механизм CAP_IPC_LOCK](#механизм-cap_ipc_lock)**).

### Шаг 2: Запуск и инициализация

1. Перечитайте конфигурацию системных служб и активируйте Vault:

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable --now vault
    ```

2. Укажите адрес сервера для **CLI (Command Line Interface)**:

    ```bash
    export VAULT_ADDR='http://127.0.0.1:8200'
    ```

3. Выполните инициализацию (будут сгенерированы ключи распечатывания и корневой токен):

    ```bash
    vault operator init
    ```

    **Важно:** Сохраните полученные ключи и токен в безопасном месте. Их утрата ведет к невозможности восстановления доступа к данным.

### Шаг 3: Распечатывание и вход

1. Введите ключи распечатывания (по умолчанию требуется 3 ввода):

    ```bash
    vault operator unseal <unseal_key_1>
    vault operator unseal <unseal_key_2>
    vault operator unseal <unseal_key_3>
    ```

2. Проверьте состояние сервера: `vault status`. Поле `Sealed` должно иметь значение `false`.
3. Выполните вход, используя корневой токен (Root Token):

    ```bash
    vault login <root_token>
    ```

## Дополнительная информация

### Решение типовых проблем

| Проблема | Причина и решение |
| :--- | :--- |
| Ошибка прав доступа (Permission denied) | Проверьте владельца и права на `/etc/vault.d/` и `/var/lib/vault/data` (`chown vault:vault`) |
| Ошибка конфигурации хранилища | Убедитесь, что в `vault.hcl` определен только один блок `storage` |
| Сервис не запускается | Изучите логи: `journalctl -u vault -e`. Проверьте синтаксис HCL |

### Связанные документы

* **[Обзор HashiCorp Vault](../overview.md)** — общие сведения о системе.
* **[Основные концепции Vault](../concepts.md)** — архитектура, методы аутентификации, жизненный цикл секретов.
* **[Vault с Consul в качестве бэкенда](./vault_with_consul_backend.md)** — настройка отказоустойчивого кластера.
* **[Интеграция Vault с Docker](./vault_docker_integration.md)** — запуск сервера в контейнеризованном окружении.
