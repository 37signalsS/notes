# REST API Proxmox VE

**Актуально для:** Proxmox VE 9.x (HTTP API v1, base path `/api2/json`; PVE 8.x — EOL 31.08.2026)

## Определения

**Proxmox VE REST API** — HTTP-like API (ROA) для управления PVE, слушает только HTTPS на порту `8006`. Базовый URL: `https://<host>:8006/api2/json/`. Параметры передаются в URL (GET) или как `x-www-form-urlencoded` (PUT/POST). Формат ответа выбирается в URL: `json` (по умолчанию), `extjs`, `html`, `text`. Все операции GUI имеют эквивалент в API; CLI-утилиты (`qm`, `pct`, `pveum`, …) — обёртки над тем же API.

**pvesh** — CLI для прямого вызова API **только от root на узле PVE**; автоматически проксирует вызовы на другие узлы кластера по SSH. Замена HTTPS-клиента на хосте PVE.

**API Token** — stateless-креденшел вида `PVEAPIToken=USER@REALM!TOKENID=UUID`. Не требует CSRF для записывающих операций; можно отозвать без смены пароля пользователя. Секрет (UUID) показывается **один раз** при создании и больше не выдаётся.

**Ticket (PVEAuthCookie)** — подписанный cookie, выпускается через `POST /access/ticket`; срок жизни — **2 часа**, можно продлить старым ticket-ом как password-ом. Для POST/PUT/DELETE дополнительно обязателен заголовок `CSRFPreventionToken`.

**proxmoxer** — Python-бэкенд REST-обёртки; используется модулями коллекции `community.proxmox` (Ansible), некоторыми экспортерами и скриптами.

**UPID** — идентификатор фоновой задачи PVE (`UPID:<node>:...`), возвращается большинством write-операций API; полное описание — [Логирование](./proxmox_logging.md#система-задач-pve-task-log-и-upid).

## Теоретический блок

### Архитектура и поток запроса

```text
Клиент (curl, pvesh, proxmoxer, Ansible)
        │ HTTPS :8006
        ▼
   pveproxy  ── аутентификация (PAM / PVE / LDAP / AD / OIDC / Token)
             ── авторизация (RBAC: path + role)
             ── access.log (/var/log/pve/pveproxy/)
        │
        ▼
   pvedaemon ── исполнение операции; write-задачи → UPID
        │
        ▼
   pmxcfs (/etc/pve) ── конфигурация кластера
```

Все вызовы CLI `qm`/`pct`/`pveum`/`pvesm`/`pvecm` идут через тот же API-код (API и CLI используют одни и те же схемы JSON Schema). Полную интерактивную схему endpoint-ов — [API Viewer](https://pve.proxmox.com/pve-docs/api-viewer/); `pvesh usage <path>` печатает схему конкретного пути.

### Корневые поддеревья API

| Префикс | Назначение | Примеры |
| --- | --- | --- |
| `/access/` | Пользователи, группы, роли, ACL, API-токены, ticket | `/access/users`, `/access/acl`, `/access/ticket` |
| `/cluster/` | Кластер, кворум, HA, репликация, задачи, ресурсы | `/cluster/status`, `/cluster/resources`, `/cluster/ha`, `/cluster/tasks`, `/cluster/backup` |
| `/nodes/<node>/` | Узел: статус, qemu, lxc, storage, network, tasks, hardware, report, disks | `/nodes/node1/status`, `/nodes/node1/qemu`, `/nodes/node1/tasks` |
| `/storage/` | Хранилища и содержимое | `/storage`, `/storage/<store>/content` |
| `/pools/` | Resource pools | `/pools` |
| `/version` | Версия API/продукта (release, version, repoid) | `/version` |
| `/sdn/` | SDN-зоны, VNet, контроллеры | `/sdn/zones`, `/sdn/vnets` |

`/cluster/resources` — сводный инвентарь кластера (узлы, VM, LXC, хранилища); для обзора всех гостей вместо локальных `qm list`/`pct list` используйте именно его.

### Методы HTTP

| Метод | API-версия | Пример |
| --- | --- | --- |
| `GET` | `pvesh get` | `GET /nodes/node1/qemu` |
| `POST` | `pvesh create` | `POST /nodes/node1/qemu/150/status/start` |
| `PUT` | `pvesh set` | `PUT /nodes/node1/qemu/150/config` |
| `DELETE` | `pvesh delete` | `DELETE /nodes/node1/qemu/150` |

Write-операции (POST/PUT/DELETE) обычно возвращают **UPID** фоновой задачи, а не финальный результат. Ожидание и разбор — [Логирование](./proxmox_logging.md), Ansible: модуль `community.proxmox.proxmox_tasks_info`.

### Формат данных и ошибки

Успешный ответ:

```json
{
  "data": {
    "status": "running",
    "vmid": 150,
    "name": "web-server"
  }
}
```

Ошибка валидации параметров:

```json
{
  "errors": { "vmid": "property is missing" },
  "data": null
}
```

При HTTP 401/403/500 дополнительно смотрите `messages` (если есть) и `journalctl -u pveproxy` / `journalctl -u pvedaemon`.

### Аутентификация и модель прав

| Способ | Когда использовать | CSRF | Срок |
| --- | --- | --- | --- |
| API Token | Автоматизация, CI, экспортеры | не нужен | до `--expire` или отзыва |
| Ticket + password | Ручные curl, скрипты без vault | обязателен для write | 2 часа (продление старым ticket) |
| Ticket + OTP | 2FA | обязателен для write | 2 часа |
| OpenID Connect | Корпоративный SSO | как у ticket | зависит IdP |

Права API-токена — **пересечение** ACL токена и ACL пользователя (`--privsep 1`, по умолчанию). Full-привилегии (`--privsep 0`) — копия прав пользователя; для automation это широкий blast radius. Консольные endpoint-ы (`/nodes/<node>/vnc|spice|xtermjs|serial`) **не работают с API-токеном** — только пользователь-сессия.

## Практические сценарии

### 1. API-токен (рекомендуется для автоматизации)

```bash
# Отдельный пользователь (не root@pam) под задачу
pveum user add automation@pve --comment "CI/CD automation"

# Токен: privsep=1 (по умолчанию) + явные ACL на токен
pveum user token add automation@pve ci \
  --privsep 1 \
  --expire "$(date -d '+90 days' +%s)" \
  --comment "CI pipeline; owner: platform-team; rotate quarterly"
# → secret (UUID) выдаётся ОДИН раз — сразу в vault

# Явные права на токен (без них authenticated, но 403 на всё)
pveum acl modify /vms --token 'automation@pve!ci' --roles PVEVMAdmin
pveum acl modify /nodes --token 'automation@pve!ci' --roles PVEAuditor
pveum user token permissions automation@pve ci

# Проверка «прозрачности»
TOKEN="automation@pve!ci=<UUID>"
curl -s -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve.example.com:8006/api2/json/version"
```

`--privsep 0` уместен только если интеграции действительно нужны все права пользователя и нет возможности выдать ACL; чаще он маскирует ошибку «забыли выдать роль» и даёт root-подобный blast radius при утечке.

### 2. Ticket-сессия (ручные запросы)

```bash
# Пароль безопаснее передавать из файла, не из argv (ps виден другим юзерам)
curl -s -k -d 'username=root@pam' \
  --data-urlencode "password@$HOME/.pve-pass" \
  "https://pve.example.com:8006/api2/json/access/ticket"
# → data.ticket (2h), data.CSRFPreventionToken, data.username

# GET с cookie
curl -s -k -b "PVEAuthCookie=$TICKET" \
  "https://pve.example.com:8006/api2/json/nodes"

# Write: cookie + CSRF
curl -s -k -X POST \
  -b "PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  "https://pve.example.com:8006/api2/json/nodes/node1/qemu/150/status/start"
```

Продление: повторный `POST /access/ticket` с `username` и `password=<старый ticket>` до истечения срока.

### 3. curl с токеном: безопаснее

Секреты в argv видны в `ps` и shell history. Wiki рекомендует header-файл:

```bash
printf 'Authorization: PVEAPIToken=%s' "$TOKEN" > ~/.pve.headers
chmod 600 ~/.pve.headers

curl -s -H @~/.pve.headers \
  "https://pve.example.com:8006/api2/json/cluster/resources?type=vm"
```

`-k` / `verify_ssl=False` — только для лаборатории с самоподписанным сертификатом; в production — доверенный сертификат ([ACME/SSL](./proxmox_acme_ssl.md)).

### 4. Управление гостями (VM и LXC)

```bash
API="https://pve.example.com:8006/api2/json"
AUTH=(-H "Authorization: PVEAPIToken=$TOKEN")

# Инвентарь кластера (все узлы)
curl -s "${AUTH[@]}" "$API/cluster/resources?type=vm"

# Локальный список VM (только этот узел)
curl -s "${AUTH[@]}" "$API/nodes/node1/qemu"

# Создание VM (JSON body)
curl -s -X POST "${AUTH[@]}" "$API/nodes/node1/qemu" \
  -H "Content-Type: application/json" \
  -d '{
    "vmid": 150,
    "name": "new-server",
    "memory": 4096,
    "cores": 2,
    "scsihw": "virtio-scsi-pci",
    "scsi0": "local-lvm:32,discard=on",
    "net0": "virtio,bridge=vmbr0"
  }'
# → {"data":"UPID:node1:..."} — фоновая задача

# Ожидание задачи (пока UPID не пропадёт из active или status OK)
UPID="UPID:node1:..."
curl -s "${AUTH[@]}" "$API/nodes/node1/tasks/$UPID/status"
# → status: running | stopped; exitstatus: OK | ERR

# Старт/стоп/конфиг/удаление
curl -s -X POST "${AUTH[@]}" "$API/nodes/node1/qemu/150/status/start"
curl -s -X POST "${AUTH[@]}" "$API/nodes/node1/qemu/150/status/stop"
curl -s "${AUTH[@]}" "$API/nodes/node1/qemu/150/config"
curl -s -X PUT "${AUTH[@]}" "$API/nodes/node1/qemu/150/config" \
  -d 'memory=8192&cores=4'
curl -s -X DELETE "${AUTH[@]}" "$API/nodes/node1/qemu/150"
```

LXC — те же префиксы `/nodes/<node>/lxc` (создание требует `ostemplate`, `rootfs`, `password`/`ssh-public-keys` и т.д. — схема: `pvesh usage /nodes/node1/lxc`).

### 5. pvesh на узле

```bash
# Только root на узле PVE; вызовы на другие ноды — авто-прокси по SSH
pvesh get /version
pvesh get /cluster/resources --type vm --output-format json
pvesh get /nodes/node1/qemu/150/config --output-format json

pvesh create /nodes/node1/qemu \
  --vmid 150 --name new-server --memory 4096 --cores 2 \
  --scsi0 "local-lvm:32,discard=on" --net0 "virtio,bridge=vmbr0"

pvesh create /nodes/node1/qemu/150/status/start
pvesh set /nodes/node1/qemu/150/config --memory 8192 --cores 4
pvesh delete /nodes/node1/qemu/150

# Схема параметров endpoint-а
pvesh usage /nodes/node1/qemu --returns
pvesh help get /nodes
```

Формат вывода: по умолчанию `text` (таблицы, человекочитаемые epoch/длительности/размеры); для скриптов — `--output-format json`. `pvesh ls <path>` — список дочерних объектов.

### 6. Python (proxmoxer)

```python
from proxmoxer import ProxmoxAPI

proxmox = ProxmoxAPI(
    host="pve.example.com",
    user="automation@pve",
    token_name="ci",
    token_secret="<UUID>",
    verify_ssl=True,          # в production — доверенный сертификат
)

# Инвентарь и статус
for node in proxmox.nodes.get():
    print(node["node"], node.get("status"))

vms = proxmox.nodes("node1").qemu.get()
for vm in vms:
    print(f"VM {vm['vmid']}: {vm['name']} — {vm['status']}")

# Создание и запуск; write-вызовы возвращают UPID
upid = proxmox.nodes("node1").qemu.post(
    vmid=150, name="new-server", memory=4096, cores=2,
    scsi0="local-lvm:32,discard=on", net0="virtio,bridge=vmbr0",
)
proxmox.nodes("node1").qemu(150).status.start.post()
```

`proxmoxer` умеет и ticket-режим (`password=`); для автоматизации предпочтительнее token.

### 7. Ansible (краткий пример)

Полный обзор коллекции, inventory-плагин и connection-плагины — [Автоматизация через Ansible](./proxmox_ansible.md). Здесь — только минимальный скелет:

```yaml
- name: Ensure app VM
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Create/update KVM guest
      community.proxmox.proxmox_kvm:
        api_host: pve.example.com
        api_user: automation@pve
        api_token_id: ci
        api_token_secret: "{{ vault_proxmox_token_secret }}"
        node: node1
        vmid: 150
        name: web-server
        memory: 4096
        cores: 2
        scsihw: virtio-scsi-pci
        scsi:
          - "local-lvm:32,discard=on"
        net:
          - "virtio,bridge=vmbr0"
        state: present
```

Имя модуля для KVM — `community.proxmox.proxmox_kvm` (не `proxmox_vm`); LXC — `community.proxmox.proxmox`. Секреты — в Ansible Vault, не в плейбуке.

### 8. Мониторинг и health-check

```bash
# Быстрая проверка доступности API и версии (без прав — /version доступен)
curl -s -k "https://pve.example.com:8006/api2/json/version"
# → {"data":{"release":"9.2","version":"9.2.x","repoid":"..."}}

# Статус узла и кластера (нужны права)
curl -s -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve.example.com:8006/api2/json/nodes/node1/status"
curl -s -H "Authorization: PVEAPIToken=$TOKEN" \
  "https://pve.example.com:8006/api2/json/cluster/status"
```

Промetheus-экспортер, алерты и dashboards — [Мониторинг](./proxmox_monitoring.md); права минимального monitoring-токена — пример в [Service Discovery](./proxmox_service_discovery.md#сценарий-1-создание-api-токена-с-минимальными-правами).

## Диагностика и устранение неполадок

| Симптом | Причина | Диагностика / решение |
| --- | --- | --- |
| `401 Unauthorized` | Неверный token/ticket; отозванный/просроченный token | `pveum user token list <user>`; `pveum user token permissions <user> <token>`; сверьте формат `user@realm!tokenid=UUID` |
| `403 Forbidden` | Нет ACL; `--privsep 1` без выданных ролей; недостаточно path-прав | `pveum user token permissions …`; выдайте роль на path (`/vms`, `/nodes`, …) |
| `403` только на console | API-токен не работает с vnc/spice/xtermjs | Используйте ticket-сессию пользователя |
| `500 Internal Server Error` | Некорректные параметры, внутренняя ошибка | `errors`/`messages` в теле; `journalctl -u pveproxy -u pvedaemon` |
| Connection refused / timeout | pveproxy остановлен, firewall, сеть | `systemctl status pveproxy`; `ss -tlnp \| grep 8006`; `pve-firewall` |
| SSL/TLS error | Самоподписанный сертификат | `-k` только в лабе; в production — ACME/custom cert |
| Висит «принято», нет результата | Write вернул UPID, задача упала/висит | `/nodes/<node>/tasks/<UPID>/status` и `/output`; task log |
| Скрипт работает от root@pam, «ломается» при переводе на token | root-права маскировали отсутствие ACL | Создайте отдельного пользователя + privsep-токен + минимальные роли |

## Лучшие практики

1. **API-токен вместо паролей** для automation; парольные ticket-сессии — только для ручных операций.
2. **Не `root@pam!token` с `--privsep 0`** в CI: отдельный пользователь, `--privsep 1`, узкие ACL, `--expire` + ротация секрета.
3. **Секреты — в vault/header-файле**, не в argv, history и git; после `pveum user token add` secret сохраняется один раз.
4. **HTTPS обязателен** (порт 8006 только TLS); доверенные сертификаты вместо `-k`.
5. **Минимальные роли**: мониторинг — `PVEAuditor`; изменение гостей — кастомная/`PVEVMAdmin` на нужных path.
6. **Write = задача**: не считайте HTTP 200 «операцией выполнена» — дождитесь UPID.
7. **Документация**: `pvesh usage`, API Viewer; схема параметров — source of truth, не старые примеры из интернета.
8. **Аудит**: API-действия пишутся в access.log и task log с владельцем токена — полезно для расследований ([Логирование](./proxmox_logging.md)).
9. **Rate limiting**: встроенного нет; пачки запросов — с backoff, чтобы не перегружать pveproxy/pvedaemon.
10. **Не смешивайте** deep-automation (Ansible/Terraform) с этим файлом: тонкости модулей — [Ansible](./proxmox_ansible.md), SDN — [Сети](./proxmox_networking.md), ACME — [SSL](./proxmox_acme_ssl.md).

## Граничные случаи

- **Нет встроенного rate limiting**: агрессивные циклы могут нагрузить pveproxy/pvedaemon; мониторинг-экспортеры — с консервативным interval.
- **Консольные endpoint-ы** (vnc/spice/xtermjs/serial) не доступны API-токенам.
- **`/cluster/resources` без прав** вернёт почти пустой список: нужен Audit на `/vms` (и paths узлов/хранилищ).
- **`qm list` / `pct list`** — только локальный узел; инвентарь кластера — `/cluster/resources`.
- **pvesh** — только root на узле; с удалённого хоста используйте HTTPS API.
- **Ticket живёт 2 часа**; автоматизация без refresh ломается ночью — берите токен.
- **pmxcfs**: при потере кворума/перегрузке pve-cluster запись в `/etc/pve` блокируется — API write начнёт падать; диагностика кластера — [Кластер](./proxmox_cluster.md).
- **Кластерные join-операции** (create/join) — не только REST: требуют доступности SSH между узлами и ручных шагов ([Кластер](./proxmox_cluster.md)).
- **Смешанные версии клиентов**: API стабильно v1 в PVE 8/9, но схемы endpoint-ов и параметры могут меняться между мажорными версиями — проверяйте на целевом PVE через API Viewer/`pvesh usage`.

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Автоматизация Proxmox через Ansible](./proxmox_ansible.md)
- [Proxmox Service Discovery](./proxmox_service_discovery.md)
- [Безопасность и Hardening](./proxmox_security.md)
- [ACME и SSL-сертификаты](./proxmox_acme_ssl.md)
- [Мониторинг](./proxmox_monitoring.md)
- [Логирование и задачи (UPID)](./proxmox_logging.md)
- [Кластеризация и HA](./proxmox_cluster.md)
