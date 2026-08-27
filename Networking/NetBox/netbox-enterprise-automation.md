# Архитектура NetBox в Enterprise-среде

Данный документ описывает расширенные концепции использования NetBox как центрального узла автоматизации в крупных инфраструктурах. Базовые принципы и описание системы см. в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**Централизованная система учета (Primary Inventory)** — концепция, при которой база данных инвентаризации является первичной и авторитетной. Любые изменения сначала фиксируются в системе учета (NetBox), а затем транслируются на оборудование.

**NetBox Branching (Ветвление)** — механизм (версии 4.x), позволяющий создавать изолированные «ветки» базы данных для подготовки изменений. Инженер может внести группу изменений, проверить их с помощью отчетов и выполнить слияние (Merge) с основной базой только после утверждения (Git-подобный workflow).

**Аудитор соответствия (Compliance Auditor)** — механизм или плагин (например, `Validity`), проверяющий текущую конфигурацию оборудования на соответствие эталонным правилам, описанным в базе данных.

**Looking Glass (L1/L2 диагностика)** — функционал (реализуемый через `Custom Scripts`), позволяющий операторам поддержки выполнять базовые команды диагностики (ping, show route) напрямую из интерфейса NetBox.

**High Availability (HA)** — развертывание кластера NetBox (2+ узла приложения, PostgreSQL Patroni, Redis Sentinel) для обеспечения отказоустойчивости и 99.99% доступности SSoT.

**Network as Code (NaC)** — подход, при котором сетевая конфигурация управляется как код: версионируется в Git, тестируется автоматически и деплоится через CI/CD пайплайны.

**Change Control** — формальный процесс управления изменениями в production-среде, включающий согласование, тестирование и откат при необходимости.

**Configuration Drift** — расхождение между эталонной конфигурацией в NetBox и фактическим состоянием оборудования.

## Базовые концепции

### Предварительные требования

Для Enterprise-развертывания NetBox необходимы:

**Программное обеспечение:**
- NetBox 4.x или выше (рекомендуется последняя стабильная версия)
- PostgreSQL 14+ (рекомендуется 15+ для производительности)
- Redis 7.0+ (для очередей и кэширования)
- Python 3.11+ (для плагинов и скриптов)
- Git (для контроля версий конфигураций)

**Плагины (рекомендуемые для Enterprise):**
- `netbox-plugin-bgp` — BGP-сессии и политики
- `netbox-plugin-device-type-library` — расширенная библиотека типов устройств
- `netbox-plugin-netbox-documentation` — встроенная документация
- `netbox-plugin-validity` — аудит конфигураций
- `netbox-plugin-branching` — ветвление (встроен в NetBox 4.x)

**Инфраструктура:**
- Выделенные серверы или VM (минимум 4 CPU, 8 RAM для production)
- SSL-сертификаты для HTTPS
- Система мониторинга (Prometheus/Grafana или аналог)
- Система логирования (ELK/Loki или аналог)

### Проблемы разрозненной инвентаризации в ЦОД

В крупных организациях без SSoT часто наблюдается фрагментация данных, что блокирует автоматизацию:
- **NetDot**: Используется как «записная книжка» для IP и VLAN. Недостаток — отсутствие связи с карточкой заказчика и физикой.
- **Wiki/Confluence**: Хранит схемы и регламенты. Недостаток — данные быстро устаревают, отсутствие API.
- **NOC**: Используется для инвентаризации и бэкапа. Недостаток — сложность добавления кастомного функционала и перегруженный интерфейс.
- **OpenDCIM**: Только учет стоек, оторванный от сетевых настроек.

Для сборки единой «карточки клиента» инженеру приходится переключаться между 4–5 системами, что приводит к ошибкам.

**Решение:** Внедрение NetBox как SSoT с интеграцией всех смежных систем через API:

```python
# Пример интеграции с внешними системами
class NetBoxIntegration:
    def __init__(self, nb_url, nb_token):
        self.nb = pynetbox.api(nb_url, token=nb_token)
    
    def sync_from_cmdb(self, cmdb_data):
        """Синхронизация данных из CMDB в NetBox"""
        for device in cmdb_data:
            # Создание или обновление устройства
            nb_device = self.nb.dcim.devices.get(name=device['name'])
            if nb_device:
                nb_device.update({
                    'serial': device['serial'],
                    'asset_tag': device['asset_tag']
                })
                nb_device.save()
    
    def export_to_monitoring(self):
        """Экспорт данных для системы мониторинга"""
        devices = self.nb.dcim.devices.all()
        monitoring_data = []
        for device in devices:
            if device.primary_ip4:
                monitoring_data.append({
                    'host': device.name,
                    'ip': device.primary_ip4.address.split('/')[0],
                    'site': device.site.name,
                    'role': device.role.name
                })
        return monitoring_data
```

### Сравнение подходов к ведению документации

| Характеристика | Ручной учет (Legacy) | Централизованная система (SSoT) |
| :--- | :--- | :--- |
| **Актуальность** | Обновляется постфактум, часто врет | Первична, определяет реальность |
| **Внесение изменений** | CLI вручную на каждом устройстве | API-запрос в NetBox -> CI/CD пайплайн |
| **Валидация** | Отсутствует (человеческий фактор) | Автоматическая (Branching + Reports) |
| **Автоматизация** | Невозможна из-за разрозненности | Фундамент для Ansible, Terraform, Napalm |

### Глубокое моделирование физической инфраструктуры

Для создания точного кабельного журнала необходимо моделировать пассивные компоненты.

**Ключевые сущности:**
- **Cable Profiles (v4.5+)**: Моделирование сложных сборок (breakout 1-в-4) с отслеживанием каждой «линии» (lane).
- **Патч-панели**: Имеют передние порты (связь с коммутаторами) и задние порты (коммутация между панелями).
- **Сквозной проход (Pass-through)**: Позволяет функции `Trace` простроить физический путь сигнала через все кроссировки до порта сервера.

**Алгоритм моделирования вложенного кросса (Device Bays):**
1. Установка статуса `Parent` для основного шасси патч-панели.
2. Описание слотов расширения через `Device Bays`.
3. Создание шаблонов модулей (например, сплайс-кассет) со статусом `Child` (0 RU).
4. Установка Parent в стойку и добавление Child-объектов в его слоты.
5. Коммутация портов Parent с Child согласно внутренней кроссировке.

**Пример моделирования через API:**

```python
# Создание патч-панели с Device Bays
def create_patch_panel_with_bays(site_slug, panel_name):
    # Создание основного устройства
    panel = nb.dcim.devices.create(
        name=panel_name,
        device_type={'slug': 'patch-panel-24port'},
        site={'slug': site_slug},
        role={'slug': 'patch-panel'},
        status='active'
    )
    
    # Создание Device Bays для модулей
    for bay_num in range(1, 5):
        nb.dcim.device_bays.create(
            device=panel.id,
            name=f"Bay {bay_num}",
            position=str(bay_num)
        )
    
    return panel
```

### Интегрированная карточка заказчика (Tenant)

В Enterprise-инсталляциях NetBox объединяет данные в сущность **Tenant**:
- **Ресурсы**: Подсети, VLAN, VRF, серверы и стойки.
- **Связность**: Сквозная физическая трассировка кабельных трасс.
- **Сервисы и контракты**: ИТ-услуги, номера договоров, параметры BGP, лимиты полосы (Burst Rate).
- **Интеграция**: Прямые ссылки на тикеты в Jira/ServiceNow из интерфейса объекта.

**Настройка мультитенантности:**

```python
# Создание Tenant Group и Tenant
def setup_tenant_hierarchy():
    # Группа тенантов (например, по регионам)
    tenant_group = nb.tenant_groups.create(
        name="Regional Offices",
        slug="regional-offices",
        description="Группа офисов по регионам"
    )
    
    # Конкретный тенант (офис)
    tenant = nb.tenants.create(
        name="Moscow Office",
        slug="moscow-office",
        group=tenant_group.id,
        description="Московский офис компании"
    )
    
    return tenant

# Привязка ресурсов к тенанту
def assign_resources_to_tenant(tenant_id):
    # Привязка префиксов
    prefix = nb.ipam.prefixes.get(prefix="10.1.0.0/24")
    prefix.tenant = tenant_id
    prefix.save()
    
    # Привязка VLAN
    vlan = nb.ipam.vlans.get(vid=100)
    vlan.tenant = tenant_id
    vlan.save()
```

### Планирование масштабирования

Для Enterprise-развертывания необходимо учитывать:

**Рекомендуемые ресурсы:**

| Компонент | Small (<1K устройств) | Medium (1K-10K) | Large (>10K) |
| :--- | :--- | :--- | :--- |
| **CPU** | 2-4 ядра | 4-8 ядер | 8+ ядер |
| **RAM** | 4-8 GB | 8-16 GB | 16+ GB |
| **Storage** | 50-100 GB SSD | 100-500 GB SSD | 500+ GB SSD |
| **Бэкапы** | Ежедневные | Ежечасные | Реального времени |

**Оптимизация производительности:**

```bash
# Настройка PostgreSQL для производительности
# /etc/postgresql/15/main/postgresql.conf
shared_buffers = 4GB          # 25% от RAM
effective_cache_size = 12GB   # 75% от RAM
work_mem = 256MB
maintenance_work_mem = 1GB
max_connections = 200

# Включение параллельных запросов
max_parallel_workers_per_gather = 4
max_parallel_workers = 8
```

## Практические сценарии

### Сценарий 1: Автоматизированный аудит (Compliance)

Связка NetBox + Oxidized + Validity.

**Предварительные требования:**
- NetBox 4.x с плагином Validity
- Oxidized настроен и работает
- Python 3.11+ с пакетом `validity`

**Шаг 1: Настройка Oxidized для интеграции с NetBox:**

```yaml
# /etc/oxidized/config
source:
  default: http
  http:
    url: https://netbox.example.com/api/dcim/devices/
    token: YOUR_NETBOX_TOKEN
    scheme: https
    headers:
      Authorization: "Token YOUR_TOKEN"

output:
  default: git
  git:
    user: oxidized
    email: oxidized@example.com
    repo: "/var/lib/oxidized/devices.git"
```

**Шаг 2: Настройка Webhook в NetBox:**

```python
import pynetbox

nb = pynetbox.api(url="https://netbox.example.com", token="YOUR_TOKEN")

# Создание Webhook для уведомления Oxidized
webhook = nb.extras.webhooks.create(
    name="Oxidized Config Backup",
    url="https://oxidized.example.com/webhook",
    enabled=True,
    events=["created", "updated"],
    payload_url="https://oxidized.example.com/webhook",
    secret="YOUR_WEBHOOK_SECRET",
    ssl_verification=True,
    type_create=True,
    type_update=True,
    type_delete=False
)

# Привязка Webhook к модели Device
nb.extras.webhook.assignments.create(
    webhook=webhook.id,
    content_type="dcim.device",
    events=["created", "updated"]
)
```

**Шаг 3: Настройка Validity для аудита:**

```python
# Создание CompliancPolicy для проверки конфигураций
def create_compliance_policy():
    # Политика для проверки NTP-серверов
    policy = nb.extras.config_contexts.create(
        name="NTP Policy",
        description="Проверка наличия корректных NTP-серверов",
        is_active=True,
        data={
            "ntp_servers": ["pool.ntp.org", "time.google.com"],
            "min_stratum": 2,
            "max_stratum": 5
        }
    )
    
    return policy
```

**Шаг 4: Запуск аудита:**

```bash
# Ручной запуск аудита через CLI
validity-audit --netbox-url https://netbox.example.com \
               --netbox-token YOUR_TOKEN \
               --output report.html

# Или через API (автоматически по расписанию)
curl -X POST "https://netbox.example.com/api/extras/scripts/validity_audit/" \
     -H "Authorization: Token YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"data": {"force": false}}'
```

**Шаг 5: Просмотр результатов:**

```python
# Получение результатов аудита
compliance_results = nb.extras.compliance_results.all()
for result in compliance_results:
    print(f"Устройство: {result.device.name}")
    print(f"Статус: {result.status}")
    print(f"Отклонения: {result.violations}")
```

### Сценарий 2: Управление услугами (Custom Plugins + Napalm)

Для автоматизации L2VPN/Direct Connect создается собственный плагин.

**Структура плагина:**

```
netbox-network-services/
├── netbox_network_services/
│   ├── __init__.py
│   ├── models.py          # Модели данных (Connection, Service)
│   ├── views.py           # API views
│   ├── tables.py          # Таблицы для UI
│   ├── forms.py           # Формы ввода
│   ├── scripts.py         # Custom Scripts
│   ├── api/__init__.py
│   ├── api/serializers.py # Сериализаторы
│   └── api/views.py       # API endpoints
├── setup.py
└── README.md
```

**Пример модели для L2VPN:**

```python
# netbox_network_services/models.py
from django.db import models
from dcim.models import Device, Interface
from ipam.models import VLAN

class Connection(models.Model):
    """Физическое соединение"""
    name = models.CharField(max_length=100)
    site_a = models.ForeignKey('dcim.Site', on_delete=models.CASCADE, related_name='connections_a')
    site_b = models.ForeignKey('dcim.Site', on_delete=models.CASCADE, related_name='connections_b')
    device_a = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='connections_a')
    interface_a = models.ForeignKey(Interface, on_delete=models.CASCADE, related_name='connections_a')
    device_b = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='connections_b')
    interface_b = models.ForeignKey(Interface, on_delete=models.CASCADE, related_name='connections_b')
    vlan = models.ForeignKey(VLAN, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Connection"
        verbose_name_plural = "Connections"
    
    def __str__(self):
        return f"{self.site_a.name} <-> {self.site_b.name}"

class Service(models.Model):
    """Логический сервис (L2VPN)"""
    STATUS_CHOICES = [
        ('provisioning', 'Provisioning'),
        ('active', 'Active'),
        ('maintenance', 'Maintenance'),
        ('decommissioned', 'Decommissioned'),
    ]
    
    name = models.CharField(max_length=100)
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=50, choices=[
        ('l2vpn', 'L2VPN'),
        ('direct_connect', 'Direct Connect'),
        ('metro', 'Metro Ethernet'),
    ])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    bandwidth_mbps = models.IntegerField()
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.SET_NULL, null=True)
    
    class Meta:
        verbose_name = "Service"
        verbose_name_plural = "Services"
```

**Пример Custom Script для деплоя:**

```python
# netbox_network_services/scripts.py
from extras.scripts import Script, StringVar, IntegerVar
from django.core.exceptions import ValidationError
from napalm import get_network_driver

class DeployL2VPN(Script):
    """Деплой L2VPN через Napalm"""
    
    service_id = IntegerVar(description="ID сервиса для деплоя")
    device_name = StringVar(description="Имя устройства для настройки")
    
    class Meta:
        name = "Deploy L2VPN"
        description = "Автоматический деплой L2VPN сервиса"
    
    def run(self, data, commit):
        service_id = data['service_id']
        device_name = data['device_name']
        
        # Получение данных сервиса из NetBox
        service = self.nb.ipam.services.get(id=service_id)
        if not service:
            self.log_failure(f"Сервис с ID {service_id} не найден")
            return False
        
        # Получение устройства
        device = self.nb.dcim.devices.get(name=device_name)
        if not device:
            self.log_failure(f"Устройство {device_name} не найдено")
            return False
        
        # Подключение через Napalm
        driver = get_network_driver(device.platform.napalm_driver)
        optional_args = {}
        if device.platform.napalm_args:
            optional_args = device.platform.napalm_args
        
        napalm_device = driver(
            hostname=device.primary_ip4.address.split('/')[0],
            username=device.platform.napalm_username,
            password=device.platform.napalm_password,
            optional_args=optional_args
        )
        
        napalm_device.open()
        
        # Генерация конфигурации
        config = f"""
interface {service.connection.interface_a.name}
 switchport mode trunk
 switchport trunk allowed vlan {service.connection.vlan.vid}
 no shutdown
"""
        
        # Применение конфигурации
        try:
            napalm_device.load_merge_candidate(config=config)
            diff = napalm_device.compare_config()
            
            if diff:
                napalm_device.commit_config()
                self.log_success(f"Конфигурация применена:\n{diff}")
                
                # Обновление статуса сервиса
                service.status = 'active'
                service.save()
                
                return True
            else:
                self.log_info("Изменений не требуется")
                napalm_device.discard_config()
                return True
                
        except Exception as e:
            napalm_device.discard_config()
            self.log_failure(f"Ошибка деплоя: {str(e)}")
            return False
        
        finally:
            napalm_device.close()
```

**Регистрация плагина:**

```python
# /opt/netbox/netbox/netbox/configuration.py
PLUGINS = [
    'netbox_network_services',
    'netbox_bgp',
    'netbox_validity',
]

PLUGINS_CONFIG = {
    'netbox_network_services': {
        'napalm_username': os.environ.get('NAPALM_USERNAME'),
        'napalm_password': os.environ.get('NAPALM_PASSWORD'),
    }
}
```

### Сценарий 3: Сетевой CI/CD с NetBox Branching

**Полный цикл ветвления:**

```python
# Шаг 1: Создание ветки
def create_branch(branch_name, description):
    """Создание ветки для изменений"""
    branch = nb.branches.create(
        name=branch_name,
        description=description,
        created_by="automation"
    )
    return branch

# Шаг 2: Внесение изменений в ветку
def apply_changes_to_branch(branch_id, changes):
    """Применение изменений в ветке"""
    # Все изменения применяются в контексте ветки
    for change in changes:
        if change['type'] == 'create_vlan':
            nb.ipam.vlans.create(
                name=change['name'],
                vid=change['vid'],
                site={'slug': change['site']},
                _branch_id=branch_id
            )
        elif change['type'] == 'assign_ip':
            nb.ipam.ip_addresses.create(
                address=change['address'],
                status='active',
                _branch_id=branch_id
            )

# Шаг 3: Запуск тестов в ветке
def run_tests_on_branch(branch_id):
    """Запуск тестов для проверки ветки"""
    # Запуск Custom Report
    report = nb.extras.reports.run(
        report_id=get_report_id('branch_validation'),
        _branch_id=branch_id
    )
    
    # Ожидание завершения и проверка результатов
    while report.status != 'completed':
        time.sleep(5)
        report = nb.extras.reports.get(report.id, _branch_id=branch_id)
    
    return report.results

# Шаг 4: Слияние ветки (Merge)
def merge_branch(branch_id, approved_by):
    """Слияние ветки после утверждения"""
    branch = nb.branches.get(branch_id)
    
    # Проверка статуса тестов
    test_results = run_tests_on_branch(branch_id)
    if not all(r['success'] for r in test_results):
        raise ValidationError("Тесты не пройдены, слияние невозможно")
    
    # Выполнение слияния
    branch.merge(merged_by=approved_by)
    
    return branch
```

**Пример GitHub Actions workflow:**

```yaml
# .github/workflows/netbox-ci.yml
name: NetBox CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
        
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install pynetbox requests pyyaml
          
      - name: Validate NetBox changes
        env:
          NETBOX_URL: ${{ secrets.NETBOX_URL }}
          NETBOX_TOKEN: ${{ secrets.NETBOX_TOKEN }}
        run: |
          python scripts/validate_netbox_changes.py
          
  deploy:
    needs: validate
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
        
      - name: Deploy to NetBox
        env:
          NETBOX_URL: ${{ secrets.NETBOX_URL }}
          NETBOX_TOKEN: ${{ secrets.NETBOX_TOKEN }}
        run: |
          python scripts/deploy_to_netbox.py
          
      - name: Notify on success
        if: success()
        run: |
          curl -X POST ${{ secrets.SLACK_WEBHOOK }} \
            -H 'Content-type: application/json' \
            -d '{"text": "NetBox deployment successful!"}'
```

**Пример валидации изменений:**

```python
# scripts/validate_netbox_changes.py
import pynetbox
import yaml
import sys

def validate_changes(changes_file):
    """Валидация изменений перед деплоем"""
    with open(changes_file, 'r') as f:
        changes = yaml.safe_load(f)
    
    nb = pynetbox.api(
        url=os.environ['NETBOX_URL'],
        token=os.environ['NETBOX_TOKEN']
    )
    
    errors = []
    
    for change in changes:
        # Проверка существования site
        if 'site' in change:
            site = nb.dcim.sites.get(slug=change['site'])
            if not site:
                errors.append(f"Site {change['site']} не найден")
        
        # Проверка уникальности VLAN
        if change['type'] == 'create_vlan':
            existing = nb.ipam.vlans.get(vid=change['vid'], site=change['site'])
            if existing:
                errors.append(f"VLAN {change['vid']} уже существует в {change['site']}")
        
        # Проверка доступности IP-адреса
        if change['type'] == 'assign_ip':
            ip = nb.ipam.ip_addresses.get(address=change['address'])
            if ip:
                errors.append(f"IP {change['address']} уже используется")
    
    if errors:
        print("Ошибки валидации:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    print("Валидация пройдена успешно")
    return True

if __name__ == "__main__":
    validate_changes("changes.yaml")
```

### Сценарий 4: Резервное копирование и восстановление

**Автоматическое резервное копирование:**

```bash
#!/bin/bash
# /opt/netbox/scripts/backup.sh

BACKUP_DIR="/opt/backups/netbox"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Создание директории для бэкапов
mkdir -p $BACKUP_DIR

# Бэкап PostgreSQL
pg_dump -U netbox -h localhost netbox | gzip > $BACKUP_DIR/netbox_$DATE.sql.gz

# Бэкап медиафайлов
tar -czf $BACKUP_DIR/media_$DATE.tar.gz /opt/netbox/netbox/media/

# Бэкап конфигурации
tar -czf $BACKUP_DIR/config_$DATE.tar.gz /opt/netbox/netbox/netbox/configuration.py

# Удаление старых бэкапов
find $BACKUP_DIR -name "*.gz" -mtime +$RETENTION_DAYS -delete

echo "Бэкап завершен: $DATE"
```

**Расписание через cron:**

```bash
# Ежедневный бэкап в 2:00
0 2 * * * /opt/netbox/scripts/backup.sh >> /var/log/netbox-backup.log 2>&1

# Ежечасный бэкап (для критичных систем)
0 * * * * /opt/netbox/scripts/backup-incremental.sh >> /var/log/netbox-backup.log 2>&1
```

**Процедура восстановления:**

```bash
# Восстановление PostgreSQL
gunzip -c /opt/backups/netbox/netbox_20260101_020000.sql.gz | psql -U netbox -h localhost netbox

# Восстановление медиафайлов
tar -xzf /opt/backups/netbox/media_20260101_020000.tar.gz -C /

# Перезапуск сервисов
systemctl restart netbox netbox-worker
```

### Сценарий 5: Мониторинг и алертинг

**Настройка Prometheus метрик:**

```python
# netbox_metrics.py
from prometheus_client import Counter, Histogram, Gauge
import time

# Метрики API запросов
api_requests_total = Counter(
    'netbox_api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

api_request_duration = Histogram(
    'netbox_api_request_duration_seconds',
    'API request duration',
    ['method', 'endpoint']
)

# Метрики очереди задач
queue_size = Gauge(
    'netbox_queue_size',
    'Current queue size',
    ['queue_name']
)

# Метрики синхронизации
sync_operations = Counter(
    'netbox_sync_operations_total',
    'Total sync operations',
    ['source', 'status']
)

def track_api_request(method, endpoint):
    """Декоратор для трекинга API запросов"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                api_request_duration.labels(method=method, endpoint=endpoint).observe(duration)
                api_requests_total.labels(method=method, endpoint=endpoint, status='success').inc()
                return result
            except Exception as e:
                api_requests_total.labels(method=method, endpoint=endpoint, status='error').inc()
                raise
        return wrapper
    return decorator
```

**Grafana дашборд (JSON):**

```json
{
  "dashboard": {
    "title": "NetBox Monitoring",
    "panels": [
      {
        "title": "API Requests per Second",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(netbox_api_requests_total[5m])",
            "legendFormat": "{{method}} {{endpoint}}"
          }
        ]
      },
      {
        "title": "Queue Size",
        "type": "singlestat",
        "targets": [
          {
            "expr": "netbox_queue_size{queue_name='default'}",
            "legendFormat": "{{queue_name}}"
          }
        ]
      }
    ]
  }
}
```

**Алерты:**

```yaml
# prometheus/alerts.yml
groups:
  - name: netbox
    rules:
      - alert: NetBoxHighErrorRate
        expr: rate(netbox_api_requests_total{status="error"}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate in NetBox API"
          description: "Error rate is {{ $value }} per second"
          
      - alert: NetBoxQueueFull
        expr: netbox_queue_size > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "NetBox queue is full"
          description: "Queue size is {{ $value }}"
```

