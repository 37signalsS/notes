# REST API Proxmox VE

## Определения

**Proxmox REST API** -- HTTP-based API для управления Proxmox VE, доступный по адресу `https://<host>:8006/api2/json`. Поддерживает аутентификацию через токены, пароли и OpenID Connect. Все операции веб-интерфейса доступны через API.

**pvesh (Proxmox VE Shell)** -- CLI-утилита для прямого вызова Proxmox API из командной строки. Автоматически формирует HTTP-запросы, обрабатывает аутентификацию и форматирует вывод.

**API Token** -- механизм аутентификации, позволяющий автоматизированным скриптам и инструментам (Ansible, Terraform) обращаться к API без передачи пароля. Токен привязан к пользователю и имеет ограниченные права.

**proxmoxer** -- Python-библиотека, предоставляющая REST API обертку для Proxmox VE. Используется как бэкенд для Ansible-модулей `community.proxmox`.

**corosync** -- не имеет отношения к API, но API используется для управления кластером, который работает на corosync.

## Теоретический блок

### Архитектура API

```
┌─────────────────────────────────────────────┐
│  Клиент (curl, pvesh, Ansible, Terraform)   │
├─────────────────────────────────────────────┤
│  HTTPS (TLS 1.2/1.3)                        │
│  Порт: 8006                                 │
├─────────────────────────────────────────────┤
│  Proxmox API Server (pveproxy)              │
│  ├── Аутентификация (PAM, LDAP, OIDC, Token)│
│  ├── Авторизация (RBAC: /access, /nodes...) │
│  └── Логирование (audit.log)                │
├─────────────────────────────────────────────┤
│  Хранилище конфигураций (pmxcfs)            │
│  /etc/pve/ (configfs-backed)                │
└─────────────────────────────────────────────┘
```

### Доступные API endpoints

| Префикс | Назначение | Примеры |
| :--- | :--- | :--- |
| `/access/` | Управление пользователями, группами, ролями | `/access/users`, `/access/groups` |
| `/nodes/<node>/` | Управление узлом | `/nodes/node1/status`, `/nodes/node1/storage` |
| `/nodes/<node>/qemu/` | Управление VM | `/nodes/node1/qemu/100/status/start` |
| `/nodes/<node>/lxc/` | Управление LXC контейнерами | `/nodes/node1/lxc/200/status/start` |
| `/cluster/` | Управление кластером | `/cluster/status`, `/cluster/ha` |
| `/storage/` | Управление хранилищами | `/storage/local/content` |
| `/pools/` | Управление пулами ресурсов | `/pools/` |
| `/version` | Версия Proxmox | `/version` |

### Методы HTTP

| Метод | Назначение | Пример |
| :--- | :--- | :--- |
| `GET` | Чтение данных | `GET /nodes/node1/qemu` -- список VM |
| `POST` | Создание/запуск | `POST /nodes/node1/qemu/100/status/start` |
| `PUT` | Обновление конфигурации | `PUT /nodes/node1/qemu/100/config` |
| `DELETE` | Удаление | `DELETE /nodes/node1/qemu/100` |

### Формат данных

**Запросы:** JSON (`Content-Type: application/json`) или form-urlencoded.

**Ответы:** JSON:
```json
{
  "data": {
    "status": "running",
    "vmid": 100,
    "name": "web-server"
  }
}
```

**Ошибки:**
```json
{
  "errors": {
    "vmid": "property is missing"
  },
  "data": null
}
```

## Практические сценарии

### 1. Аутентификация

#### Токены (рекомендуется для автоматизации)

```bash
# Создание пользователя для API
pveum user add monitoring@pam --comment "API monitoring"

# Создание токена
pveum user token add monitoring@pam prometheus --privsep 0
# → Вывод: token secret: <UUID>
# → Сохраните token_id и secret

# Использование токена в curl
TOKEN="monitoring@pam!prometheus=<UUID>"
curl -k -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve1.example.com:8006/api2/json/nodes/node1/status"
```

#### Пароль (для ручных запросов)

```bash
# Получение тикета
curl -k -X POST "https://pve1.example.com:8006/api2/json/access/ticket" \
  -d 'username=admin@pam&password=secret'
# → {"data":{"ticket":"PVE:...","CSRFPreventionToken":"..."}}

# Использование тикета
TICKET="PVE:..."
CSRF="..."
curl -k -H "Cookie: PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  "https://pve1.example.com:8006/api2/json/nodes/node1/status"
```

### 2. Управление VM через curl

```bash
# Список всех VM на узле
curl -k -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve1.example.com:8006/api2/json/nodes/node1/qemu"

# Создание VM
curl -k -X POST "https://pve1.example.com:8006/api2/json/nodes/node1/qemu" \
  -H "Authorization: PVEAPIToken=$TOKEN" \
  -d '{
    "vmid": 150,
    "name": "new-server",
    "memory": 4096,
    "cores": 2,
    "scsihw": "virtio-scsi-pci",
    "scsi0": "local-lvm:32,discard=on",
    "net0": "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"
  }'

# Запуск VM
curl -k -X POST "https://pve1.example.com:8006/api2/json/nodes/node1/qemu/150/status/start" \
  -H "Authorization: PVEAPIToken=$TOKEN"

# Остановка VM
curl -k -X POST "https://pve1.example.com:8006/api2/json/nodes/node1/qemu/150/status/stop" \
  -H "Authorization: PVEAPIToken=$TOKEN"

# Получение конфигурации VM
curl -k -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve1.example.com:8006/api2/json/nodes/node1/qemu/150/config"

# Удаление VM
curl -k -X DELETE "https://pve1.example.com:8006/api2/json/nodes/node1/qemu/150" \
  -H "Authorization: PVEAPIToken=$TOKEN"
```

