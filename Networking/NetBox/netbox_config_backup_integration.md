# NetBox: Интеграция с системами резервного копирования конфигураций

Руководство по интеграции NetBox с Oxidized и Rancid для автоматического резервного копирования конфигураций сетевого оборудования. Обзор концепций приведен в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**Oxidized** — легковесная система для резервного копирования конфигураций сетевого оборудования с открытым исходным кодом. Поддерживает более 150 платформ (Cisco, Juniper, Arista, MikroTik и др.). Использует Git для хранения версий конфигураций.

**Rancid** (Really Awesome New Cisco confIg Differ) — традиционная система резервного копирования конфигураций, поддерживающая широкий спектр сетевого оборудования. Использует CVS/SVN/Git для хранения версий.

**Config Context** — механизм NetBox для хранения контекстных данных (SSH-учетные данные, SNMP- community, специфичные настройки), привязанных к сайтам, ролям или тегам.

**Job Queue** — очередь задач NetBox (RQ) для асинхронной обработки фоновых операций (отправка вебхуков, обновление конфигураций).

## Базовые концепции

### Архитектура интеграции

```
┌─────────────────────────────────────────────────────────┐
│                     NetBox                               │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │    DCIM    │  │    IPAM    │  │  Config Contexts  │  │
│  │ (устройства│  │  (адреса)  │  │  (учетные данные) │  │
│  │  + интерфейсы)│ │           │  │                  │  │
│  └──────┬─────┘  └──────┬─────┘  └────────┬─────────┘  │
└─────────┼───────────────┼─────────────────┼─────────────┘
          │               │                 │
          ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                    Oxidized / Rancid                      │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │  Список    │→ │   Загрузка │→ │   Git-репозиторий │  │
│  │  устройств │  │   конфигов │  │  (версионирование)│  │
│  └────────────┘  └────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Методы получения списка устройств

| Метод | Описание | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **NetBox API** | Oxidized запрашивает устройства через REST API | Автоматическое обновление списка | Зависимость от API |
| **CSV-экспорт** | Экспорт списка из NetBox в CSV | Простота | Ручное обновление |
| **LDAP** | Синхронизация из LDAP-каталога | Единая аутентификация | Сложная настройка |
| **Config Contexts** | Хранение учетных данных в NetBox | Централизация | Требует плагинов |

## Практические сценарии

### 1. Настройка NetBox для предоставления списка устройств

Создайте Export Template для генерации конфигурации Oxidized:

```python
# /opt/netbox/netbox/netbox/extras/export_templates/oxidized_devices.py
from dcim.models import Device

def export_to_oxidized(queryset):
    """Экспорт устройств для Oxidized в формате CSV"""
    output = []
    for device in queryset:
        if device.primary_ip4:
            output.append({
                'name': device.name,
                'ip': str(device.primary_ip4.address).split('/')[0],
                'model': device.device_type.slug if device.device_type else '',
                'username': device.config_context.get('oxidized_username', 'admin') if device.config_context else 'admin',
                'password': device.config_context.get('oxidized_password', '') if device.config_context else '',
                'group': device.site.slug if device.site else 'default',
                'ssh_port': device.config_context.get('ssh_port', '22') if device.config_context else '22',
            })
    return output
```

### 2. Настройка Config Contexts для учетных данных

Создайте Config Context для каждой группы устройств:

```python
# Через Django shell
python manage.py shell -c "
from extras.models import ConfigContext
from dcim.models import Site

# Создание контекста для всех устройств в site
site = Site.objects.get(slug='dc-north')
context = ConfigContext.objects.create(
    name='Oxidized Credentials - DC North',
    description='Учетные данные для резервного копирования',
    weight=1000,
    data={
        'oxidized_username': 'admin',
        'oxidized_password': 'secure_password',
        'oxidized_group': 'cisco',
        'oxidized_ssh_port': 22,
        'oxidized_enable': 'enable_password',
    },
)
context.sites.add(site)
print(f'Config Context создан: {context.name}')
"
```

### 3. Настройка Oxidized

Установите Oxidized:

```bash
# Установка (Debian/Ubuntu)
sudo apt install -y ruby-dev build-essential cmake libssl-dev
sudo gem install oxidized
sudo gem install oxidized-web

