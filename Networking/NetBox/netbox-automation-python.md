# Автоматизация NetBox с использованием Python

Программное управление инфраструктурой через REST API, GraphQL и специализированные библиотеки. Теоретические основы и архитектура NetBox описаны в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**pynetbox** — официальная клиентская библиотека Python для NetBox API. Рекомендуемый инструмент для большинства задач автоматизации, обеспечивающий объектный доступ к ресурсам.

**Slug (Подстрока)** — уникальный URL-дружественный идентификатор объекта (например, `office-msk`). Используется в API вместо числовых ID для стабильности скриптов при миграциях и обновлениях.

**nmap** — утилита сканирования сети, используемая для обнаружения живых хостов и сопоставления их с данными в IPAM.

**SNMP (Simple Network Management Protocol)** — протокол для сбора метаданных (модель, серийный номер, статус портов) напрямую с сетевого оборудования для синхронизации с NetBox.

**Custom Fields** — расширяемые пользователем поля для хранения специфичных данных (номер договора, дата ТО, стоимость аренды), доступные через API через эндпоинт `custom_fields`.

**Webhooks** — HTTP-запросы, автоматически отправляемые NetBox при изменении объектов. Управляются через эндпоинт `/api/extras/webhooks/`.

**Export Templates** — шаблоны на базе Jinja2 для экспорта данных в различные форматы. Доступны через API: `/api/extras/export-templates/`.

**GraphQL** — альтернативный API для получения связанных данных за один запрос. Оптимален для сложных выборок с вложенными связями.

**API Token** — ключ аутентификации для доступа к REST API. Создается в профиле пользователя и передается в заголовке `Authorization: Token <token>`.

**Rate Limiting** — ограничение частоты запросов API (по умолчанию 100 запросов в минуту). Нарушение возвращает HTTP 429.

**Pagination** — постраничная навигация по результатам запросов (по умолчанию 50 объектов на страницу, максимум 1000).

## Базовые концепции

### Алгоритм автоматизированного наполнения SSoT

Для корректной регистрации устройства в NetBox 4.x необходимо соблюдать строгую последовательность транзакций:

1.  **Validation**: Проверка существования `Device Type`, `Site`, `Role` и отсутствия дубликатов по имени/IP.
2.  **Device Creation**: Создание базового объекта устройства.
3.  **Interface Configuration**: Создание портов (физических/виртуальных).
4.  **MAC Assignment**: (Для NetBox 4.x+) Создание объекта MAC-адреса и его линковка с интерфейсом.
5.  **IPAM Mapping**: Создание IP-адреса с привязкой к интерфейсу.
6.  **Primary IP Assignment**: Назначение основного управляющего адреса устройству.

### Предварительные требования

Перед началом автоматизации необходимо установить зависимости:

```bash
pip install pynetbox requests python-dotenv
```

Для работы с SNMP дополнительно:

```bash
# Debian/Ubuntu
sudo apt install snmp snmp-mibs-downloader

# macOS
brew install net-snmp
```

Для работы с nmap:

```bash
# Debian/Ubuntu
sudo apt install nmap

# macOS
brew install nmap
```

### Аутентификация и управление сессиями

NetBox API поддерживает несколько методов аутентификации:

```python
# 1. Токен-базовая аутентификация (рекомендуется)
nb = pynetbox.api(url="https://netbox.example.com", token="YOUR_TOKEN")

# 2. Сессионная аутентификация (для веб-интерфейса)
import requests
session = requests.Session()
session.post("https://netbox.example.com/login/", data={
    "username": "admin",
    "password": "password"
})

# 3. OAuth2 (для интеграции с SSO)
# Требует плагина netbox-sso
nb = pynetbox.api(
    url="https://netbox.example.com",
    token="YOUR_TOKEN",
    threading=True  # Включает фоновые запросы
)
```

### Управление соединениями и таймаутами

```python
import pynetbox
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Настройка сессии с повторными попытками
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

nb = pynetbox.api(
    url="https://netbox.example.com",
    token="YOUR_TOKEN"
)
nb.http_session = session
```

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

### 6. Пакетная обработка и пагинация

При работе с большими объемами данных необходимо учитывать пагинацию API:

```python
def get_all_devices_paginated():
    """Получение всех устройств с учетом пагинации"""
    devices = []
    url = f"{os.getenv('NETBOX_URL')}/api/dcim/devices/"
    headers = {"Authorization": f"Token {os.getenv('NETBOX_TOKEN')}"}
    
    while url:
        response = requests.get(url, headers=headers)
        data = response.json()
        devices.extend(data['results'])
        url = data['next']  # URL следующей страницы или None
    
    return devices

# Или через pynetbox с автоматической пагинацией
def get_all_devices_pynetbox():
    """Получение всех устройств через pynetbox"""
    return list(nb.dcim.devices.all())  # Автоматически обрабатывает пагинацию
```

### 7. Работа с Custom Fields

Добавление и обновление пользовательских полей через API:

```python
def update_custom_fields(device_name, custom_data):
    """Обновление custom fields устройства"""
    device = nb.dcim.devices.get(name=device_name)
    if not device:
        raise ValueError(f"Устройство {device_name} не найдено")
    
    # Обновление custom fields
    device.custom_fields = custom_data
    device.save()
    
    return device

# Пример использования
update_custom_fields("SW-01", {
    "contract_number": "C-2026-001",
    "maintenance_date": "2026-12-31",
    "cost_center": "IT-123"
})
```

### 8. Управление Webhooks через API

Создание и настройка webhook для интеграции с внешними системами:

```python
def create_webhook(name, url, events):
    """Создание webhook для уведомлений"""
    webhook = nb.extras.webhooks.create(
        name=name,
        url=url,
        enabled=True,
        events=events,  # ["created", "updated", "deleted"]
        payload_url=url,
        secret=os.getenv("WEBHOOK_SECRET", ""),
        ssl_verification=True
    )
    return webhook

# Пример: webhook для Slack
create_webhook(
    name="Slack Notifications",
    url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    events=["created", "updated"]
)
```

### 9. Экспорт данных через Export Templates

Получение данных в различных форматах:

```python
def export_devices_csv():
    """Экспорт устройств в CSV через export template"""
    # Получение всех устройств
    devices = nb.dcim.devices.all()
    
    # Формирование CSV
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Site", "Role", "Status", "Primary IP"])
    
    for device in devices:
        writer.writerow([
            device.name,
            device.site.name if device.site else "",
            device.role.name if device.role else "",
            device.status,
            device.primary_ip4.address if device.primary_ip4 else ""
        ])
    
    return output.getvalue()
```

### 10. Асинхронные запросы для высокой производительности

Для сценариев с большим количеством запросов используйте асинхронность:

```python
import asyncio
import httpx

async def get_devices_async():
    """Асинхронное получение устройств"""
    url = f"{os.getenv('NETBOX_URL')}/api/dcim/devices/"
    headers = {"Authorization": f"Token {os.getenv('NETBOX_TOKEN')}"}
    
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=headers)
        return response.json()['results']

# Пример параллельного обновления
async def update_device_status(device_id, status):
    """Асинхронное обновление статуса устройства"""
    url = f"{os.getenv('NETBOX_URL')}/api/dcim/devices/{device_id}/"
    headers = {"Authorization": f"Token {os.getenv('NETBOX_TOKEN')}"}
    
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.patch(url, headers=headers, json={"status": status})
        return response.status_code

# Запуск параллельных обновлений
async def batch_update_status(device_ids, status):
    """Пакетное обновление статусов"""
    tasks = [update_device_status(did, status) for did in device_ids]
    results = await asyncio.gather(*tasks)
    return results
```

---

## Дополнительная информация

### Верификация данных перед импортом

Перед запуском импорта всегда проверяйте:
1.  **Уникальность Hostname**: `nb.dcim.devices.get(name="SW-01")`.
2.  **Наличие префикса**: Убедитесь, что IP-адрес входит в существующий в NetBox префикс (иначе создание IP может завершиться с ошибкой, если включена строгая проверка).
3.  **Корректность MAC**: Валидация регулярным выражением `^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$`.
4.  **Проверка связей**: Убедитесь, что `Site`, `Device Type`, `Role` существуют перед созданием устройства.

### Валидация API-ответов

```python
def validate_api_response(response, expected_status=201):
    """Валидация ответа API"""
    if response.status_code != expected_status:
        raise Exception(f"Ошибка API: {response.status_code} - {response.text}")
    
    try:
        data = response.json()
    except ValueError:
        raise Exception("Ответ API не является JSON")
    
    return data

# Пример использования
response = requests.post(url, headers=headers, json=payload)
data = validate_api_response(response, expected_status=201)
print(f"Создан объект с ID: {data['id']}")
```

### Обработка ошибок и повторные попытки

```python
import time
from functools import wraps

def retry_on_error(max_retries=3, delay=1):
    """Декоратор для повторных попыток при ошибках API"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    print(f"Попытка {attempt + 1} не удалась: {e}")
                    time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator

@retry_on_error(max_retries=3, delay=2)
def create_device_with_retry(device_data):
    """Создание устройства с повторными попытками"""
    return nb.dcim.devices.create(**device_data)
```

### Оптимизация производительности

```python
# 1. Использование кэша для часто запрашиваемых объектов
from functools import lru_cache

@lru_cache(maxsize=128)
def get_site_by_slug(slug):
    """Кэширование запросов site по slug"""
    return nb.dcim.sites.get(slug=slug)

# 2. Пакетное создание объектов
def bulk_create_devices(devices_data):
    """Пакетное создание устройств"""
    created_devices = []
    for data in devices_data:
        try:
            device = nb.dcim.devices.create(**data)
            created_devices.append(device)
        except Exception as e:
            print(f"Ошибка создания {data['name']}: {e}")
    return created_devices

# 3. Использование explicitly_select для уменьшения объема данных
devices = nb.dcim.devices.all()
# Только необходимые поля
for device in devices:
    print(f"{device.name}: {device.primary_ip4}")
```

### Типовые ошибки и их решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **401 Unauthorized** | Неверный токен или токен истек | Проверьте токен в профиле пользователя |
| **403 Forbidden** | Недостаточно прав | Настройте Object Permissions для токена |
| **404 Not Found** | Объект не существует | Проверьте ID или slug объекта |
| **409 Conflict** | Дубликат объекта | Проверьте уникальность имени/ключа |
| **429 Too Many Requests** | Превышен лимит запросов | Добавьте задержку между запросами |
| **500 Internal Server Error** | Ошибка сервера | Проверьте логи NetBox, повторите позже |
| **Connection Error** | Нет доступа к серверу | Проверьте URL, SSL-сертификат, сеть |
| **Timeout** | Долгий ответ сервера | Увеличьте таймаут или используйте async |

### Логирование и мониторинг

```python
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('netbox_automation')

def log_api_call(func):
    """Декоратор для логирования API-вызовов"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"API вызов: {func.__name__}")
        try:
            result = func(*args, **kwargs)
            logger.info(f"Успешно: {func.__name__}")
            return result
        except Exception as e:
            logger.error(f"Ошибка в {func.__name__}: {e}")
            raise
    return wrapper

@log_api_call
def create_device(device_data):
    """Создание устройства с логированием"""
    return nb.dcim.devices.create(**device_data)
```

### API Best Practices для production

#### Пагинация и фильтрация

```python
# Правильная работа с пагинацией
def get_all_devices_filtered(site=None, role=None):
    """Получение устройств с фильтрацией и пагинацией"""
    devices = []
    params = {'status': 'active'}
    if site:
        params['site'] = site
    if role:
        params['role'] = role

    # pynetbox автоматически обрабатывает пагинацию
    return list(nb.dcim.devices.filter(**params))

# Ручная пагинация через requests
def get_devices_paginated(page_size=100):
    """Получение всех устройств с ручной пагинацией"""
    devices = []
    url = f"{os.getenv('NETBOX_URL')}/api/dcim/devices/"
    headers = {"Authorization": f"Token {os.getenv('NETBOX_TOKEN')}"}
    params = {'limit': page_size, 'offset': 0}

    while True:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        devices.extend(data['results'])

        if not data['next']:
            break
        params['offset'] += page_size

    return devices
```

#### Rate Limiting и backoff

```python
import time
from functools import wraps

def rate_limit_handler(max_retries=5):
    """Обработчик rate limiting с exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if '429' in str(e):
                        wait_time = 2 ** attempt  # 1, 2, 4, 8, 16 секунд
                        print(f"Rate limited. Waiting {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise
            raise Exception("Max retries exceeded")
        return wrapper
    return decorator

@rate_limit_handler()
def create_device(device_data):
    return nb.dcim.devices.create(**device_data)
```

#### Безопасность API-токенов

```python
# Неправильно: токен в коде
nb = pynetbox.api(url="https://netbox.example.com", token="abc123...")

# Правильно: токен в переменных окружения
import os
nb = pynetbox.api(
    url=os.environ['NETBOX_URL'],
    token=os.environ['NETBOX_TOKEN']
)

# Правильно:最小权限 для токена
# В NetBox: Admin → Users → Tokens → Создать токен
# - write_enabled: Только чтение (для скриптов мониторинга)
# - write_enabled: Чтение+запись (для автоматизации)
# - Ограничение по IP: whitelist для конкретных IP
```

#### Валидация данных перед отправкой

```python
import re

def validate_device_data(data):
    """Валидация данных устройства перед отправкой в NetBox"""
    errors = []

    # Проверка имени
    if not data.get('name'):
        errors.append("Имя устройства обязательно")
    elif not re.match(r'^[a-zA-Z0-9\-_]+$', data['name']):
        errors.append("Имя устройства содержит недопустимые символы")

    # Проверка IP-адреса
    if 'ip' in data:
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$'
        if not re.match(ip_pattern, data['ip']):
            errors.append(f"Неверный формат IP: {data['ip']}")

    # Проверка MAC-адреса
    if 'mac' in data:
        mac_pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
        if not re.match(mac_pattern, data['mac']):
            errors.append(f"Неверный формат MAC: {data['mac']}")

    return errors

# Использование
errors = validate_device_data(device_data)
if errors:
    raise ValueError(f"Ошибки валидации: {', '.join(errors)}")
```

#### Обработка ошибок API

```python
import logging

logger = logging.getLogger('netbox_api')

class NetBoxAPIError(Exception):
    """Кастомное исключение для ошибок NetBox API"""
    def __init__(self, status_code, message, response=None):
        self.status_code = status_code
        self.message = message
        self.response = response
        super().__init__(f"[{status_code}] {message}")

def safe_api_call(func):
    """Декоратор для безопасных API-вызовов"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.error(f"Bad Request: {e.response.text}")
                raise NetBoxAPIError(400, "Invalid data", e.response)
            elif e.response.status_code == 401:
                logger.error("Unauthorized: Check your token")
                raise NetBoxAPIError(401, "Invalid token")
            elif e.response.status_code == 403:
                logger.error("Forbidden: Insufficient permissions")
                raise NetBoxAPIError(403, "Insufficient permissions")
            elif e.response.status_code == 404:
                logger.error("Not Found: Object doesn't exist")
                raise NetBoxAPIError(404, "Object not found")
            elif e.response.status_code == 429:
                logger.warning("Rate limited")
                raise NetBoxAPIError(429, "Rate limited")
            else:
                logger.error(f"HTTP Error {e.response.status_code}: {e.response.text}")
                raise
        except requests.exceptions.ConnectionError:
            logger.error("Connection error: Check NetBox URL")
            raise
        except requests.exceptions.Timeout:
            logger.error("Request timeout")
            raise
    return wrapper
```

#### Логирование API-вызовов

```python
import json
from datetime import datetime

def log_api_call(func):
    """Декоратор для логирования API-вызовов"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        call_id = start_time.strftime('%Y%m%d_%H%M%S_%f')

        logger.info(f"[{call_id}] API Call: {func.__name__}")
        logger.debug(f"[{call_id}] Args: {args}, Kwargs: {kwargs}")

        try:
            result = func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[{call_id}] Success in {duration:.3f}s")
            return result
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[{call_id}] Failed in {duration:.3f}s: {e}")
            raise
    return wrapper
```

#### Кэширование часто запрашиваемых данных

```python
from functools import lru_cache
from datetime import datetime, timedelta

# Кэш с TTL (Time-To-Live)
_cache = {}
_cache_ttl = {}

def cached_with_ttl(ttl_seconds=300):
    """Декоратор для кэширования с TTL"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{args}:{kwargs}"
            now = datetime.now()

            # Проверка кэша
            if cache_key in _cache:
                if now - _cache_ttl[cache_key] < timedelta(seconds=ttl_seconds):
                    return _cache[cache_key]

            # Вызов функции
            result = func(*args, **kwargs)
            _cache[cache_key] = result
            _cache_ttl[cache_key] = now
            return result
        return wrapper
    return decorator

@cached_with_ttl(ttl_seconds=300)
def get_device_by_name(name):
    """Получение устройства с кэшированием на 5 минут"""
    return nb.dcim.devices.get(name=name)
```

### См. также

*   [Архитектура NetBox в Enterprise-среде](./netbox-enterprise-automation.md)
*   [Установка NetBox в Debian](./netbox_debian_installation_guide.md)
*   [Интеграция NetBox с Ansible Dynamic Inventory](../../Ansible/dynamic_inventory.md)
*   [Официальная документация pynetbox](https://pynetbox.readthedocs.io/)
