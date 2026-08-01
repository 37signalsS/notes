# Установка Prometheus через APT

## Определения

**Установка через APT** — метод развертывания Prometheus и его компонентов на дистрибутивах Linux на базе Debian (включая Ubuntu) с использованием стандартного пакетного менеджера `apt`.

*   **Prometheus Server**: основной сервис сбора и хранения метрик. В репозиториях поставляется как пакет `prometheus`.
*   **Node Exporter**: агент для мониторинга ресурсов хоста. Поставляется как пакет `prometheus-node-exporter`.
*   **PPA (Personal Package Archive)**: сторонний репозиторий, используемый для установки более новых версий ПО, чем те, что доступны в официальных репозиториях дистрибутива.

## Основные концепции

### Преимущества пакетной установки

1.  **Интеграция с ОС**: Пакеты автоматически настраивают `systemd` unit-файлы, создают системных пользователей и настраивают ротацию логов.
2.  **Безопасность**: Обновления безопасности устанавливаются через стандартный цикл `apt upgrade`.
3.  **Стандартные пути**:
    *   Конфигурация: `/etc/prometheus/prometheus.yml`
    *   Параметры запуска (флаги): `/etc/default/prometheus`
    *   Хранилище (TSDB): `/var/lib/prometheus/`
    *   Бинарные файлы: `/usr/bin/prometheus`

### Особенности версий
В стандартных репозиториях Debian/Ubuntu версии Prometheus часто отстают от официальных релизов на GitHub. Для получения актуальных возможностей (например, Prometheus 3.0+) рекомендуется использовать PPA или бинарную установку.

## Практические сценарии

### Сценарий 1: Базовая установка (Standard Repos)

Подходит для стабильных сред, где не требуются новейшие функции.

```bash
# 1. Обновление индексов
sudo apt update

# 2. Установка сервера и экспортера
sudo apt install -y prometheus prometheus-node-exporter

# 3. Проверка статуса сервисов
sudo systemctl status prometheus
sudo systemctl status prometheus-node-exporter
```

### Сценарий 2: Использование PPA для свежих версий (Ubuntu)

Если в системном репозитории доступна только старая версия (например, 2.x), используйте PPA от сообщества:

```bash
# Добавление репозитория (пример для prometheus-community)
sudo add-apt-repository ppa:prometheus-community/ppa
sudo apt update
sudo apt install -y prometheus
```

### Сценарий 3: Настройка Firewall (UFW)

Для корректной работы мониторинга необходимо разрешить входящий трафик на соответствующие порты:

```bash
# Доступ к Web UI и API Prometheus
sudo ufw allow 9090/tcp comment 'Prometheus Web UI'

# Доступ к метрикам Node Exporter (только для сервера мониторинга)
sudo ufw allow from <IP_PROMETHEUS_SERVER> to any port 9100 proto tcp comment 'Node Exporter'
```

### Сценарий 4: Настройка дополнительных флагов

Если нужно изменить время хранения данных (retention) или путь к хранилищу при установке через APT, редактируйте файл `/etc/default/prometheus`:

```bash
# /etc/default/prometheus
ARGS="--storage.tsdb.retention.time=30d --web.enable-lifecycle"
```

После изменения флагов перезапустите сервис:
```bash
sudo systemctl restart prometheus
```

## Дополнительная информация

### Диагностика и логи

При возникновении проблем используйте `journalctl` для анализа логов сервиса:

```bash
# Просмотр логов в реальном времени
sudo journalctl -u prometheus -f

# Проверка синтаксиса конфигурации
promtool check config /etc/prometheus/prometheus.yml
```

### См. также
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение способов развертывания.
*   **[Управление службами через systemctl](../../Linux/Core/systemd/service_management.md)** — общие команды управления.
*   **[Конфигурация Prometheus](../configuration.md)** — детальная настройка `prometheus.yml`.
*   **[Node Exporter: установка](./node_exporter_installation.md)** — подробнее об агенте.

---
**Надежность:** 10 (SSoT + Валидация путей Debian/Ubuntu)
**,file_path: