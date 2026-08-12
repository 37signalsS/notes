# Автоматизация NetBox с использованием Python

Программное управление инфраструктурой через REST API, GraphQL и специализированные библиотеки. Теоретические основы и архитектура NetBox описаны в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**pynetbox** — официальная клиентская библиотека Python для NetBox API. Рекомендуемый инструмент для большинства задач автоматизации, обеспечивающий объектный доступ к ресурсам.

**Slug (Подстрока)** — уникальный URL-дружественный идентификатор объекта (например, `office-msk`). Используется в API вместо числовых ID для стабильности скриптов при миграциях и обновлениях.

**nmap** — утилита сканирования сети, используемая для обнаружения живых хостов и сопоставления их с данными в IPAM.

**SNMP (Simple Network Management Protocol)** — протокол для сбора метаданных (модель, серийный номер, статус портов) напрямую с сетевого оборудования для синхронизации с NetBox.

## Базовые концепции

### Алгоритм автоматизированного наполнения SSoT

Для корректной регистрации устройства в NetBox 4.x необходимо соблюдать строгую последовательность транзакций:

1.  **Validation**: Проверка существования `Device Type`, `Site`, `Role` и отсутствия дубликатов по имени/IP.
2.  **Device Creation**: Создание базового объекта устройства.
3.  **Interface Configuration**: Создание портов (физических/виртуальных).
4.  **MAC Assignment**: (Для NetBox 4.x+) Создание объекта MAC-адреса и его линковка с интерфейсом.
5.  **IPAM Mapping**: Создание IP-адреса с привязкой к интерфейсу.
6.  **Primary IP Assignment**: Назначение основного управляющего адреса устройству.

---

## Практические сценарии

### 1. Подготовка окружения

Используйте `.env` для хранения токенов и параметров подключения.

```bash
# .env
NETBOX_URL="https://netbox.example.com"
NETBOX_TOKEN="your_token_here"
SNMP_COMMUNITY="public"
MGMT_VLAN_NAME="vlan4090"
SITE_SLUG="dc-north"
ROLE_SLUG="access-switch"
```

### 2. Низкоуровневая автоматизация (requests)

Использование `requests` полезно для легковесных скриптов и понимания структуры API. Ниже представлена реализация класса для пакетного добавления устройств, обновленная под NetBox 4.x.

```python
import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

class NbPostDevice:
    def __init__(self, data):
        self.url = os.getenv("NETBOX_URL")
        self.headers = {
            "Authorization": f"Token {os.getenv('NETBOX_TOKEN')}",
            "Content-Type": "application/json"
        }
        self.data = data # Должен содержать hostname, ip, mac, model_slug и т.д.

    def post_device(self):
        """Создает устройство и возвращает его ID"""
        url = f"{self.url}/api/dcim/devices/"
        payload = {
            "name": self.data['hostname'],
            "device_type": {"slug": self.data['model_slug']},
            "role": {"slug": os.getenv('ROLE_SLUG')},
            "site": {"slug": os.getenv('SITE_SLUG')},
            "status": "active"
        }
        res = requests.post(url, headers=self.headers, json=payload, verify=False)
        return res.json()['id'] if res.status_code == 201 else None

    def post_interface(self, device_id):
        """Создает интерфейс управления"""
        url = f"{self.url}/api/dcim/interfaces/"
        payload = {
            "device": device_id,
            "name": os.getenv('MGMT_VLAN_NAME'),
            "type": "virtual",
            "enabled": True
        }
        res = requests.post(url, headers=self.headers, json=payload, verify=False)
        return res.json()['id'] if res.status_code == 201 else None

    def post_mac(self, interface_id):
        """Создает MAC-адрес (NetBox 4.x+)"""
        url = f"{self.url}/api/dcim/mac-addresses/"
        payload = {
            "mac_address": self.data['mac_address'],
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": interface_id
        }
        return requests.post(url, headers=self.headers, json=payload, verify=False).status_code

    def post_ip(self, interface_id):
        """Добавляет IP-адрес на интерфейс"""
        url = f"{self.url}/api/ipam/ip-addresses/"
        payload = {
            "address": self.data['ipaddress'],
            "status": "active",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": interface_id
        }
        res = requests.post(url, headers=self.headers, json=payload, verify=False)
        return res.json()['id'] if res.status_code == 201 else None

    def set_primary_ip(self, device_id, ip_id):
        """Назначает IP основным для устройства"""
        url = f"{self.url}/api/dcim/devices/{device_id}/"
        payload = {"primary_ip4": ip_id}
        return requests.patch(url, headers=self.headers, json=payload, verify=False).status_code
```

