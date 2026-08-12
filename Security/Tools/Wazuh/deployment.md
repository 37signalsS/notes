# Развертывание и архитектура Wazuh

## Определения

**Развертывание Wazuh** — комплексный процесс инсталляции и настройки узлов платформы безопасности. С 2026 года (версия **Wazuh 5.0+**) процесс ориентирован на создание высокопроизводительной аналитической среды на базе OpenSearch 3.x, обеспечивающей полную видимость событий (Full Visibility).

**Wazuh-Engine** — современное аналитическое ядро (написано на C++), пришедшее на смену классическому `wazuh-analysisd`. Интегрировано напрямую в процесс индексатора для минимизации задержек при обработке миллионов событий в секунду (EPS).
**Wazuh Indexer** — высокомасштабируемое хранилище данных на базе **OpenSearch 3.x**, оптимизированное для поиска по метаданным безопасности и векторного анализа (AI-интеграции).
**Wazuh Server (Manager)** — узел управления агентами, отвечающий за регистрацию, инвентаризацию активов и оркестрацию API.
**Wazuh Dashboard** — визуальный интерфейс управления на базе OpenSearch Dashboards, поддерживающий нативную работу с событиями (**wazuh-events**) и алертами.

## Основные концепции

### Архитектура SSoT и взаимодействие (Wazuh 5.0+)

В версии 5.0 архитектура эволюционировала от «сборщика логов» к **платформе данных безопасности**:
- **Агенты**: используют протокол **Delta-синхронизации** для передачи изменений инвентаря и логов, снижая нагрузку на сеть.
- **Wazuh-Engine SSoT**: фильтрация, обогащение (GeoIP, CTI) и корреляция (Sigma) теперь происходят на уровне движка данных.
- **Full Visibility**: система сохраняет все события (`wazuh-events-*`), а не только сработавшие алерты, что критично для ретроспективного анализа (Threat Hunting).

### Требования к оборудованию

С внедрением Wazuh-Engine требования к ресурсам (особенно RAM) возросли для обеспечения стабильности OpenSearch 3.x.

**Пример требований для All-in-one (до 100 агентов, 2026 год):**

| Количество агентов | CPU (cores) | RAM (GB) | Диск (NVMe рекомендуется) |
| :--- | :--- | :--- | :--- |
| 1–25 | 4 | 12 | 100 GB |
| 25–100 | 8 | 24 | 300 GB |
| 100–500 | 16 | 48 | 1 TB+ |

*Примечание: Использование HDD крайне не рекомендуется из-за высокой интенсивности операций ввода-вывода (IOPS) в OpenSearch 3.x.*

### Сетевые порты

| Компонент | Порт | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| **Агент ↔ Менеджер** | 1514 | TCP | Передача событий (mTLS по умолчанию) |
| **Агент ↔ Менеджер** | 1515 | TCP | Регистрация и получение сертификатов |
| **Engine ↔ Indexer** | 9200 | TCP | Внутренняя шина данных (Native) |
| **Dashboard ↔ Indexer** | 9200 | TCP | API-запросы визуализации |
| **Dashboard ↔ Пользователь** | 443 | TCP | HTTPS веб-интерфейс |
| **OTLP Receiver** | 4317/4318 | gRPC/HTTP | Сбор OpenTelemetry сигналов (Wazuh 5.0+) |

### Поддерживаемые ОС (2026)
- Ubuntu 24.04 LTS (рекомендуется)
- RHEL 9, 10
- Debian 12
- Amazon Linux 2023

## Практические сценарии

### 1. Установка «все в одном» (All-in-one)

Идеально для POC (Proof of Concept) и малых офисов.

```bash
curl -sO https://packages.wazuh.com/5.x/installation-assistant/wazuh-install.sh
sudo bash ./wazuh-install.sh -a
```
# → Скрипт установит OpenSearch 3.x, Wazuh-Engine и Dashboard. Сохраните пароль из файла /var/wazuh-manager/etc/wazuh-passwords.txt.

### 2. Распределенная установка (Production)

В 2026 году стандарт де-факто — разделение уровней хранения и управления.

#### Шаг А: Подготовка конфигурации
```bash
curl -sO https://packages.wazuh.com/5.x/installation-assistant/config.yml
```

Отредактируйте `config.yml`, включив поддержку `wazuh-engine` на узлах индексатора:
```yaml
nodes:
  indexer:
    - name: indexer-node-1
      ip: "10.0.0.10"
      engine_enabled: true
  server:
    - name: manager-master
      ip: "10.0.0.20"
  dashboard:
    - name: wazuh-dashboard
      ip: "10.0.0.30"
```

#### Шаг Б: Установка
Выполните развертывание последовательно. В Wazuh 5.0 сертификаты генерируются автоматически в рамках запуска ассистента на мастере.

```bash
# На мастере менеджере:
sudo bash wazuh-install.sh --generate-config-files
# → Перенесите архив wazuh-install-files.tar на остальные узлы.

# На узлах Indexer:
sudo bash wazuh-install.sh --wazuh-indexer indexer-node-1
```

### 3. Установка агентов

#### Windows (PowerShell v5+)

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri https://packages.wazuh.com/5.x/windows/wazuh-agent-5.x.y.msi -OutFile $env:tmp\wazuh-agent.msi
msiexec.exe /i $env:tmp\wazuh-agent.msi /q WAZUH_MANAGER='wazuh-manager.local' WAZUH_AGENT_NAME='WS-ADMIN'
Start-Service -Name Wazuh
```

#### Linux (APT-based)

```bash
wget -qO - https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --dearmor -o /usr/share/keyrings/wazuh.gpg
echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/5.x/apt/ stable main" | tee /etc/apt/sources.list.d/wazuh.list
sudo apt update
WAZUH_MANAGER='10.0.0.20' apt install wazuh-agent
systemctl enable --now wazuh-agent
```

## Дополнительная информация

### Стратегия миграции (4.x → 5.0)

Миграция на 5.0 является «разрушительной» для старых индексов из-за смены схем данных (ECS 2026):
1.  **Обновите агентов до 4.14.x** (минимальная версия для понимания протокола 5.0).
2.  **Разверните новый кластер 5.0** параллельно старому.
3.  **Подключите старые данные** через Legacy Connector в Dashboard для чтения архивных алертов.
4.  **Переключите агентов** на новый менеджер через смену IP/DNS в `ossec.conf`.

### Планирование дискового пространства
С переходом на модель **Full Visibility** (хранение всех событий) объем данных вырос в 4–6 раз по сравнению с алерт-моделью 4.x. Рекомендуется использовать механизмы **OpenSearch Cold Storage** для архивирования данных старше 30 дней.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Сбор логов (Logcollector)](./wazuh-log-collection.md) — настройка источников данных 5.0.
- [Мониторинг здоровья и самодиагностика Wazuh](./wazuh-health-monitoring.md) — контроль OTLP-метрик.
