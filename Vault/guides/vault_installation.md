# Vault Installation Guide

## Definitions

* **Vault Installation** — процесс развёртывания бинарного файла Vault, настройки его как системной службы, инициализации и приведения в рабочее состояние (unseal).

## Basic Concepts

### System Preparation

1. **Непривилегированный пользователь:** запуск от выделенного пользователя `vault` изолирует сервис от других процессов.

    ```bash
    sudo useradd --system --home /etc/vault.d --shell /bin/false vault
    ```

2. **Выделенные директории:** отдельные каталоги для конфигурации (`/etc/vault.d`) и данных (`/var/lib/vault/data`) позволяют гранулярно управлять правами.

    ```bash
    sudo mkdir --parents /etc/vault.d /var/lib/vault/data
    sudo chown --recursive vault:vault /etc/vault.d /var/lib/vault/
    sudo chmod 750 /var/lib/vault/data
    ```

### Base Configuration (`vault.hcl`)

Файл `/etc/vault.d/vault.hcl` определяет поведение Vault:

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

* Права: `sudo chown vault:vault /etc/vault.d/vault.hcl && sudo chmod 640 /etc/vault.d/vault.hcl`
* Для production с внешним бэкендом: [vault_with_consul_backend.md](./vault_with_consul_backend.md)

### Systemd Unit

Файл `/etc/systemd/system/vault.service` управляет Vault как системной службой:

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

### CAP_IPC_LOCK Capability

Capability `cap_ipc_lock` позволяет Vault блокировать память от выгрузки в swap через `mlock()`, предотвращая попадание чувствительных данных на диск:

```bash
sudo setcap cap_ipc_lock=+eip /usr/local/bin/vault
```

### Seal/Unseal Process

Процесс запечатывания/распечатывания описан в [concepts.md#процесс-запечатывания-seal-и-распечатывания-unseal](../concepts.md#процесс-запечатывания-seal-и-распечатывания-unseal). Кратко:

* При инициализации генерируются unseal keys и root token
* Для перевода в рабочее состояние требуется ввести минимум `K` из `N` ключей (по умолчанию 3 из 5)

## Practical Scenarios

### Step 1: Download and Install Binary

1. Скачать бинарный файл с [официального сайта](https://developer.hashicorp.com/vault/downloads).
2. Распаковать и переместить в `PATH`:

    ```bash
    unzip vault_*_linux_amd64.zip
    sudo mv vault /usr/local/bin/
    ```

3. Установить capability (см. [Basic Concepts → CAP_IPC_LOCK](#cap_ipc_lock-capability)).

### Step 2: Start and Initialize Vault

1. Перезагрузить конфигурацию systemd и запустить сервис:

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start vault
    sudo systemctl enable vault
    ```

2. Экспортировать адрес Vault:

    ```bash
    export VAULT_ADDR='http://127.0.0.1:8200'
    ```

3. Инициализировать Vault (генерирует unseal keys + root token):

    ```bash
    vault operator init
    ```

    > **Критично:** сохранить unseal keys и root token в надёжном месте. Восстановление невозможно.

### Step 3: Unseal and Login

1. Ввести unseal keys (минимум 3):

    ```bash
    vault operator unseal <unseal_key_1>
    vault operator unseal <unseal_key_2>
    vault operator unseal <unseal_key_3>
    ```

2. Проверить статус: `vault status` → `Sealed: false`.
3. Войти с root token:

    ```bash
    vault login <root_token>
    ```

## Additional Information

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| Нет прав на конфигурацию/данные | Проверить `chown vault:vault` на `/etc/vault.d/` и `/var/lib/vault/data` |
| Конфликт storage backend | Активен только один блок `storage` в `vault.hcl` |
| Vault не стартует | Проверить `journalctl -u vault -e`, валидность HCL-синтаксиса |

### Related Documents

* [Vault Overview](../overview.md) — общее описание технологии
* [Vault Concepts](../concepts.md) — архитектура, Seal/Unseal, бэкенды, аутентификация
* [Consul Backend for Vault](./vault_with_consul_backend.md) — HA-кластер с внешним хранилищем
* [Vault Docker Integration](./vault_docker_integration.md) — запуск в контейнерах
* [Official Installation Guide](https://developer.hashicorp.com/vault/tutorials/getting-started/getting-started-install)