## Жизненный цикл сетевой автоматизации (Network as Code)

1. **Инвентаризация и отчетность**: Формирование поисковых запросов и генерация стартовых конфигов.
2. **Пассивный сбор (GET)**: Синхронизация данных из сети в базу (только чтение).
3. **Активное управление (POST/PATCH)**: Внедрение изменений через API.
4. **Контроль версий и тесты**: Использование Git, Branching и автоматических тестов перед применением на продуктив.

**Валидация на каждом этапе:**

```python
# Проверка целостности данных после синхронизации
def validate_sync_integrity(expected_count, actual_count, sync_type):
    """Валидация результатов синхронизации"""
    if actual_count != expected_count:
        raise ValidationError(
            f"Расхождение данных: ожидалось {expected_count}, "
            f"получено {actual_count} для {sync_type}"
        )
    
    # Проверка наличия критических полей
    devices = nb.dcim.devices.all()
    for device in devices:
        if not device.name:
            raise ValidationError(f"Устройство {device.id} не имеет имени")
        if not device.site:
            raise ValidationError(f"Устройство {device.name} не привязано к site")
```

## Дополнительная информация

### Типовые ошибки и их решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Branching не работает** | NetBox версии < 4.0 | Обновите NetBox до версии 4.0+ |
| **Oxidized не забирает конфиги** | Неверный Webhook URL | Проверьте URL и secret в настройках Oxidized |
| **Validity не запускается** | Плагин не установлен | Установите плагин: `pip install validity` |
| **Очередь задач не обрабатывается** | Worker не запущен | Запустите: `python manage.py rqworker default` |
| **HA кластер не переключается** | Проблемы с PostgreSQL Patroni | Проверьте статус: `patronictl list` |
| **Производительность падает** | Мало ресурсов сервера | Увеличьте RAM/CPU или оптимизируйте запросы |
| **API возвращает 429** | Превышен лимит запросов | Добавьте задержку: `time.sleep(1)` между запросами |

**Диагностика проблем:**

```bash
# Проверка статуса сервисов
systemctl status netbox netbox-worker netbox-scheduler

# Проверка логов
tail -f /var/log/netbox/netbox.log
tail -f /var/log/netbox/rqworker.log

# Проверка очереди задач
python manage.py rqinfo

# Проверка подключения к PostgreSQL
pg_isready -h localhost -p 5432

# Проверка подключения к Redis
redis-cli ping
```

### Best Practices для Enterprise

1. **Безопасность:**
   - Используйте TLS для всех подключений
   - Регулярно ротируйте API-токены
   - Настройте RBAC с最小限界権限
   - Включите аудит изменений (Object Changes)

2. **Производительность:**
   - Используйте connection pooling для PostgreSQL
   - Настройте кэширование (Redis)
   - Оптимизируйте API-запросы (пагинация, фильтрация)
   - Регулярно очищайте старые данные

3. **Надежность:**
   - Настройте HA для всех компонентов
   - Регулярно тестируйте восстановление из бэкапов
   - Мониторьте все компоненты системы
   - Ведите документацию по инцидентам

4. **Масштабируемость:**
   - Планируйте рост заранее
   - Используйте микросервисную архитектуру где возможно
   - Автоматизируйте масштабирование
   - Тестируйте производительность при нагрузке

### Перспективные направления (2026)
- **NetBox Copilot (Agentic AI)**: Анализ топологии на естественном языке и автоматическое построение планов изменений в ветках.
- **NetBox Data Exchange (NDX)**: Автоматический импорт BOM (Bill of Materials) напрямую от поставщиков оборудования.
- **High Availability (HA)**: Развертывание кластера NetBox (2+ узла приложения, PostgreSQL Patroni, Redis Sentinel) для обеспечения 99.99% доступности SSoT.
- **GitOps Integration**: Полная интеграция с ArgoCD/Flux для управления сетевой конфигурацией через Git.
- **AIOps**: Предиктивный анализ инцидентов на основе исторических данных NetBox.

### См. также
- [Автоматизация NetBox (Python API)](./netbox-automation-python.md)
- [Установка NetBox в Debian](./netbox_debian_installation_guide.md)
- [Документация по NetBox Branching](https://netboxlabs.com/docs/netbox/branching/)