### 3. pvesh -- CLI для API

```bash
# Список команд
pvesh help

# Список VM
pvesh get /nodes/node1/qemu --output-format json

# Создание VM
pvesh create /nodes/node1/qemu \
  --vmid 150 \
  --name new-server \
  --memory 4096 \
  --cores 2 \
  --scsi0 "local-lvm:32,discard=on" \
  --net0 "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0"

# Запуск VM
pvesh create /nodes/node1/qemu/150/status/start

# Остановка VM
pvesh create /nodes/node1/qemu/150/status/stop

# Просмотр конфигурации
pvesh get /nodes/node1/qemu/150/config

# Изменение конфигурации
pvesh set /nodes/node1/qemu/150/config \
  --memory 8192 \
  --cores 4

# Удаление VM
pvesh delete /nodes/node1/qemu/150
```

### 4. Python (proxmoxer)

```python
from proxmoxer import ProxmoxAPI

# Подключение
proxmox = ProxmoxAPI(
    host='pve1.example.com',
    user='monitoring@pam',
    token_name='prometheus',
    token_secret='<UUID>',
    verify_ssl=False
)

# Список узлов
nodes = proxmox.nodes.get()
print(nodes)

# Список VM
vms = proxmox.nodes('node1').qemu.get()
for vm in vms:
    print(f"VM {vm['vmid']}: {vm['name']} - {vm['status']}")

# Создание VM
proxmox.nodes('node1').qemu.post(
    vmid=150,
    name='new-server',
    memory=4096,
    cores=2,
    scsi0='local-lvm:32,discard=on',
    net0='virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0'
)

# Запуск VM
proxmox.nodes('node1').qemu(150).status.start.post()

# Получение статуса
status = proxmox.nodes('node1').qemu(150).status.get()
print(status)
```

### 5. Интеграция с Ansible

```yaml
# Пример использованияcommunity.proxmox
- name: Deploy VM
  community.proxmox.proxmox_vm:
    api_host: pve1.example.com
    api_user: automation@pam
    api_token_id: ansible
    api_token_secret: "{{ vault_proxmox_token }}"
    node: node1
    vmid: 150
    name: web-server
    memory: 4096
    cores: 2
    scsihw: virtio-scsi-pci
    scsi:
      - "local-lvm:32,discard=on"
    net:
      - virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0
    state: present
```

### 6. Массовые операции

```bash
# Скрипт для создания нескольких VM
#!/bin/bash
API="https://pve1.example.com:8006/api2/json"
TOKEN="monitoring@pam!prometheus=<UUID>"

for i in {1..5}; do
  curl -k -X POST "$API/nodes/node1/qemu" \
    -H "Authorization: PVEAPIToken=$TOKEN" \
    -d "vmid=$((150+i))&name=web-0${i}&memory=4096&cores=2&scsi0=local-lvm:32&net0=virtio,bridge=vmbr0"
done

# Получение списка всех работающих VM
curl -k -H "Authorization: PVEAPIToken=$TOKEN" \
  "$API/nodes/node1/qemu?filter=running"
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` | Неверный токен/пароль | Проверьте права токена: `pveum user token info monitoring@pam prometheus` |
| `403 Forbidden` | Недостаточно прав | Проверьте роль: `pveum user list` |
| `500 Internal Server Error` | Некорректные параметры | Проверьте логи: `journalctl -u pveproxy` |
| Connection refused | Сервис не запущен | `systemctl status pveproxy` |
| SSL certificate error | Самоподписанный сертификат | Используйте `-k` (curl) или `verify_ssl=False` |
| Timeout | Сеть/нагрузка | Проверьте сеть: `ping pve1.example.com` |

## Лучшие практики

1. **Используйте API Tokens** вместо паролей для автоматизации. Токены можно отозвать без смены пароля.
2. **Минимальные права**: Для мониторинга -- `PVEAuditor`, для автоматизации -- кастомная роль с необходимыми permissions.
3. **HTTPS обязателен**: API доступен только по HTTPS (порт 8006). Не используйте HTTP.
4. **Rate limiting**: При массовых операциях добавляйте задержки между запросами.
5. **Версионность**: API поддерживает версии через заголовок `Accept: application/json;version=X.Y`.
6. **Логирование**: Все запросы логируются в `/var/log/pve/pveproxy/access.log`.
7. **Таймауты**: Устанавливайте разумные таймауты для операций (especially live migration, backup).

## Граничные случаи

- **API Rate Limiting**: Proxmox не имеет встроенного rate limiting, но чрезмерные запросы могут перегрузить pveproxy.
- **Конфликт токенов**: Один пользователь может иметь несколько токенов с разными правами. Проверяйте права каждого токена отдельно.
- **pmxcfs**: Все конфигурации хранятся вpmxcfs (configfs-backed). При перегрузке этого сервиса API перестает отвечать.
- **Кластерные операции**: Некоторые операции (создание кластера) требуют SSH-доступа между узлами, а не только API.

## Дополнительная информация

### Связанные темы

- [Автоматизация Proxmox через Ansible](./proxmox_ansible.md)
- [Proxmox Service Discovery](./proxmox_service_discovery.md)
- [Обзор Proxmox VE](./proxmox_overview.md)