### 3. Современный подход через pynetbox

Библиотека `pynetbox` инкапсулирует логику HTTP-запросов и упрощает работу со связями.

```python
import pynetbox

nb = pynetbox.api(url=os.getenv("NETBOX_URL"), token=os.getenv("NETBOX_TOKEN"))

def pynetbox_sync(device_data):
    # Поиск Device Type
    dt = nb.dcim.device_types.get(slug=device_data['model_slug'])
    if not dt:
        raise ValueError(f"Модель {device_data['model_slug']} не найдена в NetBox")

    # Создание устройства
    dev = nb.dcim.devices.create(
        name=device_data['name'],
        device_type=dt.id,
        role={'slug': 'access-switch'},
        site={'slug': 'dc-north'}
    )

    # Интерфейс и IP
    face = nb.dcim.interfaces.create(device=dev.id, name="GigabitEthernet0/1", type="1000base-t")
    
    ip = nb.ipam.ip_addresses.create(
        address=device_data['ip'],
        assigned_object_type="dcim.interface",
        assigned_object_id=face.id
    )
    
    # Обновление Primary IP
    dev.update({'primary_ip4': ip.id})
```

### 4. Сбор данных через SNMP и nmap

Скрипт для извлечения `sysDescr` и парсинга ARP-таблиц для автоматического наполнения.

```python
import subprocess
import re

class SwitchSnmpGet:
    def __init__(self, ip):
        self.ip = ip
        self.community = os.getenv("SNMP_COMMUNITY")

    def get_sys_descr(self):
        """Получение модели устройства через SNMP sysDescr (OID 1.3.6.1.2.1.1.1.0)"""
        cmd = ["snmpwalk", "-v2c", "-c", self.community, self.ip, "1.3.6.1.2.1.1.1.0"]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = process.communicate()
        
        # Парсинг строки вида: STRING: Cisco IOS Software, C2960...
        match = re.search(r'STRING: (.*)', out.decode('utf-8'))
        return match.group(1).strip() if match else "Unknown"

# Пример вызова nmap для обнаружения
# nmap -sn 192.168.1.0/24 | grep "Nmap scan report for"
```

### 5. Оптимизация запросов через GraphQL (NetBox 4.x)

Используйте GraphQL для получения связанных данных за один запрос (например, устройства + их префиксы).

```python
def get_inventory_gql():
    query = """
    {
      device_list {
        name
        primary_ip4 {
          address
        }
        site {
          name
        }
      }
    }
    """
    url = f"{os.getenv('NETBOX_URL')}/graphql/"
    headers = {"Authorization": f"Token {os.getenv('NETBOX_TOKEN')}"}
    response = requests.post(url, json={'query': query}, headers=headers)
    return response.json()['data']['device_list']
```

## Дополнительная информация

### Верификация данных перед импортом
Перед запуском импорта всегда проверяйте:
1.  **Уникальность Hostname**: `nb.dcim.devices.get(name="SW-01")`.
2.  **Наличие префикса**: Убедитесь, что IP-адрес входит в существующий в NetBox префикс (иначе создание IP может завершиться с ошибкой, если включена строгая проверка).
3.  **Корректность MAC**: Валидация регулярным выражением `^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$`.

### См. также
*   [Архитектура NetBox в Enterprise-среде](./netbox-enterprise-automation.md)
*   [Установка NetBox в Debian](./netbox_debian_installation_guide.md)
*   [Интеграция NetBox с Ansible Dynamic Inventory](../../Ansible/dynamic_inventory.md)
*   [Официальная документация pynetbox](https://pynetbox.readthedocs.io/)