# Создание пользователя
sudo useradd -r -s /bin/false oxidized
```

Конфигурация `/etc/oxidized/config`:

```yaml
---
username: admin
password: ${OXIDIZED_PASSWORD}
model: cisco
use_db: true

source:
  default: http
  http:
    url: https://netbox.example.com/api/dcim/devices/
    token: YOUR_NETBOX_TOKEN
    mapping:
      name: name
      ip: primary_ip4.address
      model: device_type.slug
      group: site.slug

    # Фильтрация: только активные устройства с IP
    url_mapping:
      - url: "https://netbox.example.com/api/dcim/devices/?status=active&has_primary_ip=true"
        mapping:
          name: name
          ip: primary_ip4.address
          model: device_type.slug
          group: site.slug

output:
  default: git
  git:
    user: Oxidized
    email: oxidized@example.com
    repo: /var/lib/oxidized/devices.git

threads: 30
timeout: 20
retries: 3
```

### 4. Настройка hooks для автоматического обновления

Создайте hook для уведомления Slack при изменении конфигурации:

```ruby
# /var/lib/oxidized/hooks/slack_hook.rb
#!/usr/bin/env ruby
require 'net/http'
require 'json'

repo, node, old, new = ARGV

uri = URI('https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK')
message = {
  text: "Config changed: #{node}",
  attachments: [{
    color: old ? 'warning' : 'good',
    fields: [
      { title: 'Device', value: node, short: true },
      { title: 'Repo', value: repo, short: true },
      { title: 'Old Revision', value: old || 'N/A', short: true },
      { title: 'New Revision', value: new, short: true }
    ]
  }]
}

http = Net::HTTP.new(uri.host, uri.port)
http.use_ssl = true
request = Net::HTTP::Post.new(uri.path, { 'Content-Type' => 'application/json' })
request.body = message.to_json
http.request(request)
```

### 5. Синхронизация списка устройств из NetBox

Скрипт для периодической синхронизации:

```python
#!/usr/bin/env python3
# /opt/netbox/scripts/sync_oxidized_devices.py

import pynetbox
import json
import subprocess
import os
from datetime import datetime

NB_URL = os.getenv('NETBOX_URL')
NB_TOKEN = os.getenv('NETBOX_TOKEN')

def sync_devices():
    """Синхронизация списка устройств из NetBox в Oxidized"""
    nb = pynetbox.api(url=NB_URL, token=NB_TOKEN)

    # Получение активных устройств с IP
    devices = nb.dcim.devices.filter(status='active', has_primary_ip=True)

    oxidized_config = []
    for device in devices:
        if not device.primary_ip4:
            continue

        oxidized_config.append({
            'name': device.name,
            'ip': str(device.primary_ip4.address).split('/')[0],
            'model': device.device_type.slug if device.device_type else 'unknown',
            'group': device.site.slug if device.site else 'default',
            'username': device.custom_fields.get('oxidized_username', 'admin'),
            'ssh_port': int(device.custom_fields.get('ssh_port', 22)),
        })

    # Запись в файл
    with open('/etc/oxidized/devices.json', 'w') as f:
        json.dump(oxidized_config, f, indent=2)

    # Перезапуск Oxidized
    subprocess.run(['systemctl', 'restart', 'oxidized'], check=True)

    print(f"[{datetime.now()}] Синхронизировано {len(oxidized_config)} устройств")

if __name__ == '__main__':
    sync_devices()
```

```bash
# Расписание: каждые 6 часов
0 */6 * * * /opt/netbox/venv/bin/python /opt/netbox/scripts/sync_oxidized_devices.py >> /var/log/oxidized-sync.log 2>&1
```

### 6. Настройка Rancid (альтернатива)

Конфигурация `/etc/rancid/rancid.conf`:

```bash
# Репозиторий для NetBox
LIST_OF_GROUPS="netbox"

# Метод получения устройств
RCSSYS=git; export RCSSYS
```

Скрипт для получения списка устройств:

```bash
#!/bin/bash
# /var/lib/rancid/netbox/bin/device_list.sh

NB_URL="https://netbox.example.com"
NB_TOKEN="YOUR_TOKEN"

curl -s -H "Authorization: Token $NB_TOKEN" \
  "$NB_URL/api/dcim/devices/?status=active&has_primary_ip=true" | \
  jq -r '.results[] | "\(.name) cisco \(.primary_ip4.address | split("/")[0])"'
```

### 7. Webhook для автоматического обновления при изменении устройства

Настройте Webhook в NetBox:

```python
# Через pynetbox
import pynetbox
import os

nb = pynetbox.api(url=os.getenv('NETBOX_URL'), token=os.getenv('NETBOX_TOKEN'))

webhook = nb.extras.webhooks.create(
    name="Oxidized Sync",
    url="http://localhost:8080/webhook/oxidized",
    enabled=True,
    events=["created", "updated", "deleted"],
    type_create=True,
    type_update=True,
    type_delete=True,
    payload_url="http://localhost:8080/webhook/oxidized",
    secret=os.getenv('WEBHOOK_SECRET'),
    ssl_verification=True
)

# Привязка к модели Device
content_type = nb.extras.content_types.get(app_label='dcim', model='device')
nb.extras.webhook_assignments.create(
    webhook=webhook.id,
    content_type=content_type.id
)
```

Обработчик webhook:

```python
# /opt/netbox/scripts/webhook_handler.py
from flask import Flask, request, jsonify
import hmac
import hashlib

app = Flask(__name__)
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')

@app.route('/webhook/oxidized', methods=['POST'])
def handle_webhook():
    # Проверка подписи
    signature = request.headers.get('X-NetBox-Signature', '')
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        request.data,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        return jsonify({'error': 'Invalid signature'}), 401

    # Обработка события
    data = request.json
    event = data.get('event')
    device = data.get('object', {}).get('name', 'unknown')

    print(f"[{event}] Device: {device}")

    # Триггер синхронизации
    import subprocess
    subprocess.Popen(['/opt/netbox/scripts/sync_oxidized_devices.py'])

    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

### 8. Мониторинг резервного копирования

```python
# /opt/netbox/scripts/check_oxidized_backup.py
import subprocess
import os
from datetime import datetime, timedelta

def check_last_backup():
    """Проверка времени последнего бэкапа"""
    repo_path = '/var/lib/oxidized/devices.git'

    # Получение последнего коммита
    result = subprocess.run(
        ['git', '-C', repo_path, 'log', '-1', '--format=%ci'],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        return False, "Git-репозиторий недоступен"

    last_commit = datetime.strptime(result.stdout.strip(), '%Y-%m-%d %H:%M:%S %z')
    hours_ago = (datetime.now(last_commit.tzinfo) - last_commit).total_seconds() / 3600

    if hours_ago > 24:
        return False, f"Последний бэкап {hours_ago:.1f} часов назад"

    return True, f"Последний бэкап {hours_ago:.1f} часов назад"

if __name__ == '__main__':
    ok, message = check_last_backup()
    print(f"{'OK' if ok else 'CRITICAL'}: {message}")
    if not ok:
        exit(1)
```

### 9. Экспорт конфигураций из NetBox в Git

Скрипт для экспорта конфигураций:

```python
#!/usr/bin/env python3
# /opt/netbox/scripts/export_configs_to_git.py

import pynetbox
import os
import subprocess
from pathlib import Path

NB_URL = os.getenv('NETBOX_URL')
NB_TOKEN = os.getenv('NETBOX_TOKEN')
EXPORT_DIR = Path('/opt/netbox-configs')

def export_device_configs():
    """Экспорт конфигураций устройств из NetBox"""
    nb = pynetbox.api(url=NB_URL, token=NB_TOKEN)

    EXPORT_DIR.mkdir(exist_ok=True)

    devices = nb.dcim.devices.filter(status='active')
    for device in devices:
        device_dir = EXPORT_DIR / device.site.slug if device.site else EXPORT_DIR / 'default'
        device_dir.mkdir(exist_ok=True)

        # Генерация базовой конфигурации
        config = f"! Configuration for {device.name}\n"
        config += f"! Site: {device.site.name if device.site else 'N/A'}\n"
        config += f"! Role: {device.role.name if device.role else 'N/A'}\n"
        config += f"! Model: {device.device_type if device.device_type else 'N/A'}\n"
        config += f"hostname {device.name}\n"

        config_file = device_dir / f"{device.name}.cfg"
        config_file.write_text(config)

    # Git commit
    subprocess.run(['git', '-C', str(EXPORT_DIR), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(EXPORT_DIR), 'commit', '-m', f'Update configs {datetime.now().isoformat()}'], check=True)
    subprocess.run(['git', '-C', str(EXPORT_DIR), 'push'], check=True)

    print(f"Экспортировано {len(list(devices))} конфигураций")

if __name__ == '__main__':
    export_device_configs()
```

## Обслуживание и эксплуатация

### Типовые проблемы и их решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Oxidized: Connection refused** | Устройство недоступно | Проверьте сеть, SSH-доступ, firewall |
| **Oxidized: Authentication failed** | Неверный пароль в Config Context | Обновите `oxidized_password` в NetBox |
| **Rancid: Device not in list** | Нет синхронизации с NetBox | Запустите скрипт синхронизации |
| **Git push failed** | Нет прав на запись | Проверьте SSH-ключи для Git |
| **Config Context не привязан** | Нет связки с site/device | Привяжите через веб-интерфейс NetBox |
| **Webhook не отправляется** | Ошибка в обработчике | Проверьте логи `netbox-rq` |

### Безопасность

1. **Изоляция учетных данных**: Используйте Config Contexts вместо хардкода паролей.
2. **Шифрование**: Включите SSH для всех подключений.
3. **Ограничение доступа**: NetBox API-токен должен иметь минимальные права.
4. **Аудит**: Включите Object Changes для отслеживания изменений Config Contexts.
5. **Ротация паролей**: Регулярно обновляйте учетные данные в Config Contexts.

### Проверка целостности данных

```bash
# Проверка, что все устройства в Oxidized есть в NetBox
cd /var/lib/oxidized/devices.git
git log --oneline -10  # Проверка истории коммитов

# Сравнение списков
curl -s -H "Authorization: Token YOUR_TOKEN" \
  https://netbox.example.com/api/dcim/devices/?status=active | \
  jq '.results | length'
# → 150 (в NetBox)

oxidized -l  # Список в Oxidized
# → 148 (в Oxidized) — расхождение!
```

## Дополнительная информация

### Полезные ресурсы

- [Официальная документация Oxidized](https://github.com/ytti/oxidized)
- [Документация Rancid](https://www.shrubbery.net/rancid/)
- [NetBox Config Contexts](https://docs.netbox.dev/en/stable/models/extras/configcontext/)

### См. также

- [NetBox: Обзор и базовые концепции](./overview.md)
- [Установка NetBox в Debian](./netbox_debian_installation_guide.md)
- [Автоматизация NetBox с использованием Python](./netbox-automation-python.md)
- [Мониторинг NetBox (Prometheus/Grafana)](./netbox_monitoring_integration.md)
- [Архитектура NetBox в Enterprise-среде](./netbox-enterprise-automation.md)
